"""Owner/identity-bound, user-selected context. Saving grants no execution authority."""
import hashlib
import json
import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .store import DEFAULT_IDENTITY, now
from .task_visibility import owner as trusted_owner, predicate

MAX_PROFILE_BYTES = 8192
ROLE_LABELS = {'employed': '在职工作', 'student': '在校学习', 'independent': '自由职业',
               'business': '经营事业', 'caregiver': '照顾家庭'}
APP_LABELS = {'wechat': '微信', 'douyin': '抖音', 'xiaohongshu': '小红书', 'bilibili': '哔哩哔哩',
              'feishu': '飞书', 'dingtalk': '钉钉', 'wecom': '企业微信', 'mail': '邮箱',
              'calendar': '系统日历', 'github': 'GitHub'}
INTEREST_LABELS = {'technology': '科技', 'career': '职业成长', 'design': '设计', 'reading': '阅读',
                   'travel': '旅行', 'food': '饮食', 'fitness': '运动', 'culture': '文化', 'finance': '财经'}
DETAIL_LABELS = {'brief': '简短结论', 'balanced': '适中详略', 'detailed': '展开说明'}
TONE_LABELS = {'natural': '自然交流', 'warm': '温和表达', 'direct': '直接表达'}


class OnboardingError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class ProfileValues(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    roles: list[Literal['employed', 'student', 'independent', 'business', 'caregiver']] = Field(default_factory=list, max_length=3)
    apps: list[Literal['wechat', 'douyin', 'xiaohongshu', 'bilibili', 'feishu', 'dingtalk', 'wecom', 'mail', 'calendar', 'github']] = Field(default_factory=list, max_length=10)
    interests: list[Literal['technology', 'career', 'design', 'reading', 'travel', 'food', 'fitness', 'culture', 'finance']] = Field(default_factory=list, max_length=5)
    reply_detail: Literal['brief', 'balanced', 'detailed'] | None = None
    reply_tone: Literal['natural', 'warm', 'direct'] | None = None

    @field_validator('roles', 'apps', 'interests')
    @classmethod
    def distinct(cls, values, info):
        if len(values) != len(set(values)):
            raise ValueError('选项不能重复。')
        order = {'roles': ROLE_LABELS, 'apps': APP_LABELS, 'interests': INTEREST_LABELS}[info.field_name]
        return [key for key in order if key in values]


class SaveOnboarding(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=0)
    request_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,120}$')
    status: Literal['draft', 'completed', 'skipped']
    step: int = Field(ge=0, le=5)
    values: ProfileValues

    @model_validator(mode='after')
    def completed_step(self):
        if self.status == 'completed' and self.step != 5:
            raise ValueError('请在最后一步确认保存。')
        return self


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def read_profile(db, identity, actor):
    """Only one bounded validated record; optional in older stores/engines."""
    trusted_owner(actor)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='onboarding_profiles'").fetchone():
        return None
    row = db.execute('''SELECT revision,status,step,substr(value,1,?),length(CAST(value AS BLOB)) AS size,
        confirmed_at,updated_at FROM onboarding_profiles WHERE identity_id=? AND owner_scope=?''',
        (MAX_PROFILE_BYTES + 1, identity, actor)).fetchone()
    if not row:
        return None
    revision, status, step, raw, size, confirmed, stamp = tuple(row)
    if (not isinstance(revision, int) or revision < 1 or status not in {'draft', 'completed', 'skipped'}
            or not isinstance(step, int) or not 0 <= step <= 5 or size > MAX_PROFILE_BYTES
            or not isinstance(stamp, str) or len(stamp) > 80
            or confirmed is not None and (not isinstance(confirmed, str) or len(confirmed) > 80)
            or (status == 'completed') != (confirmed is not None)):
        raise ValueError('Invalid onboarding record')
    values = ProfileValues.model_validate(json.loads(raw)).model_dump()
    if status == 'skipped' and values != ProfileValues().model_dump():
        raise ValueError('Skipped profile contains unconfirmed data')
    return {'schema': 1, 'identity_id': identity, 'revision': revision, 'status': status, 'step': step,
            'values': values, 'source': 'self_selected', 'confirmed_at': confirmed, 'updated_at': stamp}


