import asyncio
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import httpx
import pytest

from wearing.cloud.commands import DeviceCommand
from wearing.cloud.device_files import DeviceFiles, TransferRequest, ChunkRequest, install_device_file_routes
from wearing.cloud.relay import (RelayStore, RelayError, PairRequest, ConnectionRequest, PollRequest,
    ClaimRequest, ResultRequest, ResourceControl, create_relay_app)
from wearing.cloud.instance import initialize_instance
from wearing.config import write_private_json
from wearing.device_files_io import (InboxOutbox, source_info, FileChannelError, MAX_BYTES, FILE_METHODS,
                                    directory_fd, read_regular)
from wearing.device_files_native import dispatch, execute_transfer
from wearing.device_gateway import DeviceGateway, GatewayScope
from wearing.connectors.remote.client import Connector
from wearing.store import Store

TOKEN = 'a' * 64
RID = 'computer_test'
from wearing.cloud.mobile_auth import session_storage_scope
ACTOR = session_storage_scope('user_test', 'tenant_test')
SPEC = {'resource_id': RID, 'name': 'Synthetic desktop', 'kind': 'computer', 'methods': ['computer.status', *FILE_METHODS]}


@pytest.fixture
def fixture(tmp_path):
    root = tmp_path.resolve() / 'tenant'
    initialize_instance(root, 'tenant_test', 'https://app.example')
    relay = RelayStore(root / 'data/device-relay', 'tenant_test')
    bundle = relay.pair_code('daily', [SPEC], [])
    relay.pair(PairRequest(code=bundle['code'], token=TOKEN))
    conn = relay.connect(TOKEN, ConnectionRequest())['connection_id']
    relay.poll(TOKEN, PollRequest(connection_id=conn, availability={RID: True}))
    channel = DeviceFiles(relay, actor=ACTOR)
    from wearing.cloud.device_admission import AccountProof
    from wearing.cloud.instance import load_instance
    import time
    channel.bind_owner(AccountProof(tenant_id='tenant_test', identity_id='daily',
        instance_id=load_instance(root).instance_id, owner_user_id='user_test', ownership_revision=1,
        member_digest='a'*64, source_sha256='b'*64, observed_at=time.time()), RID)
    workspace = root / 'workspace'; workspace.mkdir()
    local = root / 'local'; local.mkdir()
    write_private_json(local / 'connector.json', {**bundle, 'endpoint': 'https://relay.example', 'ca_pem': 'test',
        'token': TOKEN, 'local_data': str(root / 'data'), 'connection_id': conn})
    io = InboxOutbox(root / 'native' / 'Pajio'); io.prepare()
    return root, relay, bundle, conn, channel, workspace, local, io


def command(relay, request_id):
    with relay.tx() as db:
        row = db.execute('SELECT envelope FROM commands JOIN file_transfers ON file_transfers.command=commands.id WHERE file_transfers.id=?', (request_id,)).fetchone()
        return DeviceCommand.model_validate_json(row[0])


async def execute(fixture, monkeypatch, request_id, *, break_after_commit=False):
    root, relay, bundle, conn, channel, workspace, local, io = fixture
    import wearing.device_files_native as native
    class Bound:
        def __init__(self, resource): assert resource == RID
        def call(self, action, **params):
            value = dispatch(io, action, params)
            if break_after_commit and action == 'send': raise OSError('connection dropped after commit')
            return value
    monkeypatch.setattr(native, 'NativeFiles', Bound)
    adapter = SimpleNamespace(gateway=DeviceGateway(root / 'gateway'))
    relay_app = create_relay_app(root)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=relay_app), base_url='https://relay.example',
                                 headers={'Authorization': 'Bearer ' + TOKEN}) as client:
        connector = Connector(local, adapter)
        await connector.execute(client, command(relay, request_id))
    return adapter


