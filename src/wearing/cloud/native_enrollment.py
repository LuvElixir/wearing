"""Native invitation enrollment with bounded, recoverable operation receipts.

The receipt and PKCE verifier are independent client-held capabilities. Durable
state contains hashes, invite hash, outcome, and a short-lived PKCE-bound handoff;
never a password, raw invitation, verifier, bearer session, or IdP token. Unknown create outcomes
are reconciled through the private broker's inspect-only route.
"""
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
import secrets
import time
from urllib.parse import parse_qs, urlparse

from sqlalchemy import delete, insert, select
from starlette.responses import JSONResponse
from starlette.routing import Route

from .control import digest, states
from .invitations import InvitationError, InvitationStore, code_hash
from .mobile_auth import handoff_key, issue_handoff, mobile_request
from .registration import RegistrationError, credentials

PREFIX = '/auth/mobile/enrollment/'
LIFETIME = 900
PROOF_FIELDS = {'operation_id', 'receipt', 'verifier', 'state'}
DEFINITIVE = {'username_invalid', 'username_unavailable', 'password_invalid'}


class EnrollmentError(ValueError):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def operation_key(operation_id):
    return digest('native-enrollment:' + operation_id)


def verifier_challenge(verifier):
    if not isinstance(verifier, str) or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier):
        raise EnrollmentError('operation_unavailable', 404)
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


