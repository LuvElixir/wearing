"""Explicit operator CLI, deliberately absent from public routes and Agent tools."""
import argparse
import json
from pathlib import Path

from .device_provisioning import DeviceSpec, Policy, ProvisionBook, ProvisionError
from .instance import read_private
from .proxmox_devices import ProxmoxDevices
from .device_admission import AdmissionSources, TrustedSSHAdmission
from .device_queue import DeviceQueue
from .device_adoption import AdoptionBook
from .device_adoption_ssh import SSHAdoptionAdapter
from .device_enrollment import EnrollmentBook,EnrollmentSpec,EnrollmentSources,SSHEnrollmentAdapter
from .device_delivery import DeviceDelivery
from .device_delivery_ssh import SSHDeliveryAdapter
from .device_power import DevicePower
from .device_bootstrap import BootstrapBook, BootstrapSpec, write_bundle
from .device_bootstrap_ssh import SSHBootstrapAdapter
from .device_power_ssh import SSHPowerAdapter, PowerSources
from ..config import write_private_json


def main():
    parser = argparse.ArgumentParser(description='Operator-only stopped device provisioning')
    parser.add_argument('action', choices=['inventory', 'plan', 'reserve', 'apply', 'status', 'cancel', 'queue', 'queue-tick', 'queue-status', 'queue-cancel', 'sleep', 'wake', 'power-status', 'bootstrap-plan', 'stage-network', 'adopt-plan', 'adopt', 'adoption-status', 'enrollment-plan', 'enroll', 'enrollment-status', 'boot-device', 'install-runtime', 'verify-delivery', 'delivery-status', 'bind-device-ssh', 'startup-plan', 'finalize-startup'])
    parser.add_argument('--root', type=Path)
    parser.add_argument('--ssh-config', type=Path)
    parser.add_argument('--host')
    parser.add_argument('--node')
    parser.add_argument('--storage', default='local-lvm')
    parser.add_argument('--vg', default='pve')
    parser.add_argument('--pool', default='data')
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--policy', type=Path)
    parser.add_argument('--admission-sources', type=Path)
    parser.add_argument('--power-sources', type=Path)
    parser.add_argument('--bootstrap', type=Path)
    parser.add_argument('--identity-file', type=Path)
    parser.add_argument('--runtime-bundle', type=Path)
    parser.add_argument('--runtime-installer', type=Path)
    parser.add_argument('--enrollment-spec', type=Path)
    parser.add_argument('--enrollment-sources', type=Path)
    parser.add_argument('--bundle-output', type=Path)
    parser.add_argument('--bundle-sha256')
    parser.add_argument('--operation-id')
    parser.add_argument('--request-id')
    parser.add_argument('--plan-sha256')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.action != 'inventory' and not args.root:
            raise ProvisionError('operator_ledger_root_required')
        admission = None
        if args.action in ('plan', 'reserve', 'apply', 'queue', 'queue-tick', 'sleep', 'wake', 'bootstrap-plan', 'stage-network', 'adopt-plan', 'adopt', 'enrollment-plan', 'enroll', 'enrollment-status', 'boot-device', 'install-runtime', 'verify-delivery', 'bind-device-ssh', 'startup-plan', 'finalize-startup'):
            if not args.admission_sources or not args.ssh_config:
                raise ProvisionError('trusted_admission_sources_required')
            sources = AdmissionSources.model_validate_json(read_private(args.admission_sources))
            admission = TrustedSSHAdmission(ssh_config=args.ssh_config, sources=sources)
        book = ProvisionBook(args.root, operator=True, admission=admission) if args.root else None
        if args.action in ('status', 'queue-status', 'queue-cancel', 'power-status', 'adoption-status', 'delivery-status'):
            if args.action == 'status': result = book.status(args.request_id)
            elif args.action == 'power-status': result = DevicePower(book).status(args.request_id)
            elif args.action == 'adoption-status': result = AdoptionBook(book).status(args.request_id)
            elif args.action == 'delivery-status': result = DeviceDelivery(book).status(args.request_id)
            elif args.action == 'queue-status': result = DeviceQueue(book).status(args.request_id)
            else: result = DeviceQueue(book).cancel(args.request_id)
        else:
            if not args.ssh_config or not args.host or not args.node:
                raise ProvisionError('operator_ssh_target_required')
            adapter = ProxmoxDevices(ssh_config=args.ssh_config, host=args.host, node=args.node,
                                     storage=args.storage, vg=args.vg, pool=args.pool,
                                     allow_create=args.action == 'apply')
            if args.action in ('boot-device', 'install-runtime', 'verify-delivery', 'bind-device-ssh', 'startup-plan', 'finalize-startup'):
                if not args.enrollment_sources or not args.request_id:raise ProvisionError('reviewed_delivery_sources_required')
                with book._tx() as db:row=db.execute('SELECT policy FROM devices WHERE request=?',(args.request_id,)).fetchone()
                if not row:raise ProvisionError('request_not_found')
                limits=Policy.model_validate_json(row['policy'])
                if limits.node!=args.node or limits.storage!=args.storage:raise ProvisionError('delivery_host_policy_changed')
                sources=EnrollmentSources.model_validate_json(read_private(args.enrollment_sources))
                adapter=SSHDeliveryAdapter(ssh_config=args.ssh_config,host=args.host,node=args.node,storage=args.storage,vg=args.vg,pool=args.pool,
                    allow_create=True,delivery_sources=sources,runtime_bundle=args.runtime_bundle,installer=args.runtime_installer,
                    host_memory_mib=limits.host_memory_mib,host_cores=limits.host_cores)
                delivery=DeviceDelivery(book)
                if args.action=='boot-device':result=delivery.boot(args.request_id,adapter,reviewed_sha256=args.bundle_sha256)
                elif args.action=='bind-device-ssh':
                    if not args.identity_file:raise ProvisionError('operator_ssh_identity_required')
                    result=delivery.bind_ssh(args.request_id,adapter,identity_file=args.identity_file,base_config=args.ssh_config)
                elif args.action=='install-runtime':result=delivery.install_runtime(args.request_id,adapter)
                elif args.action=='startup-plan':result=delivery.startup_plan(args.request_id,adapter)
                elif args.action=='finalize-startup':result=delivery.finalize_startup(args.request_id,adapter,reviewed_sha256=args.plan_sha256)
                else:result=delivery.verify(args.request_id,adapter,SSHEnrollmentAdapter(config=args.ssh_config,sources=sources,allow_apply=False))
            elif args.action in ('enrollment-plan', 'enroll', 'enrollment-status'):
                if not args.enrollment_sources or not args.request_id:raise ProvisionError('reviewed_enrollment_sources_required')
                enrollment=EnrollmentBook(book)
                adapter=SSHEnrollmentAdapter(config=args.ssh_config,sources=EnrollmentSources.model_validate_json(read_private(args.enrollment_sources)),allow_apply=args.action=='enroll')
                if args.action=='enrollment-status':result=enrollment.inspect(args.request_id,adapter)
                else:
                    if not args.enrollment_spec:raise ProvisionError('reviewed_enrollment_spec_required')
                    settings=EnrollmentSpec.model_validate_json(read_private(args.enrollment_spec))
                    result=enrollment.plan(args.request_id,settings,adapter) if args.action=='enrollment-plan' else enrollment.enroll(args.request_id,settings,adapter,reviewed_sha256=args.plan_sha256)
            elif args.action in ('adopt-plan', 'adopt'):
                if not args.power_sources: raise ProvisionError('reviewed_power_sources_required')
                adapter=SSHAdoptionAdapter(ssh_config=args.ssh_config,host=args.host,node=args.node,storage=args.storage,vg=args.vg,pool=args.pool,
                    allow_create=True,sources=PowerSources.model_validate_json(read_private(args.power_sources)))
                adoption=AdoptionBook(book)
                if args.action=='adopt-plan':
                    if not args.spec or not args.policy:raise ProvisionError('reviewed_operator_spec_and_policy_required')
                    result=adoption.plan(DeviceSpec.model_validate_json(read_private(args.spec)),Policy.model_validate_json(read_private(args.policy)),adapter)
                else: result=adoption.apply(args.request_id,adapter,reviewed_sha256=args.plan_sha256)
            elif args.action in ('bootstrap-plan', 'stage-network'):
                if not args.bootstrap or not args.request_id:
                    raise ProvisionError('reviewed_bootstrap_spec_required')
                settings=BootstrapSpec.model_validate_json(read_private(args.bootstrap))
                if settings.node!=args.node: raise ProvisionError('bootstrap_host_changed')
                adapter=SSHBootstrapAdapter(ssh_config=args.ssh_config,host=args.host,node=args.node,storage=args.storage,vg=args.vg,pool=args.pool,
                    allow_create=args.action=='stage-network',sources={'tenants':{},'devices':{}})
                lifecycle=BootstrapBook(book)
                if args.action=='bootstrap-plan':
                    bundle=lifecycle.plan(args.request_id,settings,adapter)
                    if args.bundle_output: write_bundle(args.bundle_output,bundle)
                    result={key:bundle[key] for key in ('manifest','bundle_sha256','product_ready')}
                else:
                    result=lifecycle.stage_network(args.request_id,settings,adapter,reviewed_sha256=args.bundle_sha256)
            elif args.action in ('sleep', 'wake'):
                if not args.power_sources or not args.request_id or not args.operation_id:
                    raise ProvisionError('reviewed_power_sources_and_operation_required')
                with book._tx() as db:
                    row = db.execute('SELECT policy FROM devices WHERE request=?', (args.request_id,)).fetchone()
                if not row: raise ProvisionError('request_not_found')
                limits = Policy.model_validate_json(row['policy'])
                if limits.node != args.node or limits.storage != args.storage:
                    raise ProvisionError('power_host_policy_changed')
                adapter = SSHPowerAdapter(ssh_config=args.ssh_config,host=args.host,node=args.node,storage=args.storage,vg=args.vg,pool=args.pool,
                    allow_create=True,sources=PowerSources.model_validate_json(read_private(args.power_sources)),
                    host_memory_mib=limits.host_memory_mib,host_cores=limits.host_cores)
                power = DevicePower(book)
                result = power.sleep(args.request_id,args.operation_id,adapter) if args.action == 'sleep' else power.wake(args.request_id,args.operation_id,adapter)
            elif args.action == 'inventory':
                result = adapter.inventory().model_dump(mode='json')
            elif args.action == 'apply':
                result = book.apply(args.request_id, adapter, plan_sha256=args.plan_sha256)
            elif args.action == 'queue-tick':
                result = DeviceQueue(book).tick(adapter)
            elif args.action == 'cancel':
                result = book.cancel_unattempted(args.request_id, adapter)
            else:
                if not args.spec or not args.policy:
                    raise ProvisionError('reviewed_operator_spec_and_policy_required')
                spec = DeviceSpec.model_validate_json(read_private(args.spec))
                policy = Policy.model_validate_json(read_private(args.policy))
                if args.action == 'queue':
                    result = DeviceQueue(book).enqueue(spec, policy)
                elif args.action == 'plan':
                    result = book.plan(spec, policy, adapter)
                else:
                    result = book.reserve(spec, policy, adapter, plan_sha256=args.plan_sha256)
        if args.output:
            if args.output.is_symlink():
                raise ProvisionError('unsafe_operator_output')
            write_private_json(args.output, result)
            print(json.dumps({'written': True, 'action': args.action, 'product_ready': False}))
        elif args.action == 'inventory':
            # Full inventories include operator ownership proofs; use a private
            # output file when exact per-VM data is needed for a reviewed plan.
            print(json.dumps({key: result[key] for key in ('node', 'storage', 'observed_at',
                  'physical_cores', 'memory_mib', 'available_memory_mib', 'storage_mib',
                  'available_storage_mib', 'committed_storage_mib')}))
        else:
            print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError) as error:
        code = str(error) if isinstance(error, ProvisionError) else 'invalid_operator_configuration'
        parser.exit(2, code + '\n')


if __name__ == '__main__':
    main()
