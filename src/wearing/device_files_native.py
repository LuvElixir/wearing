"""Trusted Linux native file binding and narrow Android Unix-socket client."""
import asyncio
import base64
import json
import os
from pathlib import Path
import socket
import stat
import struct

from .device_files_io import (InboxOutbox, FileChannelError, MAX_BYTES, CHUNK_BYTES,
    FILE_METHODS, source_checked, source_info, id_checked)

CONFIG = Path('/etc/pajio-device-files.json')
SOCKET = '/run/pajio-device-files/socket'
WIRE_LIMIT = 4 * ((MAX_BYTES + 2) // 3) + 16384


def require_peer_uid(sock, expected):
    _, uid, _ = struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if uid != expected: raise FileChannelError('file_broker_peer_invalid')


def configuration(path=CONFIG):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 8192:
            raise FileChannelError('file_binding_unsafe')
        with os.fdopen(fd, 'r', closefd=False) as stream: config = json.load(stream)
    finally: os.close(fd)
    if set(config) != {'version', 'kind', 'resource_id', 'user', 'root'} or config['version'] != 1:
        raise FileChannelError('file_binding_invalid')
    if config['kind'] == 'android':
        if config['user'] != 'pajio-phone' or config['root'] != '/var/lib/pajio-phone/data/media/0/Download/Pajio':
            raise FileChannelError('file_binding_invalid')
    elif config['kind'] == 'computer':
        if config['user'] != 'pajio-desktop' or config['root'] != '/home/pajio-desktop/Pajio':
            raise FileChannelError('file_binding_invalid')
    else: raise FileChannelError('file_binding_invalid')
    from .cloud.commands import Identifier
    from pydantic import TypeAdapter
    TypeAdapter(Identifier).validate_python(config['resource_id'])
    return config


def receive(sock):
    def exact(size):
        data = bytearray()
        while len(data) < size:
            part = sock.recv(min(CHUNK_BYTES, size - len(data)))
            if not part: raise FileChannelError('file_broker_disconnected')
            data.extend(part)
        return bytes(data)
    length = struct.unpack('!I', exact(4))[0]
    if length > WIRE_LIMIT: raise FileChannelError('file_broker_too_large')
    return json.loads(exact(length))


def transmit(sock, value):
    data = json.dumps(value, ensure_ascii=True, separators=(',', ':')).encode()
    if len(data) > WIRE_LIMIT: raise FileChannelError('file_broker_too_large')
    sock.sendall(struct.pack('!I', len(data)) + data)


class NativeFiles:
    def __init__(self, resource, *, config=None):
        self.config = config if config is not None else configuration()
        if self.config['resource_id'] != resource: raise FileChannelError('file_resource_not_bound')
        self.resource = resource

    def call(self, action, *, permit_epoch=None, **params):
        if self.config['kind'] == 'computer':
            import pwd
            if os.geteuid() != pwd.getpwnam(self.config['user']).pw_uid:
                raise FileChannelError('file_native_user_changed')
            return dispatch(InboxOutbox(self.config['root']), action, params)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(15)
            sock.connect(SOCKET)
            # A local unprivileged impostor must never receive file bytes.
            require_peer_uid(sock, 0)
            transmit(sock, {'resource_id': self.resource, 'action': action, 'params': params, 'permit_epoch': permit_epoch})
            result = receive(sock)
        if result.get('error'): raise FileChannelError('file_broker_rejected')
        return result

    def available(self): return self.call('available').get('available') is True


def dispatch(io, action, params):
    if action == 'available' and not params: return {'available': io.available()}
    if action == 'list' and not params: return io.listing()
    if action == 'fetch' and set(params) == {'source'}:
        return {'data': base64.b64encode(io.fetch(params['source'])).decode()}
    if action == 'send' and set(params) == {'request_id', 'source', 'data'}:
        try: data = base64.b64decode(params['data'], validate=True)
        except (ValueError, TypeError): raise FileChannelError('file_chunk_invalid') from None
        return io.send(params['request_id'], params['source'], data)
    raise FileChannelError('file_action_invalid')


async def execute_transfer(adapter, command, client, connection):
    """One journalled command; no retries, stdin/argv/shell/clipboard are unused."""
    from .connectors.remote.client import response
    if command.method not in FILE_METHODS: raise FileChannelError('file_method_invalid')
    params = command.params
    expected = {'request_id'} if command.method == 'files.list' else {'request_id', 'source'}
    if set(params) != expected: raise FileChannelError('file_command_invalid')
    request_id = id_checked(params['request_id'])
    source = source_checked(params['source']) if 'source' in params else None
    native = NativeFiles(command.resource_id)
    broker_fenced = getattr(native, 'config', {}).get('kind') == 'android'
    permit = adapter.gateway.permit_agent(command.resource_id)
    async def call(action, **args):
        # Cancellation must not release the native fence while a file write is
        # still running in the worker thread. A timed-out command stays unknown.
        if broker_fenced: args['permit_epoch'] = permit.epoch
        pending = asyncio.create_task(asyncio.to_thread(native.call, action, **args))
        try: return await asyncio.shield(pending)
        except asyncio.CancelledError:
            while not pending.done():
                try: await asyncio.shield(pending)
                except asyncio.CancelledError: continue
                except Exception: break
            raise
    # Human handoff and native data access share the same OS action fence.
    # Android broker owns the lock for the actual I/O, even if this process dies.
    from contextlib import nullcontext
    if broker_fenced:
        with adapter.gateway.native_lock(command.resource_id): adapter.gateway.validate_agent(permit)
    with nullcontext() if broker_fenced else adapter.gateway.native_lock(command.resource_id):
        adapter.gateway.validate_agent(permit)
        if command.method == 'files.list':
            result = await call('list')
        elif command.method == 'files.send':
            data = bytearray()
            for offset in range(0, source['size'], CHUNK_BYTES):
                adapter.gateway.validate_agent(permit)
                block = await response(client, '/v1/files/download', {'connection_id': connection,
                    'command_id': command.command_id, 'offset': offset})
                if block.get('offset') != offset: raise FileChannelError('file_offset_invalid')
                chunk = base64.b64decode(block['data'], validate=True)
                if len(chunk) != min(CHUNK_BYTES, source['size'] - offset): raise FileChannelError('file_chunk_invalid')
                data.extend(chunk)
            if source_info(source['name'], data) != source: raise FileChannelError('file_hash_changed')
            adapter.gateway.validate_agent(permit)
            result = await call('send', request_id=request_id, source=source,
                                             data=base64.b64encode(data).decode())
        else:
            block = await call('fetch', source=source)
            data = base64.b64decode(block['data'], validate=True)
            if source_info(source['name'], data) != source: raise FileChannelError('file_hash_changed')
            for offset in range(0, len(data), CHUNK_BYTES):
                adapter.gateway.validate_agent(permit)
                receipt = await response(client, '/v1/files/upload', {'connection_id': connection,
                    'command_id': command.command_id, 'offset': offset,
                    'data': base64.b64encode(data[offset:offset + CHUNK_BYTES]).decode()})
                if receipt.get('accepted') is not True: raise FileChannelError('file_chunk_unconfirmed')
            result = {'source': source, 'receipt_id': request_id}
        adapter.gateway.validate_agent(permit)
        return result


def advertised(resource):
    try:
        return list(FILE_METHODS) if NativeFiles(resource).available() else []
    except (OSError, ValueError, KeyError, TypeError): return []
