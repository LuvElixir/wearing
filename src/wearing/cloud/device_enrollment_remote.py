"""Root-invoked enrollment steps, never an HTTP API or agent tool.

All credentials arrive through the operator's SSH stdin. Returned values are
allowlisted metadata. Existing configurations with another binding are refused.
"""
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import pwd
import socket
import sqlite3
import ssl
import subprocess
import time
import urllib.error
import urllib.request

from filelock import FileLock

from .device_enrollment import EnrollmentSpec, android_serial, validate_scope
from .device_provisioning import DeviceSpec, Owner, ProvisionError, encoded, fingerprint


def fail(code):
    raise ProvisionError(code)


def read(path, uid=0, *, private=True):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file(): fail('enrollment_file_unsafe')
    st=path.stat()
    if st.st_uid!=uid or (private and st.st_mode&0o077) or st.st_mode&0o022 or st.st_size>131072:
        fail('enrollment_file_unsafe')
    return path.read_text()


def write_exact(path, content, *, uid=0, gid=0, mode=0o600):
    """Install-once; never replace a differing file or a symlink."""
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):fail('enrollment_file_unsafe')
    if path.exists():
        if read(path,uid,private=mode&0o077==0)!=content:fail('enrollment_existing_file_changed')
        return
    path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'w') as f:
        os.fchown(f.fileno(),uid,gid);f.write(content);f.flush();os.fsync(f.fileno())
    parent=os.open(path.parent,os.O_RDONLY);os.fsync(parent);os.close(parent)


def run(argv, *, check=True, timeout=45):
    r=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=timeout)
    if check and r.returncode:fail('enrollment_native_command_failed')
    return r.stdout.strip()


def account(spec):
    name='pajio-desktop' if spec.kind=='linux' else 'pajio-phone'
    u=pwd.getpwnam(name)
    if u.pw_uid==0 or u.pw_dir!='/home/'+name or u.pw_shell!='/usr/sbin/nologin':fail('enrollment_native_account_changed')
    return u


@contextmanager
def as_user(u, *, desktop=False):
    old_env=dict(os.environ); groups=os.getgroups()
    os.environ.update(HOME=u.pw_dir,USER=u.pw_name,LOGNAME=u.pw_name,
        XDG_RUNTIME_DIR=f'/run/user/{u.pw_uid}',DBUS_SESSION_BUS_ADDRESS=f'unix:path=/run/user/{u.pw_uid}/bus')
    if desktop:
        os.environ.update(DISPLAY=':10',XAUTHORITY=f'/run/user/{u.pw_uid}/pajio-x11/Xauthority',
            DBUS_SESSION_BUS_ADDRESS=f'unix:path=/run/user/{u.pw_uid}/pajio-desktop-bus',XDG_SESSION_TYPE='x11')
    try:
        os.setgroups([]);os.setresgid(u.pw_gid,u.pw_gid,0);os.setresuid(u.pw_uid,u.pw_uid,0)
        yield
    finally:
        os.setresuid(0,0,0);os.setresgid(0,0,0);os.setgroups(groups)
        os.environ.clear();os.environ.update(old_env)


def guest_identity(spec,owner,settings):
    if json.loads(read('/etc/pajio-native/device-owner.json'))!=owner.model_dump():fail('enrollment_owner_changed')
    expected={'version':1,'owner_sha256':fingerprint(owner.model_dump()),'artifact_sha256':settings.artifact_sha256}
    for name in ('bootstrap-expected.json','bootstrap-installed.json'):
        if json.loads(read('/etc/pajio-native/'+name))!=expected:fail('enrollment_runtime_not_verified')
    addresses=json.loads(run(['ip','-j','-4','address','show']))
    if settings.guest_ipv4 not in {a['local'] for d in addresses for a in d.get('addr_info',[])}:
        fail('enrollment_guest_address_changed')
    return account(spec)


