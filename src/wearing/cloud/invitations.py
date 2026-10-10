"""One-time admission for an authenticated identity; never a login credential.

Only the operator can reserve a NEW empty tenant and issue/revoke codes. The
web role checks and redeems through narrowly audited PostgreSQL functions. A
separate registration role reserves an immutable IdP creation intent; it has
no table DML, membership, route, or login-session privilege.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
import time
import uuid

from sqlalchemy import insert, select, text, update

from .control import ControlError, digest, invitations, members, ownership, routes, tenants, users


class InvitationError(ControlError):
    def __init__(self, code='invitation_unavailable'):
        self.code = code
        super().__init__(code)


def code_hash(code):
    if not isinstance(code, str) or not re.fullmatch(r'pajio_[A-Za-z0-9_-]{43}', code):
        raise InvitationError()
    return digest(code)


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise InvitationError()
    return value


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise InvitationError()
    return value


def _identity(issuer, subject=None):
    if not isinstance(issuer, str) or not 1 <= len(issuer) <= 2048 or any(ord(c) < 33 for c in issuer):
        raise InvitationError()
    if subject is not None and (not isinstance(subject, str) or not 1 <= len(subject) <= 512
                                or any(ord(c) < 32 for c in subject)):
        raise InvitationError()


class InvitationStore:
    def __init__(self, store):
        self.store = store

    def _operator(self):
        if not self.store.operator:
            raise InvitationError('invitation_operator_required')

    def _registration(self):
        if not self.store.registration:
            raise InvitationError('invitation_registration_required')

    def reserve_tenant(self, tenant_id):
        """Prepare an empty control record; creates no VM, route or membership."""
        self._operator()
        if not isinstance(tenant_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', tenant_id):
            raise InvitationError()
        with self.store.transaction(mutating=True) as db:
            current = db.execute(select(tenants).where(tenants.c.id == tenant_id)).mappings().first()
            if current is not None:
                if (current['deletion_state'] != 'active' or db.scalar(select(members.c.user_id).where(members.c.tenant_id == tenant_id))
                        or db.scalar(select(ownership.c.tenant_id).where(ownership.c.tenant_id == tenant_id))):
                    raise InvitationError('invitation_tenant_not_empty')
            else:
                db.execute(insert(tenants).values(id=tenant_id))
        return {'tenant_id': tenant_id, 'status': 'reserved', 'provisioned': False}

    def issue(self, *, issuer, tenant_id, invitation_id, code, expires_at):
        """Idempotent issue using a code already durably saved by the operator.

        Existing issuance must match EVERY immutable field, including code hash;
        retries never rotate or resurrect an expired/revoked/consumed code.
        """
        self._operator()
        _identity(issuer)
        hashed, ident = code_hash(code), _id(invitation_id)
        now = int(time.time())
        if type(expires_at) is not int:
            raise InvitationError()
        with self.store.transaction(mutating=True) as db:
            previous = db.execute(select(invitations).where(invitations.c.id == ident)).mappings().first()
            if previous is not None:
                if any(previous[k] != v for k, v in {'issuer': issuer, 'tenant_id': tenant_id,
                        'code_hash': hashed, 'expires_at': expires_at}.items()):
                    raise InvitationError('invitation_conflict')
                return self._public(previous, now)
            if not now < expires_at <= now + 30 * 86400:
                raise InvitationError('invitation_expiry_invalid')
            route = db.execute(select(routes).where(routes.c.tenant_id == tenant_id)).mappings().first()
            if (route is None or not self.store.tenant_editable(db, tenant_id)
                    or db.scalar(select(tenants.c.id).where(tenants.c.id == tenant_id)) is None
                    or db.scalar(select(members.c.user_id).where(members.c.tenant_id == tenant_id))
                    or db.scalar(select(ownership.c.tenant_id).where(ownership.c.tenant_id == tenant_id))
                    or db.scalar(select(invitations.c.id).where(invitations.c.tenant_id == tenant_id))):
                raise InvitationError('invitation_tenant_not_empty')
            row = {'id': ident, 'code_hash': hashed, 'issuer': issuer, 'tenant_id': tenant_id,
                   'instance_id': route['instance_id'], 'created_at': now, 'expires_at': expires_at}
            db.execute(insert(invitations).values(**row))
            return self._public(row, now)

    @staticmethod
    def _public(row, now):
        status = ('redeemed' if row.get('redeemed_user_id') else 'revoked' if row.get('revoked_at') is not None
                  else 'expired' if row['expires_at'] <= now else 'registering' if row.get('registration_id') else 'issued')
        return {'id': row['id'], 'tenant_id': row['tenant_id'], 'status': status,
                'created_at': row['created_at'], 'expires_at': row['expires_at'],
                'revoked': row.get('revoked_at') is not None}

    def status(self, invitation_id):
        self._operator()
        with self.store.transaction() as db:
            row = db.execute(select(invitations).where(invitations.c.id == _id(invitation_id))).mappings().first()
        if row is None:
            raise InvitationError()
        return self._public(row, int(time.time()))

    def revoke(self, invitation_id):
        self._operator()
        with self.store.transaction(mutating=True) as db:
            row = db.execute(select(invitations).where(invitations.c.id == _id(invitation_id))).mappings().first()
            if row is None:
                raise InvitationError()
            if row['revoked_at'] is None:
                db.execute(update(invitations).where(invitations.c.id == row['id']).values(revoked_at=int(time.time())))
        # Revoking a code never modifies admitted memberships; use explicit member
        # revocation separately. It also does not delete a possibly created IdP user.
        return self.status(invitation_id)

    def _pg(self, name, *, issuer, hashed, **values):
        fields = {'p_hash': hashed, 'p_issuer': issuer, **{'p_' + k: v for k, v in values.items()}}
        placeholders = ','.join(':' + name for name in fields)
        with self.store.transaction(mutating=name != 'invitation_check', issuer=issuer,
                                    subject=values.get('subject', '')) as db:
            value = db.scalar(text(f'SELECT wearing_control.{name}({placeholders})'), fields)
        if value is None:
            raise InvitationError()
        return value

    def _eligible(self, db, hashed, issuer):
        row = db.execute(select(invitations).where(invitations.c.code_hash == hashed,
                         invitations.c.issuer == issuer)).mappings().first()
        if (row is None or row['revoked_at'] is not None or row['expires_at'] <= int(time.time())
                or row['redeemed_user_id'] is not None):
            raise InvitationError()
        route = db.execute(select(routes).where(routes.c.tenant_id == row['tenant_id'])).mappings().first()
        if (not self.store.tenant_editable(db, row['tenant_id']) or route is None
                or route['instance_id'] != row['instance_id']
                or db.scalar(select(members.c.user_id).where(members.c.tenant_id == row['tenant_id']))
                or db.scalar(select(ownership.c.tenant_id).where(ownership.c.tenant_id == row['tenant_id']))):
            raise InvitationError()
        return row

    def check_code(self, code, *, issuer):
        _identity(issuer)
        hashed = code_hash(code)
        if self.store.postgres:
            if self._pg('invitation_check', issuer=issuer, hashed=hashed) is not True:
                raise InvitationError()
        else:
            with self.store.transaction() as db:
                self._eligible(db, hashed, issuer)
        return hashed

    def check(self, code, *, issuer):
        try:
            return {'eligible': True, 'code_hash': self.check_code(code, issuer=issuer)}
        except InvitationError:
            return {'eligible': False}

    def redeem_hash(self, hashed, *, issuer, subject):
        if self.store.registration:
            raise InvitationError()
        _identity(issuer, subject)
        _hash(hashed)
        if self.store.postgres:
            return self._pg('invitation_redeem', issuer=issuer, hashed=hashed, subject=subject)
        with self.store.transaction(mutating=True) as db:
            user = db.execute(select(users).where(users.c.issuer == issuer, users.c.subject == subject)).mappings().first()
            if user is not None:
                if not self.store.user_available(db, user['id']):
                    raise InvitationError()
                for tenant in db.scalars(select(members.c.tenant_id).where(members.c.user_id == user['id'],
                                        members.c.active.is_(True)).order_by(members.c.tenant_id)):
                    if self.store.tenant_available(db, tenant):
                        return {'status': 'already_member', 'user_id': user['id'], 'tenant_id': tenant}
            row = self._eligible(db, hashed, issuer)
            if row['registration_id'] is not None and row['registration_subject'] != subject:
                raise InvitationError()
            uid = user['id'] if user else 'user_' + uuid.uuid4().hex
            if user is None:
                db.execute(insert(users).values(id=uid, issuer=issuer, subject=subject))
            db.execute(insert(members).values(user_id=uid, tenant_id=row['tenant_id'], active=True))
            db.execute(insert(ownership).values(tenant_id=row['tenant_id'], classification='private', owner_user_id=uid,
                       member_count=1, member_digest=digest(json.dumps([(uid, True)], separators=(',', ':'))),
                       instance_id=row['instance_id'], revision=1))
            db.execute(update(invitations).where(invitations.c.id == row['id']).values(
                       redeemed_user_id=uid, redeemed_at=int(time.time())))
            return {'status': 'admitted', 'user_id': uid, 'tenant_id': row['tenant_id']}

    def reserve_registration(self, hashed, *, issuer, registration_id, username_hash):
        self._registration()
        _identity(issuer)
        _hash(hashed), _id(registration_id), _hash(username_hash)
        if self.store.postgres:
            return self._pg('invitation_reserve_registration', issuer=issuer, hashed=hashed,
                            registration_id=registration_id, username_hash=username_hash)
        with self.store.transaction(mutating=True) as db:
            row = self._eligible(db, hashed, issuer)
            if row['registration_id'] is not None:
                if row['username_hash'] != username_hash:
                    raise InvitationError()
            else:
                db.execute(update(invitations).where(invitations.c.id == row['id']).values(
                           registration_id=registration_id, username_hash=username_hash))
                row = {**row, 'registration_id': registration_id, 'username_hash': username_hash}
            return self._registration_view(row)

    @staticmethod
    def _registration_view(row):
        return {'registration_id': row['registration_id'], 'username_hash': row['username_hash'],
                'subject': row['registration_subject'], 'expires_at': row['expires_at']}

    def get_registration(self, hashed, *, issuer):
        self._registration()
        _identity(issuer)
        _hash(hashed)
        if self.store.postgres:
            return self._pg('invitation_get_registration', issuer=issuer, hashed=hashed)
        with self.store.transaction() as db:
            row = self._eligible(db, hashed, issuer)
            if row['registration_id'] is None:
                raise InvitationError()
            return self._registration_view(row)

    def bind_registration_subject(self, hashed, *, issuer, registration_id, subject):
        self._registration()
        _identity(issuer, subject)
        _hash(hashed), _id(registration_id)
        if self.store.postgres:
            return self._pg('invitation_bind_registration', issuer=issuer, hashed=hashed,
                            registration_id=registration_id, subject=subject)
        with self.store.transaction(mutating=True) as db:
            row = self._eligible(db, hashed, issuer)
            if row['registration_id'] != registration_id or row['registration_subject'] not in (None, subject):
                raise InvitationError()
            db.execute(update(invitations).where(invitations.c.id == row['id']).values(registration_subject=subject))
            return self._registration_view({**row, 'registration_subject': subject})

    def release_registration(self, hashed, *, issuer, registration_id):
        """Broker only, AFTER a definitive no-create conflict; never for unknown.

        The broker retains the failed intent in its private journal. A late bind
        from this released intent cannot attach to a subsequent reservation.
        """
        self._registration()
        _identity(issuer)
        _hash(hashed), _id(registration_id)
        if self.store.postgres:
            return self._pg('invitation_release_registration', issuer=issuer, hashed=hashed,
                            registration_id=registration_id)
        with self.store.transaction(mutating=True) as db:
            row = self._eligible(db, hashed, issuer)
            if row['registration_id'] != registration_id or row['registration_subject'] is not None:
                raise InvitationError()
            db.execute(update(invitations).where(invitations.c.id == row['id']).values(
                       registration_id=None, username_hash=None))
            return {'released': True}


def issue_to_file(store, *, issuer, tenant_id, output, lifetime=7 * 86400):
    """Save the only plaintext copy BEFORE DB issue; same path is a safe retry."""
    api = InvitationStore(store)
    api._operator()
    output = Path(output).absolute()
    parent = output.parent
    if (parent.is_symlink() or not parent.is_dir() or parent.stat().st_uid != os.getuid()
            or parent.stat().st_mode & 0o077):
        raise InvitationError('invitation_output_not_private')
    if type(lifetime) is not int or not 60 <= lifetime <= 30 * 86400:
        raise InvitationError('invitation_expiry_invalid')
    if not output.exists() and not output.is_symlink():
        data = {'version': 1, 'issuer': issuer, 'tenant_id': tenant_id, 'id': uuid.uuid4().hex,
                'code': 'pajio_' + secrets.token_urlsafe(32), 'expires_at': int(time.time()) + lifetime}
        fd, temporary = tempfile.mkstemp(prefix='.invite-', dir=parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, output)
            except FileExistsError:
                pass
            directory = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            os.unlink(temporary)
    fd = os.open(output, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 4096):
            raise InvitationError('invitation_output_not_private')
        raw = os.read(fd, 4097)
        data = json.loads(raw)
    finally:
        os.close(fd)
    if (set(data) != {'version', 'issuer', 'tenant_id', 'id', 'code', 'expires_at'} or type(data['version']) is not int
            or data['version'] != 1 or data['issuer'] != issuer or data['tenant_id'] != tenant_id):
        raise InvitationError('invitation_conflict')
    return api.issue(issuer=issuer, tenant_id=tenant_id, invitation_id=data['id'], code=data['code'], expires_at=data['expires_at'])
