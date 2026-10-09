"""User-facing task text. Execution prompts never become recovery chat bubbles.

The recovery ledger, not prompt matching or client input, chooses the projection.
No history is rewritten, including recovery rows created by earlier versions.
"""
EXECUTION_LIMIT_MESSAGE = '已达到本轮执行上限，现有结果和查看记录已保留；这件事尚未完成。'


def recovery_title(card):
    title = card.get('title') if isinstance(card, dict) else None
    return '重新核对：' + title.strip()[:120] if isinstance(title, str) and title.strip() else '重新核对之前暂停的事情'


def recovery_corpus(db):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'confirmation_recovery_tasks', 'durable_confirmations'} <= tables:
        return "SELECT NULL AS task_id,NULL AS label WHERE 0"
    # Restrict the source card to this task's identity even if an old ledger is
    # incomplete. In that case show a generic label, never the internal prompt.
    return """SELECT r.task_id,
      CASE WHEN json_valid(d.card) AND json_type(d.card,'$.title')='text'
           AND length(trim(json_extract(d.card,'$.title')))>0
        THEN '重新核对：'||substr(trim(json_extract(d.card,'$.title')),1,120)
        ELSE '重新核对之前暂停的事情' END AS label
      FROM confirmation_recovery_tasks r JOIN tasks rt ON rt.id=r.task_id
      LEFT JOIN durable_confirmations d ON d.id=r.source_id AND d.identity_id=rt.identity_id"""


def recovery_label(db, task_id):
    row = db.execute('SELECT label FROM (' + recovery_corpus(db) + ') WHERE task_id=?', (task_id,)).fetchone()
    return row[0] if row else None


def message_controls(db, task, *, allow_unowned=False):
    """Capabilities only; the service rechecks trusted scope in its transaction."""
    task = dict(task)
    fresh = task['status'] == 'draft' and all(task.get(k) is None for k in ('run_id', 'payload', 'idempotency_key'))
    handoff = db.execute('SELECT state,blocked_reason FROM message_handoffs WHERE task_id=?', (task['id'],)).fetchone()
    principal = db.execute('SELECT owner_scope FROM task_principals WHERE task_id=?', (task['id'],)).fetchone()
    own_saved = bool(principal or allow_unowned)
    message = db.execute('SELECT 1 FROM messages WHERE task_id=?', (task['id'],)).fetchone()
    saved = bool(fresh and message and handoff and handoff['state'] == 'saved' and own_saved)
    queued = bool(fresh and handoff and handoff['state'] in {'queued', 'blocked'})
    if fresh and not handoff and db.execute("SELECT 1 FROM sqlite_master WHERE name='goal_messages'").fetchone():
        queued = bool(db.execute('SELECT 1 FROM goal_messages WHERE task_id=? AND queued=1', (task['id'],)).fetchone())
    return {'can_cancel': saved or queued, 'can_retry': saved,
            'blocked_reason': handoff['blocked_reason'] if fresh and handoff else None}


def present_task_in(db, task, *, local_devices=False):
    result = {key: value for key, value in task.items() if key not in {'payload', 'idempotency_key', 'error'}}
    result['failure_code'] = ('execution_limit' if task.get('status') == 'failed'
                              and task.get('error') == EXECUTION_LIMIT_MESSAGE else None)
    label = recovery_label(db, task['id'])
    if label:
        result.update(title=label, prompt=label, message_kind='confirmation_recovery')
    result.update(message_controls(db, task, allow_unowned=local_devices))
    return result


def present_task(store, task, *, local_devices=False):
    with store.connection() as db:
        return present_task_in(db, task, local_devices=local_devices)


def present_message_in(db, message):
    result = dict(message)
    label = recovery_label(db, message['task_id'])
    if label:
        result.update(content=label, kind='confirmation_recovery')
    return result


def present_messages(store, messages):
    with store.connection() as db:
        return [present_message_in(db, message) for message in messages]
