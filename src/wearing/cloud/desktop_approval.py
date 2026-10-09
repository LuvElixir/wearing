"""Tenant-private proposals. Only an authenticated user's decision queues input."""
from datetime import datetime, timedelta, timezone
import json
from pydantic import Field
from typing import Literal
from .commands import Record, Identifier
from .relay import RelayError, ident, utc, encoded, fingerprint
from ..desktop_input import DesktopAction, DesktopApproval, action_hash


class InputProposal(Record):
    resource_id: Identifier
    action: DesktopAction
    reason: str = Field(min_length=2,max_length=500)
    checkpoint: Literal['routine','commitment'] = 'commitment'


class InputDecision(Record):
    approval_id: Identifier
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    choice: str = Field(pattern='^(task|once|deny)$')


def revision(row):
    return fingerprint(encoded([row['id'],row['identity'],row['resource'],row['params'],row['connection'],row['expires'],row['state'],row['command']]))


def expire_proposals(store,db):
    db.execute("UPDATE desktop_proposals SET state='expired' WHERE state='awaiting_user' AND expires<=?",(utc().timestamp(),))
    db.execute("UPDATE desktop_proposals SET state='cancelled' WHERE state='awaiting_user' AND NOT EXISTS "
        "(SELECT 1 FROM connectors c WHERE c.id=desktop_proposals.connector AND c.revoked=0 "
        "AND c.connection=desktop_proposals.connection AND c.expires>?)",(utc().timestamp(),))


def public(row,db):
    state=row['state']
    if row['command']:
        command=db.execute('SELECT state FROM commands WHERE id=?',(row['command'],)).fetchone()
        state=command[0] if command else 'unknown'
    waiter=db.execute('SELECT * FROM desktop_run_waiters WHERE proposal=?',(row['id'],)).fetchone()
    grant=db.execute('SELECT grant_id FROM desktop_proposal_grants WHERE proposal=?',(row['id'],)).fetchone()
    return {'approval_id':row['id'],'resource_id':row['resource'],'action':json.loads(row['params']),
        'reason':row['reason'],'state':state,'revision':revision(row),'command_id':row['command'],
        'run_wait':{'task_id':waiter['task'],'state':waiter['state']} if waiter else None,
        'can_decide':not waiter or waiter['state']=='waiting',
        'task_eligible':bool(waiter and row['checkpoint']=='routine'),
        'delegated':bool(grant),'task_grant_id':grant[0] if grant else None,
        'created_at':datetime.fromtimestamp(row['expires']-90,timezone.utc).isoformat(),
        'expires_at':datetime.fromtimestamp(row['expires'],timezone.utc).isoformat()}


def propose(store,identity,body,*,for_run=False):
    with store.tx() as db:
        store.expire(db);expire_proposals(store,db)
        if for_run:
            from .desktop_tasks import ensure_run_not_stopped
            ensure_run_not_stopped(store,db,identity)
        matches=[c for c in db.execute('SELECT * FROM connectors WHERE identity=? AND revoked=0',(identity,))
                 if any(r['resource_id']==body.resource_id and 'computer.input' in r['methods'] for r in json.loads(c['resources']))]
        if len(matches)!=1:raise RelayError('desktop_input_not_granted')
        c=matches[0]
        if c['expires']<=utc().timestamp() or not json.loads(c['availability']).get(body.resource_id) or not store.control_ready(db,body.resource_id,c['connection']):
            raise RelayError('resource_offline_or_paused')
        if db.execute("SELECT 1 FROM desktop_proposals WHERE resource=? AND state='awaiting_user'",(body.resource_id,)).fetchone():
            raise RelayError('desktop_approval_pending')
        if db.execute("SELECT 1 FROM commands WHERE resource=? AND (state IN ('queued','executing') OR (state IN ('unknown','device_error') AND resolved=0))",(body.resource_id,)).fetchone():
            raise RelayError('previous_action_needs_review')
        pid=ident('desktop_approval')
        from .desktop_tasks import routine_action
        checkpoint='routine' if body.checkpoint=='routine' and routine_action(body.action) else 'commitment'
        db.execute('INSERT INTO desktop_proposals(id,identity,resource,connector,connection,params,reason,expires,state,command,decided,checkpoint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (pid,identity,body.resource_id,c['id'],c['connection'],encoded(body.action.model_dump(exclude_none=True)),body.reason,
             utc().timestamp()+90,'awaiting_user',None,None,checkpoint))
        if for_run:
            marker=db.execute('SELECT rowid FROM desktop_proposals WHERE id=?',(pid,)).fetchone()[0]
            db.execute("INSERT INTO desktop_run_waiters VALUES (?,?,NULL,NULL,NULL,'binding',NULL)",(pid,marker))
        return public(db.execute('SELECT * FROM desktop_proposals WHERE id=?',(pid,)).fetchone(),db)


