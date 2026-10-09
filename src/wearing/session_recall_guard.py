"""Owner-bound Hermes history recall, installed only by the Pajio host.

The native inline executor bypasses the registry, so the module callable is the
boundary. No model argument supplies execution authority. The source databases
are read-only; this neither deletes history nor promises semantic forgetting.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import time


LIVE = {'starting', 'running', 'waiting_for_approval'}
BLOCKING = LIVE | {'stopping', 'connection_lost', 'ambiguous'}
MAX_SESSIONS = 10000


class RecallDenied(ValueError):
    pass


@contextmanager
def readonly(path):
    if path.is_symlink() or not path.is_file():
        raise RecallDenied('历史记录暂时无法核对。')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
    db.row_factory = sqlite3.Row
    deadline = time.monotonic() + 2
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    db.execute('PRAGMA query_only=ON')
    try:
        yield db
    finally:
        db.close()


@dataclass(frozen=True)
class RecallConfig:
    data_dir: Path
    identity: str
    local: bool = False

    def __post_init__(self):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', self.identity):
            raise ValueError('Invalid recall identity')
        if not self.data_dir.is_absolute() or self.data_dir.is_symlink():
            raise ValueError('Invalid recall data directory')

    @property
    def task_path(self):
        return self.data_dir / 'wearing.sqlite3'

    @property
    def history_path(self):
        root = self.data_dir if self.identity == 'daily' else self.data_dir / 'identities' / self.identity
        path = root / 'hermes' / 'state.db'
        ancestors = [path, *path.parents]
        ancestors = ancestors[:ancestors.index(self.data_dir) + 1]
        if any(p.is_symlink() for p in ancestors):
            raise RecallDenied('历史记录目录无法核对。')
        return path


def _sid(value):
    return isinstance(value, str) and 0 < len(value) <= 256 and '/' not in value and not any(ord(c) < 32 for c in value)


def _claims(db):
    """Only admitted conversation receipts or server-minted standalone ids.

    Conversation payload.session_id retains the admitted predecessor after
    compaction updates the latest receipt. Pre-upgrade shared sessions have no
    receipt and are intentionally not adopted by a cloud owner.
    """
    rows = db.execute('''SELECT t.id,t.identity_id,t.session_id,t.payload,p.owner_scope,
        c.identity_id AS receipt_identity,c.owner_scope AS receipt_owner,c.session_id AS receipt_session,
        EXISTS(SELECT 1 FROM messages m WHERE m.task_id=t.id) AS conversation
        FROM tasks t LEFT JOIN task_principals p ON p.task_id=t.id
        LEFT JOIN task_conversation_sessions c ON c.task_id=t.id
        WHERE t.payload IS NOT NULL LIMIT ?''', (MAX_SESSIONS + 1,)).fetchall()
    if len(rows) > MAX_SESSIONS:
        raise RecallDenied('历史会话范围较大，暂未执行检索。')
    admissions = {}
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='conversation_source_tasks'").fetchone():
        if 'initial_session_id' in {r[1] for r in db.execute('PRAGMA table_info(conversation_source_tasks)')}:
            admissions = {r['task_id']: dict(r) for r in db.execute('SELECT * FROM conversation_source_tasks LIMIT ?', (MAX_SESSIONS + 1,))}
    claims = {}
    for row in rows:
        principal = (row['identity_id'], row['owner_scope'])
        if row['conversation']:
            if (row['receipt_identity'], row['receipt_owner']) != principal:
                # A missing/mismatched receipt is a negative claim too: do not
                # accidentally adopt that session as an unclaimed descendant.
                principal = (row['identity_id'], None)
                candidates = [row['session_id']]
            else:
                candidates = [row['receipt_session']]
            try:
                candidates.append(json.loads(row['payload']).get('session_id'))
            except (ValueError, TypeError, AttributeError):
                pass
        else:
            # Host admission also proves goal/schedule session names. Only the
            # immutable exact receipt agrees with the server's frozen payload.
            receipt = admissions.get(row['id'])
            try:
                admitted = json.loads(row['payload']).get('session_id')
            except (ValueError, TypeError, AttributeError):
                admitted = None
            if (receipt and receipt['identity_id'] == row['identity_id']
                    and receipt['owner_scope'] == (row['owner_scope'] or 'local')
                    and receipt['initial_session_id'] == admitted and _sid(admitted)):
                candidates = [admitted]
            else:
                candidates = ['wearing-' + row['id']]
                # Missing background admission must also stop descendants from
                # being adopted through a different owner's positive root.
                for unknown in (admitted, row['session_id'], (receipt or {}).get('initial_session_id')):
                    if _sid(unknown) and unknown not in candidates:
                        claims.setdefault(unknown, set()).add((row['identity_id'], None))
        for sid in candidates:
            if _sid(sid):
                claims.setdefault(sid, set()).add(principal)
    return claims


def authority(config, run_id, current_session, history):
    if not _sid(run_id) or not _sid(current_session):
        raise RecallDenied('当前运行的历史读取授权无法核对。')
    with readonly(config.task_path) as db:
        # An old known run never falls through to a new pending task.
        rows = db.execute('SELECT * FROM tasks WHERE run_id=?', (run_id,)).fetchall()
        if rows:
            if len(rows) != 1 or rows[0]['identity_id'] != config.identity or rows[0]['status'] not in LIVE:
                raise RecallDenied('原运行已停止或不属于当前身份。')
            task = rows[0]
        else:
            marks = ','.join('?' for _ in BLOCKING)
            pending = db.execute(f'SELECT * FROM tasks WHERE status IN ({marks})', tuple(BLOCKING)).fetchall()
            if len(pending) != 1 or pending[0]['identity_id'] != config.identity or pending[0]['status'] != 'starting' or pending[0]['run_id'] is not None:
                raise RecallDenied('当前运行尚未获得可核对的历史读取授权。')
            task = pending[0]
        principal = db.execute('SELECT owner_scope FROM task_principals WHERE task_id=?', (task['id'],)).fetchone()
        owner = principal[0] if principal else None
        if config.local:
            if owner not in {None, 'local'}:
                raise RecallDenied('当前本机运行的账户归属无法核对。')
        elif not isinstance(owner, str) or not re.fullmatch(r'[a-f0-9]{64}', owner):
            raise RecallDenied('当前运行缺少可信账户归属，未读取历史。')
        from .conversation_sources import current_generation, excluded_sessions
        if not current_generation(db, task['id'], config.identity, owner or 'local'):
            raise RecallDenied('来源设置已变化，原运行不能读取历史。')
        claims = _claims(db)
        expected = (config.identity, owner)
        acceptable = {expected} | ({(config.identity, None), (config.identity, 'local')} if config.local else set())
        seeds = {sid for sid, owners in claims.items() if owners <= acceptable}
        if config.local:
            # Legacy unowned local history remains explicitly local. Any known
            # cloud/foreign claim is excluded even in a reused local directory.
            seeds.update(row[0] for row in history.execute('SELECT id FROM sessions LIMIT ?', (MAX_SESSIONS + 1,))
                         if row[0] not in claims)
        if len(seeds) > MAX_SESSIONS:
            raise RecallDenied('历史会话范围较大，暂未执行检索。')
        forbidden = {sid for sid, owners in claims.items() if not owners <= acceptable}
        # Follow only descendants of positively owned roots. Never walk upward
        # into a pre-upgrade shared parent. A foreign claim stops the branch.
        allowed = {r[0] for r in history.execute('''WITH RECURSIVE owned(id) AS (
            SELECT value FROM json_each(?) WHERE value NOT IN (SELECT value FROM json_each(?))
            UNION SELECT s.id FROM sessions s JOIN owned o ON s.parent_session_id=o.id
              WHERE s.id NOT IN (SELECT value FROM json_each(?)))
            SELECT id FROM owned LIMIT ?''', (json.dumps(sorted(seeds)), json.dumps(sorted(forbidden)), json.dumps(sorted(forbidden)), MAX_SESSIONS + 1))}
        allowed -= excluded_sessions(db, history, config.identity, owner or 'local')
        if len(allowed) > MAX_SESSIONS:
            raise RecallDenied('历史会话范围较大，暂未执行检索。')
        # Bind this call to the active task's own admitted session, including a
        # native compression continuation. Another allowed old session is not a
        # substitute for the active task during the POST /runs receipt gap.
        base = task['session_id']
        lineage, cursor = set(), current_session
        for _ in range(64):
            if not cursor or cursor in lineage or cursor not in allowed:
                break
            lineage.add(cursor)
            if cursor == base:
                return task['id'], owner, allowed
            row = history.execute('SELECT parent_session_id FROM sessions WHERE id=?', (cursor,)).fetchone()
            cursor = row[0] if row else None
        raise RecallDenied('工具调用与当前运行的会话不一致。')


def _integer(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (ValueError, TypeError, OverflowError):
        return default


def _message(row, cap=4000):
    return {k: row[k] for k in ('id', 'role', 'timestamp')} | {'content': (row['content'] or '')[:cap]}


def _time_bound(value):
    if value in {None, ''}:
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise RecallDenied('Invalid time bound')
    if match := re.fullmatch(r'(\d+)\s*([hdw])', value.strip(), re.I):
        return int(time.time()) - int(match[1]) * {'h': 3600, 'd': 86400, 'w': 604800}[match[2].lower()]
    parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    return int((parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp())


class RecallGuard:
    def __init__(self, config, run_id):
        self.config, self.run_id = config, run_id

    def search(self, query='', role_filter=None, limit=3, db=None, current_session_id=None,
               session_id=None, around_message_id=None, window=5, sort=None, profile=None,
               detail='adaptive', after=None, before=None, exclude_session_ids=None):
        # db/current_session_id arrive from the native inline executor, never
        # from its model argument map. Ignore db's path; only host config wins.
        del db, detail
        try:
            if profile not in {None, ''} or session_id is not None and not _sid(session_id):
                raise RecallDenied('历史检索仅限当前身份和账户，不能切换 profile。')
            if not isinstance(query, str) or len(query) > 600:
                raise RecallDenied('请使用不超过 600 字的历史关键词。')
            run_id = self.run_id()
            with readonly(self.config.history_path) as history:
                task, owner, allowed = authority(self.config, run_id, current_session_id, history)
                result = self._read(history, allowed, current_session_id, query, role_filter, limit,
                                    session_id, around_message_id, window, sort, after, before, exclude_session_ids)
                # A stopped run, switched owner or lost admission while reading
                # cannot return a cached successful result to its old caller.
                task_after, owner_after, allowed_after = authority(self.config, run_id, current_session_id, history)
                if (task_after, owner_after) != (task, owner) or not allowed <= allowed_after:
                    raise RecallDenied('当前运行的历史读取授权已变化。')
                return json.dumps(result, ensure_ascii=False)
        except (RecallDenied, OSError, sqlite3.Error, ValueError, TypeError):
            return json.dumps({'success': False, 'error': '当前运行无法核对这段历史的账户授权，未返回历史内容。'}, ensure_ascii=False)

    def _read(self, db, allowed, current, query, role_filter, limit, sid, anchor, window, sort, after, before, excluded):
        limit = _integer(limit, 3, 1, 10)
        if sid is not None:
            if sid not in allowed:
                raise RecallDenied('History outside caller scope')
            meta = db.execute('SELECT id,title,source,model,started_at FROM sessions WHERE id=?', (sid,)).fetchone()
            if not meta:
                raise RecallDenied('Unknown history')
            if anchor is not None:
                if type(anchor) is not int:
                    raise RecallDenied('Invalid anchor')
                found = db.execute('SELECT id FROM messages WHERE id=? AND session_id=? AND (active=1 OR compacted=1)', (anchor, sid)).fetchone()
                if not found:
                    raise RecallDenied('Anchor outside caller scope')
                width = _integer(window, 5, 1, 20)
                before_rows = db.execute('''SELECT id,role,substr(content,1,4000) content,timestamp FROM messages
                    WHERE session_id=? AND (active=1 OR compacted=1) AND id<? ORDER BY id DESC LIMIT ?''', (sid, anchor, width)).fetchall()
                after_rows = db.execute('''SELECT id,role,substr(content,1,4000) content,timestamp FROM messages
                    WHERE session_id=? AND (active=1 OR compacted=1) AND id>=? ORDER BY id LIMIT ?''', (sid, anchor, width + 1)).fetchall()
                return {'success': True, 'mode': 'scroll', 'session_id': sid, 'session_meta': dict(meta),
                        'messages': [_message(r) for r in list(reversed(before_rows)) + after_rows], 'window': width}
            count = db.execute('SELECT count(*) FROM messages WHERE session_id=? AND active=1', (sid,)).fetchone()[0]
            head = db.execute('''SELECT id,role,substr(content,1,2000) content,timestamp FROM messages
                WHERE session_id=? AND active=1 ORDER BY id LIMIT 20''', (sid,)).fetchall()
            tail = db.execute('''SELECT id,role,substr(content,1,2000) content,timestamp FROM messages
                WHERE session_id=? AND active=1 ORDER BY id DESC LIMIT 10''', (sid,)).fetchall()
            rows = {r['id']: r for r in head + tail}
            return {'success': True, 'mode': 'read', 'session_id': sid, 'session_meta': dict(meta), 'message_count': count,
                    'truncated': count > len(rows), 'messages': [_message(rows[k], 2000) for k in sorted(rows)]}
        banned = {current}
        if isinstance(excluded, str):
            banned.add(excluded)
        elif isinstance(excluded, list):
            banned.update(v for v in excluded[:20] if isinstance(v, str))
        sessions = json.dumps(sorted(allowed - banned))
        if not query.strip():
            rows = db.execute('''SELECT s.id session_id,s.title,s.source,s.started_at,s.last_active,s.message_count
                FROM sessions s JOIN json_each(?) a ON a.value=s.id
                WHERE s.source NOT IN ('kanban','subagent','tool') ORDER BY s.last_active DESC,s.id LIMIT ?''', (sessions, limit)).fetchall()
            return {'success': True, 'mode': 'browse', 'results': [dict(r) for r in rows], 'count': len(rows)}
        # Keep search scoped in SQL BEFORE ranking/limit, including literal CJK
        # fallback; another owner's matching rows cannot starve this account.
        roles = [r.strip() for r in role_filter.split(',')] if isinstance(role_filter, str) else ['user', 'assistant']
        if not roles or any(r not in {'user', 'assistant', 'tool', 'system'} for r in roles):
            raise RecallDenied('Invalid history role')
        clauses = '''FROM messages m JOIN sessions s ON s.id=m.session_id JOIN json_each(:sessions) a ON a.value=s.id
            WHERE (m.active=1 OR m.compacted=1) AND m.role IN (SELECT value FROM json_each(:roles))
            AND s.source NOT IN ('kanban','subagent','tool')
            AND (:after IS NULL OR s.started_at>=:after) AND (:before IS NULL OR s.started_at<:before)'''
        params = {'sessions': sessions, 'roles': json.dumps(roles), 'after': _time_bound(after), 'before': _time_bound(before),
                  'query': query.strip(), 'limit': limit * 10}
        direction = 'ASC' if sort == 'oldest' else 'DESC'
        select = 'SELECT m.id,m.session_id,m.role,substr(m.content,1,4000) content,m.timestamp,s.title,s.source,s.started_at '
        rows = []
        semantics = 'fts5'
        try:
            rows = db.execute(select + clauses + f''' AND m.id IN (SELECT rowid FROM messages_fts WHERE messages_fts MATCH :query)
                ORDER BY m.timestamp {direction},m.id LIMIT :limit''', params).fetchall()
        except sqlite3.OperationalError:
            pass  # Missing/incompatible tokenizer or invalid FTS syntax: scoped literal fallback.
        if not rows:
            semantics = 'literal'
            rows = db.execute(select + clauses + f''' AND instr(lower(m.content),lower(:query))>0
                ORDER BY m.timestamp {direction},m.id LIMIT :limit''', params).fetchall()
        results, seen = [], set()
        for row in rows:
            if row['session_id'] in seen:
                continue
            seen.add(row['session_id'])
            results.append({'session_id': row['session_id'], 'title': row['title'], 'source': row['source'],
                            'when': row['started_at'], 'match_message_id': row['id'], 'matched_role': row['role'],
                            'snippet': row['content'][:1000], 'messages': [_message(row)]})
            if len(results) == limit:
                break
        return {'success': True, 'mode': 'discover', 'results': results, 'count': len(results), 'query_semantics': semantics}


def install_session_recall_guard(config):
    """Install before serving any runs. No fallback to unrestricted native recall."""
    # Validate host-owned paths at boot; missing ledger is a startup failure.
    with readonly(config.task_path) as db:
        db.execute('SELECT task_id,owner_scope FROM task_principals LIMIT 0')
        db.execute('SELECT task_id,identity_id,owner_scope,session_id FROM task_conversation_sessions LIMIT 0')
    from tools import session_search_tool
    from tools.approval_context import _approval_session_key
    # The public helper also accepts legacy environment/session fallbacks.
    # Only the /runs host's contextvar is execution authority here.
    guard = RecallGuard(config, _approval_session_key.get)
    session_search_tool.session_search = guard.search
    return True
