"""Frozen 0004 activation functions. Changing installed bodies needs a migration."""
from . import invitation_0003 as previous

GRACE_SECONDS = 900
TABLES = {'wearing_bundles', 'wearing_bundle_activations'}
DEFINER_TABLES = previous.DEFINER_TABLES | TABLES
WEB_FUNCTIONS = previous.WEB_FUNCTIONS | {'bundle_activation_status'}
REGISTRATION_FUNCTIONS = previous.REGISTRATION_FUNCTIONS
ACTIVATION_FUNCTIONS = {'activation_claim', 'activation_heartbeat', 'activation_update', 'activation_release'}
FUNCTION_ARGUMENTS = dict(previous.FUNCTION_ARGUMENTS, **{
    'bundle_activation_status': 'p_tenant text',
    'activation_claim': 'p_worker text,p_seconds integer',
    'activation_heartbeat': 'p_event text,p_worker text,p_generation integer,p_seconds integer',
    'activation_update': 'p_event text,p_worker text,p_generation integer,p_state text,p_step text,p_receipt_sha256 text,p_reason text,p_members jsonb',
    'activation_release': 'p_event text,p_worker text,p_generation integer',
})
FUNCTION_SIGNATURES = dict(previous.FUNCTION_SIGNATURES, **{
    'bundle_activation_status': 'text', 'activation_claim': 'text,integer',
    'activation_heartbeat': 'text,text,integer,integer',
    'activation_update': 'text,text,integer,text,text,text,text,jsonb',
    'activation_release': 'text,text,integer',
})
BUNDLE_ELIGIBLE = """
  IF inv.bundle_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM wearing_control.wearing_bundles b WHERE b.id=inv.bundle_id
      AND b.tenant_id=inv.tenant_id AND b.instance_id=inv.instance_id
      AND b.reservation_expires_at >= inv.expires_at+900
  ) THEN RETURN NULL; END IF;
"""
FUNCTION_BODIES = {name: body.replace(previous.ELIGIBLE, previous.ELIGIBLE+BUNDLE_ELIGIBLE)
                   for name, body in previous.FUNCTION_BODIES.items()}
# The new outbox is part of precisely the existing ownership transaction.
anchor = "  RETURN jsonb_build_object('status','admitted','user_id',uid,'tenant_id',inv.tenant_id);"
assert FUNCTION_BODIES['invitation_redeem'].count(anchor) == 1
FUNCTION_BODIES['invitation_redeem'] = FUNCTION_BODIES['invitation_redeem'].replace(anchor, """
  IF inv.bundle_id IS NOT NULL THEN
    INSERT INTO wearing_control.wearing_bundle_activations
      (id,invitation_id,bundle_id,user_id,tenant_id,instance_id,ownership_revision,member_digest,
       state,members_json,step,generation,created_at,updated_at)
    VALUES(replace(gen_random_uuid()::text,'-',''),inv.id,inv.bundle_id,uid,inv.tenant_id,inv.instance_id,1,
       encode(sha256(convert_to('[['||to_json(uid)::text||',true]]','UTF8')),'hex'),
       'reserved','{"core":{"state":"pending"},"linux":{"state":"pending"},"android":{"state":"pending"}}',
       'planned',0,EXTRACT(EPOCH FROM clock_timestamp())::bigint,EXTRACT(EPOCH FROM clock_timestamp())::bigint);
  END IF;
  RETURN jsonb_build_object('status','admitted','user_id',uid,'tenant_id',inv.tenant_id,
    'activation_id',(SELECT a.id FROM wearing_control.wearing_bundle_activations a WHERE a.invitation_id=inv.id));
""")
old = "IF FOUND THEN RETURN jsonb_build_object('status','already_member','user_id',usr.id,'tenant_id',existing_tenant); END IF;"
assert FUNCTION_BODIES['invitation_redeem'].count(old) == 1
FUNCTION_BODIES['invitation_redeem'] = FUNCTION_BODIES['invitation_redeem'].replace(old, """IF FOUND THEN
    RETURN jsonb_build_object('status','already_member','user_id',usr.id,'tenant_id',existing_tenant,
      'activation_id',(SELECT a.id FROM wearing_control.wearing_bundle_activations a
        WHERE a.tenant_id=existing_tenant AND a.user_id=usr.id));
    END IF;""")

