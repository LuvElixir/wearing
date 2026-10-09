"""Operator-only enrollment of a freshly bootstrapped, owned execution guest.

No tenant HTTP endpoint accepts these operations. SSH host trust and the
provisioning account proof are prerequisites. Lost mutation responses are
reconciled against live state; an incomplete mutation is never replayed.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
from urllib.parse import urlparse

from pydantic import Field, model_validator

from .commands import Record
from .device_admission import MetadataTarget
from .device_provisioning import DeviceSpec, Owner, ProvisionError, encoded, fingerprint
from ..config import private_directory, write_private_json


STAGES = ('prepare', 'issue', 'configure', 'bind', 'activate')


class EnrollmentSpec(Record):
    guest_ipv4: str
    tenant_endpoint: str
    relay_ca_pem: str = Field(max_length=16384, repr=False)
    artifact_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def checked(self):
        from cryptography import x509
        ip = ipaddress.ip_address(self.guest_ipv4)
        url = urlparse(self.tenant_endpoint)
        if (ip.version != 4 or ip not in ipaddress.ip_network('10.78.0.0/16')
                or int(ip) % 4 != 2 or url.scheme != 'https' or url.port != 8444
                or not url.hostname or not ipaddress.ip_address(url.hostname).is_private
                or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment):
            raise ValueError('invalid_enrollment_network')
        ca = x509.load_pem_x509_certificate(self.relay_ca_pem.encode())
        if not ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError('relay_ca_required')
        return self


class GuestTarget(Record):
    host: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$')
    python: str = '/opt/pajio-native/venv/bin/python'

    @model_validator(mode='after')
    def fixed_runtime(self):
        if self.python != '/opt/pajio-native/venv/bin/python':
            raise ValueError('pinned_native_runtime_required')
        return self


class EnrollmentSources(Record):
    tenants: dict[str, MetadataTarget]
    devices: dict[str, GuestTarget]


def android_serial(spec):
    if spec.kind != 'android' or spec.vmid > 45535:
        raise ProvisionError('invalid_android_device_port')
    return '127.0.0.1:' + str(20000 + spec.vmid)


def validate_scope(spec, owner):
    if owner != Owner(tenant_id=spec.tenant_id, identity_id=spec.identity_id,
            resource_id=spec.resource_id, request_id=spec.request_id,
            request_sha256=fingerprint(spec.model_dump()), nonce=owner.nonce,
            kind=spec.kind, vcpus=spec.vcpus, memory_mib=spec.memory_mib, disk_mib=spec.disk_mib):
        raise ProvisionError('enrollment_owner_changed')
    if spec.kind == 'android':
        from ..mobile import resource_id
        if spec.resource_id != resource_id(android_serial(spec)):
            raise ProvisionError('enrollment_android_resource_mismatch')
    elif not re.fullmatch(r'computer_[a-f0-9]{20}', spec.resource_id):
        raise ProvisionError('enrollment_computer_resource_invalid')


def certificate_material(owner, address):
    """One CA per device; discard the signing key after the two leaf certs."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Pajio device ' + owner.request_id)])
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=90))
          .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
          .add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False),critical=True)
          .sign(ca_key,hashes.SHA256()))
    result = {'ca_cert': ca.public_bytes(serialization.Encoding.PEM).decode()}
    for role, usage in (('server', ExtendedKeyUsageOID.SERVER_AUTH), ('client', ExtendedKeyUsageOID.CLIENT_AUTH)):
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, owner.resource_id+' '+role)])
        builder = (x509.CertificateBuilder().subject_name(subject).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=89))
            .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
            .add_extension(x509.ExtendedKeyUsage([usage]),critical=True)
            .add_extension(x509.KeyUsage(True,False,False,False,False,False,False,False,False),critical=True))
        if role == 'server':
            builder = builder.add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(address))]),critical=False)
        result[role+'_cert'] = builder.sign(ca_key,hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode()
        result[role+'_key'] = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()).decode()
    result.update(pair_code=secrets.token_urlsafe(32), connector_id='connector_'+secrets.token_hex(16),
                  connector_token=secrets.token_urlsafe(48), host_token=secrets.token_urlsafe(48))
    return result


