"""Named lists and stable ordering over existing life task records."""
import hashlib
import json
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .life import LifeDraft, LifeError
from .store import now

MAX_LISTS = 500
MAX_BACKFILL = 50000
MAX_RENAME_ITEMS = 5000


class ListChange(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    action: Literal['create', 'rename', 'archive', 'restore', 'add', 'move', 'reorder']
    revision: int = Field(ge=0, strict=True)
    request_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,120}$')
    list_id: str | None = Field(default=None, pattern=r'^list_[a-f0-9]{32}$')
    name: str | None = Field(default=None, min_length=1, max_length=80)
    record_id: str | None = Field(default=None, pattern=r'^life_[a-f0-9]{32}$')
    record_revision: int | None = Field(default=None, ge=1, strict=True)
    target_list_id: str | None = Field(default=None, pattern=r'^list_[a-f0-9]{32}$')
    before_id: str | None = Field(default=None, pattern=r'^life_[a-f0-9]{32}$')
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, max_length=12000)
    timezone: str | None = Field(default=None, max_length=80)

    @model_validator(mode='after')
    def arguments(self):
        required = {'create': {'name'}, 'rename': {'list_id', 'name'}, 'archive': {'list_id'},
                    'restore': {'list_id'}, 'add': {'list_id', 'title'},
                    'move': {'list_id', 'record_id', 'record_revision', 'target_list_id'},
                    'reorder': {'list_id', 'record_id', 'record_revision'}}[self.action]
        allowed = required | ({'before_id'} if self.action in {'move', 'reorder'} else {'content', 'timezone'} if self.action == 'add' else set())
        fields = self.model_dump(exclude={'action', 'revision', 'request_key'})
        if any(fields[key] is None for key in required) or any(value is not None and key not in allowed for key, value in fields.items()):
            raise ValueError('清单操作的字段不完整或不适用。')
        return self