# e is the immutable activation row alias. No fabricated proof: all current
# controller facts must still match the committed authenticated redemption.
FRESH = """EXISTS (
  SELECT 1 FROM wearing_control.wearing_tenant_ownership o
  JOIN wearing_control.wearing_tenants t ON t.id=o.tenant_id AND t.deletion_state='active'
  JOIN wearing_control.wearing_users u ON u.id=o.owner_user_id AND u.deletion_state='active'
  JOIN wearing_control.wearing_routes r ON r.tenant_id=o.tenant_id AND r.instance_id=e.instance_id
  JOIN wearing_control.wearing_memberships m ON m.tenant_id=o.tenant_id AND m.user_id=e.user_id AND m.active
  JOIN wearing_control.wearing_bundles b ON b.id=e.bundle_id AND b.tenant_id=e.tenant_id AND b.instance_id=e.instance_id
  WHERE o.tenant_id=e.tenant_id AND o.classification='private' AND o.owner_user_id=e.user_id
    AND o.member_count=1 AND o.revision=e.ownership_revision AND o.member_digest=e.member_digest
    AND o.instance_id=e.instance_id
    AND (SELECT count(*) FROM wearing_control.wearing_memberships x WHERE x.tenant_id=e.tenant_id)=1
    AND e.member_digest=encode(sha256(convert_to('[['||to_json(e.user_id)::text||',true]]','UTF8')),'hex')
    AND NOT EXISTS (SELECT 1 FROM wearing_control.wearing_deletion_requests d WHERE d.user_id=e.user_id)
    AND NOT EXISTS (SELECT 1 FROM wearing_control.wearing_deletion_requests d,
      LATERAL jsonb_array_elements(d.plan_json::jsonb->'tenants') item
      WHERE item->>'tenant_id'=e.tenant_id AND (item->>'action'='erase_private' OR d.state='awaiting_operator'))
)"""
EVENT_RETURN = """  RETURN to_jsonb(ev) || jsonb_build_object('bundle',
    (SELECT to_jsonb(b) FROM wearing_control.wearing_bundles b WHERE b.id=ev.bundle_id));
"""
LOCK = previous.LOCK
LEASE_VALIDATE = """
  IF p_event IS NULL OR p_event !~ '^[a-f0-9]{32}$' OR p_worker IS NULL OR p_worker !~ '^[a-f0-9]{32}$'
     OR p_generation IS NULL OR p_generation<1 THEN RETURN NULL; END IF;
"""
LEASE_GET = """  SELECT * INTO ev FROM wearing_control.wearing_bundle_activations a
    WHERE a.id=p_event AND a.lease_owner=p_worker AND a.generation=p_generation
      AND a.lease_until>EXTRACT(EPOCH FROM clock_timestamp())::bigint FOR UPDATE;
  IF NOT FOUND THEN RETURN NULL; END IF;
  IF NOT """+FRESH.replace("e.", "ev.")+""" THEN RETURN NULL; END IF;
"""
FUNCTION_BODIES['bundle_activation_status'] = """DECLARE ev wearing_control.wearing_bundle_activations%ROWTYPE;
BEGIN
  IF p_tenant IS NULL OR p_tenant IS DISTINCT FROM current_setting('wearing.tenant_id',true)
    THEN RETURN NULL; END IF;
  SELECT * INTO ev FROM wearing_control.wearing_bundle_activations a
    WHERE a.tenant_id=p_tenant AND a.user_id=current_setting('wearing.user_id',true);
  IF NOT FOUND THEN RETURN NULL; END IF;
  IF NOT """+FRESH.replace("e.", "ev.")+""" THEN RETURN NULL; END IF;
  RETURN jsonb_build_object('state',ev.state,'members',ev.members_json::jsonb,'updated_at',ev.updated_at,
    'reason',ev.reason,'retry_after',5);
END;"""
FUNCTION_BODIES['activation_claim'] = """DECLARE ev wearing_control.wearing_bundle_activations%ROWTYPE;
BEGIN
  IF p_worker IS NULL OR p_worker !~ '^[a-f0-9]{32}$' OR p_seconds IS NULL OR p_seconds NOT BETWEEN 30 AND 300
    THEN RETURN NULL; END IF;
"""+LOCK+"""  SELECT e.* INTO ev FROM wearing_control.wearing_bundle_activations e
    WHERE e.state NOT IN ('ready','needs_review')
      AND (e.lease_until IS NULL OR e.lease_until<=EXTRACT(EPOCH FROM clock_timestamp())::bigint)
      AND """+FRESH+"""
    ORDER BY e.created_at,e.id LIMIT 1 FOR UPDATE SKIP LOCKED;
  IF NOT FOUND THEN RETURN NULL; END IF;
  UPDATE wearing_control.wearing_bundle_activations SET lease_owner=p_worker,generation=ev.generation+1,
    lease_until=EXTRACT(EPOCH FROM clock_timestamp())::bigint+p_seconds,
    updated_at=EXTRACT(EPOCH FROM clock_timestamp())::bigint WHERE id=ev.id RETURNING * INTO ev;
"""+EVENT_RETURN+"END;"
FUNCTION_BODIES['activation_heartbeat'] = "DECLARE ev wearing_control.wearing_bundle_activations%ROWTYPE;\nBEGIN\n"+LEASE_VALIDATE+"""
  IF p_seconds IS NULL OR p_seconds NOT BETWEEN 30 AND 300 THEN RETURN NULL; END IF;
"""+LOCK+LEASE_GET+"""  UPDATE wearing_control.wearing_bundle_activations
    SET lease_until=EXTRACT(EPOCH FROM clock_timestamp())::bigint+p_seconds,
        updated_at=EXTRACT(EPOCH FROM clock_timestamp())::bigint WHERE id=ev.id RETURNING * INTO ev;
"""+EVENT_RETURN+"END;"
FUNCTION_BODIES['activation_release'] = "DECLARE ev wearing_control.wearing_bundle_activations%ROWTYPE;\nBEGIN\n"+LEASE_VALIDATE+LOCK+LEASE_GET+"""
  UPDATE wearing_control.wearing_bundle_activations SET lease_owner=NULL,lease_until=NULL,
    updated_at=EXTRACT(EPOCH FROM clock_timestamp())::bigint WHERE id=ev.id RETURNING * INTO ev;
"""+EVENT_RETURN+"END;"
STEPS = ('planned','core','preparing','installing','pairing','complete','inspection','review',
         *(f'{kind}:{step}' for kind in ('linux','android') for step in ('reserve','clone','network','boot','runtime','pair','verify','startup')))
