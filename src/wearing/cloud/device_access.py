"""Control metadata only for an optional, trusted private device gateway.

There are deliberately no input, pixels, passwords or media-key fields here.
The relay's readiness is a server composition choice and defaults to false.
"""
import json
import secrets

from ..device_gateway import identifier


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS human_access(
        resource TEXT PRIMARY KEY, connector TEXT NOT NULL, identity TEXT NOT NULL,
        actor TEXT NOT NULL, session TEXT NOT NULL, epoch INTEGER NOT NULL,
        request_id TEXT NOT NULL, state TEXT NOT NULL, expires REAL NOT NULL,
        revision INTEGER NOT NULL, directive TEXT NOT NULL,
        gateway_epoch INTEGER, ack_connection TEXT,
        safe_screen INTEGER NOT NULL DEFAULT 0, scope_confirmed INTEGER NOT NULL DEFAULT 0)''')
    if 'human_access_ready' not in {r[1] for r in db.execute('PRAGMA table_info(connectors)')}:
        db.execute('ALTER TABLE connectors ADD COLUMN human_access_ready INTEGER NOT NULL DEFAULT 0')
    if 'human_availability' not in {r[1] for r in db.execute('PRAGMA table_info(connectors)')}:
        db.execute("ALTER TABLE connectors ADD COLUMN human_availability TEXT NOT NULL DEFAULT '{}'")


def error(code, status=409):
    from .relay import RelayError
    raise RelayError(code, status)


def now():
    from .relay import utc
    return utc().timestamp()


def owned(db, identity, resource):
    matches = [(c, r) for c in db.execute('SELECT * FROM connectors WHERE revoked=0 AND identity=?', (identity,))
               for r in json.loads(c['resources']) if r['resource_id'] == resource]
    if len(matches) != 1:
        error('resource_not_paired', 404)
    return matches[0]


def expire(db):
    stamp=now()
    db.execute("UPDATE human_access SET state='paused',directive='pause',revision=revision+1,ack_connection=NULL WHERE state IN ('handoff_pending','human_private','return_pending') AND (expires<=? OR NOT EXISTS (SELECT 1 FROM connectors c WHERE c.id=human_access.connector AND c.revoked=0 AND c.expires>?))", (stamp,stamp))


def active(db, resource):
    expire(db)
    row = db.execute('SELECT * FROM human_access WHERE resource=?', (resource,)).fetchone()
    return row and row['state'] != 'agent_ready'


def public(store, db, c, spec, row=None):
    supported = bool(store.human_access_ready and c['human_access_ready'] and spec['kind'] in ('android', 'computer'))
    control = db.execute('SELECT generation FROM controls WHERE resource=?', (spec['resource_id'],)).fetchone()
    return {'resource_id': spec['resource_id'], 'supported': supported,
            'unavailable_reason': None if supported else 'private_gateway_unavailable',
            'state': row['state'] if row else 'unavailable' if not supported else 'agent_ready',
            'control_generation': control['generation'] if control else 0,
            'session_id': row['session'] if row else None, 'epoch': row['epoch'] if row else 0,
            'gateway_epoch': row['gateway_epoch'] if row else None,
            'device_confirmed': bool(row and row['ack_connection'] == c['connection'] and row['gateway_epoch'] is not None),
            'expires_at': row['expires'] if row and row['state'] in ('handoff_pending','human_private','return_pending') else None}


def status(store, identity, actor, resource):
    identifier(actor)
    with store.tx() as db:
        c, spec = owned(db, identity, resource)
        expire(db)
        row = db.execute('SELECT * FROM human_access WHERE resource=?', (resource,)).fetchone()
        if row and row['actor'] != actor:
            error('resource_not_paired', 404)
        return public(store, db, c, spec, row)


def fence(db, resource, connector):
    old = db.execute('SELECT generation FROM controls WHERE resource=?', (resource,)).fetchone()
    generation = (old['generation'] if old else 0) + 1
    db.execute('INSERT OR REPLACE INTO controls(resource,generation,paused) VALUES (?,?,1)', (resource, generation))
    db.execute("UPDATE commands SET state=CASE WHEN state='queued' THEN 'blocked' ELSE 'unknown' END,result=NULL,updated=? WHERE resource=? AND state IN ('queued','executing')", (now(), resource))
    db.execute('UPDATE leases SET epoch=epoch+1 WHERE resource=?', (resource,))
    db.execute("UPDATE desktop_proposals SET state='cancelled' WHERE resource=? AND state='awaiting_user'", (resource,))


def request(store, identity, actor, resource, *, expected_generation, request_id):
    identifier(actor); identifier(request_id)
    if type(expected_generation) is not int or expected_generation < 0:
        error('invalid_human_request', 422)
    with store.tx() as db:
        c, spec = owned(db, identity, resource)
        from .device_maintenance import guard as maintenance_guard
        maintenance_guard(db, resource)
        if not store.human_access_ready or not c['human_access_ready'] or spec['kind'] not in ('android', 'computer'):
            error('private_gateway_unavailable')
        # Agent availability is intentionally false while paused. A new human
        # session needs physical connectivity, not permission to run an agent.
        if not c['connection'] or (c['expires'] or 0) <= now() or not json.loads(c['human_availability']).get(resource):
            error('connector_offline')
        expire(db)
        old = db.execute('SELECT * FROM human_access WHERE resource=?', (resource,)).fetchone()
        if old and old['actor'] != actor:
            error('resource_not_paired', 404)
        if old and old['request_id'] == request_id:
            return public(store, db, c, spec, old)
        if old and old['state'] not in ('agent_ready', 'paused'):
            error('human_session_busy')
        control = db.execute('SELECT generation FROM controls WHERE resource=?', (resource,)).fetchone()
        if expected_generation != (control['generation'] if control else 0):
            error('control_changed')
        fence(db, resource, c['id'])
        db.execute('''INSERT OR REPLACE INTO human_access(resource,connector,identity,actor,session,epoch,
          request_id,state,expires,revision,directive) VALUES (?,?,?,?,?,?,?,'handoff_pending',?,?,'takeover')''',
          (resource,c['id'],identity,actor,'human_'+secrets.token_hex(16),(old['epoch'] if old else 0)+1,
           request_id,now()+600,(old['revision'] if old else 0)+1))
        return public(store, db, c, spec, db.execute('SELECT * FROM human_access WHERE resource=?', (resource,)).fetchone())


def session(db, identity, actor, resource, session_id, epoch):
    c, spec = owned(db, identity, resource)
    expire(db)
    row = db.execute('SELECT * FROM human_access WHERE resource=?', (resource,)).fetchone()
    if not row or row['actor'] != actor:
        error('resource_not_paired', 404)
    if row['session'] != session_id or type(epoch) is not int or row['epoch'] != epoch:
        error('human_session_changed')
    return c, spec, row


def close(store, identity, actor, resource, *, session_id, epoch):
    with store.tx() as db:
        c, spec, row = session(db, identity, actor, resource, session_id, epoch)
        if row['state'] == 'agent_ready':
            error('human_session_changed')
        if row['state'] != 'paused':
            fence(db, resource, c['id'])
            db.execute("UPDATE human_access SET state='paused',directive='pause',revision=revision+1,ack_connection=NULL WHERE resource=?", (resource,))
        return public(store, db, c, spec, db.execute('SELECT * FROM human_access WHERE resource=?', (resource,)).fetchone())


def finish(store, identity, actor, resource, *, session_id, epoch, safe_screen_confirmed, scope_confirmed):
    with store.tx() as db:
        c, spec, row = session(db, identity, actor, resource, session_id, epoch)
        from .device_maintenance import guard as maintenance_guard
        maintenance_guard(db, resource)
        if not store.human_access_ready or not c['human_access_ready']:
            error('private_gateway_unavailable')
        if safe_screen_confirmed is not True or scope_confirmed is not True:
            error('human_return_confirmation_required', 422)
        if row['state'] == 'return_pending':
            return public(store, db, c, spec, row)
        if row['state'] != 'human_private' or row['ack_connection'] != c['connection']:
            error('human_session_not_active')
        # User acknowledgement does not enable the agent. Only a fresh trusted
        # gateway ACK after clearing its private media buffers can do that.
        db.execute("UPDATE human_access SET state='return_pending',directive='return',safe_screen=1,scope_confirmed=1,revision=revision+1,ack_connection=NULL WHERE resource=?", (resource,))
        return public(store, db, c, spec, db.execute('SELECT * FROM human_access WHERE resource=?', (resource,)).fetchone())


def disconnect(db, connector):
    db.execute("UPDATE human_access SET state='paused',directive='pause',revision=revision+1,ack_connection=NULL WHERE connector=? AND state IN ('handoff_pending','human_private','return_pending')", (connector,))


def poll(store, db, connector, request):
    expire(db)
    if not store.human_access_ready or not request.human_access_ready:
        disconnect(db, connector['id'])
    for row in db.execute("SELECT resource FROM human_access WHERE connector=? AND state IN ('handoff_pending','human_private','return_pending')", (connector['id'],)).fetchall():
        if not request.human_availability.get(row['resource']):
            db.execute("UPDATE human_access SET state='paused',directive='pause',revision=revision+1,ack_connection=NULL WHERE resource=?", (row['resource'],))
    for resource, ack in request.human_acks.items():
        row = db.execute('SELECT * FROM human_access WHERE resource=? AND connector=?', (resource, connector['id'])).fetchone()
        if not row or row['session'] != ack.session_id or row['epoch'] != ack.epoch or row['revision'] != ack.revision:
            # A response may race a user's close/new session. Old ACKs never
            # change ownership and must not prevent delivery of the new fence.
            continue
        if ack.state == 'human_private' and row['state'] == 'handoff_pending':
            db.execute("UPDATE human_access SET state='human_private',gateway_epoch=?,ack_connection=? WHERE resource=?", (ack.gateway_epoch,connector['connection'],resource))
        elif ack.state == 'agent_ready' and row['state'] == 'return_pending' and row['safe_screen'] and row['scope_confirmed']:
            if row['gateway_epoch'] is None or ack.gateway_epoch <= row['gateway_epoch']:
                error('invalid_human_ack')
            db.execute("UPDATE human_access SET state='agent_ready',gateway_epoch=?,ack_connection=? WHERE resource=?", (ack.gateway_epoch,connector['connection'],resource))
            # A standard control ACK still has to round-trip before new work.
            control = db.execute('SELECT generation FROM controls WHERE resource=?', (resource,)).fetchone()
            db.execute('UPDATE controls SET generation=?,paused=0,ack=0,connection=NULL WHERE resource=?', (control['generation']+1,resource))
        elif ack.state == 'paused':
            db.execute("UPDATE human_access SET state='paused',directive='pause',gateway_epoch=?,ack_connection=? WHERE resource=?", (ack.gateway_epoch,connector['connection'],resource))
        elif ack.state != row['state']:
            error('invalid_human_ack')
    rows = db.execute("SELECT * FROM human_access WHERE connector=? AND state!='agent_ready'", (connector['id'],)).fetchall()
    return [{'resource_id': r['resource'], 'tenant_id':store.tenant, 'identity_id':r['identity'],
             'user_id':r['actor'], 'connector_id':r['connector'], 'session_id':r['session'], 'epoch':r['epoch'],
             'revision':r['revision'], 'action':r['directive'], 'safe_screen_confirmed':bool(r['safe_screen']),
             'scope_confirmed':bool(r['scope_confirmed'])} for r in rows]