class NativeEnrollment:
    def __init__(self, config, store, cache, registration):
        self.config, self.store, self.cache, self.registration = config, store, cache, registration
        self.invites = InvitationStore(store)

    def _save(self, db, key, value):
        db.execute(delete(states).where(states.c.id_hash == key))
        db.execute(insert(states).values(id_hash=key, value=json.dumps(value, separators=(',', ':')), expires=value['expires']))

    def _limited(self, request, operation):
        # Raw addresses and operation capabilities are not retained. The global
        # bucket bounds deliberate IP/operation rotation as well.
        address = request.client.host if request.client else 'unavailable'
        source = hmac.new(self.config.session_key.get_secret_value().encode(), address.encode(), hashlib.sha256).hexdigest()
        now = int(time.time())
        for scope, maximum in [('global', 600), ('source:' + source, 90), ('operation:' + operation, 60)]:
            key = digest('native-enrollment-rate:' + scope)
            with self.store.transaction(mutating=True, state_hash=key) as db:
                row = db.execute(select(states).where(states.c.id_hash == key)).mappings().first()
                active = row is not None and row['expires'] > now
                count = int(row['value']) if active else 0
                if count >= maximum:
                    raise EnrollmentError('rate_limited', 429)
                db.execute(delete(states).where(states.c.id_hash == key))
                db.execute(insert(states).values(id_hash=key, value=str(count + 1), expires=row['expires'] if active else now + 60))

    async def _body(self, request, fields):
        if (request.scope.get('query_string') or request.headers.getlist('origin') not in ([], [self.config.public_origin])
                or request.headers.getlist('content-type') not in (['application/json'], ['application/json; charset=utf-8'])):
            raise EnrollmentError('invalid_request', 400)
        raw = await request.body()
        if len(raw) > 4096:
            raise EnrollmentError('request_too_large', 413)
        try:
            body = json.loads(raw, object_pairs_hook=unique_object)
        except (ValueError, UnicodeError):
            raise EnrollmentError('invalid_request', 422) from None
        if (not isinstance(body, dict) or set(body) != fields
                or not isinstance(body.get('operation_id'), str) or not re.fullmatch(r'[a-f0-9]{32}', body['operation_id'])
                or not isinstance(body.get('receipt'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', body['receipt'])):
            raise EnrollmentError('invalid_request', 422)
        self._limited(request, body['operation_id'])
        return body

    def _change(self, body, change=lambda value: None):
        key = operation_key(body['operation_id'])
        with self.store.transaction(mutating=True, state_hash=key) as db:
            row = db.execute(select(states).where(states.c.id_hash == key)).mappings().first()
            value = json.loads(row['value']) if row else None
            challenge = verifier_challenge(body['verifier'])
            if (not value or not secrets.compare_digest(value['receipt_hash'], digest(body['receipt']))
                    or body['state'] != value['state'] or challenge != value['challenge']):
                raise EnrollmentError('operation_unavailable', 404)
            if value['expires'] <= int(time.time()):
                raise EnrollmentError('operation_expired', 410)
            change(value)
            self._save(db, key, value)
            return value

    async def verify(self, request):
        body = await self._body(request, {'operation_id', 'receipt', 'code', 'challenge', 'state'})
        try:
            mobile_request(body)
            hashed = code_hash(body['code'])
        except (ValueError, InvitationError):
            raise EnrollmentError('invitation_unavailable', 422) from None
        key = operation_key(body['operation_id'])
        # Idempotent verify needs no plaintext receipt persisted or returned.
        with self.store.transaction(mutating=True, state_hash=key) as db:
            row = db.execute(select(states).where(states.c.id_hash == key)).mappings().first()
            value = json.loads(row['value']) if row else None
            if value:
                if any(value[k] != v for k, v in {'receipt_hash': digest(body['receipt']), 'code_hash': hashed,
                                                  'challenge': body['challenge'], 'state': body['state']}.items()):
                    raise EnrollmentError('operation_unavailable', 404)
                if value['expires'] <= int(time.time()):
                    raise EnrollmentError('operation_expired', 410)
                return self._response(value)
        try:
            self.invites.check_code(body['code'], issuer=self.config.issuer)
        except InvitationError:
            raise EnrollmentError('invitation_unavailable', 422) from None
        value = {'version': 1, 'operation_id': body['operation_id'], 'receipt_hash': digest(body['receipt']),
                 'code_hash': hashed, 'challenge': body['challenge'], 'state': body['state'],
                 'expires': int(time.time()) + LIFETIME, 'status': 'verified', 'attempts': 0, 'cancel_requested': False}
        with self.store.transaction(mutating=True, state_hash=key) as db:
            prior = db.execute(select(states).where(states.c.id_hash == key)).mappings().first()
            if prior:
                saved = json.loads(prior['value'])
                if any(saved[k] != value[k] for k in ('receipt_hash', 'code_hash', 'challenge', 'state')):
                    raise EnrollmentError('operation_unavailable', 404)
                if saved['expires'] <= int(time.time()):
                    raise EnrollmentError('operation_expired', 410)
                value = saved
            else:
                self._save(db, key, value)
        return self._response(value)

    def _response(self, value):
        status = value['status']
        result = {k: value[k] for k in ('operation_id', 'state', 'status', 'cancel_requested')}
        result['expires_at'] = datetime.fromtimestamp(value['expires'], timezone.utc).isoformat()
        result['attempts_remaining'] = max(0, 5 - value['attempts'])
        result['next_action'] = {'verified': 'register', 'rejected': 'register', 'pending': 'check_status',
                                 'cancelled': 'start_over', 'completed': 'existing_login'}[status]
        if value.get('code'):
            result['code'] = value['code']
        if status == 'pending':
            result['retry_after'] = 2
        handoff = value.get('handoff')
        if (status == 'completed' and handoff and handoff['expires'] > int(time.time())
                and not value.get('handoff_used') and not value['cancel_requested']):
            result['handoff'] = {'code': handoff['code'], 'state': value['state']}
            result['next_action'] = 'exchange'
        return JSONResponse(result, status_code=202 if status == 'pending' else 200,
                            headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})

    async def register(self, request):
        body = await self._body(request, PROOF_FIELDS | {'username', 'password'})
        current = self._change(body)
        if current['status'] not in {'verified', 'rejected'}:
            return self._response(current)
        try:
            username, password = credentials(body['username'], body['password'])
        except RegistrationError as error:
            raise EnrollmentError(error.code, 422) from None
        claim = secrets.token_hex(16)
        def start(value):
            if value['status'] not in {'verified', 'rejected'}:
                return
            if value['attempts'] >= 5:
                raise EnrollmentError('attempts_exhausted', 429)
            value.update(status='pending', attempts=value['attempts'] + 1, username=username, claim=claim,
                         busy_until=int(time.time()) + 45)
            value.pop('code', None)
            value['recovery_binding'] = digest(json.dumps([value['operation_id'], value['receipt_hash'],
                                                          value['challenge'], value['state'], value['attempts']]))
        current = self._change(body, start)
        if current.get('claim') != claim:
            return self._response(current)
        return await self._resolve(body, current, password=password)

    async def status(self, request):
        body = await self._body(request, PROOF_FIELDS)
        claim = secrets.token_hex(16)
        def inspect(value):
            if value['status'] == 'pending' and value.get('busy_until', 0) <= int(time.time()):
                value.update(claim=claim, busy_until=int(time.time()) + 45)
        current = self._change(body, inspect)
        if current['status'] == 'pending' and current.get('claim') == claim:
            return await self._resolve(body, current)
        return self._response(current)

    async def _resolve(self, body, current, *, password=None):
        claim = current['claim']
        def own(value):
            if value['status'] != 'pending' or value.get('claim') != claim:
                raise EnrollmentError('registration_pending', 409)
        try:
            subject = current.get('subject')
            if not subject:
                if password is not None:
                    subject = await self.registration.register_native(current['code_hash'], current['username'], password, current['recovery_binding'])
                else:
                    subject = await self.registration.inspect_native(current['code_hash'], current['username'], current['recovery_binding'])
                def remember(value):
                    own(value)
                    value['subject'] = subject
                current = self._change(body, remember)
            admitted = self.invites.redeem_hash(current['code_hash'], issuer=self.config.issuer, subject=subject)
            # Both owner identity and tenant are fixed by the redeemed invitation,
            # never by a tenant ID supplied by the client.
            tenant = admitted['tenant_id']
            if current.get('tenant_id') not in (None, tenant):
                raise EnrollmentError('operation_unavailable', 409)
            callback = None
            latest = self._change(body)
            if not latest['cancel_requested']:
                callback = await issue_handoff(self.cache, mobile_request(current), subject, tenant_id=tenant,
                                               enrollment_operation=current['operation_id'])
            def complete(value):
                own(value)
                value.update(status='completed', tenant_id=tenant, user_id=admitted['user_id'], busy_until=0)
                if callback:
                    value['handoff'] = {'code': parse_qs(urlparse(callback).query)['code'][0], 'expires': int(time.time()) + 120}
            result = self._change(body, complete)
            if result['cancel_requested'] and callback:
                await self.cache.delete(handoff_key(result['handoff']['code'], result['challenge'], result['state']))
            return self._response(result)
        except (RegistrationError, InvitationError) as error:
            def failed(value):
                own(value)
                value['busy_until'] = 0
                if error.code == 'registration_not_dispatched' and password is not None:
                    # This internal-only code is produced exclusively by a local
                    # socket-connect failure, never by a broker HTTP response.
                    value.update(status='cancelled' if value['cancel_requested'] else 'verified',
                                 attempts=value['attempts'] - 1, code='registration_unavailable')
                elif error.code in DEFINITIVE:
                    value.update(status='cancelled' if value['cancel_requested'] else 'rejected', code=error.code)
                else:
                    value['code'] = 'registration_pending'
            return self._response(self._change(body, failed))

    async def cancel(self, request):
        body = await self._body(request, PROOF_FIELDS)
        def cancel(value):
            value['cancel_requested'] = True
            if value['status'] in {'verified', 'rejected'}:
                value['status'] = 'cancelled'
        value = self._change(body, cancel)
        if value.get('handoff'):
            await self.cache.delete(handoff_key(value['handoff']['code'], value['challenge'], value['state']))
        return self._response(value)

    def consume_handoff(self, operation, code):
        """Called only after the one-use PKCE exchange has consumed its proof."""
        key = operation_key(operation)
        with self.store.transaction(mutating=True, state_hash=key) as db:
            row = db.execute(select(states).where(states.c.id_hash == key)).mappings().first()
            value = json.loads(row['value']) if row else None
            if (not value or value['expires'] <= int(time.time()) or value['status'] != 'completed'
                    or value['cancel_requested'] or value.get('handoff_used')
                    or not secrets.compare_digest(value.get('handoff', {}).get('code', ''), code)):
                raise EnrollmentError('operation_unavailable', 400)
            value['handoff_used'] = True
            self._save(db, key, value)

    async def handle(self, request):
        try:
            action = request.url.path.rsplit('/', 1)[-1]
            return await getattr(self, action)(request)
        except EnrollmentError as error:
            return JSONResponse({'code': error.code}, status_code=error.status,
                                headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})

    def routes(self):
        return [Route(PREFIX + action, self.handle, methods=['POST']) for action in ('verify', 'register', 'status', 'cancel')]
