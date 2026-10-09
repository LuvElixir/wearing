"""Read-only operator admission from authoritative control and tenant metadata.

Neither caller-supplied active flags nor cached receipts authorize provisioning.
Remote inspection uses existing SSH host trust and never returns credentials.
"""
from contextlib import contextmanager
import inspect
import json
import math
from pathlib import Path
import re
import shlex
import subprocess
import time

from pydantic import Field
from .commands import Identifier, Record


class AdmissionError(ValueError):
    pass


class AccountProof(Record):
    tenant_id: Identifier
    identity_id: Identifier
    instance_id: Identifier
    owner_user_id: Identifier
    ownership_revision: int = Field(strict=True, ge=1)
    member_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    observed_at: float

    def scope(self):
        return self.model_dump(exclude={'observed_at'})


@contextmanager
def readonly_control(store):
    with store.engine.connect() as db:
        try:
            if store.postgres:
                db.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                from wearing.cloud.postgres import scoped
                scoped(db)
            else:
                db.exec_driver_sql('PRAGMA query_only=ON')
                db.exec_driver_sql('BEGIN')
            yield db
        finally:
            db.rollback()
            if not store.postgres:
                db.exec_driver_sql('PRAGMA query_only=OFF')


def control_evidence(store, tenant_id):
    """Only metadata SELECTs, with the existing operator-role/RLS boundary."""
    import json
    import time
    from sqlalchemy import select
    from wearing.cloud.control import ownership, routes, members, digest
    if not store.operator:
        raise AdmissionError('control_operator_required')
    with readonly_control(store) as db:
        if not store.tenant_editable(db, tenant_id):
            raise AdmissionError('account_frozen_or_deleting')
        row = db.execute(select(ownership).where(ownership.c.tenant_id == tenant_id)).mappings().first()
        route = db.execute(select(routes.c.instance_id).where(routes.c.tenant_id == tenant_id)).scalar_one_or_none()
        people = sorted((r.user_id, bool(r.active)) for r in db.execute(select(members).where(members.c.tenant_id == tenant_id)))
        if not row:
            raise AdmissionError('account_registry_missing')
        if row['classification'] != 'private':
            raise AdmissionError('account_not_private')
        if (len(people) != 1 or people != [(row['owner_user_id'], True)] or row['member_count'] != 1
                or row['member_digest'] != digest(json.dumps(people, separators=(',', ':')))
                or not route or route != row['instance_id']):
            raise AdmissionError('account_ownership_unconfirmed')
        if not store.user_available(db, row['owner_user_id']):
            raise AdmissionError('account_frozen_or_deleting')
        return {'tenant_id': tenant_id, 'instance_id': route, 'owner_user_id': row['owner_user_id'],
                'ownership_revision': row['revision'], 'member_digest': row['member_digest'],
                'observed_at': time.time()}


def tenant_evidence(root, tenant_id, identity_id, instance_id):
    """Read only the identity ID from its verified private instance database."""
    import os
    from pathlib import Path
    import sqlite3
    import time
    from wearing.cloud.instance import load_instance
    root = Path(root)
    instance = load_instance(root)
    if instance.tenant_id != tenant_id or instance.instance_id != instance_id:
        raise AdmissionError('tenant_instance_mismatch')
    path = root / 'data/wearing.sqlite3'
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise AdmissionError('tenant_metadata_unavailable')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5) as db:
        db.execute('PRAGMA query_only=ON')
        if not db.execute('SELECT 1 FROM identities WHERE id=?', (identity_id,)).fetchone():
            raise AdmissionError('identity_not_owned')
    # Recheck deletion marker and volume ownership after the identity query.
    if load_instance(root) != instance:
        raise AdmissionError('tenant_instance_changed')
    return {'tenant_id': tenant_id, 'identity_id': identity_id, 'instance_id': instance_id,
            'observed_at': time.time()}


def remote_entry():
    import json
    import os
    from pathlib import Path
    import pwd
    import sys
    from wearing.cloud.instance import read_private
    from wearing.cloud.gateway import load_gateway, operator_store
    p = json.load(sys.stdin)
    try:
        # Root reads only the existing private operator credential; then drops
        # to the fixed service user before opening its private instance files.
        if os.geteuid() != 0:
            raise AdmissionError('trusted_metadata_privilege_required')
        account = pwd.getpwnam(p['account'])
        if account.pw_uid == 0:
            raise AdmissionError('service_account_required')
        operator_url = None
        if p['action'] == 'control':
            values = dict(line.split('=', 1) for line in read_private(Path(p['operator_env'])).splitlines()
                          if line and not line.startswith('#') and '=' in line)
            operator_url = values.get('WEARING_CONTROL_OPERATOR_DATABASE_URL')
            if not operator_url:
                raise AdmissionError('control_operator_required')
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
        if p['action'] == 'control':
            config = load_gateway(Path(p['root']))
            if config.database_url.get_secret_value().startswith('sqlite:'):
                raise AdmissionError('production_control_database_required')
            store = operator_store(config, database_url=operator_url)
            try: result = control_evidence(store, p['tenant_id'])
            finally: store.close()
        elif p['action'] == 'tenant':
            result = tenant_evidence(p['root'], p['tenant_id'], p['identity_id'], p['instance_id'])
        else:
            raise AdmissionError('metadata_action_not_allowed')
        print(json.dumps(result))
    except Exception as error:
        code = str(error) if isinstance(error, AdmissionError) else 'account_evidence_unavailable'
        print(json.dumps({'error': code}))
        sys.exit(1)