@pytest.mark.parametrize('size', [2800000, MAX_BYTES])
async def test_real_api_connector_multichunk_round_trip(fixture, monkeypatch, size):
    """Actual API models, SQLite leases/journal, ASGI chunk transport and filesystem."""
    root, relay, bundle, conn, channel, workspace, local, io = fixture
    from fastapi import FastAPI, Request
    app = FastAPI()
    @app.middleware('http')
    async def identity(request: Request, next):
        request.scope['pajio.storage_scope'] = ACTOR
        request.scope['pajio.private_owner_scope'] = ACTOR
        request.state.identity_id = request.headers.get('test-identity', 'daily')
        return await next(request)
    store = Store(root / 'files.sqlite3')
    install_device_file_routes(app, store, lambda identity: SimpleNamespace(workspace=workspace), lambda: relay)
    body = (b'Synthetic data\0' * (size // 15 + 1))[:size]
    (workspace / '材料.bin').write_bytes(body)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://app.example') as client:
        prefix = f'/api/devices/{RID}/files'
        assert (await client.get(prefix)).json()['available'] is True
        reply = await client.post(prefix + '/workspace-source', json={'path': '材料.bin'})
        assert reply.status_code == 200, reply.text
        source = reply.json()
        assert source['sha256'] == hashlib.sha256(body).hexdigest()
        request = {'request_id': '1' * 32, 'direction': 'to_device', 'source': source}
        assert (await client.post(prefix + '/transfers', json=request)).json()['state'] == 'queued'
        assert (await client.post(prefix + '/transfers', json=request)).json()['state'] == 'queued'
        await execute(fixture, monkeypatch, '1' * 32)
        status = (await client.get(prefix + '/transfers/' + '1' * 32)).json()
        assert status['state'] == 'completed' and status['bytes_completed'] == len(body)
        assert (io.root / 'Inbox' / ('1' * 32 + '-材料.bin')).read_bytes() == body
        assert (io.root / 'Inbox' / ('1' * 32 + '-材料.bin')).stat().st_mode & 0o111 == 0
        assert (await client.post(prefix + '/transfers', json=request)).json()['state'] == 'completed'
        (io.root / 'Outbox' / 'result.txt').write_bytes(body)
        assert (await client.post(prefix + '/transfers', json={'request_id': '2' * 32, 'direction': 'list'})).status_code == 200
        await execute(fixture, monkeypatch, '2' * 32)
        listed = (await client.get(prefix + '/transfers/' + '2' * 32)).json()
        assert listed['state'] == 'completed' and len(listed['files']) == 1
        result = listed['files'][0]
        request = {'request_id': '3' * 32, 'direction': 'from_device', 'source': result}
        assert (await client.post(prefix + '/transfers', json=request)).status_code == 200
        await execute(fixture, monkeypatch, '3' * 32)
        fetched = (await client.get(prefix + '/transfers/' + '3' * 32)).json()
        assert fetched['state'] == 'completed', fetched
        assert (workspace / fetched['workspace_file']['path']).read_bytes() == body
        assert len((await client.get(prefix + '/transfers')).json()['transfers']) == 3
        saved = workspace / fetched['workspace_file']['path']
        saved.unlink()
        refreshed = (await client.get(prefix + '/transfers/' + '3' * 32)).json()
        assert refreshed['state'] == 'unknown' and not saved.exists()
        saved.write_bytes(b'user edited this file')
        assert (await client.get(prefix + '/transfers/' + '3' * 32)).json()['state'] == 'unknown'
        assert saved.read_bytes() == b'user edited this file'
        assert (await client.get(prefix + '/transfers/' + '1' * 32, headers={'test-identity': 'other'})).status_code == 404
        with relay.tx() as db: assert db.execute('SELECT COUNT(*) FROM commands').fetchone()[0] == 3


def test_snapshot_is_immutable_owner_scoped_and_symlink_safe(fixture, tmp_path):
    root, relay, bundle, conn, channel, workspace, local, io = fixture
    path = workspace / 'safe.txt'; path.write_bytes(b'first')
    source = channel.snapshot('daily', RID, workspace, 'safe.txt')
    path.write_bytes(b'second')
    assert channel.snapshot('daily', RID, workspace, 'safe.txt') != source
    with pytest.raises(RelayError): channel.snapshot('other', RID, workspace, 'safe.txt')
    (workspace / 'linked.txt').symlink_to(path)
    with pytest.raises(OSError): channel.snapshot('daily', RID, workspace, 'linked.txt')
    (workspace / 'folder').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError): channel.snapshot('daily', RID, workspace, 'folder/outside.txt')
    with pytest.raises(ValueError): channel.start('daily', RID, TransferRequest(request_id='1'*32, direction='to_device', source={**source, 'name': '../x'}))
    channel.start('daily', RID, TransferRequest(request_id='1'*32, direction='to_device', source=source))
    with pytest.raises(RelayError, match='request_changed'):
        channel.start('daily', RID, TransferRequest(request_id='1'*32, direction='list'))


async def test_unknown_after_native_commit_never_replays(fixture, monkeypatch):
    root, relay, bundle, conn, channel, workspace, local, io = fixture
    (workspace / 'doc.txt').write_bytes(b'data')
    source = channel.snapshot('daily', RID, workspace, 'doc.txt')
    request = TransferRequest(request_id='1'*32, direction='to_device', source=source)
    channel.start('daily', RID, request)
    await execute(fixture, monkeypatch, '1'*32, break_after_commit=True)
    assert channel.status('daily', RID, '1'*32)['state'] == 'unknown'
    assert len(list((io.root / 'Inbox').iterdir())) == 1
    await execute(fixture, monkeypatch, '1'*32)
    assert channel.start('daily', RID, request)['state'] == 'unknown'
    assert len(list((io.root / 'Inbox').iterdir())) == 1
    with relay.tx() as db: assert db.execute('SELECT COUNT(*) FROM commands').fetchone()[0] == 1


def test_chunks_reject_other_connector_stale_lease_pause_and_changed_bytes(fixture):
    root, relay, bundle, conn, channel, workspace, local, io = fixture
    (workspace / 'doc.txt').write_bytes(b'data')
    source = channel.snapshot('daily', RID, workspace, 'doc.txt')
    channel.start('daily', RID, TransferRequest(request_id='1'*32, direction='to_device', source=source))
    cmd = command(relay, '1'*32)
    req = ChunkRequest(connection_id=conn, command_id=cmd.command_id, offset=0)
    with pytest.raises(RelayError, match='not_executing'): channel.chunk(TOKEN, req, upload=False)
    relay.claim(TOKEN, ClaimRequest(connection_id=conn, command_id=cmd.command_id))
    assert base64.b64decode(channel.chunk(TOKEN, req, upload=False)['data']) == b'data'
    with pytest.raises(RelayError): channel.chunk('z'*64, req, upload=False)
    with pytest.raises(RelayError): channel.chunk(TOKEN, req.model_copy(update={'connection_id': 'other'}), upload=False)
    with pytest.raises(RelayError, match='offset'): channel.chunk(TOKEN, req.model_copy(update={'offset': 1}), upload=False)
    relay.control('daily', ResourceControl(resource_id=RID, paused=True, expected_generation=0))
    with pytest.raises(RelayError): channel.chunk(TOKEN, req, upload=False)
    assert channel.status('daily', RID, '1'*32)['state'] == 'unknown'


def test_outbox_only_regular_bounded_files_and_no_path_or_install(fixture):
    *_, io = fixture
    path = io.root / 'Outbox' / 'data.apk'; path.write_bytes(b'not an installed application')
    (io.root / 'Outbox' / 'link').symlink_to(path)
    (io.root / 'Outbox' / 'big').write_bytes(b'a' * (MAX_BYTES + 1))
    os.mkfifo(io.root / 'Outbox' / 'pipe')
    result = io.listing()
    assert [x['name'] for x in result['files']] == ['data.apk']
    source = result['files'][0]
    assert io.fetch(source) == path.read_bytes()
    path.write_bytes(b'changed')
    with pytest.raises(FileChannelError, match='changed'): io.fetch(source)
    data = b'#!/bin/sh\nfalse\n'
    source = source_info('script.sh', data)
    first = io.send('a'*32, source, data)
    assert io.send('a'*32, source, data)['replayed'] is True
    saved = io.root / 'Inbox' / first['destination_name']
    assert saved.stat().st_mode & 0o111 == 0
    saved.unlink(); saved.symlink_to(path)
    with pytest.raises(OSError): io.send('a'*32, source, data)
    with pytest.raises(FileChannelError): dispatch(io, 'shell', {'command': 'id'})


def test_file_permission_does_not_widen_existing_input(fixture):
    from wearing.cloud.device_permissions import create_permission, ChangePermission
    root, relay, bundle, conn, channel, workspace, local, io = fixture
    write_private_json(root/'data/device-endpoint.json', {'endpoint': 'https://relay.example', 'ca_pem': 'test'})
    rev = relay.inventory('daily')[0]['permission_revision']
    update = create_permission(relay, root, 'daily', ChangePermission(request_id='a'*32, resource_id=RID,
        revision=rev, mode='files', file_access=False))
    assert update['resources'][0]['methods'] == ['computer.status']


def test_exact_20mb_limit_and_hash_failure_never_publishes(fixture):
    *_, io = fixture
    data = b'x' * MAX_BYTES
    source = source_info('maximum.bin', data)
    io.send('a'*32, source, data)
    assert (io.root/'Inbox'/('a'*32+'-maximum.bin')).stat().st_size == MAX_BYTES
    with pytest.raises(FileChannelError, match='too_large'): source_info('oversize.bin', data + b'x')
    with pytest.raises(FileChannelError, match='hash_changed'): io.send('b'*32, source, b'y'*MAX_BYTES)
    assert not (io.root/'Inbox'/('b'*32+'-maximum.bin')).exists()
    with pytest.raises(FileChannelError): source_info('empty.txt', b'')


def test_hardlinks_and_replaced_directory_do_not_expose_other_files(fixture):
    root, *_, io = fixture
    secret = root/'outside.txt'; secret.write_bytes(b'not in the shared directory')
    os.link(secret, io.root/'Outbox'/'hardlink.txt')
    assert io.listing() == {'files': [], 'truncated': False}
    (io.root/'Outbox'/'hardlink.txt').unlink()
    (io.root/'Outbox').rmdir(); (io.root/'Outbox').symlink_to(root)
    with pytest.raises(OSError): io.listing()


async def test_local_private_handoff_blocks_file_access_even_if_server_stale(fixture, monkeypatch):
    root, relay, bundle, conn, channel, workspace, local, io = fixture
    import wearing.device_files_native as native
    touched = []
    class Bound:
        def __init__(self, resource): pass
        def call(self, action, **params): touched.append(action); return {}
    monkeypatch.setattr(native, 'NativeFiles', Bound)
    channel.start('daily', RID, TransferRequest(request_id='1'*32, direction='list'))
    gateway = DeviceGateway(root/'gateway', private_access_ready=True)
    scope = GatewayScope(tenant_id='tenant_test', identity_id='daily', user_id='user_test',
                         connector_id=bundle['connector_id'], resource_id=RID)
    gateway.begin_human(scope, 'human_'+'a'*32, expected_epoch=gateway.snapshot(RID)['epoch'])
    with pytest.raises(Exception):
        await execute_transfer(SimpleNamespace(gateway=gateway), command(relay, '1'*32), None, conn)
    assert touched == []


async def test_cancellation_keeps_native_lock_until_worker_stops(fixture, monkeypatch):
    root, relay, bundle, conn, channel, workspace, local, io = fixture
    import wearing.device_files_native as native
    entered, release = threading.Event(), threading.Event()
    class Bound:
        def __init__(self, resource): pass
        def call(self, action, **params):
            entered.set(); assert release.wait(3); return {'files': [], 'truncated': False}
    monkeypatch.setattr(native, 'NativeFiles', Bound)
    channel.start('daily', RID, TransferRequest(request_id='1'*32, direction='list'))
    gateway = DeviceGateway(root/'gateway')
    task = asyncio.create_task(execute_transfer(SimpleNamespace(gateway=gateway), command(relay, '1'*32), None, conn))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel(); await asyncio.sleep(.03)
    assert not task.done()
    with pytest.raises(Exception):
        with gateway.native_lock(RID): pass
    release.set()
    with pytest.raises(asyncio.CancelledError): await task
    with gateway.native_lock(RID): pass


async def test_transport_auth_happens_before_upload_body_and_no_browser_access(fixture):
    root, relay, *_ = fixture
    app = create_relay_app(root)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://relay.example') as client:
        assert (await client.post('/v1/files/upload', content=b'not-json')).status_code == 401
        assert (await client.post('/v1/files/upload', content=b'not-json', headers={'Origin': 'https://other.example'})).status_code == 403
        assert (await client.post('/v1/files/upload', content=b'not-json', headers={'Authorization': 'Bearer '+TOKEN})).status_code == 422


async def test_concurrent_first_status_cannot_recreate_deleted_import(fixture, monkeypatch):
    from fastapi import FastAPI, Request
    from wearing.workspace_upload import WorkspaceImports
    root, relay, bundle, conn, channel, workspace, local, io = fixture
    (io.root/'Outbox'/'result.txt').write_bytes(b'synthetic output')
    channel.start('daily', RID, TransferRequest(request_id='1'*32, direction='list'))
    await execute(fixture, monkeypatch, '1'*32)
    source = channel.status('daily', RID, '1'*32)['files'][0]
    channel.start('daily', RID, TransferRequest(request_id='2'*32, direction='from_device', source=source))
    await execute(fixture, monkeypatch, '2'*32)
    app = FastAPI()
    @app.middleware('http')
    async def identity(request: Request, next):
        request.scope['pajio.storage_scope'] = ACTOR
        request.scope['pajio.private_owner_scope'] = ACTOR
        request.state.identity_id = 'daily'; return await next(request)
    install_device_file_routes(app, Store(root/'files.sqlite3'), lambda _: SimpleNamespace(workspace=workspace), lambda: relay)
    original = WorkspaceImports.upload
    barrier, deleted, mutex = threading.Barrier(2), threading.Event(), threading.Lock()
    calls = 0
    def race(self, *args, **kwargs):
        nonlocal calls
        with mutex: calls += 1; first = calls == 1
        barrier.wait(3)  # Both GETs already observed old=None outside the transaction.
        if first:
            result = original(self, *args, **kwargs)
            (workspace/result['file']['path']).unlink()
            deleted.set()
            return result
        assert deleted.wait(3)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(WorkspaceImports, 'upload', race)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://app.example') as client:
        replies = await asyncio.gather(*(client.get(f'/api/devices/{RID}/files/transfers/'+'2'*32) for _ in range(2)))
    assert sorted(r.json()['state'] for r in replies) == ['completed', 'unknown']
    assert not (workspace/'imports'/('2'*32)/'result.txt').exists()


def test_old_grants_stay_disabled_and_explicit_files_permission_is_two_sided(fixture):
    from wearing.cloud.device_permissions import create_permission, ChangePermission, apply_permission, ApplyPermission
    root, relay, bundle, conn, channel, workspace, local, io = fixture
    with relay.tx() as db:
        db.execute('UPDATE connectors SET resources=?', (json.dumps([{**SPEC, 'methods': ['computer.status', 'computer.observe']}]),))
    assert channel.capabilities('daily', RID)['reason'] == 'files_permission_required'
    with pytest.raises(RelayError, match='files_permission_required'):
        channel.start('daily', RID, TransferRequest(request_id='1'*32, direction='list'))
    write_private_json(root/'data/device-endpoint.json', {'endpoint': 'https://relay.example', 'ca_pem': 'test'})
    revision = relay.inventory('daily')[0]['permission_revision']
    old_input = create_permission(relay, root, 'daily', ChangePermission(request_id='a'*32, resource_id=RID,
        revision=revision, mode='input'))
    assert not set(old_input['resources'][0]['methods']).intersection(FILE_METHODS)
    files = create_permission(relay, root, 'daily', ChangePermission(request_id='b'*32, resource_id=RID,
        revision=revision, mode='files', file_access=True))
    assert set(files['resources'][0]['methods']) == {'computer.status', 'computer.observe', *FILE_METHODS}
    assert channel.capabilities('daily', RID)['supported'] is False
    apply_permission(relay, TOKEN, ApplyPermission(**{k: files[k] for k in ('request_id', 'code', 'digest')}))
    assert channel.capabilities('daily', RID)['supported'] is True
    assert channel.capabilities('daily', RID)['available'] is False  # New policy needs a fresh connector lease.


@pytest.mark.parametrize('kind', ['computer', 'android'])
async def test_real_two_sided_permission_enable_then_disable_preserves_native_methods(fixture, monkeypatch, kind):
    from wearing.cloud.device_permissions import create_permission, ChangePermission
    from wearing.connectors.remote.permissions import update_permissions
    from wearing.connectors.remote.adapter import NativeAdapter
    import wearing.connectors.remote.permissions as module
    root, relay, bundle, conn, channel, workspace, local, io = fixture
    methods = ['computer.status', 'computer.observe'] if kind == 'computer' else ['phone.mobile_get_screen_size']
    old = {**SPEC, 'kind': kind, 'methods': methods}
    with relay.tx() as db: db.execute('UPDATE connectors SET resources=?', (json.dumps([old]),))
    config = json.loads((local/'connector.json').read_text()); config['resources'] = [old]
    write_private_json(local/'connector.json', config)
    write_private_json(root/'data/device-endpoint.json', {'endpoint': 'https://relay.example', 'ca_pem': 'test'})
    app = create_relay_app(root)
    monkeypatch.setattr(module, 'client_for', lambda config, local: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url='https://relay.example', headers={'Authorization': 'Bearer '+TOKEN}))
    class Adapter:
        verify_binding = NativeAdapter.verify_binding
        async def inventory(self): return {'resources': [{**old, 'methods': methods + list(FILE_METHODS)}]}
    for index, enabled in enumerate((True, False)):
        update = create_permission(relay, root, 'daily', ChangePermission(request_id=str(index+1)*32,
            resource_id=RID, revision=relay.inventory('daily')[0]['permission_revision'], mode='files', file_access=enabled))
        path = root/'permission.json'; write_private_json(path, update)
        assert (await update_permissions(path, local, Adapter()))['applied'] is True
        current = json.loads((local/'connector.json').read_text())
        assert set(current['resources'][0]['methods']) == set(methods) | (set(FILE_METHODS) if enabled else set())
        assert set(relay.inventory('daily')[0]['methods']) == set(current['resources'][0]['methods'])
        assert current['policy_revision'] == index + 2


