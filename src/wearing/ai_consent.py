"""Explicit provider sharing consent for an immutable private tenant owner.

The HTTP boundary supplies verified ownership. The SDK reads the same ledger
on every dispatch; no message, password, token or model payload is stored here.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

POLICY_VERSION = 'deepseek-2026-10-10-v1'
PROVIDER = {'id': 'deepseek', 'name': 'DeepSeek', 'origin': 'https://api.deepseek.com',
            'privacy_url': 'https://cdn.deepseek.com/policies/zh-CN/deepseek-privacy-policy.html'}
DISCLOSURE = {
    'title': '允许 DeepSeek 处理本次 AI 功能所需的内容？',
    'purpose': '回答问题、整理记录和简报，以及执行你授权的 Agent 任务。',
    'data_categories': ['你提交的对话和任务内容', '完成请求所需且获准使用的记忆、文件及上下文', '任务读取的工具结果，包括可能含个人信息的设备画面和应用内容'],
    'withdrawal': '可随时撤回，之后的新 AI 请求和后台调用会停止。已经发送给服务商的内容无法收回，进行中的回复可能已经传出部分内容。',
}


class ConsentError(ValueError):
    def __init__(self, code='ai_consent_unavailable', status=409):
        self.code, self.status = code, status
        super().__init__({'ai_consent_required': '请先明确同意将相关内容交给 DeepSeek 处理，再使用 AI 功能。',
                          'ai_provider_not_supported': '当前模型服务尚未完成隐私授权，未发送内容。',
                          'ai_consent_owner_changed': 'AI 授权不属于当前个人空间，请重新核对账号。',
                          'ai_consent_revision_changed': 'AI 授权状态已变化，请刷新后确认。'}.get(code, 'AI 授权暂时无法核对，未发送新的内容。'))


def _identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', value):
        raise ConsentError()
    return value


def _owner(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ConsentError('ai_consent_private_owner_required', 403)
    return value


def _private_json(path):
    """Stdlib-only: the managed model interpreter has no Core dependencies."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.getuid() or before.st_mode & 0o077 or before.st_size > 65536):
            raise ValueError('Unsafe scope file')
        with os.fdopen(fd, 'rb', closefd=False) as stream: value = json.loads(stream.read(65537))
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('Scope file changed')
        return value
    finally: os.close(fd)