def remote_source():
    return ('from contextlib import contextmanager\nclass AdmissionError(ValueError): pass\n'
            + inspect.getsource(readonly_control) + '\n' + inspect.getsource(control_evidence)
            + '\n' + inspect.getsource(tenant_evidence) + '\n' + inspect.getsource(remote_entry)
            + '\nremote_entry()\n')


class MetadataTarget(Record):
    host: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$')
    python: str = '/opt/wearing/venv/bin/python'
    account: str = Field(default='wearing', pattern=r'^[a-z_][a-z0-9_-]{0,31}$')
    root: str


class AdmissionSources(Record):
    control: MetadataTarget
    operator_env: str
    tenants: dict[Identifier, MetadataTarget]


class TrustedSSHAdmission:
    def __init__(self, *, ssh_config, sources, runner=subprocess.run, clock=time.time):
        self.config = Path(ssh_config).expanduser().resolve()
        if not self.config.is_file():
            raise AdmissionError('trusted_ssh_config_required')
        self.sources = AdmissionSources.model_validate(sources)
        for path in [self.sources.operator_env, *[v for t in [self.sources.control, *self.sources.tenants.values()] for v in (t.python, t.root)]]:
            if not path.startswith('/') or any(ord(c) < 32 for c in path):
                raise AdmissionError('invalid_metadata_path')
        self.runner, self.clock = runner, clock

    def _read(self, target, action, **data):
        command = shlex.join(['sudo', '-n', target.python, '-c', remote_source()])
        argv = ['ssh', '-F', str(self.config), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'ConnectTimeout=10', target.host, command]
        try:
            response = self.runner(argv, input=json.dumps({'action': action, 'root': target.root,
                 'account': target.account, **data}), capture_output=True, text=True, timeout=45)
            if len(response.stdout) > 8192:
                raise ValueError()
            result = json.loads(response.stdout)
            if response.returncode or result.get('error'):
                code = result.get('error')
                raise AdmissionError(code if isinstance(code, str) and re.fullmatch(r'[a-z_]{1,80}', code)
                                     else 'account_evidence_unavailable')
            observed = result.get('observed_at')
            if type(observed) not in (int, float) or not math.isfinite(observed) or not 0 <= self.clock() - observed <= 60:
                raise AdmissionError('account_evidence_stale')
            return result
        except AdmissionError:
            raise
        except Exception:
            raise AdmissionError('account_evidence_unavailable') from None

    def check(self, spec):
        import hashlib
        target = self.sources.tenants.get(spec.tenant_id)
        if not target:
            raise AdmissionError('tenant_metadata_target_unregistered')
        source = self.sources.control
        before = self._read(source, 'control', tenant_id=spec.tenant_id, operator_env=self.sources.operator_env)
        tenant = self._read(target, 'tenant', tenant_id=spec.tenant_id, identity_id=spec.identity_id,
                            instance_id=before.get('instance_id'))
        after = self._read(source, 'control', tenant_id=spec.tenant_id, operator_env=self.sources.operator_env)
        if {k:v for k,v in before.items() if k != 'observed_at'} != {k:v for k,v in after.items() if k != 'observed_at'}:
            raise AdmissionError('account_changed_during_check')
        if (tenant.get('tenant_id') != spec.tenant_id or after.get('tenant_id') != spec.tenant_id
                or tenant.get('identity_id') != spec.identity_id or tenant.get('instance_id') != after.get('instance_id')):
            raise AdmissionError('account_scope_mismatch')
        observed = min(tenant['observed_at'], before['observed_at'], after['observed_at'])
        if not 0 <= self.clock() - observed <= 60:
            raise AdmissionError('account_evidence_stale')
        selected = {'control': source.model_dump(), 'tenant': target.model_dump(),
                    'operator_env': self.sources.operator_env}
        digest = hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        try:
            return AccountProof.model_validate({**after, 'identity_id': spec.identity_id,
                       'source_sha256': digest, 'observed_at': observed})
        except ValueError:
            raise AdmissionError('account_evidence_unavailable') from None
