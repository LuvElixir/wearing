"""Operator deletion journal and explicitly selected production adapter.

python -m wearing.account_deletion_cli --journal /new/private/path init
Synthetic end-to-end: --mode synthetic fixture, then plan/request/resume.
"""
import argparse
import json
from pathlib import Path

from .account_deletion import DeletionError, DeletionJobs
from .account_deletion_fixture import SyntheticDeletionAdapter


def parser():
    command=argparse.ArgumentParser(description=__doc__)
    command.add_argument('--journal',type=Path,required=True)
    command.add_argument('--mode',choices=['operator','synthetic'],default='operator')
    sub=command.add_subparsers(dest='command',required=True)
    sub.add_parser('init')
    sub.add_parser('fixture',help='Create new synthetic temp data; never adopt an existing data directory')
    register=sub.add_parser('register',help='Operator-verified ownership; include inactive members')
    register.add_argument('--tenant',required=True)
    register.add_argument('--classification',choices=['private','shared','unknown'],required=True)
    register.add_argument('--owner')
    register.add_argument('--member',action='append',required=True)
    register.add_argument('--instance')
    register.add_argument('--revision',type=int)
    plan=sub.add_parser('plan');plan.add_argument('--user',required=True)
    request=sub.add_parser('request');request.add_argument('--user',required=True)
    request.add_argument('--request-key',required=True);request.add_argument('--plan-revision',required=True)
    status=sub.add_parser('status');status.add_argument('--job',required=True)
    resume=sub.add_parser('resume');resume.add_argument('--job',required=True)
    resume.add_argument('--synthetic-root',type=Path)
    resume.add_argument('--max-steps',type=int,default=50)
    assets = sub.add_parser('assets-register', help='Register a complete operator-audited exclusive Tencent asset manifest')
    assets.add_argument('--file', type=Path, required=True)
    prepare = sub.add_parser('operator-prepare', help='Import an already accepted user request; freeze business access')
    prepare.add_argument('--gateway-root', type=Path, required=True)
    prepare.add_argument('--request', required=True)
    execute = sub.add_parser('operator-resume', help='Reconcile and execute registered cloud deletion steps')
    execute.add_argument('--gateway-root', type=Path, required=True)
    execute.add_argument('--job', required=True)
    execute.add_argument('--profile', required=True)
    execute.add_argument('--operator-keys', type=Path, required=True)
    execute.add_argument('--execute', action='store_true', help='Required to enable production network actions')
    execute.add_argument('--max-steps', type=int, default=50)
    return command


def run(arguments):
    args=parser().parse_args(arguments)
    if args.command=='fixture' and args.mode!='synthetic':raise DeletionError('fixture_requires_synthetic_mode',422)
    jobs=DeletionJobs(args.journal,initialize=args.command in {'init','fixture'},mode=args.mode)
    if args.command=='init':return {'initialized':True,'mode':jobs.mode,'production_adapter_configured':False}
    if args.command=='fixture':
        rows=[
            {'tenant_id':'fixture_private_a','classification':'private','owner_user_id':'fixture_user_a','member_ids':['fixture_user_a'],'instance_id':'fixture_instance_a'},
            {'tenant_id':'fixture_private_b','classification':'private','owner_user_id':'fixture_user_b','member_ids':['fixture_user_b'],'instance_id':'fixture_instance_b'},
            {'tenant_id':'fixture_shared','classification':'shared','owner_user_id':'fixture_user_b','member_ids':['fixture_user_a','fixture_user_b'],'instance_id':'fixture_instance_shared'},
        ]
        for row in rows:
            jobs.register(row['tenant_id'],row['classification'],row['member_ids'],owner_user_id=row['owner_user_id'],instance_id=row['instance_id'])
        adapter=SyntheticDeletionAdapter.create(rows)
        return {'mode':'synthetic','fixture_root':str(adapter.root),'user_id':'fixture_user_a','plan':jobs.preview('fixture_user_a'),'production_adapter_configured':False}
    if args.command in {'assets-register', 'operator-prepare', 'operator-resume'}:
        from .account_deletion_operator import OperatorRegistry, ProductionDeletionAdapter, TenantDeletionClient
        registry = OperatorRegistry(jobs)
        if args.command == 'assets-register':
            from .cloud.instance import read_private
            return registry.register(json.loads(read_private(args.file)))
        if args.command == 'operator-resume' and not args.execute:
            raise DeletionError('explicit_operator_execution_required', 422)
        from .cloud.gateway import load_gateway, operator_store
        from .cloud.control import ControlStore
        config = load_gateway(args.gateway_root)
        if config.database_url.get_secret_value().startswith('sqlite:///'):
            control = ControlStore(config.database_url.get_secret_value(), operator=True)
        else:
            control = operator_store(config)
        try:
            if args.command == 'operator-prepare':
                return ProductionDeletionAdapter(control, jobs, registry, None, None).prepare(args.request)
            from .cloud.deletion_tencent import DeletionTencentCLI, TencentDeletionProvider
            providers = {}
            def provider_for(asset):
                key = (asset['account_id'], asset['region'])
                if key not in providers:
                    providers[key] = TencentDeletionProvider(jobs, DeletionTencentCLI(args.profile, asset['region']))
                return providers[key]
            adapter = ProductionDeletionAdapter(control, jobs, registry, provider_for, TenantDeletionClient(args.operator_keys))
            return adapter.resume(args.job, max_steps=args.max_steps)
        finally:
            control.close()
    if args.command=='register':return jobs.register(args.tenant,args.classification,args.member,owner_user_id=args.owner,instance_id=args.instance,revision=args.revision)
    if args.command=='plan':return jobs.preview(args.user)
    if args.command=='request':return jobs.request(args.user,args.request_key,args.plan_revision)
    if args.command=='status':return jobs.status(args.job)
    if args.command=='resume':
        if args.synthetic_root and jobs.mode!='synthetic':raise DeletionError('fixture_requires_synthetic_mode',422)
        adapter=SyntheticDeletionAdapter(args.synthetic_root) if args.synthetic_root else None
        return jobs.run(args.job,adapter,max_steps=args.max_steps)
    raise DeletionError('unknown_command',422)


def main():
    import sys
    try: result=run(sys.argv[1:])
    except DeletionError as error:
        print(json.dumps({'error':error.code,'status':error.status}));return 2
    except Exception:
        # No raw provider/DB/path/credential values on the operator error channel.
        print(json.dumps({'error':'operator_command_failed'}));return 2
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