def list_proposals(store,identity):
    with store.tx() as db:
        store.expire(db);expire_proposals(store,db)
        return [public(r,db) for r in db.execute('SELECT * FROM desktop_proposals WHERE identity=? ORDER BY rowid DESC LIMIT 10',(identity,))]


def decide(store,identity,body):
    with store.tx() as db:
        store.expire(db);expire_proposals(store,db)
        row=db.execute('SELECT * FROM desktop_proposals WHERE id=? AND identity=?',(body.approval_id,identity)).fetchone()
        if not row:raise RelayError('command_not_found',404)
        if row['state']!='awaiting_user' or revision(row)!=body.revision:raise RelayError('desktop_approval_changed')
        if body.choice=='deny':
            db.execute("UPDATE desktop_proposals SET state='denied',decided=? WHERE id=?",(utc().timestamp(),row['id']))
        else:
            waiter=db.execute('SELECT * FROM desktop_run_waiters WHERE proposal=?',(row['id'],)).fetchone()
            if body.choice=='task' and not waiter:raise RelayError('desktop_run_consent_required')
            if waiter:
                from .desktop_runs import live_task
                live_task(store,waiter,identity)
                if waiter['state']!='answered' or waiter['choice'] not in ('once','task'):raise RelayError('desktop_run_consent_required')
            c=db.execute('SELECT * FROM connectors WHERE id=?',(row['connector'],)).fetchone()
            if c['connection']!=row['connection']:raise RelayError('connection_stale')
            db.execute("UPDATE desktop_proposals SET state='approved',decided=? WHERE id=?",(utc().timestamp(),row['id']))
            command=store._enqueue(db,identity,row['resource'],'computer.input',json.loads(row['params']),approval_id=row['id'])
            db.execute('UPDATE desktop_proposals SET command=? WHERE id=?',(command.command_id,row['id']))
        return public(db.execute('SELECT * FROM desktop_proposals WHERE id=?',(row['id'],)).fetchone(),db)


def authority(store,db,command):
    row=db.execute("SELECT * FROM desktop_proposals WHERE id=? AND command=? AND state='approved'",
        (command.params.get('approval_id'),command.command_id)).fetchone()
    if (not row or row['identity']!=command.scope.identity_id or row['resource']!=command.resource_id
            or row['connection']!=command.connection_id or action_hash(json.loads(row['params']))!=action_hash({k:v for k,v in command.params.items() if k!='approval_id'})):
        raise RelayError('desktop_approval_required')
    waiter=db.execute('SELECT * FROM desktop_run_waiters WHERE proposal=?',(row['id'],)).fetchone()
    if waiter:
        from .desktop_runs import live_task
        live_task(store,waiter,command.scope.identity_id)
        if command.task_id!=waiter['task']:raise RelayError('desktop_run_changed')
    from .desktop_tasks import check_proposal_grant
    check_proposal_grant(store,db,row)
    return DesktopApproval(approval_id=row['id'],command_id=command.command_id,scope=command.scope,
        resource_id=command.resource_id,connection_id=command.connection_id,params_hash=action_hash(json.loads(row['params'])),
        expires_at=min(command.expires_at,datetime.fromtimestamp(row['expires'],timezone.utc)))