def test_snapshot_quota_is_bounded_and_same_snapshot_is_idempotent(fixture, monkeypatch):
    import wearing.cloud.device_files as module
    root, relay, bundle, conn, channel, workspace, local, io = fixture
    monkeypatch.setattr(module, 'QUOTA_BYTES', 4)
    (workspace/'one.txt').write_bytes(b'1234')
    first = channel.snapshot('daily', RID, workspace, 'one.txt')
    assert channel.snapshot('daily', RID, workspace, 'one.txt') == first
    (workspace/'two.txt').write_bytes(b'1')
    with pytest.raises(RelayError, match='quota_exceeded'): channel.snapshot('daily', RID, workspace, 'two.txt')


@pytest.mark.skipif(not __import__('sys').platform.startswith('linux'), reason='Linux root broker uses procfs and SO_PEERCRED')
def test_broker_owns_independent_lock_and_readonly_epoch_check(tmp_path, monkeypatch):
    from wearing.device_files_broker import agent_fence
    import wearing.device_gateway as module
    home = tmp_path.resolve()
    monkeypatch.setattr(module.Path, 'home', classmethod(lambda cls: home))
    gateway = DeviceGateway(home/'.wearing/device-gateway')
    permit = gateway.permit_agent(RID)
    with gateway.native_lock(RID):
        with pytest.raises(BlockingIOError):
            with agent_fence(home, os.getuid(), RID, permit.epoch): pass
    with agent_fence(home, os.getuid(), RID, permit.epoch):
        with pytest.raises(Exception):
            with gateway.native_lock(RID): pass
    with gateway.tx() as db: db.execute("UPDATE ownership SET state='human_private',epoch=epoch+1 WHERE resource=?", (RID,))
    with pytest.raises(ValueError, match='private_or_epoch'):
        with agent_fence(home, os.getuid(), RID, permit.epoch): pass


