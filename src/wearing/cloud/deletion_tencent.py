"""Narrow operator-only Tencent destruction transport and state reconciliation.

Never used by TencentCLI, web routes or normal provisioning. A RequestId is not
an erasure receipt. All mutating attempts are journaled before sending and are
never automatically replayed after an ambiguous response.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from ..account_deletion import DeletionError, digest, encoded

ACTIONS = {
    'sts': {'GetCallerIdentity'},
    'cvm': {'DescribeInstances', 'StopInstances', 'TerminateInstances'},
    'cbs': {'DescribeDisks', 'DescribeSnapshots', 'TerminateDisks', 'DeleteSnapshots'},
}
VERSIONS = {'sts': '2018-08-13', 'cvm': '2017-03-12', 'cbs': '2017-03-12'}


class DeletionTencentCLI:
    """Fixed official endpoints, no shell/credential arguments/automatic retries."""
    def __init__(self, profile, region):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', profile) or not re.fullmatch(r'[a-z][a-z0-9-]{1,62}', region):
            raise DeletionError('incomplete_registry')
        self.executable = shutil.which('tccli')
        if not self.executable: raise DeletionError('provider_unavailable')
        self.profile, self.region = profile, region

    def call(self, service, action, params):
        if action not in ACTIONS.get(service, set()): raise DeletionError('adapter_mismatch')
        with tempfile.TemporaryDirectory(prefix='pajio-delete-request-') as directory:
            path = Path(directory) / 'request.json'
            path.write_text(encoded(params)); path.chmod(0o600)
            command = [self.executable, service, action, '--profile', self.profile, '--region', self.region,
                       '--version', VERSIONS[service], '--endpoint', service + '.tencentcloudapi.com',
                       '--timeout', '20', '--cli-input-json', path.as_uri()]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=30)
                value = json.loads(result.stdout)
                value = value.get('Response', value)
                if result.returncode or not isinstance(value, dict) or 'Error' in value: raise ValueError()
            except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
                raise DeletionError('provider_unavailable') from None
        return value


class TencentDeletionProvider:
    """One registered account/region; caller owns the exclusive asset manifest.

    Supported layout: one exclusive on-demand CVM, CBS disks, ordinary private
    local snapshots, no scheduled/cross-region/image/shared backups. Every other
    layout waits for a separate provider instead of expanding deletion scope.
    """
    def __init__(self, jobs, transport):
        self.jobs, self.transport = jobs, transport
        self.readback = []
        with jobs.tx() as db:
            db.execute('CREATE TABLE IF NOT EXISTS cloud_delete_intents (id TEXT PRIMARY KEY, request TEXT NOT NULL, response TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS cloud_delete_proofs (id TEXT PRIMARY KEY, value TEXT NOT NULL)')

    def _call(self, service, action, params):
        value = self.transport.call(service, action, params)
        if not isinstance(value, dict) or not isinstance(value.get('RequestId'), str) or not value['RequestId']:
            raise DeletionError('provider_unavailable')
        if action.startswith(('Describe', 'Get')):
            self.readback.append({'service': service, 'action': action, 'request_id': value['RequestId']})
        return value

    def _account(self, asset):
        value = self._call('sts', 'GetCallerIdentity', {})
        if str(value.get('AccountId', '')) != asset['account_id'] or self.transport.region != asset['region']:
            raise DeletionError('ownership_changed')

    def _list(self, service, action, params, field, id_field):
        # Always bounded and scoped to registered IDs/disks; never enumerate the
        # account broadly or treat a truncated/malformed page as absence.
        result, offset, total = [], 0, None
        while True:
            value = self._call(service, action, {**params, 'Limit': 100, 'Offset': offset})
            rows, count = value.get(field), value.get('TotalCount')
            if not isinstance(rows, list) or type(count) is not int or count < 0 or count > 1000:
                raise DeletionError('provider_unavailable')
            if total is not None and total != count: raise DeletionError('instance_busy')
            total = count
            if any(not isinstance(r, dict) or not isinstance(r.get(id_field), str) for r in rows):
                raise DeletionError('provider_unavailable')
            result.extend(rows)
            if len(result) == count: break
            if not rows or len(result) > count: raise DeletionError('provider_unavailable')
            offset += len(rows)
        if len({r[id_field] for r in result}) != len(result): raise DeletionError('provider_unavailable')
        return result

    def observe(self, asset):
        self.readback = []
        self._account(asset)
        vm = self._list('cvm', 'DescribeInstances', {'InstanceIds': [asset['cvm_id']]}, 'InstanceSet', 'InstanceId')
        disks = self._list('cbs', 'DescribeDisks', {'DiskIds': asset['disk_ids'], 'ReturnBindAutoSnapshotPolicy': True}, 'DiskSet', 'DiskId')
        snaps = []
        for disk in asset['disk_ids']:
            snaps.extend(self._list('cbs', 'DescribeSnapshots', {'Filters': [{'Name': 'disk-id', 'Values': [disk]}]}, 'SnapshotSet', 'SnapshotId'))
        # Exact-ID query must not introduce unrelated objects, even if provider
        # credentials have a wider CAM scope than the manifest.
        if any(v['InstanceId'] != asset['cvm_id'] for v in vm) or len(vm) > 1:
            raise DeletionError('ownership_changed')
        if {d['DiskId'] for d in disks} - set(asset['disk_ids']): raise DeletionError('ownership_changed')
        if {s['SnapshotId'] for s in snaps} - set(asset['snapshot_ids']): raise DeletionError('incomplete_registry')
        if vm:
            v = vm[0]
            actual_disks = [v.get('SystemDisk', {}).get('DiskId')] + [d.get('DiskId') for d in v.get('DataDisks', [])]
            if set(actual_disks) != set(asset['disk_ids']) or len(actual_disks) != len(set(actual_disks)):
                raise DeletionError('ownership_changed')
            if v.get('SystemDisk', {}).get('DiskId') != asset['system_disk_id'] or v.get('InstanceChargeType') != 'POSTPAID_BY_HOUR':
                raise DeletionError('incomplete_registry')
        for d in disks:
            if d.get('InstanceId') not in ('', None, asset['cvm_id']): raise DeletionError('ownership_changed')
            if d.get('DiskChargeType') != 'POSTPAID_BY_HOUR' or d.get('AutoSnapshotPolicyIds') != []:
                raise DeletionError('incomplete_registry')
            if type(d.get('Attached')) is not bool: raise DeletionError('provider_unavailable')
            if d.get('InstanceIdList') != [] or type(d.get('DiskBackupCount')) is not int or d['DiskBackupCount'] != 0 or d.get('BackupDisk') is not False:
                raise DeletionError('incomplete_registry')
        for s in snaps:
            if s.get('DiskId') not in asset['disk_ids']: raise DeletionError('ownership_changed')
            if (s.get('SnapshotType') != 'PRIVATE_SNAPSHOT' or type(s.get('ShareReference')) is not int
                    or s['ShareReference'] != 0 or s.get('Images') != [] or s.get('CopyingToRegions') != []
                    or s.get('CopyFromRemote') is not False or s.get('IsLocked') is not False
                    or s.get('AutoSnapshotPolicyId') not in ('', None)):
                raise DeletionError('incomplete_registry')
        return {'vm': vm, 'disks': disks, 'snapshots': snaps, 'query_ids': list(self.readback)}

    def _proof(self, key, value=None):
        with self.jobs.tx() as db:
            if value is not None:
                db.execute('INSERT OR REPLACE INTO cloud_delete_proofs VALUES(?,?)', (key, encoded(value)))
            row = db.execute('SELECT value FROM cloud_delete_proofs WHERE id=?', (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def _once(self, op, service, action, params):
        key = digest([op.job_id, op.tenant_id, service, action, params])
        request = encoded([service, action, params])
        with self.jobs.tx() as db:
            old = db.execute('SELECT request FROM cloud_delete_intents WHERE id=?', (key,)).fetchone()
            if old:
                if old[0] != request: raise DeletionError('adapter_mismatch')
                return  # Poll only. Never replay an ambiguous destructive send.
            db.execute('INSERT INTO cloud_delete_intents(id,request) VALUES(?,?)', (key, request))
        reply = self._call(service, action, params)
        with self.jobs.tx() as db:
            db.execute('UPDATE cloud_delete_intents SET response=? WHERE id=?', (encoded({'RequestId': reply['RequestId']}), key))

    def run(self, op, asset):
        key = digest([op.job_id, asset])
        state = self.observe(asset)
        baseline = self._proof(key)
        if baseline is None:
            if (len(state['vm']) != 1 or {d['DiskId'] for d in state['disks']} != set(asset['disk_ids'])
                    or {s['SnapshotId'] for s in state['snapshots']} != set(asset['snapshot_ids'])):
                raise DeletionError('incomplete_registry')
            self._proof(key, {'asset_hash': digest(asset), 'inventory_hash': digest(state)})
        if op.phase == 'stop_instance':
            if len(state['vm']) != 1: raise DeletionError('ownership_changed')
            vm = state['vm'][0]
            if vm.get('InstanceState') == 'STOPPED' and vm.get('LatestOperationState') == 'SUCCESS': return state
            if vm.get('InstanceState') == 'RUNNING':
                self._once(op, 'cvm', 'StopInstances', {'InstanceIds': [asset['cvm_id']], 'StopType': 'SOFT', 'StoppedMode': 'KEEP_CHARGING'})
            raise DeletionError('instance_busy')
        if op.phase in {'erase_primary', 'erase_indexes', 'erase_backups', 'finalize_tenant'}:
            if state['vm']:
                vm = state['vm'][0]
                if vm.get('InstanceState') == 'STOPPED' and vm.get('LatestOperationState') == 'SUCCESS':
                    self._once(op, 'cvm', 'TerminateInstances', {'InstanceIds': [asset['cvm_id']], 'ReleaseAddress': False, 'ReleasePrepaidDataDisks': False})
                raise DeletionError('instance_busy')
            for disk in state['disks']:
                if disk['DiskId'] == asset['system_disk_id']:
                    # The CVM owns this disk's lifecycle. Wait for its absence.
                    raise DeletionError('instance_busy')
                if disk.get('DiskState') == 'UNATTACHED' and disk['Attached'] is False and not disk.get('InstanceId'):
                    self._once(op, 'cbs', 'TerminateDisks', {'DiskIds': [disk['DiskId']], 'DeleteSnapshot': 0})
                else: raise DeletionError('instance_busy')
            if state['disks']: raise DeletionError('instance_busy')
            if op.phase in {'erase_primary', 'erase_indexes'}: return state
            for snap in state['snapshots']:
                if snap.get('SnapshotState') != 'NORMAL': raise DeletionError('backup_retained')
                self._once(op, 'cbs', 'DeleteSnapshots', {'SnapshotIds': [snap['SnapshotId']], 'DeleteBindImages': False})
            if state['snapshots']: raise DeletionError('backup_retained')
            return state
        raise DeletionError('adapter_mismatch')
