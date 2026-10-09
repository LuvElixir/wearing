"""Durable first boot/runtime/ready coordinator over the same operator ledger.

Enrollment remains independently resumable. A stale ready record never serves
as current readiness; verify() collects current host, native and relay evidence.
"""
import json
from .device_provisioning import DeviceSpec,Owner,Policy,ProvisionError,encoded,fingerprint
from .device_bootstrap import validate_delivery
from .device_enrollment import EnrollmentBook


class DeviceDelivery:
    def __init__(self,book):
        self.book=book
        with book._tx() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS device_delivery(
              request TEXT PRIMARY KEY, phase TEXT NOT NULL, config_sha256 TEXT NOT NULL,
              machine_sha256 TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '{}',
              code TEXT NOT NULL DEFAULT '', updated REAL NOT NULL)''')
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_device_os ON device_delivery(machine_sha256) WHERE machine_sha256!=''")
            db.execute('CREATE TABLE IF NOT EXISTS device_startup_config(request TEXT PRIMARY KEY, plan TEXT NOT NULL, state TEXT NOT NULL, updated REAL NOT NULL)')

    def _bound(self,request):
        with self.book._tx() as db:
            row=db.execute('SELECT * FROM devices WHERE request=?',(request,)).fetchone()
            account=db.execute('SELECT scope FROM device_accounts WHERE request=?',(request,)).fetchone()
            boot=db.execute('SELECT * FROM device_bootstrap WHERE request=?',(request,)).fetchone()
        if not row or row['state']!='staged' or not account or not boot or boot['state']!='network_staged':raise ProvisionError('owned_network_staged_device_required')
        spec,owner,policy=DeviceSpec.model_validate_json(row['spec']),Owner.model_validate_json(row['owner']),Policy.model_validate_json(row['policy'])
        self.book._account(spec,json.loads(account['scope']))
        return spec,owner,policy,json.loads(boot['bundle'])

    def _attest(self,adapter,spec,owner,bundle):
        proof=adapter.attest(spec,owner,bundle)
        if (proof.get('owner_sha256')!=fingerprint(owner.model_dump())
                or (proof.get('cloud_init_ready') is not True and proof.get('bootstrap_repair_verified') is not True)
                or not __import__('re').fullmatch('[a-f0-9]{64}',proof.get('machine_sha256',''))):
            raise ProvisionError('fresh_os_attestation_pending')
        return proof

    def _row(self,request):
        with self.book._tx() as db:row=db.execute('SELECT * FROM device_delivery WHERE request=?',(request,)).fetchone()
        if not row:raise ProvisionError('delivery_not_started')
        return row

    def _set(self,request,phase,*,evidence=None,machine=None,code=''):
        with self.book._tx() as db:
            row=db.execute('SELECT * FROM device_delivery WHERE request=?',(request,)).fetchone()
            db.execute('UPDATE device_delivery SET phase=?,evidence=?,machine_sha256=?,code=?,updated=? WHERE request=?',
                (phase,encoded(evidence) if evidence is not None else row['evidence'],machine or row['machine_sha256'],code,self.book.clock(),request))

    def status(self,request):
        row=self._row(request)
        return {'request_id':request,'state':row['phase'],'code':row['code'],'product_ready':False,'last_verified_ready':row['phase']=='ready'}

    def boot(self,request,adapter,*,reviewed_sha256):
        with self.book._guard():
            spec,owner,policy,bundle=self._bound(request)
            if bundle['bundle_sha256']!=reviewed_sha256:raise ProvisionError('bootstrap_plan_changed')
            vm=adapter.inspect_vm(spec.vmid)
            if not vm or vm.owner!=owner or vm.locked or vm.template:raise ProvisionError('vm_owner_or_state_conflict')
            try:row=self._row(request)
            except ProvisionError:row=None
            if not row:
                if vm.state!='stopped':raise ProvisionError('first_boot_requires_stopped_vm')
                adapter.verify_staged_network(spec,owner,bundle)
                adapter.assert_wake_capacity(spec)
                self._bound(request)
                with self.book._tx() as db:
                    db.execute('INSERT INTO device_delivery(request,phase,config_sha256,updated) VALUES(?,?,?,?)',
                               (request,'boot_sent',vm.config_sha256,self.book.clock()))
                adapter.power('start',spec,owner,vm.config_sha256)
                row=self._row(request)
            if vm.config_sha256!=row['config_sha256']:raise ProvisionError('boot_configuration_changed')
            # An earlier start may have succeeded; never replay it if uncertain.
            vm=adapter.inspect_vm(spec.vmid)
            if not vm or vm.owner!=owner or vm.state!='running' or vm.config_sha256!=row['config_sha256']:
                raise ProvisionError('first_boot_outcome_unknown_no_replay')
            attestation=self._attest(adapter,spec,owner,bundle)
            if (attestation.get('owner_sha256')!=fingerprint(owner.model_dump()) or (attestation.get('cloud_init_ready') is not True and attestation.get('bootstrap_repair_verified') is not True)
                    or not __import__('re').fullmatch('[a-f0-9]{64}',attestation.get('machine_sha256',''))):
                raise ProvisionError('fresh_os_attestation_pending')
            if row['machine_sha256'] and row['machine_sha256']!=attestation['machine_sha256']:
                raise ProvisionError('device_os_identity_changed')
            self._bound(request)
            phase='bootstrapped' if row['phase']=='boot_sent' else row['phase']
            self._set(request,phase,evidence=attestation,machine=attestation['machine_sha256'])
            return {**self.status(request),'ssh_host_key':attestation.get('ssh_host_key'),'guest_ipv4':bundle['manifest']['guest_ipv4']}

    def bind_ssh(self,request,adapter,*,identity_file,base_config):
        """Trust only the fresh key read through the host-authenticated QGA."""
        from pathlib import Path
        import os
        import shlex
        from ..config import private_directory
        with self.book._guard():
            spec,owner,policy,bundle=self._bound(request);row=self._row(request)
            if not row['machine_sha256']:raise ProvisionError('fresh_os_attestation_required')
            proof=self._attest(adapter,spec,owner,bundle)
            if proof.get('machine_sha256')!=row['machine_sha256']:raise ProvisionError('device_os_identity_changed')
            key=Path(identity_file).absolute();base=Path(base_config).absolute()
            if (key.is_symlink() or not key.is_file() or key.stat().st_uid!=os.getuid() or key.stat().st_mode&0o077
                    or not base.is_file() or any(ord(c)<32 for c in str(key)+str(base))):raise ProvisionError('operator_ssh_identity_required')
            expected=json.loads(bundle['files']['user-data'].split('\n',1)[1])['users'][0]['ssh_authorized_keys'][0].split()[:2]
            if Path(str(key)+'.pub').read_text().split()[:2]!=expected:raise ProvisionError('bootstrap_ssh_identity_changed')
            directory=self.book.root/'ssh';private_directory(directory)
            alias='pajio-device-'+str(spec.vmid);known=directory/(request+'.known_hosts');config=directory/(request+'.conf')
            hostkey=' '.join(proof['ssh_host_key'].split()[:2])
            def quote(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"')+'"'
            proxy=' '.join(['/usr/bin/ssh','-F',shlex.quote(str(base)),'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-W','%h:%p',shlex.quote(adapter.host)])
            text=('Host '+alias+'\n  HostName '+bundle['manifest']['guest_ipv4']+'\n  User pajio-admin\n  IdentityFile '+quote(key)+'\n'
                  '  IdentitiesOnly yes\n  BatchMode yes\n  StrictHostKeyChecking yes\n  HostKeyAlias '+alias+'\n  UserKnownHostsFile '+quote(known)+'\n  ProxyCommand '+proxy+'\nHost *\nInclude '+quote(base)+'\n')
            for path,body in ((known,alias+' '+hostkey+'\n'),(config,text)):
                if path.exists():
                    if path.is_symlink() or path.stat().st_mode&0o077 or path.read_text()!=body:raise ProvisionError('operator_ssh_binding_changed')
                else:
                    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                    with os.fdopen(fd,'w') as f:f.write(body);f.flush();os.fsync(f.fileno())
            self._bound(request)
            return {'request_id':request,'ssh_config':str(config),'guest_host':alias,'host_key_source':'authenticated_proxmox_qga','product_ready':False}

    def install_runtime(self,request,adapter):
        with self.book._guard():
            spec,owner,policy,bundle=self._bound(request);row=self._row(request)
            if row['phase'] not in ('bootstrapped','runtime_installing','runtime_installed'):raise ProvisionError('fresh_os_attestation_required')
            observed=self._attest(adapter,spec,owner,bundle)
            if observed.get('machine_sha256')!=row['machine_sha256']:raise ProvisionError('device_os_identity_changed')
            self._bound(request)
            if row['phase']!='runtime_installed':
                self._set(request,'runtime_installing')
                # Repeating exact package installation is allowed only while the
                # guest is not paired. Installer has an artifact+owner journal.
                adapter.install_runtime(spec,owner,bundle,row['machine_sha256'])
            runtime=adapter.runtime_status(spec,owner,bundle,row['machine_sha256'])
            if runtime!={'version':1,'owner_sha256':fingerprint(owner.model_dump()),'artifact_sha256':bundle['manifest']['artifact_sha256']}:
                raise ProvisionError('runtime_install_unconfirmed')
            self._bound(request);self._set(request,'runtime_installed')
            return self.status(request)

    def verify(self,request,adapter,enrollment_adapter):
        with self.book._guard():
            spec,owner,policy,bundle=self._bound(request);row=self._row(request)
            if row['phase'] not in ('runtime_installed','awaiting_verification','ready'):raise ProvisionError('runtime_install_required')
            os=self._attest(adapter,spec,owner,bundle)
            if os.get('machine_sha256')!=row['machine_sha256']:raise ProvisionError('device_os_identity_changed')
            runtime=adapter.runtime_status(spec,owner,bundle,row['machine_sha256'])
            if runtime!={'version':1,'owner_sha256':fingerprint(owner.model_dump()),'artifact_sha256':bundle['manifest']['artifact_sha256']}:
                raise ProvisionError('runtime_install_unconfirmed')
            enrollment=EnrollmentBook(self.book).inspect(request,enrollment_adapter)
            independent=adapter.delivery_evidence(spec,owner,bundle,row['machine_sha256'])
            evidence={**enrollment,**independent,'owner_sha256':fingerprint(owner.model_dump()),'unique_os_identity':True}
            self._bound(request)
            result=validate_delivery(owner,evidence)
            self._set(request,result['state'],evidence=evidence)
            return {**self.status(request),**result,'verified_at':self.book.clock()}


    def startup_plan(self,request,adapter):
        with self.book._guard():
            spec,owner,policy,bundle=self._bound(request);row=self._row(request)
            if row['phase']!='ready':raise ProvisionError('verified_device_required')
            proof=self._attest(adapter,spec,owner,bundle)
            if proof['machine_sha256']!=row['machine_sha256']:raise ProvisionError('device_os_identity_changed')
            observed=adapter.startup_config(spec,owner)
            if observed.get('before_sha256')!=row['config_sha256']:raise ProvisionError('device_configuration_changed')
            plan={'request_id':request,'owner_sha256':fingerprint(owner.model_dump()),'before_sha256':observed['before_sha256'],
                  'after_sha256':observed['after_sha256'],'onboot':1}
            return {**plan,'plan_sha256':fingerprint(plan),'product_ready':False}

    def finalize_startup(self,request,adapter,*,reviewed_sha256):
        with self.book._guard():
            spec,owner,policy,bundle=self._bound(request);row=self._row(request)
            if row['phase']!='ready':raise ProvisionError('verified_device_required')
            proof=self._attest(adapter,spec,owner,bundle)
            if proof['machine_sha256']!=row['machine_sha256']:raise ProvisionError('device_os_identity_changed')
            with self.book._tx() as db:operation=db.execute('SELECT * FROM device_startup_config WHERE request=?',(request,)).fetchone()
            if operation:
                plan=json.loads(operation['plan'])
                if fingerprint(plan)!=reviewed_sha256 or plan['owner_sha256']!=fingerprint(owner.model_dump()):raise ProvisionError('startup_plan_changed')
                # An uncertain configuration command is only observed. Never
                # resend it if the original old state is still visible.
                current=adapter.startup_config(spec,owner)
                if current['before_sha256']!=plan['after_sha256'] or current.get('onboot')!=1:raise ProvisionError('startup_outcome_unknown_no_replay')
            else:
                observed=adapter.startup_config(spec,owner)
                plan={'request_id':request,'owner_sha256':fingerprint(owner.model_dump()),'before_sha256':observed['before_sha256'],
                      'after_sha256':observed['after_sha256'],'onboot':1}
                if fingerprint(plan)!=reviewed_sha256 or plan['before_sha256']!=row['config_sha256']:raise ProvisionError('startup_plan_changed')
                self._bound(request)
                with self.book._tx() as db:db.execute('INSERT INTO device_startup_config VALUES(?,?,?,?)',(request,encoded(plan),'intent',self.book.clock()))
                adapter.set_autostart(spec,owner,plan)
                current=adapter.startup_config(spec,owner)
                if current['before_sha256']!=plan['after_sha256'] or current.get('onboot')!=1:raise ProvisionError('startup_outcome_unknown_no_replay')
            self._bound(request)
            with self.book._tx() as db:
                db.execute('UPDATE device_delivery SET config_sha256=?,updated=? WHERE request=?',(plan['after_sha256'],self.book.clock(),request))
                db.execute("UPDATE device_startup_config SET state='verified',updated=? WHERE request=?",(self.book.clock(),request))
            return {'request_id':request,'onboot':True,'state':'startup_verified','before_sha256':plan['before_sha256'],'after_sha256':plan['after_sha256'],'product_ready':False}
