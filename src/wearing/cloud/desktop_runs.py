"""Bind MCP elicitation to its existing Wearing task; never submit a second run."""
import asyncio
import json
import re
import sqlite3

from .relay import RelayError, utc
from .desktop_approval import InputDecision, decide, list_proposals, revision, expire_proposals

MARKER='Wearing 电脑操作确认 #'


def live_task(store,waiter,identity):
    path=store.root.parent/'wearing.sqlite3'
    if not path.is_file() or path.is_symlink() or not waiter['task']:raise RelayError('desktop_run_changed')
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        task=db.execute('SELECT * FROM tasks WHERE id=?',(waiter['task'],)).fetchone()
        if (not task or task['identity_id']!=identity or task['run_id']!=waiter['run']
                or task['status'] not in ('running','waiting_for_approval')):
            raise RelayError('desktop_run_changed')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='goal_steps'").fetchone():
            step=db.execute('SELECT * FROM goal_steps WHERE task_id=?',(task['id'],)).fetchone()
            if step:
                goal=db.execute('SELECT * FROM personal_goals WHERE id=?',(step['goal_id'],)).fetchone()
                if not goal or goal['status']!='active' or goal['revision']!=step['revision']:
                    raise RelayError('desktop_goal_changed')
        return dict(task)


def bind(store,task,approval):
    """Called only with the authenticated engine's current run approval response."""
    if not isinstance(approval,dict):return approval
    match=re.match(r'^'+re.escape(MARKER)+r'(\d{1,12})\n',str(approval.get('command','')))
    if not match:return approval
    if approval.get('pattern_key')!='mcp_elicitation':raise RelayError('desktop_run_changed')
    with store.tx() as db:
        expire_proposals(store,db)
        row=db.execute('SELECT w.*,p.identity,p.state AS proposal_state FROM desktop_run_waiters w '
            'JOIN desktop_proposals p ON p.id=w.proposal WHERE w.marker=?',(int(match[1]),)).fetchone()
        if not row or row['identity']!=task['identity_id'] or row['proposal_state']!='awaiting_user':
            raise RelayError('desktop_run_changed')
        if row['task'] and (row['task'],row['run'],row['request'])!=(task['id'],task['run_id'],approval.get('request_id')):
            raise RelayError('desktop_run_changed')
        live_task(store,{**dict(row),'task':task['id'],'run':task['run_id']},task['identity_id'])
        if not approval.get('request_id'):raise RelayError('desktop_run_changed')
        db.execute("UPDATE desktop_run_waiters SET task=?,run=?,request=?,state=CASE WHEN state='binding' THEN 'waiting' ELSE state END WHERE proposal=?",
            (task['id'],task['run_id'],approval['request_id'],row['proposal']))
        return {**approval,'kind':'desktop_input','desktop_approval_id':row['proposal']}


def answer(store,task,request_id,choice):
    """Persist user intent before resolving the original engine approval."""
    with store.tx() as db:
        expire_proposals(store,db)
        row=db.execute('SELECT w.*,p.identity,p.state AS proposal_state FROM desktop_run_waiters w '
            'JOIN desktop_proposals p ON p.id=w.proposal WHERE w.task=? AND w.run=? AND w.request=?',
            (task['id'],task['run_id'],request_id)).fetchone()
        if not row:return  # Other upstream approval types are unchanged.
        live_task(store,row,task['identity_id'])
        if row['state']!='waiting' or row['proposal_state']!='awaiting_user':raise RelayError('desktop_run_changed')
        if choice=='task':
            from .desktop_tasks import create_grant
            proposal=db.execute('SELECT * FROM desktop_proposals WHERE id=?',(row['proposal'],)).fetchone()
            create_grant(store,db,proposal,row)
        db.execute("UPDATE desktop_run_waiters SET state='answered',choice=? WHERE proposal=?",(choice,row['proposal']))


def pending_decision(store,identity,body):
    with store.tx() as db:
        expire_proposals(store,db)
        row=db.execute('SELECT * FROM desktop_proposals WHERE id=? AND identity=?',(body.approval_id,identity)).fetchone()
        if not row or row['state']!='awaiting_user' or revision(row)!=body.revision:raise RelayError('desktop_approval_changed')
        waiter=db.execute('SELECT * FROM desktop_run_waiters WHERE proposal=?',(row['id'],)).fetchone()
        if not waiter:return None
        if waiter['state']!='waiting':raise RelayError('desktop_run_binding_pending')
        live_task(store,waiter,identity)
        return dict(waiter)


