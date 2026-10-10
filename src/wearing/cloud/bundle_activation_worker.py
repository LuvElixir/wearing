"""Persistent activation service; each provider mutation uses the existing ledger.

An expired lease never authorizes replay. The provisioning books reconcile an
earlier attempt against its immutable owner and actual provider state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time

from filelock import FileLock, Timeout

from .bundle_activation import ActivationError, ActivationStore, KINDS, member_progress


class LeaseLost(ActivationError):
    pass


def receipt(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class Lease:
    def __init__(self, store, event, worker_id, *, seconds=120, interval=20):
        self.store, self.event, self.worker_id = store, event, worker_id
        self.seconds, self.interval = seconds, interval
        self.stopped, self.lost = threading.Event(), threading.Event()
        self.thread = None

    @property
    def args(self):
        return self.event['id'], self.worker_id, self.event['generation']

    def check(self):
        if self.lost.is_set() or not self.store.heartbeat(*self.args, self.seconds):
            self.lost.set()
            raise LeaseLost('activation_lease_lost')

    def _run(self):
        while not self.stopped.wait(self.interval):
            try:
                self.check()
            except Exception:
                self.lost.set()
                return

    def __enter__(self):
        self.check()
        self.thread = threading.Thread(target=self._run, daemon=True, name='pajio-activation-lease')
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stopped.set()
        self.thread.join(timeout=30)
        if self.thread.is_alive():
            self.lost.set()


class ActivationWorker:
    def __init__(self, store, pipeline, *, worker_id=None, lease_factory=Lease):
        self.store, self.pipeline = store, pipeline
        self.worker_id = worker_id or secrets.token_hex(16)
        self.lease_factory = lease_factory

    def tick(self):
        event = self.store.claim(self.worker_id)
        if event is None:
            return {'state': 'idle'}
        args = event['id'], self.worker_id, event['generation']
        try:
            with self.lease_factory(self.store, event, self.worker_id) as lease:
                # The pipeline checks the real control owner and root reservation
                # before every action, including a resumed event.
                result = self.pipeline.advance(event, lease.check)
                lease.check()
                saved = self.store.update(*args, state=result['state'], step=result['step'],
                    receipt_sha256=receipt(result['evidence']), reason=result.get('reason'),
                    members=result['members'])
                if saved is None:
                    raise LeaseLost('activation_lease_lost')
                result = {'state': saved['state'], 'step': saved['step']}
        except LeaseLost:
            # Do not publish or release using an expired generation. A later
            # service can only continue via the provider books' observation path.
            return {'state': 'lease_lost'}
        except Exception:
            # Raw provider/SSH exceptions may contain addresses or payloads.
            # Keep their durable detail in private books, never status/log output.
            progress = member_progress(event.get('members', event.get('members_json')))
            progress = {k: {'state': 'needs_review' if v['state'] != 'ready' else 'ready'}
                        for k, v in progress.items()}
            result = {'state': 'needs_review', 'step': 'review'}
            if self.store.update(*args, **result, receipt_sha256=receipt(result),
                    reason='provisioning_requires_review', members=progress) is None:
                return {'state': 'lease_lost'}
        finally:
            # CAS release is harmless if the lease expired or another generation
            # owns the event. It never changes provider capacity reservations.
            try:
                self.store.release(*args)
            except Exception:
                pass
        return result


def main():
    parser = argparse.ArgumentParser(description='Pajio private bundle activation worker')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    root = args.root.absolute()
    if (root.is_symlink() or not root.is_dir() or root.stat().st_uid != os.getuid()
            or root.stat().st_mode & 0o077):
        parser.exit(2, 'activation_private_root_required\n')
    from .control import ControlStore
    from .bundle_activation_pipeline import BundlePipeline
    database = os.environ.get('PAJIO_ACTIVATION_DATABASE_URL', '')
    if not database.startswith('postgresql'):
        parser.exit(2, 'activation_postgres_required\n')
    store = ControlStore(database, activation=True)
    worker = ActivationWorker(ActivationStore(store), BundlePipeline(root))
    try:
        # All instances on this host share the provider ledger and this lock.
        # Other hosts are fenced by SQL generation and the provider root claim.
        with FileLock(root / 'activation.lock', timeout=0):
            while True:
                result = worker.tick()
                print(json.dumps(result), flush=True)
                if args.once:
                    break
                time.sleep(5 if result['state'] != 'idle' else 10)
    except Timeout:
        parser.exit(2, 'activation_service_already_running\n')
    finally:
        store.close()


if __name__ == '__main__':
    main()
