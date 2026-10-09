"""Recoverable manual power lifecycle. Capacity reservations are never released.

The adapter is operator-owned; its methods inspect authoritative relay, guest and
hypervisor state. No public route accepts readiness receipts or shell commands.
"""
import json
import re

from .device_provisioning import DeviceSpec, Owner, ProvisionError, encoded, fingerprint


class DevicePower:
    def __init__(self, book):
        self.book = book
        with book._tx() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS device_power(
              request TEXT PRIMARY KEY, operation TEXT NOT NULL, phase TEXT NOT NULL,
              config_sha256 TEXT NOT NULL, boot_id TEXT NOT NULL, gateway_epoch INTEGER NOT NULL,
              code TEXT NOT NULL DEFAULT '', updated REAL NOT NULL)''')

    def _bound(self, request):
        with self.book._tx() as db:
            row = db.execute('SELECT * FROM devices WHERE request=?', (request,)).fetchone()
            account = db.execute('SELECT scope FROM device_accounts WHERE request=?', (request,)).fetchone()
        if not row or not account or row['state'] not in ('staged', 'needs_operator') or not row['attempted']:
            raise ProvisionError('provisioned_binding_required')
        spec, owner = DeviceSpec.model_validate_json(row['spec']), Owner.model_validate_json(row['owner'])
        self.book._account(spec, json.loads(account['scope']))
        return spec, owner

    @staticmethod
    def _vm(adapter, spec, owner, expected=None):
        vm = adapter.inspect_vm(spec.vmid)
        if (not vm or vm.owner != owner or vm.locked or vm.template
                or (vm.vcpus, vm.memory_mib, vm.disk_mib) != (spec.vcpus, spec.memory_mib, spec.disk_mib)
                or (expected is not None and vm.config_sha256 != expected)):
            raise ProvisionError('vm_owner_or_configuration_changed')
        return vm

    def _row(self, request):
        with self.book._tx() as db:
            row = db.execute('SELECT * FROM device_power WHERE request=?', (request,)).fetchone()
        if not row: raise ProvisionError('power_request_not_found')
        return row

    def _set(self, request, phase, code=''):
        with self.book._tx() as db:
            db.execute('UPDATE device_power SET phase=?,code=?,updated=? WHERE request=?',
                       (phase, code, self.book.clock(), request))

    def status(self, request):
        row = self._row(request)
        return {'request_id': request, 'operation_id': row['operation'], 'state': row['phase'],
                'code': row['code'], 'resources_reserved': True, 'product_ready': False,
                'last_verified_ready': row['phase'] == 'ready'}

    def sleep(self, request, operation, adapter):
        if not re.fullmatch('[a-f0-9]{32}', operation): raise ProvisionError('invalid_power_operation')
        with self.book._guard():
            spec, owner = self._bound(request)
            vm = self._vm(adapter, spec, owner)
            try: row = self._row(request)
            except ProvisionError: row = None
            if row and row['operation'] != operation and row['phase'] != 'ready':
                raise ProvisionError('power_operation_changed')
            if not row or row['operation'] != operation:
                if vm.state != 'running': raise ProvisionError('running_device_required')
                native = adapter.native('health', spec, owner, operation)
                adapter.assert_ready(spec, owner)
                with self.book._tx() as db:
                    db.execute('INSERT OR REPLACE INTO device_power VALUES (?,?,?,?,?,?,?,?)',
                               (request, operation, 'freezing', vm.config_sha256, native['boot_id'],
                                native['gateway_epoch'], '', self.book.clock()))
                row = self._row(request)
            if row['operation'] == operation and row['phase'] in ('sleeping', 'ready'):
                expected = 'stopped' if row['phase'] == 'sleeping' else 'running'
                if vm.state != expected: raise ProvisionError('power_state_changed')
                return self.status(request)
            self._vm(adapter, spec, owner, row['config_sha256'])
            try:
                args = (spec, owner, operation)
                if row['phase'] == 'freezing':
                    adapter.maintenance('begin', *args)
                    adapter.maintenance('freeze', *args)
                    value = adapter.maintenance('assert_drained', *args)
                    if value['phase'] != 'frozen' or not value['acknowledged']:
                        raise ProvisionError('maintenance_ack_pending')
                    self._bound(request)
                    self._set(request, 'quiescing')
                    adapter.native('quiesce', *args)
                    row = self._row(request)
                if row['phase'] == 'quiescing':
                    # A lost reply is recovered from durable guest intent + real
                    # service readback, never by replaying a possibly-live action.
                    native = adapter.native('quiesced', *args)
                    if native['boot_id'] != row['boot_id'] or native['gateway_epoch'] != row['gateway_epoch']:
                        raise ProvisionError('native_generation_changed')
                    self._bound(request)
                    self._vm(adapter, spec, owner, row['config_sha256'])
                    self._set(request, 'shutdown_sent')
                    adapter.power('shutdown', spec, owner, row['config_sha256'])
                    row = self._row(request)
                if row['phase'] == 'shutdown_sent':
                    vm = self._vm(adapter, spec, owner, row['config_sha256'])
                    if vm.state != 'stopped': raise ProvisionError('shutdown_outcome_unknown_no_replay')
                    self._set(request, 'sleeping')
                elif row['phase'] not in ('quiescing', 'freezing'):
                    raise ProvisionError('power_phase_changed')
                return self.status(request)
            except Exception as error:
                code = str(error) if isinstance(error, ProvisionError) else 'power_outcome_unknown'
                self._set(request, self._row(request)['phase'], code)
                raise ProvisionError(code) from None

    def wake(self, request, operation, adapter):
        with self.book._guard():
            spec, owner = self._bound(request)
            row = self._row(request)
            if row['operation'] != operation: raise ProvisionError('power_operation_changed')
            vm = self._vm(adapter, spec, owner, row['config_sha256'])
            if row['phase'] == 'ready':
                if vm.state != 'running': raise ProvisionError('power_state_changed')
                adapter.assert_ready(spec, owner)
                return {**self.status(request), 'product_ready': True, 'verified_at': self.book.clock()}
            try:
                if row['phase'] == 'sleeping':
                    if vm.state != 'stopped': raise ProvisionError('power_state_changed')
                    # Allocations remain in ProvisionBook even while stopped.
                    # Check fresh physical pressure before consuming reserved RAM.
                    adapter.assert_wake_capacity(spec)
                    self._bound(request)
                    self._set(request, 'start_sent')
                    adapter.power('start', spec, owner, row['config_sha256'])
                    row = self._row(request)
                if row['phase'] == 'start_sent':
                    vm = self._vm(adapter, spec, owner, row['config_sha256'])
                    if vm.state != 'running': raise ProvisionError('start_outcome_unknown_no_replay')
                    native = adapter.native('health', spec, owner, operation)
                    if native['boot_id'] == row['boot_id'] or native['gateway_epoch'] != row['gateway_epoch']:
                        raise ProvisionError('wake_native_generation_unconfirmed')
                    self._bound(request)
                    adapter.maintenance('wake', spec, owner, operation)
                    self._set(request, 'waking')
                    row = self._row(request)
                if row['phase'] == 'waking':
                    native = adapter.native('health', spec, owner, operation)
                    if native['boot_id'] == row['boot_id'] or native['gateway_epoch'] != row['gateway_epoch']:
                        raise ProvisionError('wake_native_generation_unconfirmed')
                    self._bound(request)
                    adapter.maintenance('finish_wake', spec, owner, operation)
                    adapter.assert_ready(spec, owner)
                    self._set(request, 'ready')
                elif row['phase'] not in ('start_sent', 'sleeping'):
                    raise ProvisionError('power_phase_changed')
                return {**self.status(request), 'product_ready': True, 'verified_at': self.book.clock()}
            except Exception as error:
                code = str(error) if isinstance(error, ProvisionError) else 'power_outcome_unknown'
                self._set(request, self._row(request)['phase'], code)
                raise ProvisionError(code) from None