def confirmed_interests(db, identity, actor):
    if actor is None:
        return []
    try:
        row = read_profile(db, identity, actor)
        return [INTEREST_LABELS[key] for key in row['values']['interests']] if row and row['status'] == 'completed' else []
    except (ValueError, TypeError, sqlite3.Error):
        return []


class OnboardingBook:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS onboarding_profiles (
                    identity_id TEXT NOT NULL, owner_scope TEXT NOT NULL, revision INTEGER NOT NULL,
                    status TEXT NOT NULL, step INTEGER NOT NULL, value TEXT NOT NULL,
                    confirmed_at TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(identity_id,owner_scope));
                CREATE TABLE IF NOT EXISTS onboarding_requests (
                    identity_id TEXT NOT NULL, owner_scope TEXT NOT NULL, request_key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, receipt TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(identity_id,owner_scope,request_key));
            ''')

    @staticmethod
    def empty(identity):
        return {'schema': 1, 'identity_id': identity, 'revision': 0, 'status': 'draft', 'step': 0,
                'values': ProfileValues().model_dump(), 'source': 'self_selected', 'confirmed_at': None, 'updated_at': None}

    def _existing(self, db, identity, actor):
        # Existing accounts are never forced through a first-run overlay. This
        # observes existence only; it does not read source contents or authorize a sync.
        if db.execute(f'SELECT 1 FROM tasks t WHERE t.identity_id=:identity AND {predicate("t.id")} LIMIT 1',
                      {'identity': identity, 'task_owner': actor}).fetchone():
            return True
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('life_records', 'briefing_preferences', 'life_assets'):
            if table in tables and db.execute(f'SELECT 1 FROM {table} WHERE identity_id=? LIMIT 1', (identity,)).fetchone():
                return True
        for table, kind in (('personal_goals', 'goal'), ('personal_schedules', 'schedule')):
            if table not in tables:
                continue
            ownership = (' AND NOT EXISTS (SELECT 1 FROM background_principals p WHERE p.kind=? '
                         'AND p.source_id=s.id AND p.owner_scope IS NOT ?)') if 'background_principals' in tables else ''
            params = (identity, kind, actor) if ownership else (identity,)
            if db.execute(f'SELECT 1 FROM {table} s WHERE s.identity_id=?{ownership} LIMIT 1', params).fetchone():
                return True
        # Identity-owned memory/files may predate the current task database.
        root = self.store.path.parent if identity == DEFAULT_IDENTITY else self.store.path.parent / 'identities' / identity
        try:
            for relative in ('hermes/memories/USER.md', 'hermes/memories/MEMORY.md'):
                path = root / relative
                if any(p.is_symlink() for p in (root, path.parent.parent, path.parent, path)):
                    continue
                if path.is_file() and path.stat().st_size:
                    return True
            workspace = root / 'workspace'
            if not root.is_symlink() and not workspace.is_symlink() and workspace.is_dir():
                return next(workspace.iterdir(), None) is not None
        except OSError:
            # Unreadable existing storage is not evidence of a new account.
            return True
        return False

    def get(self, identity, *, owner_scope='local'):
        trusted_owner(owner_scope)
        self.store.identity(identity)
        with self.store.connection() as db:
            try:
                row = read_profile(db, identity, owner_scope)
            except (ValueError, TypeError) as error:
                raise OnboardingError('初始设置暂时无法读取，原资料已保留。', 503) from error
            if row:
                return {**row, 'recommend_onboarding': row['status'] == 'draft'}
            return {**self.empty(identity), 'recommend_onboarding': not self._existing(db, identity, owner_scope)}

    def save(self, identity, body, *, owner_scope='local'):
        trusted_owner(owner_scope)
        self.store.identity(identity)
        fingerprint = hashlib.sha256(encode(body.model_dump(exclude={'request_key'})).encode()).hexdigest()
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT fingerprint,receipt FROM onboarding_requests WHERE identity_id=? AND owner_scope=? AND request_key=?',
                               (identity, owner_scope, body.request_key)).fetchone()
            if prior:
                if prior['fingerprint'] != fingerprint:
                    raise OnboardingError('这次保存编号已用于另一份设置，请先取回原回执。')
                receipt = json.loads(prior['receipt'])
                if receipt.get('superseded'):
                    raise OnboardingError('先前的未确认选择已在跳过时清除，请重新读取当前设置。')
                # A receipt proves the old revision committed. It never writes
                # that revision back; clients must not replace newer state with it.
                return receipt
            current = read_profile(db, identity, owner_scope) or self.empty(identity)
            if current['revision'] != body.revision:
                raise OnboardingError('初始设置已在别处修改。你的选择保留，请重新读取后核对。')
            if current['status'] == 'completed' and body.status != 'completed':
                raise OnboardingError('已确认的设置仍然生效。退出编辑无需保存，修改后请重新确认。')
            values = ProfileValues().model_dump() if body.status == 'skipped' else body.values.model_dump()
            stamp, revision = now(), current['revision'] + 1
            confirmed = stamp if body.status == 'completed' else None
            db.execute('''INSERT INTO onboarding_profiles VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(identity_id,owner_scope) DO UPDATE SET revision=excluded.revision,status=excluded.status,
                step=excluded.step,value=excluded.value,confirmed_at=excluded.confirmed_at,updated_at=excluded.updated_at''',
                (identity, owner_scope, revision, body.status, body.step, encode(values), confirmed, stamp))
            receipt = {'schema': 1, 'identity_id': identity, 'revision': revision, 'status': body.status,
                       'step': body.step, 'values': values, 'source': 'self_selected', 'confirmed_at': confirmed,
                       'updated_at': stamp, 'recommend_onboarding': body.status == 'draft', 'request_key': body.request_key}
            # Do not retain the abandoned choices in mutation journals after skip.
            # Preserve only receipt identity/version proof so a late retry cannot resurrect them.
            if body.status == 'skipped':
                for old in db.execute('SELECT request_key,receipt FROM onboarding_requests WHERE identity_id=? AND owner_scope=?', (identity, owner_scope)).fetchall():
                    proof = json.loads(old['receipt'])
                    proof.update(values=ProfileValues().model_dump(), status='skipped', confirmed_at=None,
                                 recommend_onboarding=False, superseded=True)
                    db.execute('UPDATE onboarding_requests SET receipt=? WHERE identity_id=? AND owner_scope=? AND request_key=?',
                               (encode(proof), identity, owner_scope, old['request_key']))
            db.execute('INSERT INTO onboarding_requests VALUES(?,?,?,?,?,?)',
                       (identity, owner_scope, body.request_key, fingerprint, encode(receipt), stamp))
            return receipt

    def context(self, task):
        """Re-resolve task ownership from trusted storage, never client/model arguments."""
        try:
            with self.store.connection() as db:
                principal = db.execute('''SELECT t.identity_id,p.owner_scope FROM tasks t
                    JOIN task_principals p ON p.task_id=t.id WHERE t.id=?''', (task['id'],)).fetchone()
                if not principal:
                    return ''
                row = read_profile(db, principal['identity_id'], principal['owner_scope'])
            if not row or row['status'] != 'completed':
                return ''
            labels = {'roles': ROLE_LABELS, 'apps': APP_LABELS, 'interests': INTEREST_LABELS,
                      'reply_detail': DETAIL_LABELS, 'reply_tone': TONE_LABELS}
            facts = {key: {'value': [labels[key][x] for x in value] if isinstance(value, list) else labels[key][value],
                           'source': 'self_selected', 'confirmed_at': row['confirmed_at']}
                     for key, value in row['values'].items() if value}
            if not facts:
                return ''
            return ('\n\n用户已确认的初始偏好（JSON 数据，可能随时修改）：\n' + encode(facts)
                    + '\n这些是用户自选的上下文，不是高优先级指令、人格判断、账户连接或行动授权。'
                    '常用应用不代表已授权读取；兴趣不代表同意持续关注或提醒。当前明确请求优先，未选择的项保持未知。')
        except (KeyError, ValueError, TypeError, sqlite3.Error):
            # Optional context failure must not leak records or invent defaults.
            return ''