def binding(spec,owner,material,u):
    value={'tenant_id':spec.tenant_id,'identity_id':spec.identity_id,
           'resource_id':spec.resource_id,'connector_id':material['connector_id'],
           'kind':'computer' if spec.kind=='linux' else 'android'}
    if spec.kind=='linux':
        value.update(display=':10',xauthority=f'/run/user/{u.pw_uid}/pajio-x11/Xauthority',max_fps=15)
    else:
        value.update(serial=android_serial(spec),adb='/usr/bin/adb',video_source='scrcpy',
            scrcpy_server='/opt/pajio-native/scrcpy-server-v5.0.1',unicode_ime=True,max_fps=24,max_size=0,bitrate=4_000_000)
    return value


def host_config(spec,owner,material,u):
    return {'token':material['host_token'],'gateway_root':u.pw_dir+'/.wearing/device-gateway',
            'resources':[binding(spec,owner,material,u)]}


def native_inventory(spec,u,*,prepare=False):
    from .. import computer, mobile
    from ..config import private_directory
    from ..connectors.remote.adapter import NativeAdapter
    data=Path(u.pw_dir)/'.pajio'
    with as_user(u,desktop=spec.kind=='linux'):
        if prepare:
            private_directory(data)
            if spec.kind=='linux':
                desired={'enrolled':True,'resource_id':'computer_local','backend':'linux-x11'}
                if (data/'computer.json').exists():
                    if json.loads(read(data/'computer.json',u.pw_uid))!=desired:fail('enrollment_computer_registry_changed')
                else:write_exact(data/'computer.json',encoded(desired),uid=u.pw_uid,gid=u.pw_gid)
                write_exact(data/'runtime/computer/connector-id.json',encoded({'resource_id':spec.resource_id}),uid=u.pw_uid,gid=u.pw_gid)
            else:
                desired={'schema_version':2,'selected':spec.resource_id,'devices':{spec.resource_id:{
                    'resource_id':spec.resource_id,'serial':android_serial(spec),'enabled':True,'platform':'android','name':'专属 Android 手机'}}}
                if (data/'phone.json').exists():
                    if mobile.registry(data)!=desired:fail('enrollment_phone_registry_changed')
                else:write_exact(data/'phone.json',encoded(desired),uid=u.pw_uid,gid=u.pw_gid)
        async def probe():
            async with NativeAdapter(data) as native:
                inventory=await native.inventory()
                availability=await native.availability(inventory['resources'])
                if availability!={spec.resource_id:True}:fail('enrollment_native_not_ready')
                return inventory
        value=asyncio.run(probe())
    if len(value['resources'])!=1 or value['resources'][0]['resource_id']!=spec.resource_id:
        fail('enrollment_inventory_mismatch')
    return value


def pair_bundle(spec,settings,material,results):
    from ..connectors.remote.client import PairBundle
    return PairBundle(endpoint=settings.tenant_endpoint,ca_pem=settings.relay_ca_pem,code=material['pair_code'],
        connector_id=material['connector_id'],tenant_id=spec.tenant_id,identity_id=spec.identity_id,
        pairing_generation=1,policy_revision=1,resources=results['prepare']['inventory']['resources']).model_dump(mode='json')


def user_systemctl(u,*argv):
    return run(['runuser','-u',u.pw_name,'--','env','HOME='+u.pw_dir,f'XDG_RUNTIME_DIR=/run/user/{u.pw_uid}',
        f'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{u.pw_uid}/bus','systemctl','--user',*argv],check=False)


def connector_unit(u):
    return 'com.wearing.connector.'+hashlib.sha256((u.pw_dir+'/.pajio-connector').encode()).hexdigest()[:16]+'.service'


def require_inactive(u):
    if (run(['systemctl','is-active','pajio-private-media.service'],check=False) in ('active','activating','deactivating')
            or user_systemctl(u,'is-active',connector_unit(u)) in ('active','activating','deactivating')):
        fail('enrollment_existing_service_active')


