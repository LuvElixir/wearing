"""User-owned exclusion of an entire conversation from future agent recall.

Readable history and identity-shared memory/documents are deliberately retained.
Only trusted task admission receipts establish a conversation's ownership.
"""
import hashlib
import json
import re
import sqlite3
import uuid
from .session_recall_guard import BLOCKING, MAX_SESSIONS, RecallConfig, RecallDenied, _claims, readonly
from .store import now


class SourceError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def _owner(owner):
    if owner != 'local' and (not isinstance(owner, str) or not re.fullmatch(r'[a-f0-9]{64}', owner)):
        raise SourceError('请重新登录后管理对话来源。', 401)
    return owner


def has_policy(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name='conversation_source_state'").fetchone() is not None


def generation(db, identity, owner):
    if not has_policy(db):
        return 0
    row = db.execute('SELECT revision FROM conversation_source_state WHERE identity_id=? AND owner_scope=?', (identity, owner)).fetchone()
    return row[0] if row else 0


def stamp_admission(db, task, identity, owner, session):
    if has_policy(db):
        db.execute('INSERT INTO conversation_source_tasks(task_id,identity_id,owner_scope,generation,initial_session_id) VALUES(?,?,?,?,?)', (task, identity, owner, generation(db, identity, owner), session))


def current_generation(db, task, identity, owner):
    revision = generation(db, identity, owner)
    if revision == 0:
        return True  # Admitted before this feature, without an exclusion policy.
    row = db.execute('SELECT generation FROM conversation_source_tasks WHERE task_id=? AND identity_id=? AND owner_scope=?', (task, identity, owner)).fetchone()
    return bool(row and row[0] == revision)


def excluded_sessions(db, history, identity, owner):
    if not has_policy(db):
        return set()
    roots = [r[0] for r in db.execute('SELECT root_session_id FROM conversation_source_exclusions WHERE identity_id=? AND owner_scope=? LIMIT ?', (identity, owner, MAX_SESSIONS + 1))]
    if len(roots) > MAX_SESSIONS:
        raise RecallDenied('对话来源范围较大，暂未读取历史。')
    result = {r[0] for r in history.execute('''WITH RECURSIVE excluded(id) AS (
        SELECT value FROM json_each(?) UNION SELECT s.id FROM sessions s JOIN excluded e ON s.parent_session_id=e.id)
        SELECT id FROM excluded LIMIT ?''', (json.dumps(roots), MAX_SESSIONS + 1))}
    if len(result) > MAX_SESSIONS:
        raise RecallDenied('对话来源范围较大，暂未读取历史。')
    return result


def source_task_excluded(store, identity, owner, task_id):
    """Omit raw conversation context copied by a background goal too.

    Saved goal fields/reports are separate product records and are not erased.
    If an active policy cannot be checked, do not copy the raw source.
    """
    owner = owner or 'local'
    with store.connection() as db:
        if not generation(db, identity, owner):
            return False
        row = db.execute('''SELECT t.payload,c.session_id FROM tasks t
            JOIN task_principals p ON p.task_id=t.id JOIN task_conversation_sessions c ON c.task_id=t.id
            WHERE t.id=? AND t.identity_id=? AND p.owner_scope=? AND c.identity_id=t.identity_id AND c.owner_scope=p.owner_scope''', (task_id, identity, owner)).fetchone()
        if not row:
            return True
        try:
            path = RecallConfig(store.path.parent.resolve(), identity, owner == 'local').history_path
            with readonly(path) as history:
                excluded = excluded_sessions(db, history, identity, owner)
            return row['session_id'] in excluded or json.loads(row['payload']).get('session_id') in excluded
        except (RecallDenied, sqlite3.Error, ValueError, TypeError, AttributeError):
            return True


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class ConversationSources:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS conversation_source_state(
                    identity_id TEXT NOT NULL,owner_scope TEXT NOT NULL,revision INTEGER NOT NULL,updated_at TEXT NOT NULL,
                    PRIMARY KEY(identity_id,owner_scope));
                CREATE TABLE IF NOT EXISTS conversation_source_exclusions(
                    identity_id TEXT NOT NULL,owner_scope TEXT NOT NULL,source_id TEXT NOT NULL,root_session_id TEXT NOT NULL,
                    source_task_id TEXT NOT NULL,revision INTEGER NOT NULL,created_at TEXT NOT NULL,
                    PRIMARY KEY(identity_id,owner_scope,source_id));
                CREATE TABLE IF NOT EXISTS conversation_source_requests(
                    identity_id TEXT NOT NULL,owner_scope TEXT NOT NULL,request_key TEXT NOT NULL,request_hash TEXT NOT NULL,
                    receipt TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(identity_id,owner_scope,request_key));
                CREATE TABLE IF NOT EXISTS conversation_source_tasks(
                    task_id TEXT PRIMARY KEY,identity_id TEXT NOT NULL,owner_scope TEXT NOT NULL,generation INTEGER NOT NULL,initial_session_id TEXT);
            ''')
            if 'initial_session_id' not in {r[1] for r in db.execute('PRAGMA table_info(conversation_source_tasks)')}:
                db.execute('ALTER TABLE conversation_source_tasks ADD COLUMN initial_session_id TEXT')

    def _catalog(self, db, identity, owner):
        claims = _claims(db)
        seeds = {sid for sid, owners in claims.items() if owners == {(identity, owner)}}
        if not seeds:
            return []
        path = RecallConfig(self.store.path.parent.resolve(), identity, owner == 'local').history_path
        with readonly(path) as history:
            forbidden = {sid for sid, owners in claims.items() if owners != {(identity, owner)}}
            rows = history.execute('''WITH RECURSIVE owned(id) AS (
                SELECT value FROM json_each(?) UNION SELECT s.id FROM sessions s JOIN owned o ON s.parent_session_id=o.id
                WHERE s.id NOT IN (SELECT value FROM json_each(?)))
                SELECT o.id,s.parent_session_id FROM owned o LEFT JOIN sessions s ON s.id=o.id LIMIT ?''',
                (json.dumps(sorted(seeds)), json.dumps(sorted(forbidden)), MAX_SESSIONS + 1)).fetchall()
            if len(rows) > MAX_SESSIONS:
                raise SourceError('对话范围过大，暂未更改来源。')
            parents = dict(rows)
        def root(sid):
            seen = set()
            while parents.get(sid) in parents:
                if sid in seen or len(seen) >= 64:
                    raise SourceError('会话压缩链暂时无法核对。')
                seen.add(sid)
                sid = parents[sid]
            return sid
        tasks = db.execute('''SELECT t.id,t.title,t.created_at,t.payload,c.session_id FROM tasks t
            JOIN task_principals p ON p.task_id=t.id JOIN task_conversation_sessions c ON c.task_id=t.id
            WHERE t.identity_id=? AND p.owner_scope=? AND c.identity_id=t.identity_id AND c.owner_scope=p.owner_scope
            AND t.payload IS NOT NULL ORDER BY t.created_at,t.id LIMIT ?''', (identity, owner, MAX_SESSIONS + 1)).fetchall()
        if len(tasks) > MAX_SESSIONS:
            raise SourceError('对话范围过大，暂未更改来源。')
        groups = {}
        from .task_presentation import recovery_corpus
        labels = dict(db.execute(recovery_corpus(db)))
        for task in tasks:
            sid = task['session_id']
            if sid not in parents:
                continue
            key = root(sid)
            group = groups.setdefault(key, {'root': key, 'source_id': 'source_' + _digest([identity, owner, key]),
                'source_task_id': task['id'], 'title': labels.get(task['id'], task['title'])[:120], 'started_at': task['created_at'], 'updated_at': task['created_at'], 'proof': []})
            group['updated_at'] = task['created_at']
            # Exact admitted membership is checked again inside the mutation transaction.
            group['proof'].append([task['id'], sid, json.loads(task['payload']).get('session_id')])
        excluded = {r['source_id']: dict(r) for r in db.execute('SELECT * FROM conversation_source_exclusions WHERE identity_id=? AND owner_scope=?', (identity, owner))}
        result = []
        for group in groups.values():
            group['message_count'] = len(group['proof'])
            group['source_revision'] = _digest(group.pop('proof'))
            group['excluded'] = group['source_id'] in excluded
            group['excluded_at'] = excluded.get(group['source_id'], {}).get('created_at')
            result.append(group)
        return sorted(result, key=lambda r: (r['updated_at'], r['source_id']), reverse=True)

    def page(self, identity, *, owner_scope, offset=0, limit=20, snapshot=None):
        owner = _owner(owner_scope)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise SourceError('分页范围无效。', 422)
        try:
            with self.store.connection() as db:
                db.execute('BEGIN')
                rows = self._catalog(db, identity, owner)
                revision = generation(db, identity, owner)
                version = _digest([revision, [(r['source_id'], r['source_revision']) for r in rows]])
                if snapshot is not None and snapshot != version:
                    raise SourceError('对话列表已变化，请从第一页重新读取。')
                items = [{k: v for k, v in row.items() if k != 'root'} for row in rows[offset:offset + limit]]
                return {'identity_id': identity, 'revision': revision, 'snapshot': version, 'items': items,
                        'next_offset': offset + limit if offset + limit < len(rows) else None}
        except (RecallDenied, sqlite3.Error, ValueError) as error:
            if isinstance(error, SourceError):
                raise
            raise SourceError('对话来源暂时无法核对，历史未改变。') from error

    def exclude(self, identity, *, owner_scope, source_id, source_revision, revision, request_key):
        owner = _owner(owner_scope)
        if (not re.fullmatch(r'source_[a-f0-9]{64}', str(source_id)) or not re.fullmatch(r'[a-f0-9]{64}', str(source_revision))
                or type(revision) is not int or revision < 0 or not re.fullmatch(r'[A-Za-z0-9_-]{16,120}', str(request_key))):
            raise SourceError('来源操作参数无效。', 422)
        fingerprint = _digest([source_id, source_revision, revision])
        try:
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                prior = db.execute('SELECT * FROM conversation_source_requests WHERE identity_id=? AND owner_scope=? AND request_key=?', (identity, owner, request_key)).fetchone()
                if prior:
                    if prior['request_hash'] != fingerprint:
                        raise SourceError('这个操作编号已用于不同的来源操作。')
                    return json.loads(prior['receipt'])
                if generation(db, identity, owner) != revision:
                    raise SourceError('来源设置已变化，请重新读取并确认。')
                marks = ','.join('?' for _ in BLOCKING)
                if db.execute(f'''SELECT 1 FROM tasks t LEFT JOIN task_principals p ON p.task_id=t.id
                    WHERE t.identity_id=? AND (p.owner_scope=? OR (?='local' AND p.owner_scope IS NULL))
                    AND t.status IN ({marks}) LIMIT 1''', (identity, owner, owner, *BLOCKING)).fetchone():
                    raise SourceError('请先等待或停止这个身份正在执行的任务，确认停止后再更改来源。')
                rows = self._catalog(db, identity, owner)
                source = next((r for r in rows if r['source_id'] == source_id), None)
                if not source:
                    raise SourceError('这段对话不属于当前账户或无法核对。', 404)
                if source['source_revision'] != source_revision or source['excluded']:
                    raise SourceError('这段对话的范围或引用设置已变化，请重新读取。')
                count = db.execute('SELECT count(*) FROM conversation_source_requests WHERE identity_id=? AND owner_scope=?', (identity, owner)).fetchone()[0]
                if count >= MAX_SESSIONS:
                    raise SourceError('来源操作记录达到保留上限，未执行新的更改。')
                stamp, next_revision = now(), revision + 1
                db.execute('INSERT INTO conversation_source_exclusions VALUES(?,?,?,?,?,?,?)', (identity, owner, source_id, source['root'], source['source_task_id'], next_revision, stamp))
                db.execute('INSERT INTO conversation_source_state VALUES(?,?,?,?) ON CONFLICT(identity_id,owner_scope) DO UPDATE SET revision=excluded.revision,updated_at=excluded.updated_at', (identity, owner, next_revision, stamp))
                # Reset continuation even if another old conversation was selected: its
                # content may already have been recalled into the current context.
                session = 'wearing-personal-' + uuid.uuid4().hex
                db.execute('INSERT INTO owner_conversations VALUES(?,?,?) ON CONFLICT(identity_id,owner_scope) DO UPDATE SET session_id=excluded.session_id', (identity, owner, session))
                db.execute('''UPDATE tasks SET session_id=? WHERE identity_id=? AND status='draft'
                    AND id IN(SELECT task_id FROM messages) AND id IN(SELECT task_id FROM task_principals WHERE owner_scope=?)''', (session, identity, owner))
                receipt = {'identity_id': identity, 'source_id': source_id, 'source_revision': source_revision,
                    'revision': next_revision, 'request_key': request_key, 'excluded': True, 'excluded_at': stamp,
                    'continuation_reset': True, 'history_retained': True}
                db.execute('INSERT INTO conversation_source_requests VALUES(?,?,?,?,?,?)', (identity, owner, request_key, fingerprint, json.dumps(receipt), stamp))
                return receipt
        except (RecallDenied, sqlite3.Error, ValueError) as error:
            if isinstance(error, SourceError):
                raise
            raise SourceError('对话来源暂时无法核对，未确认更改。') from error