@pytest.mark.skipif(not __import__('sys').platform.startswith('linux'), reason='Requires real Linux SO_PEERCRED')
def test_unix_socket_real_peer_credential_and_bounded_frames():
    import socket
    import struct
    from wearing.device_files_native import require_peer_uid, receive, transmit, WIRE_LIMIT
    left, right = socket.socketpair()
    try:
        require_peer_uid(left, os.getuid())
        with pytest.raises(FileChannelError, match='peer_invalid'): require_peer_uid(left, os.getuid()+1)
        transmit(left, {'available': True}); assert receive(right) == {'available': True}
        left.sendall(struct.pack('!I', WIRE_LIMIT + 1))
        with pytest.raises(FileChannelError, match='too_large'): receive(right)
    finally: left.close(); right.close()


async def test_public_file_api_inherits_real_tenant_identity_and_csrf_boundary(fixture, monkeypatch):
    monkeypatch.setenv("PAJIO_TRIAL_LIMITS", "1")
    from wearing.cloud.worker import create_tenant_app
    root, relay, *_ = fixture
    app = create_tenant_app(root, engine_autostart=False)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://app.example') as client:
        path = f'/api/devices/{RID}/files'
        assert (await client.get(path)).status_code == 401
        client.headers.update({'Authorization': 'Bearer '+(root/'gateway.key').read_text().strip(), 'X-Wearing-Tenant': 'other'})
        assert (await client.get(path)).status_code == 403
        client.headers['X-Wearing-Tenant'] = 'tenant_test'
        assert (await client.get(path)).status_code == 401
        client.headers['X-Wearing-Token'] = (await client.get('/api/bootstrap')).json()['token']
        client.headers['X-Pajio-Storage-Scope'] = ACTOR
        assert (await client.get(path)).status_code == 403
        client.headers['X-Pajio-Private-Owner-Scope'] = ACTOR
        assert (await client.get(path)).status_code == 200
        assert (await client.post(path+'/transfers', json={'request_id':'1'*32, 'direction':'list'}, headers={'Origin':'https://other.example'})).status_code == 403
        client.headers['X-Wearing-Identity'] = 'overseas'
        assert (await client.get(path)).status_code == 404
        assert not list(channel for channel in relay.inventory('overseas'))