class TaskListBook:
    def __init__(self, life):
        self.life, self.store = life, life.store
        with self.store.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS task_list_boards (
                    identity_id TEXT PRIMARY KEY, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS task_lists (
                    id TEXT PRIMARY KEY, identity_id TEXT NOT NULL, name TEXT NOT NULL,
                    name_key TEXT NOT NULL, revision INTEGER NOT NULL, archived_at TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(identity_id,name_key));
                CREATE TABLE IF NOT EXISTS task_list_members (
                    record_id TEXT PRIMARY KEY, identity_id TEXT NOT NULL, list_id TEXT NOT NULL,
                    position INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS task_list_order ON task_list_members(identity_id,list_id,position,record_id);
                CREATE TABLE IF NOT EXISTS task_list_requests (
                    identity_id TEXT NOT NULL, request_key TEXT NOT NULL, spec TEXT NOT NULL,
                    receipt TEXT NOT NULL, PRIMARY KEY(identity_id,request_key));
            ''')

    @staticmethod
    def bump(db, identity):
        db.execute('INSERT INTO task_list_boards VALUES(?,1) ON CONFLICT(identity_id) DO UPDATE SET revision=revision+1', (identity,))

    @staticmethod
    def revision(db, identity):
        row = db.execute('SELECT revision FROM task_list_boards WHERE identity_id=?', (identity,)).fetchone()
        return row[0] if row else 0

    def _create_list(self, db, identity, name):
        if db.execute('SELECT count(*) FROM task_lists WHERE identity_id=?', (identity,)).fetchone()[0] >= MAX_LISTS:
            raise LifeError(f'当前身份最多支持 {MAX_LISTS} 份清单，请先整理已有清单。', 413)
        identifier, stamp = 'list_' + uuid.uuid4().hex, now()
        db.execute('INSERT INTO task_lists VALUES(?,?,?,?,1,NULL,?,?)', (identifier, identity, name, name.casefold(), stamp, stamp))
        return db.execute('SELECT * FROM task_lists WHERE id=?', (identifier,)).fetchone()

    def sync(self, db, record):
        """Called inside every LifeBook task-write transaction, including old clients."""
        if record['kind'] != 'task': return
        identity, name = record['identity_id'], record['list_name']
        member = db.execute('SELECT m.list_id,l.name FROM task_list_members m JOIN task_lists l ON l.id=m.list_id AND l.identity_id=m.identity_id WHERE m.identity_id=? AND m.record_id=?', (identity, record['id'])).fetchone()
        if not member or member['name'] != name:
            target = db.execute('SELECT * FROM task_lists WHERE identity_id=? AND name_key=?', (identity, name.casefold())).fetchone()
            if target and target['name'] != name:
                raise LifeError('已有同名清单，请使用该清单的准确名称。', 409)
            if target and target['archived_at']:
                raise LifeError('这份清单已归档，请恢复后再新增或移入事项。', 409)
            target = target or self._create_list(db, identity, name)
            position = db.execute('SELECT COALESCE(MAX(position),0)+1 FROM task_list_members WHERE identity_id=? AND list_id=?', (identity, target['id'])).fetchone()[0]
            db.execute('INSERT INTO task_list_members VALUES(?,?,?,?) ON CONFLICT(record_id) DO UPDATE SET list_id=excluded.list_id,position=excluded.position', (record['id'], identity, target['id'], position))
        self.bump(db, identity)

    def ensure(self, db, identity):
        # An additive index migration: original record IDs/revisions are untouched.
        rows = db.execute('''SELECT r.* FROM life_records r LEFT JOIN task_list_members m
            ON m.record_id=r.id AND m.identity_id=r.identity_id
            WHERE r.identity_id=? AND json_extract(r.body,'$.kind')='task' AND m.record_id IS NULL
            ORDER BY r.created_at,r.id LIMIT ?''', (identity, MAX_BACKFILL + 1)).fetchall()
        if len(rows) > MAX_BACKFILL:
            raise LifeError('历史待办超过一次清单整理上限，请联系管理员分批迁移；原记录未修改。', 413)
        for row in rows: self.sync(db, self.life.unpack(row))

    def _list(self, db, identity, identifier):
        row = db.execute('SELECT id,name,revision,archived_at,created_at,updated_at FROM task_lists WHERE identity_id=? AND id=?', (identity, identifier)).fetchone()
        if not row: raise LifeError('当前身份没有这份清单。', 404)
        counts = db.execute('''SELECT count(*),COALESCE(SUM(CASE WHEN json_extract(r.body,'$.completed')=0 THEN 1 ELSE 0 END),0)
            FROM task_list_members m JOIN life_records r ON r.id=m.record_id AND r.identity_id=m.identity_id
            WHERE m.identity_id=? AND m.list_id=? AND r.deleted_at IS NULL''', (identity, identifier)).fetchone()
        return {**dict(row), 'total': counts[0], 'open': counts[1]}

    def catalog(self, identity):
        self.store.identity(identity)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self.ensure(db, identity)
            ids = db.execute('SELECT id FROM task_lists WHERE identity_id=? ORDER BY created_at,id LIMIT ?', (identity, MAX_LISTS + 1)).fetchall()
            if len(ids) > MAX_LISTS: raise LifeError('清单目录超过读取上限，请联系管理员分批整理。', 413)
            return {'identity_id': identity, 'revision': self.revision(db, identity), 'lists': [self._list(db, identity, row[0]) for row in ids]}

    def items(self, identity, identifier, *, offset=0, limit=100, revision=None):
        self.store.identity(identity)
        if not isinstance(offset, int) or not 0 <= offset <= 1000000 or not isinstance(limit, int) or not 1 <= limit <= 100 or offset and revision is None:
            raise LifeError('分页参数不完整，请重新读取清单。', 422)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self.ensure(db, identity)
            current = self.revision(db, identity)
            if revision is not None and current != revision: raise LifeError('清单已有变化，请从第一页重新读取，避免遗漏事项。')
            item = self._list(db, identity, identifier)
            rows = db.execute('''SELECT r.*,m.position FROM task_list_members m JOIN life_records r
                ON r.id=m.record_id AND r.identity_id=m.identity_id WHERE m.identity_id=? AND m.list_id=?
                AND r.deleted_at IS NULL ORDER BY m.position,r.id LIMIT ? OFFSET ?''', (identity, identifier, limit, offset)).fetchall()
            values = [{**self.life.with_capture(db, self.life.unpack(row)), 'position': row['position']} for row in rows]
            next_offset = offset + len(values) if offset + len(values) < item['total'] else None
            return {'identity_id': identity, 'revision': current, 'list': item, 'items': values, 'offset': offset, 'next_offset': next_offset}

    def change(self, identity, body: ListChange, *, actor='user', origin=None):
        self.store.identity(identity)
        spec = hashlib.sha256(body.model_dump_json(exclude={'request_key'}).encode()).hexdigest()
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT spec,receipt FROM task_list_requests WHERE identity_id=? AND request_key=?', (identity, body.request_key)).fetchone()
            if prior:
                if prior['spec'] != spec: raise LifeError('这个操作编号已经用于其他内容，请先取回原回执。')
                return json.loads(prior['receipt'])
            self.ensure(db, identity)
            if body.revision != self.revision(db, identity): raise LifeError('清单已在别处修改，你的操作保留。请读取最新内容后再确认。')
            record, count, affected = None, 0, []
            if body.action == 'create':
                if db.execute('SELECT 1 FROM task_lists WHERE identity_id=? AND name_key=?', (identity, body.name.casefold())).fetchone(): raise LifeError('已有同名清单，请打开它；如果已归档，可先恢复。')
                item = self._create_list(db, identity, body.name)
                affected = [item['id']]
            else:
                item = self._list(db, identity, body.list_id)
                affected = [item['id']]
                if body.action == 'rename':
                    duplicate = db.execute('SELECT 1 FROM task_lists WHERE identity_id=? AND name_key=? AND id<>?', (identity, body.name.casefold(), item['id'])).fetchone()
                    if duplicate: raise LifeError('已有同名清单，请使用其他名称。')
                    rows = db.execute('''SELECT r.* FROM life_records r JOIN task_list_members m ON m.record_id=r.id AND m.identity_id=r.identity_id
                        WHERE r.identity_id=? AND m.list_id=? LIMIT ?''', (identity, item['id'], MAX_RENAME_ITEMS + 1)).fetchall()
                    if len(rows) > MAX_RENAME_ITEMS: raise LifeError('这份清单超过 5000 条，请联系管理员分批改名；原内容未改变。', 413)
                    for row in rows:
                        draft = json.loads(row['body']); draft['list_name'] = body.name
                        db.execute('UPDATE life_records SET body=?,revision=revision+1,updated_at=? WHERE id=? AND identity_id=?', (json.dumps(draft, ensure_ascii=False), now(), row['id'], identity))
                        updated = self.life.unpack(db.execute('SELECT * FROM life_records WHERE id=?', (row['id'],)).fetchone())
                        self.life.receipt(db, updated, actor, origin)
                    count = len(rows)
                    db.execute('UPDATE task_lists SET name=?,name_key=?,revision=revision+1,updated_at=? WHERE id=?', (body.name, body.name.casefold(), now(), item['id']))
                elif body.action in {'archive', 'restore'}:
                    db.execute('UPDATE task_lists SET archived_at=?,revision=revision+1,updated_at=? WHERE id=?', (now() if body.action == 'archive' else None, now(), item['id']))
                elif body.action == 'add':
                    if item['archived_at']: raise LifeError('请先恢复这份清单，再新增事项。')
                    record = self.life._create(db, identity, LifeDraft(kind='task', title=body.title, content=body.content or '', list_name=item['name'], timezone=body.timezone or 'Asia/Shanghai'), 'listadd_' + hashlib.sha256(body.request_key.encode()).hexdigest(), actor, origin=origin)
                    count = 1
                else:
                    row = db.execute('''SELECT r.* FROM life_records r JOIN task_list_members m ON m.record_id=r.id AND m.identity_id=r.identity_id
                        WHERE r.identity_id=? AND r.id=? AND m.list_id=? AND r.deleted_at IS NULL''', (identity, body.record_id, item['id'])).fetchone()
                    if not row: raise LifeError('这条事项不在当前清单，请刷新后核对。', 404)
                    if row['revision'] != body.record_revision: raise LifeError('这条事项已有更新，请读取最新内容后再移动。')
                    target = self._list(db, identity, body.target_list_id) if body.action == 'move' else item
                    if target['archived_at']: raise LifeError('请先恢复目标清单，再移入或排序。')
                    if target['id'] != item['id']:
                        record = self.life._update(db, identity, body.record_id, body.record_revision, {'list_name': target['name']}, actor=actor, origin=origin)
                        affected.append(target['id']); count = 1
                    else: record = self.life.with_capture(db, self.life.unpack(row))
                    if body.before_id != body.record_id:
                        if body.before_id:
                            before = db.execute('''SELECT m.position FROM task_list_members m JOIN life_records r ON r.id=m.record_id AND r.identity_id=m.identity_id
                                WHERE m.identity_id=? AND m.list_id=? AND m.record_id=? AND r.deleted_at IS NULL''', (identity, target['id'], body.before_id)).fetchone()
                            if not before: raise LifeError('排序参照事项已变化，请刷新后核对。')
                            position = before[0]
                        else: position = db.execute('SELECT COALESCE(MAX(position),0)+1 FROM task_list_members WHERE identity_id=? AND list_id=?', (identity, target['id'])).fetchone()[0]
                        db.execute('UPDATE task_list_members SET position=position+1 WHERE identity_id=? AND list_id=? AND position>=?', (identity, target['id'], position))
                        db.execute('UPDATE task_list_members SET position=? WHERE identity_id=? AND record_id=?', (position, identity, body.record_id))
            self.bump(db, identity)
            receipt = {'identity_id': identity, 'request_key': body.request_key, 'action': body.action,
                       'revision': self.revision(db, identity), 'lists': [self._list(db, identity, identifier) for identifier in affected],
                       'record': record, 'changed_records': count}
            db.execute('INSERT INTO task_list_requests VALUES(?,?,?,?)', (identity, body.request_key, spec, json.dumps(receipt, ensure_ascii=False)))
            return receipt


def install_task_list_routes(app, life):
    from fastapi import Request, Query
    book = life.lists
    @app.get('/api/task-lists')
    async def catalog(request: Request): return book.catalog(request.state.identity_id)

    @app.get('/api/task-lists/{list_id}/items')
    async def items(request: Request, list_id: str, offset: int = Query(0, ge=0, le=1000000), limit: int = Query(100, ge=1, le=100), revision: int | None = Query(None, ge=0)):
        return book.items(request.state.identity_id, list_id, offset=offset, limit=limit, revision=revision)

    @app.post('/api/task-lists/change')
    async def change(request: Request, body: ListChange): return book.change(request.state.identity_id, body)