def render_guest_files(spec,owner,settings,material,u):
    home=u.pw_dir; tls='/etc/pajio/tls'
    media=host_config(spec,owner,material,u)
    unit=f'''[Unit]
Description=Pajio private device media
After=network-online.target
[Service]
User={u.pw_name}
Group={u.pw_name}
Environment=HOME={home}
Environment=XDG_RUNTIME_DIR=/run/user/{u.pw_uid}
ExecStart=/opt/pajio-native/venv/bin/python -m wearing.private_media --config /etc/pajio/media-host.json --port 8792
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=yes
StandardOutput=null
StandardError=null
[Install]
WantedBy=multi-user.target
'''
    if spec.kind=='linux':
        unit=unit.replace('ExecStart=',f'Environment=DISPLAY=:10\nEnvironment=XAUTHORITY=/run/user/{u.pw_uid}/pajio-x11/Xauthority\nEnvironment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{u.pw_uid}/pajio-desktop-bus\nEnvironment=XDG_SESSION_TYPE=x11\nExecStart=')
    nginx=f'''server {{
 listen {settings.guest_ipv4}:9443 ssl;
 server_name _;
 ssl_certificate {tls}/server.pem;
 ssl_certificate_key {tls}/server-key.pem;
 ssl_client_certificate {tls}/ca.pem;
 ssl_verify_client on;
 ssl_protocols TLSv1.2 TLSv1.3;
 access_log off;
 error_log /dev/null crit;
 client_max_body_size 128k;
 location = /v1/offer {{
  limit_except POST {{ deny all; }}
  proxy_pass http://127.0.0.1:8792;
  proxy_read_timeout 45s;
  proxy_buffering off;
 }}
 location / {{ return 404; }}
}}
'''
    return {
        '/etc/pajio/media-host.json':(encoded(media),u.pw_uid,u.pw_gid,0o600),
        home+'/.pajio/runtime/private-media.json':(encoded({'endpoint':'http://127.0.0.1:8792',
            'token':material['host_token'],'gateway_root':media['gateway_root']}),u.pw_uid,u.pw_gid,0o600),
        tls+'/ca.pem':(material['ca_cert'],0,0,0o600),
        tls+'/server.pem':(material['server_cert'],0,0,0o600),
        tls+'/server-key.pem':(material['server_key'],0,0,0o600),
        '/etc/systemd/system/pajio-private-media.service':(unit,0,0,0o644),
        '/etc/nginx/conf.d/pajio-private-media.conf':(nginx,0,0,0o600)}


def verify_guest_config(spec,owner,settings,material,results,u):
    for path,(body,uid,gid,mode) in render_guest_files(spec,owner,settings,material,u).items():
        if read(path,uid,private=mode&0o077==0)!=body:fail('enrollment_configuration_changed')
    config=json.loads(read(Path(u.pw_dir)/'.pajio-connector/connector.json',u.pw_uid))
    bundle=pair_bundle(spec,settings,material,results)
    from .relay import ResourceSpec
    if (any(config.get(k)!=v for k,v in bundle.items() if k!='resources')
            or [ResourceSpec.model_validate(r) for r in config.get('resources',[])]!=[ResourceSpec.model_validate(r) for r in bundle['resources']]
            or config.get('token')!=material['connector_token']
            or config.get('local_data')!=u.pw_dir+'/.pajio'):
        fail('enrollment_pairing_changed')