def withdraw(store,identity,approval_id):
    with store.tx() as db:
        row=db.execute('SELECT * FROM desktop_proposals WHERE id=? AND identity=?',(approval_id,identity)).fetchone()
        if not row:return
        db.execute("UPDATE desktop_proposals SET state='cancelled' WHERE id=? AND state='awaiting_user'",(approval_id,))
        db.execute("UPDATE desktop_run_waiters SET state='closed' WHERE proposal=?",(approval_id,))
        command=row['command']
    if command:store.cancel(command,identity)


def cancel_task(store,task):
    from .desktop_tasks import revoke_task
    revoke_task(store,task)
    with store.tx() as db:
        rows=db.execute('SELECT proposal FROM desktop_run_waiters WHERE task=? AND run=?',(task['id'],task['run_id'])).fetchall()
    for row in rows:withdraw(store,task['identity_id'],row[0])


def record_receipt(store,approval_id,receipt):
    with store.tx() as db:
        waiter=db.execute('SELECT * FROM desktop_run_waiters WHERE proposal=?',(approval_id,)).fetchone()
        proposal=db.execute('SELECT resource FROM desktop_proposals WHERE id=?',(approval_id,)).fetchone()
        if receipt['state']!='completed':
            db.execute('UPDATE desktop_task_grants SET revoked=1 WHERE id IN (SELECT grant_id FROM desktop_proposal_grants WHERE proposal=?)',(approval_id,))
    if not waiter or not waiter['task']:return
    message='电脑单次操作回执：'+json.dumps({'approval_id':approval_id,'command_id':receipt['command_id'],
        'resource_id':proposal['resource'],'state':receipt['state']},ensure_ascii=False)
    with sqlite3.connect(store.root.parent/'wearing.sqlite3',timeout=10) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("INSERT INTO events(task_id,kind,message,created_at) SELECT ?,'desktop_receipt',?,? "
            "WHERE NOT EXISTS(SELECT 1 FROM events WHERE task_id=? AND kind='desktop_receipt' AND message=?)",
            (waiter['task'],message,utc().isoformat(),waiter['task'],message))


async def request_and_wait(store,identity,proposal,context,*,session_grant=None):
    """Use Hermes' official MCP approval bridge, then wait for the existing receipt."""
    aid=proposal['approval_id']
    with store.tx() as db:marker=db.execute('SELECT marker FROM desktop_run_waiters WHERE proposal=?',(aid,)).fetchone()[0]
    action=proposal['action']
    message=MARKER+str(marker)+'\n'+proposal['reason']+'\n'+json.dumps(action,ensure_ascii=False)
    try:
        # Only this private tool callback owns the elicitation; no model-produced consent.
        # Let Hermes' 90 s consent timeout resolve first. Cancelling the server's
        # RPC at the same instant discarded its structured decline response.
        from .desktop_tasks import auto_answer
        automatic=bool(session_grant and auto_answer(store,identity,proposal,session_grant))
        result=None if automatic else await asyncio.wait_for(context.session.elicit_form(message,{'type':'object','properties':{}}),timeout=100)
        current=next(r for r in list_proposals(store,identity) if r['approval_id']==aid)
        if current['state']!='awaiting_user':return current
        if not automatic and result.action!='accept':
            return decide(store,identity,InputDecision(approval_id=aid,revision=current['revision'],choice='deny'))
        decided=decide(store,identity,InputDecision(approval_id=aid,revision=current['revision'],choice='once'))
        deadline=asyncio.get_running_loop().time()+65
        while asyncio.get_running_loop().time()<deadline:
            receipt=store.read_result(decided['command_id'],identity)
            if receipt['state'] not in ('queued','executing'):
                record_receipt(store,aid,receipt)
                current=next(r for r in list_proposals(store,identity) if r['approval_id']==aid)
                return {**current,'receipt':receipt,'next':'重新观察同一窗口核对实际效果；不重放这一步，也不假定业务已完成。'}
            await asyncio.sleep(.25)
        withdraw(store,identity,aid)
        return {'approval_id':aid,'state':'unknown','next':'未取得完整回执，先核对；不要重做旧动作。'}
    except asyncio.TimeoutError:
        withdraw(store,identity,aid)
        return {'approval_id':aid,'state':'cancelled','next':'确认等待已结束，没有派发新操作。不要重放旧动作。'}
    except BaseException:
        withdraw(store,identity,aid)
        raise
