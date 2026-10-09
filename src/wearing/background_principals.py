"""Immutable account provenance for new recurring commitments.

This is execution authority, separate from the identity's shared content view.
Existing commitments are deliberately left unowned; resuming does not adopt them.
"""
import re

from .store import Store


def install(store):
    with store.connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS background_principals (
            kind TEXT NOT NULL CHECK(kind IN ('goal','schedule')), source_id TEXT NOT NULL,
            owner_scope TEXT NOT NULL, source_task_id TEXT,
            PRIMARY KEY(kind,source_id))''')


def valid_owner(value, error=ValueError):
    if value is not None and value != 'local' and (not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value)):
        raise error('这项委托的账户归属无法核对。')
    return value


def owner(db, kind, source_id):
    row = db.execute('SELECT owner_scope FROM background_principals WHERE kind=? AND source_id=?', (kind, source_id)).fetchone()
    return row[0] if row else None


def task_owner(db, task_id, identity):
    row = db.execute('''SELECT p.owner_scope FROM task_principals p JOIN tasks t ON t.id=p.task_id
        WHERE t.id=? AND t.identity_id=?''', (task_id, identity)).fetchone()
    return row[0] if row else None


def check(db, kind, source_id, actor, error=ValueError, *, replay=False):
    valid_owner(actor, error)
    original = owner(db, kind, source_id)
    if (replay or original is not None) and original != actor:
        raise error('这项委托属于另一账户，不能沿用它的执行授权。')
    return original


def bind_new(db, kind, source_id, actor, error=ValueError, *, source_task_id=None):
    """Call only inside the same transaction that INSERTs a new commitment."""
    valid_owner(actor, error)
    if actor is not None:
        db.execute('INSERT INTO background_principals VALUES(?,?,?,?)', (kind, source_id, actor, source_task_id))


def inherit(db, kind, source_id, task_id):
    principal = owner(db, kind, source_id)
    if principal is not None:
        Store.bind_task_principal(db, task_id, principal)


def active_task(db, identity, active):
    """Use the sole admitted task, never the phone's currently signed-in user."""
    marks = ','.join('?' for _ in active)
    rows = db.execute(f'SELECT id,identity_id,status FROM tasks WHERE status IN ({marks})', tuple(active)).fetchall()
    if len(rows) != 1 or rows[0]['identity_id'] != identity or rows[0]['status'] not in {'starting', 'running', 'waiting_for_approval'}:
        return None
    return rows[0]['id']


def source_owner(db, identity, source_task_id, error=ValueError, *, ordinary=False):
    # Recheck provenance inside the mutation transaction. The MCP dispatcher can
    # be delayed while the previous run ends or another account starts a turn.
    from .service import ACTIVE
    if source_task_id is None or active_task(db, identity, ACTIVE) != source_task_id:
        raise error('当前对话已变化，没有可确认的原始执行授权。')
    if ordinary:
        message = db.execute('SELECT 1 FROM messages WHERE task_id=?', (source_task_id,)).fetchone()
        if not message or any(db.execute(f'SELECT 1 FROM {table} WHERE task_id=?', (source_task_id,)).fetchone()
                              for table in ('goal_steps', 'schedule_occurrences')):
            raise error('只有当前用户对话能建立新安排；后台任务不能自行扩大委托。')
    return task_owner(db, source_task_id, identity)