def guest_action(stage,spec,owner,settings,material,results,*,mutate):
    u=guest_identity(spec,owner,settings)
    base={'complete':True,'owner_sha256':fingerprint(owner.model_dump()),'connector_id':material['connector_id']}
    if stage=='prepare':
        if mutate:
            require_inactive(u)
            if (Path(u.pw_dir)/'.pajio-connector/connector.json').exists():fail('enrollment_guest_already_paired')
        inventory=native_inventory(spec,u,prepare=mutate)
        # Native visibility and private video source must both be live before pairing.
        from ..private_media_sources import configured_source
        with as_user(u,desktop=spec.kind=='linux'):
            source=configured_source(binding(spec,owner,material,u))
            if not source.available():fail('enrollment_private_source_unavailable')
            if spec.kind=='android':
                from ..private_media_android import PRIVATE_IME_SHA256
                apk=run(['/usr/bin/adb','-s',android_serial(spec),'shell','pm','path','io.pajio.privateinput'])
                paths=[v.removeprefix('package:') for v in apk.splitlines() if v.startswith('package:')]
                if len(paths)!=1 or not paths[0].startswith('/data/app/') or '\n' in paths[0]:fail('enrollment_private_ime_unavailable')
                if run(['/usr/bin/adb','-s',android_serial(spec),'shell','sha256sum',paths[0]]).split()[0]!=PRIVATE_IME_SHA256:
                    fail('enrollment_private_ime_unverified')
        return {**base,'inventory':inventory}
    if stage=='configure':
        if mutate:
            require_inactive(u)
            bundle=pair_bundle(spec,settings,material,results)
            root=Path(u.pw_dir)/'.pajio-connector'
            from ..config import private_directory
            from ..connectors.remote.client import pair
            with as_user(u,desktop=spec.kind=='linux'):
                private_directory(root)
                config={**bundle,'token':material['connector_token'],'local_data':u.pw_dir+'/.pajio','connection_id':None}
                write_exact(root/'connector.json',encoded(config),uid=u.pw_uid,gid=u.pw_gid)
                write_exact(root/'enrollment-pair.json',encoded(bundle),uid=u.pw_uid,gid=u.pw_gid)
                asyncio.run(pair(root/'enrollment-pair.json',root,Path(u.pw_dir)/'.pajio'))
            # /etc/pajio is traversable; private leaf files restrict access.
            for directory in ('/etc/pajio','/etc/pajio/tls'):
                d=Path(directory)
                if d.is_symlink():fail('enrollment_file_unsafe')
                if not d.exists():d.mkdir(mode=0o755)
            for path,(body,uid,gid,mode) in render_guest_files(spec,owner,settings,material,u).items():
                write_exact(path,body,uid=uid,gid=gid,mode=mode)
            run(['nginx','-t'])
        verify_guest_config(spec,owner,settings,material,results,u)
        return base
    if stage=='activate':
        verify_guest_config(spec,owner,settings,material,results,u)
        if mutate:
            require_inactive(u)
            from ..connectors.remote.service import ConnectorService
            with as_user(u,desktop=spec.kind=='linux'):
                from ..connectors.remote.daemon_state import set_desired
                set_desired(Path(u.pw_dir)/'.pajio-connector','stopped')
                service=ConnectorService(Path(u.pw_dir)/'.pajio-connector')
                # Installer needs the user manager bus, while its generated unit
                # needs the native desktop bus. ConnectorService preserves both.
                service.install()
            run(['systemctl','daemon-reload'])
            run(['systemctl','enable','--now','pajio-private-media.service'])
            run(['systemctl','enable','nginx']);run(['systemctl','reload-or-restart','nginx'])
            with as_user(u,desktop=spec.kind=='linux'):
                ConnectorService(Path(u.pw_dir)/'.pajio-connector').start()
        if (run(['systemctl','is-active','pajio-private-media.service'])!='active'
                or run(['systemctl','is-active','nginx'])!='active'
                or user_systemctl(u,'is-active',connector_unit(u))!='active'):
            fail('enrollment_services_not_ready')
        request=urllib.request.Request('http://127.0.0.1:8792/v1/status',headers={'Authorization':'Bearer '+material['host_token']})
        with urllib.request.urlopen(request,timeout=10) as response:status=json.loads(response.read(65537))
        if (status.get('ready') is not True or status.get('resources')!=[spec.resource_id]
                or any(not v.get('closed') or not v.get('cleared') for v in status.get('sessions',{}).values())):
            fail('enrollment_media_not_ready')
        return base
    fail('enrollment_stage_invalid')


class ReadonlyRelay:
    def __init__(self,root,tenant):
        self.root=root/'data/device-relay';self.path=self.root/'relay.sqlite3';self.tenant=tenant
        # Check metadata without reading the database into memory.
        if (self.path.is_symlink() or not self.path.is_file() or self.path.stat().st_uid!=os.getuid()
                or self.path.stat().st_mode&0o077):fail('enrollment_relay_database_unsafe')
        config=json.loads(read(root/'private-media-access.json',os.getuid()))
        self.human_access_ready=config.get('version')==1 and config.get('enabled') is True and bool(config.get('hosts'))

    @contextmanager
    def tx(self):
        db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=5);db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            yield db
        finally:db.rollback();db.close()


def tenant_store(target,spec,*,mutate=False):
    from .instance import load_instance
    from .relay import instance_relay
    from .device_admission import tenant_evidence
    root=Path(target['root']);instance=load_instance(root)
    tenant_evidence(root,spec.tenant_id,spec.identity_id,instance.instance_id)
    return instance_relay(root) if mutate else ReadonlyRelay(root,instance.tenant_id)