step_sql = ','.join("'"+s+"'" for s in STEPS)
FUNCTION_BODIES['activation_update'] = "DECLARE ev wearing_control.wearing_bundle_activations%ROWTYPE; k text;\nBEGIN\n"+LEASE_VALIDATE+"""
  IF p_state IS NULL OR p_state NOT IN ('reserved','preparing','installing','pairing','ready','needs_review')
    OR p_step IS NULL OR p_step NOT IN ("""+step_sql+""")
    OR p_receipt_sha256 IS NULL OR p_receipt_sha256 !~ '^[a-f0-9]{64}$'
    OR (p_reason IS NOT NULL AND p_reason<>'provisioning_requires_review')
    OR p_members IS NULL OR jsonb_typeof(p_members)<>'object'
    OR (SELECT count(*) FROM jsonb_object_keys(p_members))<>3
    OR NOT (p_members ?& ARRAY['core','linux','android']) THEN RETURN NULL; END IF;
  FOREACH k IN ARRAY ARRAY['core','linux','android'] LOOP
    IF jsonb_typeof(p_members->k)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(p_members->k))<>1
      OR NOT (p_members->k ? 'state') OR (p_members->k->>'state') IS NULL
      OR p_members->k->>'state' NOT IN ('pending','preparing','ready','needs_review')
      OR (p_state='ready' AND p_members->k->>'state'<>'ready') THEN RETURN NULL; END IF;
  END LOOP;
"""+LOCK+LEASE_GET+"""
  IF ev.state IN ('ready','needs_review') THEN RETURN NULL; END IF;
  IF p_state <> 'needs_review' AND array_position(ARRAY['reserved','preparing','installing','pairing','ready'],p_state)
     < array_position(ARRAY['reserved','preparing','installing','pairing','ready'],ev.state) THEN RETURN NULL; END IF;
  UPDATE wearing_control.wearing_bundle_activations SET state=p_state,step=p_step,receipt_sha256=p_receipt_sha256,
    reason=p_reason,members_json=p_members::text,updated_at=EXTRACT(EPOCH FROM clock_timestamp())::bigint
    WHERE id=ev.id RETURNING * INTO ev;
"""+EVENT_RETURN+"END;"

# Triggers preserve committed scope even when an operator accidentally issues an
# UPDATE. They have no callable privilege and do not broaden any runtime role.
TRIGGER_BODIES = {
'bundle_immutable': """BEGIN RAISE EXCEPTION 'bundle_scope_immutable'; END;""",
'invitation_bundle_immutable': """BEGIN
  IF TG_OP='INSERT' AND NEW.bundle_id IS NULL THEN RAISE EXCEPTION 'bundle_required'; END IF;
  IF TG_OP='UPDATE' AND NEW.bundle_id IS DISTINCT FROM OLD.bundle_id THEN RAISE EXCEPTION 'bundle_scope_immutable'; END IF;
  RETURN NEW;
END;""",
'activation_scope_immutable': """BEGIN
  IF (NEW.id,NEW.invitation_id,NEW.bundle_id,NEW.user_id,NEW.tenant_id,NEW.instance_id,
      NEW.ownership_revision,NEW.member_digest,NEW.created_at) IS DISTINCT FROM
     (OLD.id,OLD.invitation_id,OLD.bundle_id,OLD.user_id,OLD.tenant_id,OLD.instance_id,
      OLD.ownership_revision,OLD.member_digest,OLD.created_at) THEN RAISE EXCEPTION 'activation_scope_immutable'; END IF;
  RETURN NEW;
END;""",
}
