"""Recoverable local half of an existing device's permission change."""
import json
from contextlib import nullcontext
from pathlib import Path

from filelock import FileLock

from ...cloud.device_permissions import PermissionBundle, canonical_resources, grant_digest
from ...cloud.instance import read_private
from ...config import write_private_json
from .client import Journal, client_for, response, read_bundle


def require_settled(root):
    path=Path(root)/'permission-update.json'
    stage=json.loads(read_private(path)) if path.exists() else None
    if stage and stage['state'] not in ('applied','aborted') and not stage.get('automatic'):
        raise ValueError('permission_update_pending: 请重新运行同一权限更新命令，完成两端确认后再启动连接。')


def validate_local(config,bundle):
    for k in ('endpoint','ca_pem','connector_id','tenant_id','identity_id','pairing_generation'):
        if config.get(k)!=getattr(bundle,k):raise ValueError('permission_scope_mismatch')
    if config['policy_revision']!=bundle.from_revision:
        raise ValueError('permission_revision_mismatch')
    local={'id':config['connector_id'],'identity':config['identity_id'],
        'policy_revision':config['policy_revision'],'resources':json.dumps(config['resources'])}
    if grant_digest(local)!=bundle.expected_grant:raise ValueError('permission_local_grant_changed')
    target={r.resource_id:r for r in bundle.resources}
    old={r['resource_id']:r for r in config['resources']}
    if target.keys()!=old.keys():raise ValueError('permission_resources_changed')
    changed=0
    for resource,r in old.items():
        t=target[resource]
        if r['kind']!=t.kind or r['name']!=t.name:raise ValueError('permission_resources_changed')
        if set(r['methods'])!=t.methods:
            changed+=1
            if t.kind!='computer' or t.methods not in ({'computer.status','computer.observe'},{'computer.status','computer.observe','computer.input'}):
                raise ValueError('permission_resources_changed')
    if changed!=1:raise ValueError('permission_resources_changed')


async def update_permissions(bundle_path,root,adapter,*,runner_owned=False):
    root=Path(root).absolute()
    journal=Journal(root)
    bundle=PermissionBundle.model_validate_json(read_bundle(bundle_path))
    bundle_dict=bundle.model_dump(mode='json')
    bundle_dict['resources']=canonical_resources(bundle_dict['resources'])
    stage_path=root/'permission-update.json'
    # The daemon calls this between commands while it already owns runner.lock.
    # CLI callers must still prove the runner is stopped.
    with (nullcontext() if runner_owned else FileLock(root/'runner.lock',timeout=0)),FileLock(root/'pair.lock',timeout=0):
        config=json.loads(read_private(root/'connector.json'))
        stage=json.loads(read_private(stage_path)) if stage_path.exists() else None
        settled=False
        if stage and stage['state']=='pending':
            if stage['bundle']['digest']!=bundle.digest:raise ValueError('permission_update_pending')
            old=stage['old_config']
            if config!=stage['new_config'] and config!=old:raise ValueError('permission_local_config_changed')
        elif stage and stage['bundle']['digest']==bundle.digest and stage['state']=='applied':
            expected_config={k:v for k,v in stage['new_config'].items() if k!='connection_id'}
            current_config={k:v for k,v in config.items() if k!='connection_id'}
            if current_config!=expected_config:
                raise ValueError('permission_local_config_changed')
            old=stage['old_config'];settled=True
        else:old=config
        validate_local(old,bundle)
        with journal.tx() as db:
            if db.execute("SELECT 1 FROM actions WHERE state='started' OR uploaded=0").fetchone():
                raise ValueError('permission_receipts_pending: 请先运行原连接器交回旧动作回执，再停止并更新。')
        adapter.verify_binding(bundle.resources,(await adapter.inventory())['resources'])
        payload={k:bundle_dict[k] for k in ('request_id','code','digest')}
        async with client_for(old,root) as client:
            expected={'digest':bundle.digest,'policy_revision':bundle.policy_revision,'resources':bundle_dict['resources']}
            checked=await response(client,'/v1/permissions/check',payload)
            expired={'state':'expired','policy_revision':bundle.from_revision,
                'resources':canonical_resources(old['resources']),'digest':bundle.expected_grant}
            if checked==expired:
                if stage and stage['state']=='pending':
                    # Restore only after the authenticated cloud confirms that
                    # the original grant still holds and this request expired.
                    write_private_json(root/'connector.json',old)
                    stage['state']='aborted'
                    write_private_json(stage_path,stage)
                raise ValueError('permission_expired: 原权限已保留，请重新生成变更文件。')
            if checked!=expected:raise ValueError('permission_cloud_grant_changed')
            if settled:
                # Reconfirm the original acknowledgement without resetting the
                # live connection or silently trusting a now-revoked cloud grant.
                return {'applied':True,'policy_revision':bundle.policy_revision}
            target={**old,'policy_revision':bundle.policy_revision,'resources':bundle_dict['resources'],'connection_id':None}
            stage={'state':'pending','bundle':bundle_dict,'old_config':old,'new_config':target,'automatic':runner_owned}
            write_private_json(stage_path,stage)
            write_private_json(root/'connector.json',target)
            # A lost response leaves a stopped pending update. Retrying the same file
            # recovers the cloud commit; neither actions nor revisions are replayed.
            applied=await response(client,'/v1/permissions/apply',payload)
            if applied!=expected:raise ValueError('permission_cloud_grant_changed')
            stage['state']='applied'
            write_private_json(stage_path,stage)
        return {'applied':True,'policy_revision':bundle.policy_revision}