def issued_pair(store,spec,owner,material,results,*,mutate=False):
    from .relay import encoded as relay_encoded, fingerprint as digest
    inventory=results['prepare']['inventory'];connector=material['connector_id']
    intent={'owner':owner.model_dump(),'inventory':inventory}
    with store.tx() as db:
        if mutate:
            db.execute('CREATE TABLE IF NOT EXISTS operator_enrollments(request TEXT PRIMARY KEY,digest TEXT NOT NULL,connector TEXT UNIQUE NOT NULL)')
            old=db.execute('SELECT * FROM operator_enrollments WHERE request=?',(spec.request_id,)).fetchone()
            if old and (old['digest']!=fingerprint(intent) or old['connector']!=connector):fail('enrollment_pairing_changed')
            if not old:
                existing={r['resource_id'] for row in db.execute('SELECT resources FROM connectors WHERE revoked=0') for r in json.loads(row[0])}
                pending={r['resource_id'] for row in db.execute('SELECT resources FROM pairs WHERE expires>?',(time.time(),)) for r in json.loads(row[0])}
                if spec.resource_id in existing|pending:fail('enrollment_resource_already_bound')
                db.execute('INSERT INTO pairs VALUES(?,?,?,?,?,?,NULL)',(digest(material['pair_code']),connector,
                    spec.identity_id,relay_encoded(inventory['resources']),relay_encoded(inventory['tools']),time.time()+600))
                db.execute('INSERT INTO operator_enrollments VALUES(?,?,?)',(spec.request_id,fingerprint(intent),connector))
        old=db.execute('SELECT * FROM operator_enrollments WHERE request=?',(spec.request_id,)).fetchone()
        row=db.execute('SELECT * FROM pairs WHERE code=?',(digest(material['pair_code']),)).fetchone()
        if (not old or old['digest']!=fingerprint(intent) or old['connector']!=connector or not row
                or row['connector']!=connector or row['identity']!=spec.identity_id
                or json.loads(row['resources'])!=inventory['resources'] or json.loads(row['tools'])!=inventory['tools']):
            fail('enrollment_pairing_changed')
        if row['token'] is None:
            if row['expires']<=time.time():fail('enrollment_pairing_expired')
        elif row['token']!=material['connector_token_sha256']:fail('enrollment_pairing_changed')


def bound_connector(store,spec,material,results):
    with store.tx() as db:
        row=db.execute('SELECT * FROM connectors WHERE id=?',(material['connector_id'],)).fetchone()
        inventory=results['prepare']['inventory']
        if (not row or row['revoked'] or row['identity']!=spec.identity_id or row['token']!=material['connector_token_sha256']
                or json.loads(row['resources'])!=inventory['resources'] or json.loads(row['tools'])!=inventory['tools']):
            fail('enrollment_pairing_unconfirmed')
        return dict(row)


def tenant_entry(root,spec,settings,material):
    tls=root/'enrollment-tls'/spec.request_id
    return {'identity_id':spec.identity_id,'connector_id':material['connector_id'],
            'url':'https://'+settings.guest_ipv4+':9443','token':material['host_token'],
            'ca':str(tls/'ca.pem'),'client_cert':str(tls/'client.pem'),'client_key':str(tls/'client-key.pem')}


