"""Private, create-only identity broker. It has no account-admin or member grants.

The HTTP gateway reaches this process over a permissioned Unix socket. Passwords
exist only in request memory and the TLS/loopback identity request. The durable
journal contains a keyed request fingerprint, never a password or invite code.
"""
from contextlib import asynccontextmanager, contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import uuid

from filelock import FileLock, Timeout
import httpx
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import Route

from .control import ControlStore
from .invitations import InvitationStore, InvitationError
from .instance import read_private
from .request_body import RequestBodyBoundary, RequestBodyError, rejected_body


class RegistrationError(ValueError):
    def __init__(self, code='registration_unavailable'):
        self.code = code
        super().__init__(code)


def credentials(username, password):
    if not isinstance(username, str) or not re.fullmatch(r'[a-z][a-z0-9_.-]{3,31}', username):
        raise RegistrationError('username_invalid')
    if (not isinstance(password, str) or not 12 <= len(password) <= 128
            or any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in password)):
        raise RegistrationError('password_invalid')
    return username, password


class RegistrationBroker:
    def __init__(self, store, root, *, issuer, provider_url, provider_key, transport=None):
        if not store.registration:
            raise ValueError('A dedicated registration database role is required')
        if not re.fullmatch(r'[A-Za-z0-9_-]{64}', provider_key):
            raise ValueError('Invalid provider credential')
        # The provider is private loopback, not a client-selected host or public IdP.
        if not re.fullmatch(r'http://127\.0\.0\.1:[0-9]{2,5}/realms/pajio/pajio-registration', provider_url):
            raise ValueError('The registration provider must be local')
        self.invites, self.store = InvitationStore(store), store
        self.root, self.issuer = Path(root).absolute(), issuer
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(self.directory)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            os.close(self.directory)
            raise ValueError('The registration journal must be owner-private')
        self.url, self.key = provider_url, provider_key
        self.wire = httpx.Client(transport=transport, trust_env=False, follow_redirects=False, timeout=15)

    def close(self):
        self.wire.close()
        self.store.close()
        if self.directory is not None:
            os.close(self.directory)
            self.directory = None

    def _read(self, name):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.directory)
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
                    or info.st_nlink != 1 or info.st_size > 4096):
                raise RegistrationError('registration_pending')
            raw = os.read(fd, 4097)
            if len(raw) > 4096:
                raise RegistrationError('registration_pending')
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise RegistrationError('registration_pending')
            return value
        finally:
            os.close(fd)

    def _write(self, name, value, *, create=False):
        """Durable before network mutation: exclusive temp, fsync, atomic commit.

        A crash never leaves a partial final journal. First writes never replace
        another receipt. A directory fsync failure prevents the create request.
        """
        temporary = '.pending-' + secrets.token_hex(16)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
                stream.flush()
                os.fsync(stream.fileno())
            if create:
                os.link(temporary, name, src_dir_fd=self.directory, dst_dir_fd=self.directory, follow_symlinks=False)
                os.unlink(temporary, dir_fd=self.directory)
            else:
                os.replace(temporary, name, src_dir_fd=self.directory, dst_dir_fd=self.directory)
            os.fsync(self.directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=self.directory)
            except FileNotFoundError:
                pass

    def _provider(self, action, payload):
        try:
            with self.wire.stream('POST', self.url + '/' + action, json=payload,
                                 headers={'Authorization': 'Bearer ' + self.key}) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > 2048:
                        raise RegistrationError('registration_pending')
                    body.extend(chunk)
                data = json.loads(body)
        except (httpx.HTTPError, ValueError):
            raise RegistrationError('registration_pending') from None
        if response.status_code in (200, 201):
            if (not isinstance(data, dict) or set(data) != {'subject', 'registration_id'}
                    or data['registration_id'] != payload['registration_id']
                    or not isinstance(data['subject'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', data['subject'])):
                raise RegistrationError('registration_pending')
            return data
        # Only these explicit non-mutating provider outcomes are definitive.
        if action == 'create' and response.status_code == 409 and data == {'code': 'username_unavailable'}:
            raise RegistrationError('username_unavailable')
        if action == 'create' and response.status_code == 422 and data == {'code': 'password_policy'}:
            raise RegistrationError('password_invalid')
        raise RegistrationError('registration_pending')

    def register(self, hashed, username, password):
        username, password = credentials(username, password)
        if not isinstance(hashed, str) or not re.fullmatch(r'[a-f0-9]{64}', hashed):
            raise RegistrationError('invitation_unavailable')
        try:
            with FileLock(str(self.root / (hashed + '.lock')), timeout=0):
                return self._locked(hashed, username, password)
        except Timeout:
            raise RegistrationError('registration_pending') from None
        except InvitationError:
            raise RegistrationError('invitation_unavailable') from None
        except RegistrationError:
            raise
        except (OSError, ValueError, TypeError):
            # A local journal failure is uncertain registration state, never a
            # request-validation error and never permission to resend create.
            raise RegistrationError('registration_pending') from None

    def _locked(self, hashed, username, password):
        proposed = uuid.uuid4().hex
        intent = self.invites.reserve_registration(hashed, issuer=self.issuer,
                    registration_id=proposed, username_hash=hashlib.sha256(username.encode()).hexdigest())
        ident = intent['registration_id']
        canonical = json.dumps([ident, hashed, username, password], ensure_ascii=False, separators=(',', ':')).encode()
        fingerprint = hmac.new(self.key.encode(), canonical, hashlib.sha256).hexdigest()
        name = ident + '.json'
        request = {'username': username, 'registration_id': ident, 'fingerprint': fingerprint}
        journal = self._read(name)
        if journal is not None:
            if (journal.get('registration_id') != ident or journal.get('code_hash') != hashed
                    or not isinstance(journal.get('fingerprint'), str)
                    or not hmac.compare_digest(journal['fingerprint'], fingerprint)
                    or journal.get('state') not in {'inflight', 'confirmed', 'rejected'}):
                raise RegistrationError('registration_pending')
            if journal['state'] == 'rejected':
                if journal.get('code') not in {'username_unavailable', 'password_invalid'}:
                    raise RegistrationError('registration_pending')
                self.invites.release_registration(hashed, issuer=self.issuer, registration_id=ident)
                raise RegistrationError(journal['code'])
            # A previous create may have reached Keycloak even when its response
            # was lost. Inspect only; never retry the mutation on an unknown result.
            result = self._provider('inspect', request)
        else:
            journal = {'registration_id': ident, 'code_hash': hashed, 'fingerprint': fingerprint, 'state': 'inflight'}
            self._write(name, journal, create=True)
            if ident != proposed:
                # Reserve may have committed before the previous process died;
                # missing local state is NEVER evidence that create was not sent.
                result = self._provider('inspect', request)
            else:
                try:
                    result = self._provider('create', {**request, 'password': password})
                except RegistrationError as error:
                    if error.code in {'username_unavailable', 'password_invalid'}:
                        self._write(name, {**journal, 'state': 'rejected', 'code': error.code})
                        self.invites.release_registration(hashed, issuer=self.issuer, registration_id=ident)
                    raise
        if (intent.get('subject') not in (None, result['subject'])
                or journal.get('subject') not in (None, result['subject'])):
            raise RegistrationError('registration_pending')
        self.invites.bind_registration_subject(hashed, issuer=self.issuer, registration_id=ident,
                                                subject=result['subject'])
        self._write(name, {**journal, 'state': 'confirmed', 'subject': result['subject']})
        return {'subject': result['subject']}


def create_registration_app(config_path):
    config = json.loads(read_private(Path(config_path)))
    store = ControlStore(config['database_url'], registration=True)
    broker = RegistrationBroker(store, config['journal_root'], issuer=config['issuer'],
                                provider_url=config['provider_url'], provider_key=read_private(Path(config['provider_key_file'])).strip())

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            broker.close()

    async def register(request):
        try:
            data = await request.json()
            if not isinstance(data, dict) or set(data) != {'code_hash', 'username', 'password'}:
                raise RegistrationError('invalid_request')
            value = await run_in_threadpool(broker.register, data['code_hash'], data['username'], data['password'])
            return JSONResponse(value, headers={'Cache-Control': 'no-store'})
        except RequestBodyError:
            raise
        except RegistrationError as error:
            status = 409 if error.code == 'username_unavailable' else 422 if error.code in {'username_invalid', 'password_invalid', 'invalid_request'} else 503
            return JSONResponse({'code': error.code}, status_code=status, headers={'Cache-Control': 'no-store'})
        except (ValueError, TypeError):
            return JSONResponse({'code': 'invalid_request'}, status_code=422)
        except Exception:
            return JSONResponse({'code': 'registration_unavailable'}, status_code=503)

    app = Starlette(routes=[Route('/register', register, methods=['POST'])], lifespan=lifespan,
                    exception_handlers={RequestBodyError: rejected_body})
    app.add_middleware(RequestBodyBoundary, limit=4096)
    return app


class RegistrationClient:
    def __init__(self, socket_path=None, transport=None):
        self.socket_path, self.transport = socket_path, transport

    async def register(self, code_hash, username, password):
        if not self.socket_path and self.transport is None:
            raise RegistrationError()
        async with httpx.AsyncClient(transport=self.transport or httpx.AsyncHTTPTransport(uds=self.socket_path),
                                     trust_env=False, follow_redirects=False, timeout=25) as wire:
            try:
                response = await wire.post('http://pajio-registration/register',
                         json={'code_hash': code_hash, 'username': username, 'password': password})
                if len(response.content) > 2048:
                    raise RegistrationError()
                value = response.json()
                if (response.status_code == 200 and isinstance(value, dict) and set(value) == {'subject'}
                        and isinstance(value['subject'], str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', value['subject'])):
                    return value['subject']
                allowed = {'username_unavailable', 'username_invalid', 'password_invalid', 'invitation_unavailable', 'registration_pending'}
                code = value.get('code') if isinstance(value, dict) else None
                raise RegistrationError(code if code in allowed else 'registration_unavailable')
            except (httpx.HTTPError, ValueError) as error:
                if isinstance(error, RegistrationError):
                    raise
                raise RegistrationError() from None


@contextmanager
def private_listener(path):
    """Own the listener mode; Uvicorn's uds= option otherwise forces 0666."""
    path = Path(path).absolute()
    parent = path.parent.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid()
            or stat.S_IMODE(parent.st_mode) != 0o750):
        raise ValueError('registration_socket_directory_boundary')
    with FileLock(str(path) + '.lock', timeout=0, mode=0o600):
        if path.exists() or path.is_symlink():
            old = path.lstat()
            if not stat.S_ISSOCK(old.st_mode) or old.st_uid != os.getuid():
                raise ValueError('registration_socket_boundary')
            # A stale instance of this server has released its process lock.
            # Also refuse a live listener from an operator/other implementation.
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.2)
                try:
                    probe.connect(str(path))
                except ConnectionRefusedError:
                    if path.lstat().st_ino != old.st_ino:
                        raise ValueError('registration_socket_changed')
                    path.unlink()
                else:
                    raise ValueError('registration_socket_in_use')
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        inode = None
        try:
            listener.bind(str(path))
            os.chmod(path, 0o660)
            inode = path.lstat().st_ino
            listener.listen(128)
            listener.setblocking(False)
            yield listener
        finally:
            listener.close()
            if inode is not None and path.exists() and path.lstat().st_ino == inode:
                path.unlink()


if __name__ == '__main__':
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--socket', required=True)
    args = parser.parse_args()
    app = create_registration_app(args.config)
    with private_listener(args.socket) as listener:
        uvicorn.Server(uvicorn.Config(app, access_log=False, log_level='warning')).run(sockets=[listener])
