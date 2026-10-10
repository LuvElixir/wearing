"""Frozen function bodies for control migration 0003 and startup verification.

Never change an installed function in place: add a subsequent migration. These
functions are intentionally small privilege gateways, not general SQL runners.
"""
CLEANUP_FUNCTION_BODY = '''
DECLARE removed_count integer;
BEGIN
  WITH expired AS (
    SELECT id_hash FROM wearing_control.wearing_oidc_states
    WHERE expires <= EXTRACT(EPOCH FROM statement_timestamp())
    ORDER BY expires,id_hash LIMIT 5000 FOR UPDATE SKIP LOCKED
  ), removed AS (
    DELETE FROM wearing_control.wearing_oidc_states s USING expired e
    WHERE s.id_hash=e.id_hash AND s.expires <= EXTRACT(EPOCH FROM statement_timestamp())
    RETURNING 1
  ) SELECT count(*)::integer INTO removed_count FROM removed;
  RETURN removed_count;
END;
'''
FUNCTION_SIGNATURES = {
    'invitation_check': 'text,text',
    'invitation_redeem': 'text,text,text',
    'invitation_reserve_registration': 'text,text,text,text',
    'invitation_get_registration': 'text,text',
    'invitation_bind_registration': 'text,text,text,text',
}
REGISTRATION_FUNCTIONS = {'invitation_check', 'invitation_reserve_registration',
                          'invitation_get_registration', 'invitation_bind_registration'}
WEB_FUNCTIONS = {'invitation_check', 'invitation_redeem'}
DEFINER_TABLES = {'wearing_invitations', 'wearing_users', 'wearing_tenants', 'wearing_memberships',
                  'wearing_routes', 'wearing_tenant_ownership', 'wearing_deletion_requests'}
ELIGIBLE = """
  IF NOT FOUND OR inv.revoked_at IS NOT NULL OR inv.expires_at <= EXTRACT(EPOCH FROM clock_timestamp())::bigint
     OR inv.redeemed_user_id IS NOT NULL
     OR NOT EXISTS (SELECT 1 FROM wearing_control.wearing_tenants t WHERE t.id=inv.tenant_id AND t.deletion_state='active')
     OR NOT EXISTS (SELECT 1 FROM wearing_control.wearing_routes r WHERE r.tenant_id=inv.tenant_id AND r.instance_id=inv.instance_id)
     OR EXISTS (SELECT 1 FROM wearing_control.wearing_memberships m WHERE m.tenant_id=inv.tenant_id)
     OR EXISTS (SELECT 1 FROM wearing_control.wearing_tenant_ownership o WHERE o.tenant_id=inv.tenant_id)
     OR EXISTS (SELECT 1 FROM wearing_control.wearing_deletion_requests d,
         LATERAL jsonb_array_elements(d.plan_json::jsonb->'tenants') t
         WHERE t->>'tenant_id'=inv.tenant_id AND (t->>'action'='erase_private' OR d.state='awaiting_operator'))
  THEN RETURN NULL; END IF;
"""
HEADER = """
  IF p_hash IS NULL OR p_hash !~ '^[a-f0-9]{64}$' OR p_issuer IS NULL OR length(p_issuer) NOT BETWEEN 1 AND 2048
     OR p_issuer IS DISTINCT FROM current_setting('wearing.issuer', true) THEN RETURN NULL; END IF;
"""
LOCK = "  PERFORM pg_advisory_xact_lock(8247991102);\n"
GET = "  SELECT * INTO inv FROM wearing_control.wearing_invitations WHERE code_hash=p_hash AND issuer=p_issuer FOR UPDATE;\n"
VIEW = "  RETURN jsonb_build_object('registration_id',inv.registration_id,'username_hash',inv.username_hash,'subject',inv.registration_subject,'expires_at',inv.expires_at);\n"
FUNCTION_BODIES = {}
FUNCTION_BODIES['invitation_check'] = ("DECLARE inv wearing_control.wearing_invitations%ROWTYPE;\nBEGIN\n" + HEADER +
    "  SELECT * INTO inv FROM wearing_control.wearing_invitations WHERE code_hash=p_hash AND issuer=p_issuer;\n" +
    ELIGIBLE + "  RETURN true;\nEND;")