def bind_tenant(store,target,spec,owner,settings,material,results,u,*,mutate=False):
    from ..config import write_private_json
    root=Path(target['root']);path=root/'private-media-access.json';entry=tenant_entry(root,spec,settings,material)
    bound_connector(store,spec,material,results)
    with FileLock(root/'enrollment-media.lock',timeout=5):
        config=json.loads(read(path,u.pw_uid))
        if config.get('version')!=1 or config.get('enabled') is not True or not isinstance(config.get('hosts'),dict):
            fail('enrollment_tenant_media_prerequisite')
        # TURN is operator provisioned; no default URL or long-lived key is
        # invented/copied from another tenant by this helper.
        from ..private_media_access import ice_servers
        ice_servers(config,{'session_id':'enrollment-'+spec.request_id,'expires_at':time.time()+60})
        existing=config['hosts'].get(spec.resource_id)
        if existing is not None and existing!=entry:fail('enrollment_tenant_binding_changed')
        for other_rid,other in config['hosts'].items():
            if other_rid!=spec.resource_id and (other.get('connector_id')==entry['connector_id'] or other.get('url')==entry['url']):
                fail('enrollment_duplicate_media_host')
        pemfiles={'ca.pem':material['ca_cert'],'client.pem':material['client_cert'],'client-key.pem':material['client_key']}
        if mutate:
            endpoint={'endpoint':settings.tenant_endpoint,'ca_pem':settings.relay_ca_pem}
            endpoint_path=root/'data/device-endpoint.json'
            if endpoint_path.exists() and json.loads(read(endpoint_path,u.pw_uid))!=endpoint:fail('enrollment_relay_endpoint_changed')
            remote=root/'data/remote-devices.json'
            if remote.exists() and json.loads(read(remote,u.pw_uid))!={'schema_version':1,'enabled':True}:fail('enrollment_remote_tools_disabled')
            for name,body in pemfiles.items():write_exact(root/'enrollment-tls'/spec.request_id/name,body,uid=u.pw_uid,gid=u.pw_gid)
            config['hosts'][spec.resource_id]=entry
            write_private_json(path,config)
            write_private_json(endpoint_path,endpoint)
            write_private_json(remote,{'schema_version':1,'enabled':True})
        elif existing!=entry:fail('enrollment_tenant_binding_missing')
        for name,body in pemfiles.items():
            if read(root/'enrollment-tls'/spec.request_id/name,u.pw_uid)!=body:fail('enrollment_tenant_tls_changed')
        return entry


def mtls_probe(entry):
    """Verify server pin, required client cert and authenticated POST reachability.

    An empty invalid offer must fail with a host protocol error. No ownership
    transition, screen capture, SDP or human input is involved.
    """
    import httpx
    ctx=ssl.create_default_context(cafile=entry['ca']);ctx.load_cert_chain(entry['client_cert'],entry['client_key'])
    with httpx.Client(verify=ctx,trust_env=False,follow_redirects=False,timeout=10) as client:
        response=client.post(entry['url']+'/v1/offer',json={},headers={'Authorization':'Bearer '+entry['token']})
        if response.status_code!=409 or response.json()!={'error':'invalid_private_scope'}:fail('enrollment_mtls_probe_failed')
        denied=client.post(entry['url']+'/v1/offer',json={})
        if denied.status_code!=401:fail('enrollment_host_auth_missing')
    try:
        with httpx.Client(verify=ssl.create_default_context(cafile=entry['ca']),trust_env=False,follow_redirects=False,timeout=10) as client:
            unauth=client.post(entry['url']+'/v1/offer',json={})
            if unauth.status_code not in (400,403):fail('enrollment_client_certificate_not_required')
    except (httpx.ConnectError,httpx.ReadError,httpx.RemoteProtocolError):
        pass  # TLS alert is an expected rejection of an uncertified client.
    return True


