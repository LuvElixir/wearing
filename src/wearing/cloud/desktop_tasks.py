"""Task delegation, anchored to a human decision and the original MCP session.

This is a bounded first implementation: one app, one current run, 30 minutes,
100 routine actions. Action receipts/frame fences remain per operation.
"""
import json
import re
import sqlite3

from .relay import RelayError,ident,utc


def ensure_run_not_stopped(store,db,identity):
    """A refusal/expired prompt ends this run's input workflow, not a retry loop."""
    path=store.root.parent/'wearing.sqlite3'
    if not path.is_file():return
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as tasks:
        rows=tasks.execute("SELECT id,run_id FROM tasks WHERE identity_id=? AND status IN ('running','waiting_for_approval')",(identity,)).fetchall()
    if len(rows)!=1:return
    task,run=rows[0]
    if db.execute("SELECT 1 FROM desktop_run_waiters w JOIN desktop_proposals p ON p.id=w.proposal WHERE w.task=? AND w.run=? AND p.identity=? AND p.state IN ('denied','expired','cancelled')",(task,run,identity)).fetchone():
        raise RelayError('desktop_workflow_stopped')


def routine_action(action):
    # This deny list is an additional brake, not a semantic safety guarantee.
    # The model must also declare commitment for sending, paying, account/security
    # changes, deleting data, or accepting new legal terms. Missing declaration
    # defaults to commitment in InputProposal.
    label=(action.element_label or '')
    if re.search(r'付款|支付|转账|汇款|下单|购买|订阅|发送|发布|提交订单|删除|清空|注销|密码|验证码|同意|接受|pay|purchase|checkout|send|publish|delete|password|agree|accept',label,re.I):return False
    if action.action=='key':return False  # Enter and shortcuts can commit a form.
    return True


def create_grant(store,db,row,waiter):
    if row['checkpoint']!='routine':raise RelayError('desktop_checkpoint_required')
    from .desktop_runs import live_task
    live_task(store,waiter,row['identity'])
    c=db.execute('SELECT * FROM connectors WHERE id=?',(row['connector'],)).fetchone()
    if c['connection']!=row['connection'] or not store.control_ready(db,row['resource'],row['connection']):
        raise RelayError('connection_stale')
    control=db.execute('SELECT generation FROM controls WHERE resource=?',(row['resource'],)).fetchone()
    gid=ident('desktop_task_grant')
    db.execute('INSERT INTO desktop_task_grants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0)',
        (gid,row['identity'],waiter['task'],waiter['run'],row['resource'],row['connector'],row['connection'],c['policy_revision'],
         control[0] if control else 0,json.loads(row['params'])['app'],utc().timestamp()+1800,99))
    db.execute('INSERT INTO desktop_proposal_grants VALUES(?,?)',(row['id'],gid))
    return gid


def validate(store,db,grant,identity):
    from .desktop_runs import live_task
    if not grant or grant['identity']!=identity or grant['revoked'] or grant['expires']<=utc().timestamp():
        raise RelayError('desktop_task_grant_expired')
    live_task(store,grant,identity)
    # TaskService serializes runs. Also check the database so a new/ambiguous run
    # can never inherit consent from a persistent MCP process.
    with sqlite3.connect(f'file:{store.root.parent / "wearing.sqlite3"}?mode=ro',uri=True) as tasks:
        active=tasks.execute("SELECT id,run_id FROM tasks WHERE status IN ('starting','running','waiting_for_approval','stopping','connection_lost','ambiguous')").fetchall()
    if active!=[(grant['task'],grant['run'])]:raise RelayError('desktop_run_changed')
    c=db.execute('SELECT * FROM connectors WHERE id=?',(grant['connector'],)).fetchone()
    control=db.execute('SELECT generation FROM controls WHERE resource=?',(grant['resource'],)).fetchone()
    if (not c or c['revoked'] or c['connection']!=grant['connection'] or c['policy_revision']!=grant['policy']
            or (control[0] if control else 0)!=grant['generation']
            or not store.control_ready(db,grant['resource'],grant['connection'])):
        raise RelayError('desktop_task_grant_changed')
    return grant


def auto_answer(store,identity,proposal,grant_id):
    """grant_id comes only from this MCP session's completed human decision."""
    with store.tx() as db:
        grant=db.execute('SELECT * FROM desktop_task_grants WHERE id=?',(grant_id,)).fetchone()
        try:validate(store,db,grant,identity)
        except RelayError:return False
        row=db.execute('SELECT * FROM desktop_proposals WHERE id=? AND identity=?',(proposal['approval_id'],identity)).fetchone()
        if (not row or row['state']!='awaiting_user' or row['checkpoint']!='routine' or grant['remaining']<=0
                or row['resource']!=grant['resource'] or json.loads(row['params'])['app']!=grant['app']):return False
        db.execute("UPDATE desktop_run_waiters SET task=?,run=?,request=NULL,state='answered',choice='once' WHERE proposal=? AND state='binding'",
            (grant['task'],grant['run'],row['id']))
        db.execute('INSERT INTO desktop_proposal_grants VALUES(?,?)',(row['id'],grant_id))
        db.execute('UPDATE desktop_task_grants SET remaining=remaining-1 WHERE id=?',(grant_id,))
        return True


def check_proposal_grant(store,db,row):
    association=db.execute('SELECT grant_id FROM desktop_proposal_grants WHERE proposal=?',(row['id'],)).fetchone()
    if association:
        grant=db.execute('SELECT * FROM desktop_task_grants WHERE id=?',(association[0],)).fetchone()
        validate(store,db,grant,row['identity'])


def revoke_task(store,task):
    with store.tx() as db:
        db.execute('UPDATE desktop_task_grants SET revoked=1 WHERE task=? AND run=?',(task['id'],task['run_id']))