def test_actor_anchor_is_operator_bound_immutable_and_legacy_rows_are_hidden(fixture):
    import time
    from wearing.cloud.device_admission import AccountProof
    from wearing.cloud.instance import load_instance
    root, relay, bundle, conn, channel, workspace, *_ = fixture
    (workspace/'a.txt').write_bytes(b'synthetic')
    source = channel.snapshot('daily', RID, workspace, 'a.txt')
    channel.start('daily', RID, TransferRequest(request_id='1'*32, direction='to_device', source=source))
    other = DeviceFiles(relay, actor=session_storage_scope('another_user', 'tenant_test'))
    for action in [lambda: other.history('daily', RID), lambda: other.status('daily', RID, '1'*32),
                   lambda: other.snapshot('daily', RID, workspace, 'a.txt'),
                   lambda: other.start('daily', RID, TransferRequest(request_id='2'*32, direction='list')),
                   lambda: DeviceFiles(relay).capabilities('daily', RID)]:
        with pytest.raises(RelayError, match='file_owner_not_bound'): action()
    proof = AccountProof(tenant_id='tenant_test', identity_id='daily', instance_id=load_instance(root).instance_id,
                         owner_user_id='another_user', ownership_revision=2, member_digest='a'*64,
                         source_sha256='b'*64, observed_at=time.time())
    with pytest.raises(RelayError, match='binding_changed'): channel.bind_owner(proof, RID)
    with relay.tx() as db:
        db.execute("UPDATE file_transfers SET actor='' WHERE id=?", ('1'*32,))
        db.execute("UPDATE file_sources SET actor='' WHERE id=?", (source['file_id'],))
    assert channel.history('daily', RID) == []
    with pytest.raises(RelayError, match='not_found'): channel.status('daily', RID, '1'*32)
    with pytest.raises(RelayError, match='file_source_not_found'):
        channel.start('daily', RID, TransferRequest(request_id='3'*32, direction='to_device', source=source))