class EnrollmentBook:
    def __init__(self, book):
        self.book = book
        with book._tx() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS device_enrollment(
                request TEXT PRIMARY KEY, plan TEXT NOT NULL, spec TEXT NOT NULL,
                material_sha TEXT NOT NULL, stage INTEGER NOT NULL DEFAULT 0,
                inflight INTEGER NOT NULL DEFAULT 0, code TEXT NOT NULL DEFAULT '',
                results TEXT NOT NULL DEFAULT '{}', updated REAL NOT NULL)''')

    def _bound(self, request):
        with self.book._tx() as db:
            row = db.execute('SELECT * FROM devices WHERE request=?', (request,)).fetchone()
            account = db.execute('SELECT scope FROM device_accounts WHERE request=?', (request,)).fetchone()
            boot = db.execute('SELECT * FROM device_bootstrap WHERE request=?', (request,)).fetchone()
        if not row or row['state'] != 'staged' or not account or not boot or boot['state'] != 'network_staged':
            raise ProvisionError('owned_network_staged_device_required')
        spec, owner = DeviceSpec.model_validate_json(row['spec']), Owner.model_validate_json(row['owner'])
        validate_scope(spec, owner)
        self.book._account(spec, json.loads(account['scope']))
        bundle=json.loads(boot['bundle'])
        network={**bundle['manifest'], 'tenant_ipv4':json.loads(bundle['files']['network-lease.json'])['tenant_ipv4']}
        return spec, owner, network

    def plan(self, request, settings, adapter):
        with self.book._guard():
            spec, owner, network = self._bound(request)
            if (settings.guest_ipv4 != network['guest_ipv4'] or settings.artifact_sha256 != network['artifact_sha256']
                    or urlparse(settings.tenant_endpoint).hostname != network['tenant_ipv4']):
                raise ProvisionError('enrollment_bootstrap_mismatch')
            sources = adapter.scope_targets(spec)
            value = {'version':1, 'owner':owner.model_dump(), 'settings':settings.model_dump(), 'targets':sources}
            return {'plan_sha256':fingerprint(value), 'owner_sha256':fingerprint(owner.model_dump()),
                    'resource_id':spec.resource_id, 'product_ready':False, 'stages':list(STAGES)}

    def enroll(self, request, settings, adapter, *, reviewed_sha256):
        with self.book._guard():
            plan = self.plan(request,settings,adapter)
            if plan['plan_sha256'] != reviewed_sha256: raise ProvisionError('enrollment_review_changed')
            spec, owner, _ = self._bound(request)
            directory = self.book.root / 'enrollment' / request
            private_directory(directory)
            material_path = directory / 'material.json'
            with self.book._tx() as db:
                row = db.execute('SELECT * FROM device_enrollment WHERE request=?',(request,)).fetchone()
                if row and (row['plan'] != reviewed_sha256 or row['spec'] != encoded(settings.model_dump())):
                    raise ProvisionError('enrollment_request_changed')
                if not row:
                    if material_path.exists():
                        # An orphaned private material file may be from a lost local
                        # transaction. Never rotate keys under an unknown remote pair.
                        raise ProvisionError('enrollment_orphaned_material')
                    material = certificate_material(owner, settings.guest_ipv4)
                    write_private_json(material_path, material)
                    db.execute('INSERT INTO device_enrollment(request,plan,spec,material_sha,updated) VALUES(?,?,?,?,?)',
                               (request,reviewed_sha256,encoded(settings.model_dump()),fingerprint(material),self.book.clock()))
            from .instance import read_private
            material = json.loads(read_private(material_path))
            while True:
                self._bound(request)  # Recheck account/deletion and exact owner at every step.
                with self.book._tx() as db:
                    row = db.execute('SELECT * FROM device_enrollment WHERE request=?',(request,)).fetchone()
                if fingerprint(material) != row['material_sha']: raise ProvisionError('enrollment_material_changed')
                results = json.loads(row['results'])
                index = row['stage']
                if index >= len(STAGES): return self.inspect(request,adapter)
                stage = STAGES[index]
                try:
                    if row['inflight']:
                        result = adapter.reconcile(stage,spec,owner,settings,material,results)
                        if result is None: raise ProvisionError('enrollment_outcome_unknown')
                    else:
                        with self.book._tx() as db:
                            db.execute('UPDATE device_enrollment SET inflight=1,code=?,updated=? WHERE request=?',
                                       ('enrollment_inflight',self.book.clock(),request))
                        result = adapter.apply(stage,spec,owner,settings,material,results)
                    result = checked_stage_result(stage,result,spec,owner,material)
                    self._bound(request)
                    results[stage] = result
                    with self.book._tx() as db:
                        db.execute('UPDATE device_enrollment SET stage=?,inflight=0,code=?,results=?,updated=? WHERE request=?',
                                   (index+1,'',encoded(results),self.book.clock(),request))
                except Exception as error:
                    code = str(error) if isinstance(error,ProvisionError) and re.fullmatch('[a-z_]{1,80}',str(error)) else 'enrollment_outcome_unknown'
                    with self.book._tx() as db:
                        db.execute('UPDATE device_enrollment SET code=?,updated=? WHERE request=?',(code,self.book.clock(),request))
                    raise ProvisionError(code) from None

    def inspect(self, request, adapter):
        with self.book._guard():
            spec, owner, _ = self._bound(request)
            with self.book._tx() as db:
                row = db.execute('SELECT * FROM device_enrollment WHERE request=?',(request,)).fetchone()
            if not row: return {'state':'not_enrolled','product_ready':False}
            if row['inflight'] or row['stage'] < len(STAGES):
                return {'state':'unknown' if row['inflight'] else 'pending','stage':STAGES[min(row['stage'],len(STAGES)-1)],
                        'code':row['code'],'product_ready':False}
            settings = EnrollmentSpec.model_validate_json(row['spec'])
            from .instance import read_private
            material = json.loads(read_private(self.book.root/'enrollment'/request/'material.json'))
            if fingerprint(material) != row['material_sha']: raise ProvisionError('enrollment_material_changed')
            proof = adapter.inspect(spec,owner,settings,material,json.loads(row['results']))
            self._bound(request)
            keys = ('owner_matches','bootstrap_matches','paired_scope_matches','agent_online','human_online','mtls_verified')
            if not isinstance(proof,dict) or proof.get('owner_sha256') != fingerprint(owner.model_dump()):
                raise ProvisionError('enrollment_evidence_mismatch')
            # This is deliberately NOT overall delivery: network, terms and OS
            # identity checks still belong to the trusted Delivery adapter.
            return {'state':'verified' if all(proof.get(k) is True for k in keys) else 'pending',
                    'product_ready':False,'enrollment_ready':all(proof.get(k) is True for k in keys),
                    'owner_sha256':proof['owner_sha256'],**{k:proof.get(k) is True for k in keys}}


def checked_stage_result(stage,result,spec,owner,material):
    if (not isinstance(result,dict) or result.get('owner_sha256') != fingerprint(owner.model_dump())
            or result.get('complete') is not True):
        raise ProvisionError('enrollment_stage_unconfirmed')
    output = {'complete':True,'owner_sha256':result['owner_sha256']}
    if stage == 'prepare':
        from .relay import ResourceSpec
        inventory = result.get('inventory',{})
        resources = [ResourceSpec.model_validate(r).model_dump(mode='json') for r in inventory.get('resources',[])]
        for resource in resources: resource['methods']=sorted(resource['methods'])
        if (len(resources) != 1 or resources[0]['resource_id'] != spec.resource_id
                or resources[0]['kind'] != ('computer' if spec.kind=='linux' else 'android')
                or not isinstance(inventory.get('tools'),list) or len(encoded(inventory).encode()) > 65536):
            raise ProvisionError('enrollment_inventory_mismatch')
        output['inventory'] = {'resources':resources,'tools':inventory['tools']}
    else:
        if result.get('connector_id') != material['connector_id']:
            raise ProvisionError('enrollment_connector_mismatch')
        output['connector_id'] = material['connector_id']
    return output


class SSHEnrollmentAdapter:
    """Fixed operator hosts; user input can never provide an SSH target or URL."""
    def __init__(self, *, config, sources, allow_apply=False, runner=subprocess.run):
        self.config=Path(config).absolute(); self.sources=EnrollmentSources.model_validate(sources)
        self.allow_apply=allow_apply; self.runner=runner

    def scope_targets(self,spec):
        tenant=self.sources.tenants.get(spec.tenant_id); guest=self.sources.devices.get(spec.resource_id)
        if not tenant or not guest: raise ProvisionError('enrollment_target_missing')
        return {'tenant':tenant.model_dump(),'guest':guest.model_dump()}

    def _call(self, role, action, spec, owner, settings, material, results):
        if not self.allow_apply and action not in ('inspect','reconcile'):
            raise ProvisionError('operator_apply_required')
        targets=self.scope_targets(spec); target=targets['guest' if role=='guest' else 'tenant']
        allowed = {'ca_cert','host_token','connector_id','pair_code'}
        allowed |= {'server_cert','server_key','connector_token'} if role=='guest' else {'client_cert','client_key'}
        subset={k:v for k,v in material.items() if k in allowed}
        # The tenant stores/verifies only a hash of the connector bearer.
        subset['connector_token_sha256']=hashlib.sha256(material['connector_token'].encode()).hexdigest()
        body={'role':role,'action':action,'target':target,'spec':spec.model_dump(),'owner':owner.model_dump(),
              'settings':settings.model_dump(),'material':subset,'material_sha256':fingerprint(material),'results':results}
        command='sudo -n '+shlex.quote(target['python'])+' -m wearing.cloud.device_enrollment --remote'
        try:
            result=self.runner(['ssh','-F',str(self.config),'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                '-o','ConnectTimeout=10',target['host'],command],input=encoded(body),capture_output=True,text=True,timeout=180)
            if len(result.stdout)>131072: raise ValueError()
            value=json.loads(result.stdout)
            if result.returncode or value.get('error'):
                code=value.get('error')
                raise ProvisionError(code if isinstance(code,str) and re.fullmatch('[a-z_]{1,80}',code) else 'enrollment_outcome_unknown')
            return value
        except (ValueError,OSError,subprocess.TimeoutExpired) as error:
            if isinstance(error,ProvisionError): raise
            raise ProvisionError('enrollment_outcome_unknown') from None

    def apply(self,stage,*args):
        return self._call('tenant' if stage in ('issue','bind') else 'guest',stage,*args)

    def reconcile(self,stage,spec,owner,settings,material,results):
        value=self._call('tenant' if stage in ('issue','bind') else 'guest','reconcile',spec,owner,settings,material,{**results,'reconcile_stage':stage})
        return value if value.get('complete') else None

    def inspect(self,spec,owner,settings,material,results):
        guest=self._call('guest','inspect',spec,owner,settings,material,results)
        tenant=self._call('tenant','inspect',spec,owner,settings,material,results)
        return {'owner_sha256':fingerprint(owner.model_dump()),
                **{k:guest.get(k) is True for k in ('owner_matches','bootstrap_matches')},
                **{k:tenant.get(k) is True for k in ('paired_scope_matches','agent_online','human_online','mtls_verified')}}


def remote_entry():
    """Installed on the reviewed guest/tenant runtime; stdin only, fixed errors."""
    import sys
    try:
        value=json.loads(sys.stdin.buffer.read(262145))
        if os.geteuid()!=0: raise ProvisionError('operator_required')
        from .device_enrollment_remote import dispatch
        result=dispatch(value)
        print(encoded(result))
    except Exception as error:
        code=str(error) if isinstance(error,ProvisionError) and re.fullmatch('[a-z_]{1,80}',str(error)) else 'enrollment_outcome_unknown'
        print(encoded({'error':code}));sys.exit(1)


if __name__ == '__main__':
    import sys
    if sys.argv[1:] != ['--remote']: raise SystemExit('Operator SSH helper only')
    remote_entry()