class ConsentBook:
    def __init__(self, data_dir: Path, *, create=False):
        self.data_dir = Path(data_dir).absolute()
        self.path = self.data_dir / 'ai-consent.sqlite3'
        self.scope()  # Never adopt an arbitrary directory as a cloud tenant.
        if create:
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(fd)
            with self.connection(write=True) as db:
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS ai_owner_anchor(singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                        tenant TEXT NOT NULL,instance TEXT NOT NULL,owner TEXT NOT NULL,created REAL NOT NULL);
                    CREATE TABLE IF NOT EXISTS ai_consents(identity TEXT PRIMARY KEY,policy TEXT NOT NULL,
                        accepted INTEGER NOT NULL,revision INTEGER NOT NULL,updated REAL NOT NULL);
                    CREATE TABLE IF NOT EXISTS ai_consent_requests(identity TEXT,request TEXT,fingerprint TEXT,
                        receipt TEXT NOT NULL,PRIMARY KEY(identity,request));
                ''')

    def scope(self):
        try:
            root = self.data_dir.parent
            if self.data_dir.name != 'data' or self.data_dir.is_symlink() or root.is_symlink():
                raise ValueError()
            for directory in (root, self.data_dir):
                info = directory.stat()
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                    raise ValueError()
            tombstone = root / 'deletion-tombstone.json'
            if tombstone.exists() or tombstone.is_symlink(): raise ValueError()
            value = _private_json(root / 'instance.json')
            tenant, instance = value.get('tenant_id'), value.get('instance_id')
            if (type(value.get('schema_version')) is not int or value['schema_version'] != 1
                    or not isinstance(tenant, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', tenant)
                    or not isinstance(instance, str) or not re.fullmatch(r'instance_[a-f0-9]{32}', instance)
                    or _private_json(self.data_dir / 'instance-owner.json') != {'tenant_id': tenant, 'instance_id': instance}):
                raise ValueError()
            return tenant, instance
        except (OSError, ValueError, AttributeError, TypeError) as error:
            raise ConsentError() from error

    @contextmanager
    def connection(self, *, write=False):
        try:
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ConsentError()
            db = sqlite3.connect(self.path.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, timeout=3)
            db.row_factory = sqlite3.Row
            try:
                if write: db.execute('BEGIN IMMEDIATE')
                else: db.execute('PRAGMA query_only=ON')
                yield db
                if write: db.commit()
            except BaseException:
                if write: db.rollback()
                raise
            finally: db.close()
        except (OSError, sqlite3.Error) as error:
            raise ConsentError() from error

    def anchor(self, db, actor=None, *, required=False):
        scope = self.scope()
        row = db.execute('SELECT * FROM ai_owner_anchor WHERE singleton=1').fetchone()
        if row and ((row['tenant'], row['instance']) != scope or actor is not None and row['owner'] != actor):
            raise ConsentError('ai_consent_owner_changed', 403)
        if required and not row: raise ConsentError('ai_consent_required', 403)
        return row

    @staticmethod
    def _view(row):
        accepted = bool(row and row['accepted'] == 1 and row['policy'] == POLICY_VERSION)
        return {'required': True, 'provider': dict(PROVIDER), 'policy_version': POLICY_VERSION,
                'disclosure': dict(DISCLOSURE), 'accepted': accepted,
                'state': 'accepted' if accepted else 'revoked' if row and not row['accepted'] else 'not_granted',
                'revision': row['revision'] if row else 0, 'updated_at': row['updated'] if row else None}

    def snapshot(self, identity, actor):
        _identity(identity); _owner(actor)
        with self.connection() as db:
            self.anchor(db, actor)
            return self._view(db.execute('SELECT * FROM ai_consents WHERE identity=?', (identity,)).fetchone())

    def change(self, identity, actor, *, action, policy_version, expected_revision, request_id):
        _identity(identity); _owner(actor)
        if action not in {'accept', 'revoke'} or not isinstance(policy_version, str) or len(policy_version) > 80:
            raise ConsentError('ai_consent_request_invalid', 422)
        if type(expected_revision) is not int or expected_revision < 0 or not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9]{32}', request_id):
            raise ConsentError('ai_consent_request_invalid', 422)
        fingerprint = hashlib.sha256(json.dumps([actor, action, policy_version, expected_revision], separators=(',', ':')).encode()).hexdigest()
        with self.connection(write=True) as db:
            anchor = self.anchor(db, actor)
            prior = db.execute('SELECT * FROM ai_consent_requests WHERE identity=? AND request=?', (identity, request_id)).fetchone()
            if prior:
                if prior['fingerprint'] != fingerprint: raise ConsentError('ai_consent_request_changed', 409)
                # A historical accepted receipt must not masquerade as current
                # consent after a separate revoke. Return its receipt separately.
                current = self._view(db.execute('SELECT * FROM ai_consents WHERE identity=?', (identity,)).fetchone())
                return {**current, 'receipt': json.loads(prior['receipt'])}
            row = db.execute('SELECT * FROM ai_consents WHERE identity=?', (identity,)).fetchone()
            revision = row['revision'] if row else 0
            if expected_revision != revision or action == 'accept' and policy_version != POLICY_VERSION:
                raise ConsentError('ai_consent_revision_changed', 409)
            stamp = time.time()
            if anchor is None:
                db.execute('INSERT INTO ai_owner_anchor VALUES(1,?,?,?,?)', (*self.scope(), actor, stamp))
            db.execute('INSERT OR REPLACE INTO ai_consents VALUES(?,?,?,?,?)', (identity, POLICY_VERSION, int(action == 'accept'), revision + 1, stamp))
            receipt = {'request_id': request_id, 'action': action, 'revision': revision + 1, 'recorded_at': stamp}
            db.execute('INSERT INTO ai_consent_requests VALUES(?,?,?,?)', (identity, request_id, fingerprint, json.dumps(receipt)))
            current = self._view(db.execute('SELECT * FROM ai_consents WHERE identity=?', (identity,)).fetchone())
            return {**current, 'receipt': receipt}

    def require(self, identity, *, origin=PROVIDER['origin'], actor=None):
        _identity(identity)
        if origin != PROVIDER['origin']: raise ConsentError('ai_provider_not_supported', 403)
        if actor is not None: _owner(actor)
        with self.connection() as db:
            self.anchor(db, actor, required=True)
            row = db.execute('SELECT * FROM ai_consents WHERE identity=?', (identity,)).fetchone()
            if not self._view(row)['accepted']: raise ConsentError('ai_consent_required', 403)