async def test_worker_two_actors_and_unproven_owner_cannot_read_file_history(fixture, monkeypatch):
    from wearing.cloud.worker import create_tenant_app
    monkeypatch.setenv('PAJIO_TRIAL_LIMITS', '1')
    root, relay, bundle, conn, channel, *_ = fixture
    channel.start('daily', RID, TransferRequest(request_id='1'*32, direction='list'))
    app = create_tenant_app(root, engine_autostart=False)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://app.example') as client:
        client.headers.update({'Authorization':'Bearer '+(root/'gateway.key').read_text().strip(), 'X-Wearing-Tenant':'tenant_test'})
        client.headers['X-Wearing-Token'] = (await client.get('/api/bootstrap')).json()['token']
        prefix = f'/api/devices/{RID}/files'
        actor_b = session_storage_scope('other', 'tenant_test')
        for actor, owner, code in [(ACTOR, None,403),(actor_b,ACTOR,403),(actor_b,actor_b,404),(ACTOR,ACTOR,200)]:
            client.headers['X-Pajio-Storage-Scope'] = actor
            client.headers.pop('X-Pajio-Private-Owner-Scope', None)
            if owner: client.headers['X-Pajio-Private-Owner-Scope']=owner
            for path in [prefix, prefix+'/transfers', prefix+'/transfers/'+'1'*32]:
                assert (await client.get(path)).status_code == code