FUNCTION_BODIES['invitation_redeem'] = ("""DECLARE
  inv wearing_control.wearing_invitations%ROWTYPE;
  usr wearing_control.wearing_users%ROWTYPE;
  existing_tenant text;
  uid text;
BEGIN
""" + HEADER + """
  IF p_subject IS NULL OR length(p_subject) NOT BETWEEN 1 AND 512 OR p_subject ~ '[[:cntrl:]]'
     OR p_subject IS DISTINCT FROM current_setting('wearing.subject', true) THEN RETURN NULL; END IF;
""" + LOCK + """
  SELECT * INTO usr FROM wearing_control.wearing_users WHERE issuer=p_issuer AND subject=p_subject;
  IF FOUND THEN
    IF usr.deletion_state <> 'active' OR EXISTS (SELECT 1 FROM wearing_control.wearing_deletion_requests WHERE user_id=usr.id)
      THEN RETURN NULL; END IF;
    SELECT m.tenant_id INTO existing_tenant FROM wearing_control.wearing_memberships m
      JOIN wearing_control.wearing_tenants t ON t.id=m.tenant_id
      WHERE m.user_id=usr.id AND m.active AND t.deletion_state='active'
      AND NOT EXISTS (SELECT 1 FROM wearing_control.wearing_deletion_requests d,
          LATERAL jsonb_array_elements(d.plan_json::jsonb->'tenants') item
          WHERE item->>'tenant_id'=m.tenant_id AND item->>'action'='erase_private')
      ORDER BY m.tenant_id LIMIT 1;
    IF FOUND THEN RETURN jsonb_build_object('status','already_member','user_id',usr.id,'tenant_id',existing_tenant); END IF;
  END IF;
""" + GET + ELIGIBLE + """
  IF inv.registration_id IS NOT NULL AND inv.registration_subject IS DISTINCT FROM p_subject THEN RETURN NULL; END IF;
  uid := COALESCE(usr.id, 'user_' || replace(gen_random_uuid()::text,'-',''));
  IF usr.id IS NULL THEN
    INSERT INTO wearing_control.wearing_users(id,issuer,subject) VALUES(uid,p_issuer,p_subject);
  END IF;
  INSERT INTO wearing_control.wearing_memberships(user_id,tenant_id,active) VALUES(uid,inv.tenant_id,true);
  INSERT INTO wearing_control.wearing_tenant_ownership
    (tenant_id,classification,owner_user_id,member_count,member_digest,instance_id,revision)
    VALUES(inv.tenant_id,'private',uid,1,encode(sha256(convert_to('[['||to_json(uid)::text||',true]]','UTF8')),'hex'),inv.instance_id,1);
  UPDATE wearing_control.wearing_invitations SET redeemed_user_id=uid,redeemed_at=EXTRACT(EPOCH FROM clock_timestamp())::bigint WHERE id=inv.id;
  RETURN jsonb_build_object('status','admitted','user_id',uid,'tenant_id',inv.tenant_id);
END;""")
FUNCTION_BODIES['invitation_reserve_registration'] = ("DECLARE inv wearing_control.wearing_invitations%ROWTYPE;\nBEGIN\n" + HEADER + """
  IF p_registration_id IS NULL OR p_registration_id !~ '^[a-f0-9]{32}$'
     OR p_username_hash IS NULL OR p_username_hash !~ '^[a-f0-9]{64}$' THEN RETURN NULL; END IF;
""" + LOCK + GET + ELIGIBLE + """
  IF inv.registration_id IS NOT NULL THEN
    IF inv.username_hash <> p_username_hash THEN RETURN NULL; END IF;
  ELSE
    UPDATE wearing_control.wearing_invitations SET registration_id=p_registration_id,username_hash=p_username_hash
      WHERE id=inv.id RETURNING * INTO inv;
  END IF;
""" + VIEW + "END;")
FUNCTION_BODIES['invitation_get_registration'] = ("DECLARE inv wearing_control.wearing_invitations%ROWTYPE;\nBEGIN\n" + HEADER + LOCK + GET + ELIGIBLE +
    "  IF inv.registration_id IS NULL THEN RETURN NULL; END IF;\n" + VIEW + "END;")
FUNCTION_BODIES['invitation_bind_registration'] = ("DECLARE inv wearing_control.wearing_invitations%ROWTYPE;\nBEGIN\n" + HEADER + """
  IF p_registration_id IS NULL OR p_registration_id !~ '^[a-f0-9]{32}$'
    OR p_subject IS NULL OR length(p_subject) NOT BETWEEN 1 AND 512 OR p_subject ~ '[[:cntrl:]]'
    OR p_subject IS DISTINCT FROM current_setting('wearing.subject', true) THEN RETURN NULL; END IF;
""" + LOCK + GET + ELIGIBLE + """
  IF inv.registration_id IS DISTINCT FROM p_registration_id
     OR (inv.registration_subject IS NOT NULL AND inv.registration_subject <> p_subject) THEN RETURN NULL; END IF;
  UPDATE wearing_control.wearing_invitations SET registration_subject=p_subject WHERE id=inv.id RETURNING * INTO inv;
""" + VIEW + "END;")
FUNCTION_ARGUMENTS = {
    'invitation_check': 'p_hash text,p_issuer text',
    'invitation_redeem': 'p_hash text,p_issuer text,p_subject text',
    'invitation_reserve_registration': 'p_hash text,p_issuer text,p_registration_id text,p_username_hash text',
    'invitation_get_registration': 'p_hash text,p_issuer text',
    'invitation_bind_registration': 'p_hash text,p_issuer text,p_registration_id text,p_subject text',
}
FUNCTION_SIGNATURES['invitation_release_registration'] = 'text,text,text'
REGISTRATION_FUNCTIONS.add('invitation_release_registration')
FUNCTION_ARGUMENTS['invitation_release_registration'] = 'p_hash text,p_issuer text,p_registration_id text'
FUNCTION_BODIES['invitation_release_registration'] = ("DECLARE inv wearing_control.wearing_invitations%ROWTYPE;\nBEGIN\n" + HEADER + """
  IF p_registration_id IS NULL OR p_registration_id !~ '^[a-f0-9]{32}$' THEN RETURN NULL; END IF;
""" + LOCK + GET + ELIGIBLE + """
  IF inv.registration_id IS DISTINCT FROM p_registration_id OR inv.registration_subject IS NOT NULL THEN RETURN NULL; END IF;
  UPDATE wearing_control.wearing_invitations SET registration_id=NULL,username_hash=NULL WHERE id=inv.id;
  RETURN jsonb_build_object('released',true);
END;""")
