"""Identity-scoped file transfers over existing device command leases."""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Literal

from pydantic import Field

from .commands import Record, DeviceCommand, authorize_command
from .relay import RelayError, encoded, utc
from ..device_files_io import (MAX_BYTES, CHUNK_BYTES, FILE_METHODS, FileChannelError,
    directory_fd, read_regular, source_checked, source_info, id_checked)

QUOTA_BYTES = 200 * 1024 * 1024


class FileSource(Record):
    file_id: str = Field(pattern='^[a-f0-9]{32}$')
    name: str = Field(min_length=1, max_length=180)
    size: int = Field(ge=1, le=MAX_BYTES, strict=True)
    sha256: str = Field(pattern='^[a-f0-9]{64}$')


class TransferRequest(Record):
    request_id: str = Field(pattern='^[a-f0-9]{32}$')
    direction: Literal['to_device', 'from_device', 'list']
    source: FileSource | None = None


class ChunkRequest(Record):
    connection_id: str = Field(min_length=1, max_length=128)
    command_id: str = Field(min_length=1, max_length=128)
    offset: int = Field(ge=0, le=MAX_BYTES, strict=True)
    data: str | None = Field(default=None, max_length=4 * ((CHUNK_BYTES + 2) // 3))


class DeviceFiles:
    def __init__(self, relay, *, actor=None):
        self.relay = relay
        self.actor = actor
        self.root = relay.root / 'file-channel'
        fd = directory_fd(self.root, create=True); os.close(fd)
        with relay.tx() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS file_sources(identity TEXT, id TEXT, source TEXT, blob TEXT,
                    PRIMARY KEY(identity,id));
                CREATE TABLE IF NOT EXISTS file_transfers(identity TEXT, resource TEXT, id TEXT, intent TEXT,
                    direction TEXT, source TEXT, command TEXT UNIQUE, created REAL,
                    PRIMARY KEY(identity,id));
                CREATE TABLE IF NOT EXISTS file_owners(identity TEXT, resource TEXT PRIMARY KEY,
                    actor TEXT NOT NULL, connector TEXT NOT NULL, proof TEXT NOT NULL);
            ''')
            for table in ('file_sources', 'file_transfers'):
                columns = {r[1] for r in db.execute('PRAGMA table_info(' + table + ')')}
                if 'actor' not in columns:
                    db.execute('ALTER TABLE ' + table + " ADD COLUMN actor TEXT NOT NULL DEFAULT ''")

    def bind_owner(self, proof, resource):
        """Operator-only Python entry; no HTTP route and no first-caller adoption.

        Caller must obtain a fresh AccountProof from SSHAdmissionAdapter.check.
        Its exact tenant/instance/identity is checked against this private volume.
        Existing anchors are immutable; owner migration requires separate review.
        """
        import time
        from .device_admission import AccountProof
        from .instance import load_instance
        from .mobile_auth import session_storage_scope
        proof = AccountProof.model_validate(proof)
        instance = load_instance(self.relay.root.parent.parent)
        if (not 0 <= time.time() - proof.observed_at <= 60 or proof.tenant_id != self.relay.tenant
                or proof.tenant_id != instance.tenant_id or proof.instance_id != instance.instance_id):
            raise RelayError('file_owner_proof_invalid', 403)
        actor = session_storage_scope(proof.owner_user_id, proof.tenant_id)
        with self.relay.tx() as db:
            c, _ = self._paired(db, proof.identity_id, resource)
            old = db.execute('SELECT * FROM file_owners WHERE resource=?', (resource,)).fetchone()
            values = (proof.identity_id, resource, actor, c['id'])
            if old:
                if tuple(old[k] for k in ('identity','resource','actor','connector')) != values:
                    raise RelayError('file_owner_binding_changed', 409)
                return {'bound': True, 'resource_id': resource, 'actor': actor}
            db.execute('INSERT INTO file_owners VALUES(?,?,?,?,?)', (*values, encoded(proof.scope())))
        return {'bound': True, 'resource_id': resource, 'actor': actor}

    def _key(self, *values):
        return hashlib.sha256(encoded(values).encode()).hexdigest()

    def _write(self, name, data):
        fd = directory_fd(self.root)
        temporary = '.pending-' + secrets.token_hex(16)
        try:
            out = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                with os.fdopen(out, 'wb', closefd=False) as stream:
                    stream.write(data); stream.flush(); os.fsync(out)
            finally: os.close(out)
            try: os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            except FileExistsError:
                if read_regular(fd, name) != data: raise RelayError('file_blob_conflict')
            os.unlink(temporary, dir_fd=fd); os.fsync(fd)
        finally:
            try: os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError: pass
            os.close(fd)

    def _read(self, name):
        fd = directory_fd(self.root)
        try: return read_regular(fd, name)
        finally: os.close(fd)

    def _paired(self, db, identity, resource):
        matches = [(c, r) for c in db.execute('SELECT * FROM connectors WHERE identity=? AND revoked=0', (identity,))
                   for r in json.loads(c['resources']) if r['resource_id'] == resource]
        if len(matches) != 1: raise RelayError('resource_not_paired', 404)
        return matches[0]

    def _owned(self, db, identity, resource):
        c, spec = self._paired(db, identity, resource)
        row = db.execute('SELECT * FROM file_owners WHERE identity=? AND resource=? AND actor=? AND connector=?',
                         (identity, resource, self.actor, c['id'])).fetchone()
        if not self.actor or not row:
            raise RelayError('file_owner_not_bound', 404)
        return c, spec

    def capabilities(self, identity, resource):
        with self.relay.tx() as db:
            c, spec = self._owned(db, identity, resource)
            supported = set(FILE_METHODS) <= set(spec['methods'])
        item = next(r for r in self.relay.inventory(identity) if r['resource_id'] == resource)
        reason = ('files_permission_required' if not supported else
                  'device_private_or_paused' if item['paused'] or item['control_pending'] else
                  'connector_offline' if not item['online'] else None)
        with self.relay.tx() as db:
            from .device_access import active
            if active(db, resource): reason = 'device_private_or_paused'
        return {'supported': supported, 'available': reason is None, 'reason': reason,
                'max_bytes': MAX_BYTES, 'inbox_label': 'Pajio/Inbox', 'outbox_label': 'Pajio/Outbox'}

    def snapshot(self, identity, resource, workspace, relative):
        # Reuse workspace's fd traversal, not its path-based download helper.
        from ..workspace import _relative, _directory_fd
        _relative(relative)
        with self.relay.tx() as db: self._owned(db, identity, resource)
        directory, _, name = relative.rpartition('/')
        fd = _directory_fd(workspace, directory)
        try: data = read_regular(fd, name)
        finally: os.close(fd)
        source = source_info(name, data)
        blob = self._key(identity, self.actor, source['file_id'])
        with self.relay.tx() as db:
            self._owned(db, identity, resource)
            old = db.execute('SELECT source FROM file_sources WHERE identity=? AND actor=? AND id=?', (identity, self.actor, source['file_id'])).fetchone()
            if not old:
                self._quota(db, identity, source['size'])
                self._write(blob, data)
                db.execute('INSERT INTO file_sources VALUES(?,?,?,?,?)', (identity, source['file_id'], encoded(source), blob, self.actor))
        return source

    def _quota(self, db, identity, addition):
        sizes = [json.loads(r[0])['size'] for r in db.execute('SELECT source FROM file_sources WHERE identity=?', (identity,))]
        sizes += [json.loads(r[0])['size'] for r in db.execute("SELECT source FROM file_transfers WHERE identity=? AND direction='from_device'", (identity,))]
        if sum(sizes) + addition > QUOTA_BYTES or len(sizes) >= 1000:
            raise RelayError('file_channel_quota_exceeded', 413)

    def start(self, identity, resource, request):
        body = request.model_dump(mode='json', exclude_none=True)
        source = body.get('source')
        if (request.direction == 'list') != (source is None): raise RelayError('file_source_invalid', 422)
        if source is not None: source_checked(source)
        intent = self._key(self.actor, resource, body)
        with self.relay.tx() as db:
            c, spec = self._owned(db, identity, resource)
            old = db.execute('SELECT * FROM file_transfers WHERE identity=? AND actor=? AND id=?', (identity, self.actor, request.request_id)).fetchone()
            if old:
                if old['resource'] != resource or old['intent'] != intent: raise RelayError('transfer_request_changed')
                return self._status(db, old)
            method = {'list': 'files.list', 'to_device': 'files.send', 'from_device': 'files.fetch'}[request.direction]
            if method not in spec['methods']: raise RelayError('files_permission_required')
            if request.direction == 'to_device':
                row = db.execute('SELECT * FROM file_sources WHERE identity=? AND actor=? AND id=?', (identity, self.actor, source['file_id'])).fetchone()
                if not row or json.loads(row['source']) != source: raise RelayError('file_source_not_found', 404)
            elif request.direction == 'from_device':
                self._quota(db, identity, source['size'])
                # Fetch only a candidate returned by this identity/device's completed list.
                listed = False
                for r in db.execute("SELECT commands.result FROM file_transfers JOIN commands ON commands.id=file_transfers.command WHERE file_transfers.identity=? AND file_transfers.actor=? AND file_transfers.resource=? AND file_transfers.direction='list' AND commands.state='completed' ORDER BY file_transfers.created DESC LIMIT 20", (identity, self.actor, resource)):
                    result = json.loads(r[0] or '{}')
                    if source in result.get('files', []): listed = True; break
                if not listed: raise RelayError('file_source_not_listed', 409)
            command = self.relay._enqueue(db, identity, resource, method, {'request_id': request.request_id, **({'source': source} if source else {})})
            db.execute('INSERT INTO file_transfers VALUES(?,?,?,?,?,?,?,?,?)',
                       (identity, resource, request.request_id, intent, request.direction, encoded(source), command.command_id, utc().timestamp(), self.actor))
            row = db.execute('SELECT * FROM file_transfers WHERE identity=? AND actor=? AND id=?', (identity, self.actor, request.request_id)).fetchone()
            return self._status(db, row)

    def _status(self, db, row):
        c = db.execute('SELECT state,result FROM commands WHERE id=?', (row['command'],)).fetchone()
        state = {'device_error': 'failed', 'blocked': 'failed'}.get(c['state'], c['state'])
        value = {'request_id': row['id'], 'resource_id': row['resource'], 'direction': row['direction'],
                 'state': state, 'bytes_completed': 0}
        source = json.loads(row['source'])
        if source: value['source'] = source
        result = json.loads(c['result'] or '{}')
        if state == 'completed':
            try:
                if row['direction'] == 'list':
                    if type(result.get('truncated')) is not bool or not isinstance(result.get('files'), list) or len(result['files']) > 50:
                        raise ValueError()
                    for f in result['files']: source_checked(f)
                    value.update(files=result['files'], truncated=result['truncated'])
                elif result.get('source') != source or result.get('receipt_id') != row['id']:
                    raise ValueError()
                else: value['bytes_completed'] = source['size']
            except (ValueError, TypeError, KeyError):
                value.update(state='unknown', error='file_receipt_invalid', bytes_completed=0)
        elif state in {'failed', 'unknown'}:
            value['error'] = 'file_transfer_unknown_no_replay' if state == 'unknown' else 'file_transfer_failed'
        return value

    def status(self, identity, resource, request_id):
        id_checked(request_id)
        with self.relay.tx() as db:
            self._owned(db, identity, resource); self.relay.expire(db)
            row = db.execute('SELECT * FROM file_transfers WHERE identity=? AND actor=? AND resource=? AND id=?', (identity, self.actor, resource, request_id)).fetchone()
            if not row: raise RelayError('file_transfer_not_found', 404)
            return self._status(db, row)

    def history(self, identity, resource):
        with self.relay.tx() as db:
            self._owned(db, identity, resource); self.relay.expire(db)
            return [self._status(db, row) for row in db.execute('SELECT * FROM file_transfers WHERE identity=? AND actor=? AND resource=? ORDER BY created DESC LIMIT 50', (identity, self.actor, resource))]

    def _transport(self, db, token, request, direction):
        c = self.relay.current(db, token, request.connection_id)
        self.relay.expire(db)
        row = db.execute('SELECT * FROM commands WHERE id=? AND connector=?', (request.command_id, c['id'])).fetchone()
        if not row or row['state'] != 'executing': raise RelayError('file_command_not_executing')
        command = DeviceCommand.model_validate_json(row['envelope'])
        transfer = db.execute('SELECT * FROM file_transfers WHERE command=? AND identity=? AND direction=?', (command.command_id, c['identity'], direction)).fetchone()
        if not transfer: raise RelayError('file_transfer_not_found', 404)
        owner = db.execute('SELECT 1 FROM file_owners WHERE identity=? AND resource=? AND actor=? AND connector=?',
                           (c['identity'], command.resource_id, transfer['actor'], c['id'])).fetchone()
        if not transfer['actor'] or not owner: raise RelayError('file_owner_not_bound', 404)
        from .device_access import active
        from .device_maintenance import guard
        guard(db, command.resource_id)
        if active(db, command.resource_id) or not self.relay.control_ready(db, command.resource_id, c['connection']):
            raise RelayError('device_private_or_paused')
        lease = db.execute('SELECT * FROM leases WHERE resource=?', (command.resource_id,)).fetchone()
        if not lease or lease['command'] != command.command_id or lease['epoch'] != command.lease_epoch:
            raise RelayError('lease_stale')
        authorize_command(command, **self.relay.authorities(c, command), now=utc())
        return transfer, json.loads(transfer['source'])

    def chunk(self, token, request, *, upload):
        with self.relay.tx() as db:
            row, source = self._transport(db, token, request, 'from_device' if upload else 'to_device')
            offset = request.offset
            if offset % CHUNK_BYTES or offset >= max(source['size'], 1): raise RelayError('file_offset_invalid', 422)
            length = min(CHUNK_BYTES, source['size'] - offset)
            if upload:
                try: data = base64.b64decode(request.data or '', validate=True)
                except (ValueError, TypeError): raise RelayError('file_chunk_invalid', 422) from None
                if len(data) != length: raise RelayError('file_chunk_invalid', 422)
                self._write(self._key(row['identity'], row['actor'], row['id'], offset), data)
                return {'accepted': True, 'offset': offset, 'size': len(data)}
            if request.data is not None: raise RelayError('file_chunk_invalid', 422)
            saved = db.execute('SELECT blob,source FROM file_sources WHERE identity=? AND actor=? AND id=?', (row['identity'], row['actor'], source['file_id'])).fetchone()
            if not saved or json.loads(saved['source']) != source: raise RelayError('file_source_not_found', 404)
            data = self._read(saved['blob'])
            if source_info(source['name'], data) != source: raise RelayError('file_hash_changed')
            return {'offset': offset, 'data': base64.b64encode(data[offset:offset + length]).decode()}

    def collected(self, identity, transfer):
        source = transfer['source']
        data = b''.join(self._read(self._key(identity, self.actor, transfer['request_id'], offset))
                        for offset in range(0, max(source['size'], 1), CHUNK_BYTES))
        if source_info(source['name'], data) != source: raise RelayError('file_hash_changed')
        return data


def install_file_transport(app, relay, token):
    from fastapi import Request
    channel = DeviceFiles(relay)
    @app.post('/v1/files/download')
    async def download(value: ChunkRequest, request: Request):
        return channel.chunk(token(request), value, upload=False)
    @app.post('/v1/files/upload')
    async def upload(value: ChunkRequest, request: Request):
        return channel.chunk(token(request), value, upload=True)


def install_device_file_routes(app, store, runtime_for, relay_for):
    import asyncio
    from fastapi import Request, HTTPException
    from ..workspace_upload import WorkspaceImports
    imports = WorkspaceImports(store)
    class WorkspaceSource(Record):
        path: str = Field(min_length=1, max_length=2048)

    def channel(request):
        from ..task_visibility import request_owner
        actor = request_owner(request, local_devices=False)
        if request.scope.get('pajio.private_owner_scope') != actor:
            raise HTTPException(403, 'files_private_owner_required')
        return DeviceFiles(relay_for(), actor=actor)

    def invoke(fn, *args):
        try: return fn(*args)
        except RelayError as e: raise HTTPException(e.status, e.code) from None
        except (FileChannelError, OSError, ValueError): raise HTTPException(409, 'file_channel_unavailable') from None

    def finished(ch, identity, value):
        if value['direction'] == 'from_device' and value['state'] == 'completed':
            try:
                data = ch.collected(identity, value)
                with store.connection() as db:
                    old = db.execute('SELECT * FROM workspace_imports WHERE identity_id=? AND request_key=?',
                                     (identity, value['request_id'])).fetchone()
                if old:
                    # A status refresh must not recreate a file the user removed,
                    # or overwrite an edit made after the original completed import.
                    from ..workspace import _directory_fd
                    directory, _, leaf = old['path'].rpartition('/')
                    fd = _directory_fd(runtime_for(identity).workspace, directory)
                    try:
                        existing = read_regular(fd, leaf)
                        info = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
                    finally: os.close(fd)
                    if old['digest'] != value['source']['sha256'] or source_info(leaf, existing) != value['source']:
                        raise RelayError('file_workspace_result_changed')
                    value['workspace_file'] = {'path': old['path'], 'size': len(existing), 'modified': info.st_mtime}
                    return value
                receipt = imports.upload(identity, runtime_for(identity).workspace, value['request_id'], value['source']['name'], data,
                                         allow_recreate=False)
                value['workspace_file'] = receipt['file']
            except (OSError, ValueError, RelayError, HTTPException):
                value.update(state='unknown', bytes_completed=0, error='file_workspace_import_pending')
        return value

    prefix = '/api/devices/{resource}/files'
    @app.get(prefix)
    async def capabilities(resource: str, request: Request):
        return await asyncio.to_thread(invoke, channel(request).capabilities, request.state.identity_id, resource)

    @app.post(prefix + '/workspace-source')
    async def snapshot(resource: str, value: WorkspaceSource, request: Request):
        identity = request.state.identity_id
        return await asyncio.to_thread(invoke, channel(request).snapshot, identity, resource, runtime_for(identity).workspace, value.path)

    @app.post(prefix + '/transfers')
    async def start(resource: str, value: TransferRequest, request: Request):
        ch = channel(request); identity = request.state.identity_id
        return await asyncio.to_thread(lambda: finished(ch, identity, invoke(ch.start, identity, resource, value)))

    @app.get(prefix + '/transfers/{request_id}')
    async def status(resource: str, request_id: str, request: Request):
        ch = channel(request); identity = request.state.identity_id
        return await asyncio.to_thread(lambda: finished(ch, identity, invoke(ch.status, identity, resource, request_id)))

    @app.get(prefix + '/transfers')
    async def history(resource: str, request: Request):
        ch = channel(request); identity = request.state.identity_id
        return {'transfers': await asyncio.to_thread(lambda: [finished(ch, identity, v) for v in invoke(ch.history, identity, resource)])}


def main():
    """Private operator SSH entry. Reads fresh admission proof from stdin."""
    import argparse
    import sys
    from .relay import instance_relay
    parser = argparse.ArgumentParser(description='Bind an existing device to its verified personal owner.')
    parser.add_argument('action', choices=['bind-owner'])
    parser.add_argument('--instance-root', required=True, type=Path)
    parser.add_argument('--resource-id', required=True)
    args = parser.parse_args()
    raw = sys.stdin.buffer.read(16385)
    if len(raw) > 16384:
        raise SystemExit('file_owner_proof_invalid')
    try:
        result = DeviceFiles(instance_relay(args.instance_root)).bind_owner(json.loads(raw), args.resource_id)
    except (ValueError, OSError):
        raise SystemExit('file_owner_binding_refused') from None
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__': main()
