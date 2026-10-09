"""Identity-scoped briefing preferences; saving never starts an agent or connects an app."""
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .store import now

SOURCE_LABELS = {'event': '已保存日程', 'task': '待办', 'note': '笔记', 'files': '文件空间', 'feishu': '飞书'}
DEFAULT_SOURCES = ['event', 'task', 'note', 'files']


class PreferenceError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class PreferenceValues(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    interests: list[str] = Field(default_factory=list, max_length=8)
    priorities: str = Field(default='', max_length=1000)
    sources: list[Literal['event', 'task', 'note', 'files', 'feishu']] = Field(default_factory=lambda: list(DEFAULT_SOURCES), min_length=1, max_length=5)
    max_items: int = Field(default=3, ge=1, le=3, strict=True)

    @field_validator('interests')
    @classmethod
    def valid_interests(cls, values):
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 60 for value in cleaned) or len(set(cleaned)) != len(cleaned):
            raise ValueError('兴趣最多8项，每项1–60字，不能重复。')
        return cleaned

    @field_validator('sources')
    @classmethod
    def distinct_sources(cls, values):
        if len(set(values)) != len(values):
            raise ValueError('来源不能重复。')
        return [key for key in SOURCE_LABELS if key in values]


class SavePreferences(PreferenceValues):
    revision: int = Field(ge=0, strict=True)
    request_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,120}$')


class BriefingPreferences:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS briefing_preferences (
                    identity_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                    value TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS briefing_preference_requests (
                    identity_id TEXT NOT NULL, request_key TEXT NOT NULL,
                    spec TEXT NOT NULL, receipt TEXT NOT NULL,
                    PRIMARY KEY(identity_id,request_key));
            ''')

    @staticmethod
    def read(db, identity):
        row = db.execute('SELECT * FROM briefing_preferences WHERE identity_id=?', (identity,)).fetchone()
        values = PreferenceValues.model_validate(json.loads(row['value'])) if row else PreferenceValues()
        return {'schema': 1, 'identity_id': identity, 'revision': row['revision'] if row else 0,
                **values.model_dump(), 'updated_at': row['updated_at'] if row else None}

    def get(self, identity):
        self.store.identity(identity)
        with self.store.connection() as db:
            return self.read(db, identity)

    def save(self, identity, body):
        self.store.identity(identity)
        spec = json.dumps(body.model_dump(exclude={'request_key'}), ensure_ascii=False, sort_keys=True)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM briefing_preference_requests WHERE identity_id=? AND request_key=?', (identity, body.request_key)).fetchone()
            if prior:
                if prior['spec'] != spec:
                    raise PreferenceError('这次保存编号已用于其他设置，请先取回原回执。')
                return json.loads(prior['receipt'])
            current = self.read(db, identity)
            if body.revision != current['revision']:
                raise PreferenceError('简报偏好已在别处修改。你的输入保留，请重新读取后核对。')
            values = body.model_dump(exclude={'revision', 'request_key'})
            stamp, revision = now(), current['revision'] + 1
            db.execute('INSERT INTO briefing_preferences VALUES(?,?,?,?) ON CONFLICT(identity_id) DO UPDATE SET revision=excluded.revision,value=excluded.value,updated_at=excluded.updated_at',
                       (identity, revision, json.dumps(values, ensure_ascii=False), stamp))
            receipt = {'schema': 1, 'identity_id': identity, 'revision': revision, **values,
                       'updated_at': stamp, 'request_key': body.request_key}
            db.execute('INSERT INTO briefing_preference_requests VALUES(?,?,?,?)', (identity, body.request_key, spec, json.dumps(receipt, ensure_ascii=False)))
            return receipt