@pytest.mark.skipif(not __import__('sys').platform.startswith('linux'), reason='Real broker subprocess requires Linux procfs and SO_PEERCRED')
def test_broker_process_retains_lock_after_client_disconnect_and_rejects_old_epoch(tmp_path, monkeypatch):
    import multiprocessing
    import socket
    from wearing.device_files_broker import agent_fence
    from wearing.device_files_native import require_peer_uid
    from wearing.device_gateway import GatewayError
    import wearing.device_gateway as module
    home=tmp_path.resolve()
    monkeypatch.setattr(module.Path, 'home', classmethod(lambda cls: home))
    gateway=DeviceGateway(home/'.wearing/device-gateway', private_access_ready=True)
    permit=gateway.permit_agent(RID)
    with gateway.native_lock(RID): pass  # Actual persistent lock inode.
    context=multiprocessing.get_context('fork')
    listening,entered,release=context.Event(),context.Event(),context.Event()
    result=context.Queue();sockpath=str(home/'broker-test.sock')
    def broker():
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
            server.bind(sockpath);server.listen(1);listening.set()
            peer,_=server.accept()
            with peer:
                require_peer_uid(peer,os.getuid());peer.recv(1)
                try:
                    with agent_fence(home,os.getuid(),RID,permit.epoch):
                        entered.set();assert release.wait(5)
                        (home/'synthetic-result').write_bytes(b'completed local IO')
                    result.put('completed')
                except ValueError as e: result.put(str(e))
    child=context.Process(target=broker);child.start()
    try:
        assert listening.wait(5)
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
            client.connect(sockpath);client.sendall(b'x')
            assert entered.wait(5)
        # The caller has now disconnected, but the other process owns the IO lock.
        scope=GatewayScope('tenant_test','daily','user_test','connector_test',RID)
        pending=gateway.begin_human(scope,'human_test',expected_epoch=permit.epoch)
        with pytest.raises(GatewayError,match='device_action_inflight'):
            gateway.activate_human(scope,'human_test',pending['epoch'])
        release.set();child.join(5)
        assert not child.is_alive() and child.exitcode==0
        assert result.get(timeout=1)=='file_private_or_epoch_changed'
        assert (home/'synthetic-result').exists()  # IO may finish; stale success is discarded.
        assert gateway.activate_human(scope,'human_test',pending['epoch'])['state']=='human_private'
    finally:
        release.set()
        if child.is_alive(): child.terminate();child.join(2)