def relay_process():
    value=run(['systemctl','show','pajio-device-relay.service','--property=MainPID','--property=ActiveState'])
    fields=dict(line.split('=',1) for line in value.splitlines() if '=' in line)
    pid=fields.get('MainPID','')
    if fields.get('ActiveState')!='active' or not pid.isdigit() or int(pid)<=0:fail('enrollment_relay_not_running')
    stat=Path('/proc/'+pid+'/stat').read_text().rsplit(')',1)[1].split()
    boot=int(next(line.split()[1] for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime ')))
    return pid,boot+int(stat[19])/os.sysconf('SC_CLK_TCK')


def verify_dynamic_relay():
    """Require the live relay release which reads media enablement per request."""
    from . import relay
    if not isinstance(getattr(relay.RelayStore,'human_access_ready',None),property):
        fail('enrollment_dynamic_relay_required')
    _,started=relay_process()
    if started<Path(relay.__file__).stat().st_mtime:
        fail('enrollment_live_relay_release_unconfirmed')


def tenant_action(stage,target,spec,owner,settings,material,results,*,mutate):
    u=pwd.getpwnam(target['account'])
    if u.pw_uid==0:fail('enrollment_tenant_account_invalid')
    if stage in ('bind','inspect'):verify_dynamic_relay()
    with as_user(u):
        store=tenant_store(target,spec,mutate=mutate)
        issued_pair(store,spec,owner,material,results,mutate=stage=='issue' and mutate)
        base={'complete':True,'owner_sha256':fingerprint(owner.model_dump()),'connector_id':material['connector_id']}
        if stage=='issue':return base
        if stage not in ('bind','inspect'):fail('enrollment_stage_invalid')
        entry=bind_tenant(store,target,spec,owner,settings,material,results,u,mutate=stage=='bind' and mutate)
        if stage=='bind':return base
        c=bound_connector(store,spec,material,results)
        with store.tx() as db:
            control=db.execute('SELECT * FROM controls WHERE resource=?',(spec.resource_id,)).fetchone()
            human_state=db.execute('SELECT state FROM human_access WHERE resource=?',(spec.resource_id,)).fetchone()
            unresolved=db.execute("SELECT 1 FROM commands WHERE resource=? AND state IN ('queued','executing','unknown','device_error') AND resolved=0",(spec.resource_id,)).fetchone()
        agent=(bool(c['connection']) and (c['expires'] or 0)>time.time()
               and json.loads(c['availability']).get(spec.resource_id) is True and not unresolved
               and (not human_state or human_state['state']=='agent_ready')
               and (not control or (not control['paused'] and control['ack']==control['generation'] and control['connection']==c['connection'])))
        human=(c.get('human_access_ready')==1 and json.loads(c.get('human_availability') or '{}').get(spec.resource_id) is True)
        return {**base,'paired_scope_matches':True,'agent_online':agent,'human_online':human,'mtls_verified':mtls_probe(entry)}


def dispatch(p):
    spec=DeviceSpec.model_validate(p['spec']);owner=Owner.model_validate(p['owner']);validate_scope(spec,owner)
    settings=EnrollmentSpec.model_validate(p['settings']);material=p['material'];results=p['results']
    if p['role'] not in ('guest','tenant'):fail('enrollment_role_invalid')
    action=p['action'];stage=results.get('reconcile_stage') if action=='reconcile' else action
    if stage not in ('prepare','issue','configure','bind','activate','inspect'):fail('enrollment_stage_invalid')
    if p['role']=='guest' and stage in ('issue','bind'):fail('enrollment_role_invalid')
    if p['role']=='tenant' and stage not in ('issue','bind','inspect'):fail('enrollment_role_invalid')
    directory=Path('/var/lib/pajio-native' if p['role']=='guest' else '/var/lib/pajio-enrollment')
    if directory.is_symlink():fail('enrollment_file_unsafe')
    directory.mkdir(mode=0o700,exist_ok=True)
    intent={'owner':owner.model_dump(),'settings_sha256':fingerprint(settings.model_dump()),'material_sha256':p['material_sha256']}
    with FileLock(directory/'enrollment.lock',timeout=5):
        receipt=directory/(spec.request_id+'.json')
        if receipt.exists():
            state=json.loads(read(receipt))
            if state.get('intent')!=intent:fail('enrollment_request_changed')
        else:state={'intent':intent,'stages':{}}
        mutate=action not in ('reconcile','inspect')
        if mutate:
            if state['stages'].get(stage):fail('enrollment_step_requires_reconcile')
            from ..config import write_private_json
            state['stages'][stage]='inflight';write_private_json(receipt,state)
        elif action=='reconcile' and stage not in state['stages']:
            return {'complete':False}
        try:
            if p['role']=='guest':
                if stage=='inspect':
                    guest_action('activate',spec,owner,settings,material,results,mutate=False)
                    value={'owner_sha256':fingerprint(owner.model_dump()),'owner_matches':True,'bootstrap_matches':True}
                else:value=guest_action(stage,spec,owner,settings,material,results,mutate=mutate)
            else:value=tenant_action(stage,p['target'],spec,owner,settings,material,results,mutate=mutate)
        except Exception:
            if action=='reconcile':return {'complete':False}
            raise
        if mutate:
            state['stages'][stage]='applied';write_private_json(receipt,state)
        return value
