import argparse
import json
import os
from pathlib import Path

from .config import Settings
from .doctor import inspect_host


def main():
    parser = argparse.ArgumentParser(prog="wearing", description="Pajio 个人 Agent")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="启动 Pajio，仅监听本机")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--data-dir", default=".wearing")
    serve.add_argument("--engine-autostart", action="store_true", help="启动已经安装和配置的本机引擎；不安装新依赖")
    doctor = sub.add_parser("doctor", help="检测运行命令的电脑和 USB 手机")
    doctor.add_argument("--android", action="store_true")
    doctor.add_argument("--output", type=Path)
    engine = sub.add_parser("engine", help="安装、检查本地 Hermes，或设置模型")
    engine.add_argument("action", choices=["install", "status", "model"])
    engine.add_argument("--data-dir", default=".wearing")
    capture = sub.add_parser("capture", help="配置与检查豆包语音识别")
    capture.add_argument("action", choices=["prepare", "status", "configure"])
    capture.add_argument("--data-dir", default=".wearing")
    capture.add_argument("--browser", action="store_true", help="使用一次性本机表单配置语音密钥")
    tenant = sub.add_parser("tenant", help="初始化或启动独立租户实例（私有入口）")
    tenant_sub = tenant.add_subparsers(dest="action", required=True)
    tenant_init = tenant_sub.add_parser("init")
    tenant_init.add_argument("--root", type=Path, required=True)
    tenant_init.add_argument("--tenant-id", required=True)
    tenant_init.add_argument("--origin", required=True)
    tenant_status = tenant_sub.add_parser("status")
    tenant_status.add_argument("--root", type=Path, required=True)
    tenant_serve = tenant_sub.add_parser("serve")
    tenant_serve.add_argument("--root", type=Path, required=True)
    tenant_serve.add_argument("--port", type=int, default=8765)
    tenant_serve.add_argument("--no-engine-autostart", action="store_true", help="仅用于离线或独立执行引擎的开发验收")
    preview = tenant_sub.add_parser("preview", help="通过既有 SSH 隧道打开单人私人云端入口，不替代 SaaS 登录")
    preview.add_argument("--root", type=Path, required=True)
    preview.add_argument("--upstream", required=True)
    preview.add_argument("--port", type=int, default=18865)
    relay = tenant_sub.add_parser("relay", help="HTTPS 设备入口，不开放实例网页或本地驱动")
    relay.add_argument("--root", type=Path, required=True)
    relay.add_argument("--port", type=int, default=8443)
    relay.add_argument("--cert", type=Path, required=True)
    relay.add_argument("--key", type=Path, required=True)
    device_pair = tenant_sub.add_parser("pair-device", help="为本实例创建十分钟一次性配对文件")
    device_pair.add_argument("--root", type=Path, required=True)
    device_pair.add_argument("--endpoint", required=True)
    device_pair.add_argument("--ca", type=Path, required=True)
    device_pair.add_argument("--inventory", type=Path, required=True)
    device_pair.add_argument("--output", type=Path, required=True)
    revoke = tenant_sub.add_parser("revoke-device")
    revoke.add_argument("--root", type=Path, required=True)
    revoke.add_argument("--connector-id", required=True)
    review = tenant_sub.add_parser("review-device", help="人工核对后解除一个结果不明操作的阻塞")
    review.add_argument("--root", type=Path, required=True)
    review.add_argument("--command-id", required=True)
    connector = sub.add_parser("connector", help="电脑和 USB Android 的出站设备连接器")
    connector_sub = connector.add_subparsers(dest="action", required=True)
    inventory = connector_sub.add_parser("inventory")
    inventory.add_argument("--data-dir", type=Path, required=True)
    inventory.add_argument("--output", type=Path, required=True)
    inventory.add_argument("--offer", action="store_true", help="导出网页接入清单，不含工具描述或凭据")
    pair = connector_sub.add_parser("pair")
    pair.add_argument("--root", type=Path, required=True)
    pair.add_argument("--bundle", type=Path, required=True)
    pair.add_argument("--data-dir", type=Path, required=True)
    permissions = connector_sub.add_parser('permissions', help='用网页生成的变更文件调整现有电脑权限；先停止连接器')
    permissions.add_argument('--root', type=Path, required=True)
    permissions.add_argument('--bundle', type=Path, required=True)
    run = connector_sub.add_parser("run")
    run.add_argument("--root", type=Path, required=True)
    state = connector_sub.add_parser("status")
    state.add_argument("--root", type=Path, required=True)
    for action in ("pause", "resume"):
        control = connector_sub.add_parser(action)
        control.add_argument("--root", type=Path, required=True)
        control.add_argument("--resource-id", required=True)
    background = connector_sub.add_parser('service', help='当前用户的设备连接器常驻与停止；保留配对和动作账本')
    background.add_argument('operation', choices=['install','start','stop','status','uninstall'])
    background.add_argument('--root', type=Path, required=True)
    background.add_argument('--adopt-existing', help='迁移已有 Mac Pajio 连接器，必须指向相同连接目录与解释器')
    gateway = sub.add_parser("gateway", help="OIDC 登录、平台数据库与实例路由")
    gateway_sub = gateway.add_subparsers(dest="action", required=True)
    gateway_init = gateway_sub.add_parser("init")
    gateway_init.add_argument("--root", type=Path, required=True)
    gateway_init.add_argument("--origin", required=True)
    gateway_init.add_argument("--issuer", required=True)
    gateway_init.add_argument("--client-id", required=True)
    gateway_init.add_argument("--development", action="store_true")
    gateway_serve = gateway_sub.add_parser("serve")
    gateway_serve.add_argument("--root", type=Path, required=True)
    gateway_serve.add_argument("--port", type=int, default=8780)
    gateway_member = gateway_sub.add_parser("member")
    gateway_member.add_argument("--root", type=Path, required=True)
    gateway_member.add_argument("--subject", required=True)
    gateway_member.add_argument("--tenant-id", required=True)
    gateway_member.add_argument("--revoke", action="store_true")
    gateway_invite = gateway_sub.add_parser("invite", help="为全新独立空间发行一次性邀请码；明码仅写入私有文件")
    invite_sub = gateway_invite.add_subparsers(dest="operation", required=True)
    for operation in ("reserve", "issue", "status", "revoke"):
        invite_command = invite_sub.add_parser(operation)
        invite_command.add_argument("--root", type=Path, required=True)
        if operation in ("reserve", "issue"):
            invite_command.add_argument("--tenant-id", required=True)
        else:
            invite_command.add_argument("--invitation-id", required=True)
        if operation == "issue":
            invite_command.add_argument("--output", type=Path, required=True)
            invite_command.add_argument("--expires-in", type=int, default=7 * 86400)
    gateway_route = gateway_sub.add_parser("route")
    gateway_route.add_argument("--root", type=Path, required=True)
    gateway_route.add_argument("--tenant-root", type=Path, required=True)
    gateway_route.add_argument("--url", required=True)
    gateway_database = gateway_sub.add_parser("database", help="检查数据库或执行版本迁移")
    gateway_database.add_argument("operation", choices=["check", "upgrade"])
    gateway_database.add_argument("--root", type=Path, required=True)
    cloud = sub.add_parser("cloud", help="多云配置与腾讯云实时查询，不创建资源")
    cloud_sub = cloud.add_subparsers(dest="action", required=True)
    cloud_sub.add_parser("providers", help="列出研究与适配范围")
    cloud_plan = cloud_sub.add_parser("plan", help="离线预览要求；不是云报价或部署")
    cloud_plan.add_argument("--request", type=Path, required=True)
    tencent = cloud_sub.add_parser("tencent", help="复用本机 tccli 检查账户或实时询价（中国站）")
    tencent_sub = tencent.add_subparsers(dest="operation", required=True)
    tencent_inspect = tencent_sub.add_parser("inspect")
    tencent_inspect.add_argument("--region", default="ap-hongkong")
    tencent_inspect.add_argument("--profile", default="default")
    tencent_quote = tencent_sub.add_parser("quote")
    tencent_quote.add_argument("--request", type=Path, required=True)
    tencent_quote.add_argument("--profile", default="default")
    tencent_quote.add_argument("--billing", choices=["on-demand", "monthly"], help="覆盖示例中的计费方式；包月为 1 个月、不自动续费")
    args = parser.parse_args()
    if args.command == "capture":
        from .capture_setup import configure, configure_browser, prepare
        if args.browser and args.action != "configure":
            parser.error("--browser 仅用于 capture configure")
        action = configure_browser if args.browser else configure
        result = action(args.data_dir) if args.action == "configure" else prepare(args.data_dir)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return
    if args.command == "connector":
        if args.action=='service':
            from .connectors.remote.service import ConnectorService, ServiceError
            try:
                service=ConnectorService(args.root)
                if args.adopt_existing and args.operation!='install':
                    parser.error('只有安装时可以迁移已有任务。')
                result=service.install(args.adopt_existing) if args.operation=='install' else getattr(service,args.operation)()
                print(json.dumps(result,ensure_ascii=False))
            except (ServiceError, OSError, ValueError) as error:
                parser.error(str(error) if isinstance(error,ServiceError) else '连接器常驻未完成，请检查配对、当前登录用户和本机权限。')
            return
        import asyncio
        from .cloud.instance import read_private
        from .config import write_private_json
        from .connectors.remote.client import pair as pair_connector, Connector, Journal
        if args.action == "inventory":
            from .connectors.remote.adapter import NativeAdapter
            async def inventory_devices():
                async with NativeAdapter(args.data_dir) as adapter:
                    return await adapter.inventory()
            value = asyncio.run(inventory_devices())
            if args.offer:
                value = {"schema_version":1,"resources":value["resources"]}
            write_private_json(args.output, value)
            print("设备清单已私有保存。")
        elif args.action == "pair":
            from .connectors.remote.adapter import NativeAdapter
            from .connectors.remote.client import PairBundle, read_bundle
            async def verify_local():
                bundle = PairBundle.model_validate_json(read_bundle(args.bundle))
                async with NativeAdapter(args.data_dir) as adapter:
                    resources = (await adapter.inventory())["resources"]
                    adapter.verify_binding(bundle.resources, resources)
            asyncio.run(verify_local())
            print(json.dumps(asyncio.run(pair_connector(args.bundle,args.root,args.data_dir))))
        elif args.action == 'permissions':
            import httpx
            from filelock import Timeout
            from .connectors.remote.adapter import NativeAdapter
            from .connectors.remote.permissions import update_permissions
            data=json.loads(read_private(args.root/'connector.json'))['local_data']
            async def change_permissions():
                async with NativeAdapter(Path(data)) as adapter:
                    return await update_permissions(args.bundle,args.root,adapter)
            try:
                print(json.dumps(asyncio.run(change_permissions()),ensure_ascii=False))
            except (OSError, ValueError, httpx.HTTPError, Timeout):
                parser.error('权限更新未完成。请保留同一变更文件，检查连接器已停止、本机授权与网络后重试。')
        elif args.action in ("pause", "resume"):
            journal = Journal(args.root)
            config = json.loads(read_private(args.root / "connector.json"))
            if args.resource_id not in {r["resource_id"] for r in config["resources"]}:
                parser.error("这项资源不属于此连接器。")
            journal.pause(args.resource_id,args.action == "pause")
            print("已暂停设备转发。" if args.action == "pause" else "已恢复设备转发；本地驱动的接管仍独立生效。")
        elif args.action == "status":
            print(read_private(args.root / "status.json"))
        else:
            from .connectors.remote.adapter import NativeAdapter
            data = json.loads(read_private(args.root / "connector.json"))["local_data"]
            async def run_connector():
                import signal
                stop = asyncio.Event()
                loop = asyncio.get_running_loop()
                try:
                    loop.add_signal_handler(signal.SIGTERM, stop.set)
                except NotImplementedError:
                    signal.signal(signal.SIGTERM, lambda *_: loop.call_soon_threadsafe(stop.set))
                async with NativeAdapter(Path(data)) as adapter:
                    await Connector(args.root,adapter).run(stop)
            try:
                asyncio.run(run_connector())
            except KeyboardInterrupt:
                pass
        return
    if args.command == "cloud":
        from .cloud.placement import VMSelection, catalog, preview
        from .cloud.tencent import TencentCLI, TencentQuoteRequest, discover, quote
        try:
            if args.action == "providers":
                result = {"mode": "catalog", "implementation_status": "planned", "cloud_verified": False,
                          **catalog().model_dump(mode="json")}
            elif args.action == "tencent" and args.operation == "inspect":
                result = discover(TencentCLI(args.profile, args.region))
            else:
                if not args.request.is_file() or args.request.stat().st_size > 65536:
                    raise ValueError("无效配置文件。")
                if args.action == "tencent":
                    request = TencentQuoteRequest.model_validate_json(args.request.read_text())
                    if args.billing:
                        data = request.model_dump()
                        data["selection"]["billing"] = args.billing
                        request = TencentQuoteRequest.model_validate(data)
                    result = quote(TencentCLI(args.profile, request.selection.region), request)
                else:
                    result = preview(VMSelection.model_validate_json(args.request.read_text()))
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except (ValueError, OSError) as error:
            from .cloud.tencent import TencentError
            if isinstance(error, TencentError):
                parser.error(str(error))
            parser.error("离线配置无法预览；请检查服务商、账户环境、区域及字段。不要把云密钥放进配置文件。")
        return
    if args.command == "gateway":
        from pydantic import TypeAdapter
        from sqlalchemy.exc import SQLAlchemyError
        from .cloud.commands import Identifier
        from .cloud.control import ControlStore
        from .cloud.gateway import GatewayError, create_gateway_app, initialize_gateway, load_gateway, operator_store, register_route
        try:
            if args.action == "init":
                initialize_gateway(args.root, args.origin, args.issuer, args.client_id,
                                   client_secret=os.environ.get("WEARING_OIDC_CLIENT_SECRET", ""),
                                   database_url=os.environ.get("WEARING_CONTROL_DATABASE_URL", ""),
                                   development=args.development)
                print("入口配置已私有保存。生产部署和真实登录服务仍需验收。")
            elif args.action == "member":
                config = load_gateway(args.root)
                tenant_id = TypeAdapter(Identifier).validate_python(args.tenant_id)
                store = operator_store(config)
                try:
                    store.grant(config.issuer, args.subject, tenant_id, active=not args.revoke)
                finally:
                    store.close()
                print("会员授权已更新。")
            elif args.action == "invite":
                from .cloud.invitations import InvitationStore, issue_to_file
                config = load_gateway(args.root)
                store = operator_store(config)
                try:
                    invitations = InvitationStore(store)
                    if args.operation == "reserve":
                        result = invitations.reserve_tenant(TypeAdapter(Identifier).validate_python(args.tenant_id))
                    elif args.operation == "issue":
                        result = issue_to_file(store, issuer=config.issuer,
                            tenant_id=TypeAdapter(Identifier).validate_python(args.tenant_id), output=args.output,
                            lifetime=args.expires_in)
                    elif args.operation == "revoke":
                        result = invitations.revoke(args.invitation_id)
                    else:
                        result = invitations.status(args.invitation_id)
                finally:
                    store.close()
                print(json.dumps(result, ensure_ascii=False, indent=2))
            elif args.action == "route":
                register_route(args.root, args.tenant_root, args.url)
                print("实例路由已登记；内部密钥未输出。")
            elif args.action == "database":
                from .cloud.postgres import migrate_database, same_database, validate_database_url
                config = load_gateway(args.root)
                runtime_url = config.database_url.get_secret_value()
                if args.operation == "upgrade":
                    admin_url = os.environ.get("WEARING_CONTROL_ADMIN_DATABASE_URL", "")
                    if not admin_url or not same_database(runtime_url, admin_url):
                        raise GatewayError("迁移需要同一数据库的独立迁移凭据。")
                    validate_database_url(admin_url, development=config.development)
                    migrate_database(admin_url)
                    print("平台数据库迁移已完成；网页角色仍需通过权限检查。")
                else:
                    store = ControlStore(runtime_url)
                    store.close()
                    print("平台数据库连接与权限检查通过。" if runtime_url.startswith("postgresql+") else "本地 SQLite 元数据库可用；生产隔离尚需 PostgreSQL。")
            else:
                import uvicorn
                uvicorn.run(create_gateway_app(args.root), host="127.0.0.1", port=args.port,
                            access_log=False, proxy_headers=False)
        except (ValueError, OSError, SQLAlchemyError):
            parser.error("入口操作未完成；请检查私有配置、会员授权及实例归属。原数据仍保留。")
        return
    if args.command == "tenant":
        if args.action == "preview":
            import uvicorn
            from .cloud.preview import create_preview_app
            from .cloud.instance import load_instance
            from urllib.parse import urlparse
            instance = load_instance(args.root)
            if urlparse(instance.public_origin).port != args.port:
                raise SystemExit("私人入口端口需与实例登记的网页来源一致。")
            app = create_preview_app(args.root, args.upstream)
            print(json.dumps({"entry": instance.public_origin, "access_file": str(args.root / "preview-access.json")}), flush=True)
            uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")
            return
        from .cloud.instance import InstanceError, initialize_instance, instance_status
        try:
            if args.action == "init":
                initialize_instance(args.root, args.tenant_id, args.origin)
                print(json.dumps(instance_status(args.root), ensure_ascii=False, indent=2))
            elif args.action == "status":
                print(json.dumps(instance_status(args.root), ensure_ascii=False, indent=2))
            elif args.action == "relay":
                import uvicorn
                from .cloud.relay import create_relay_app
                uvicorn.run(create_relay_app(args.root), host="0.0.0.0", port=args.port,
                            ssl_certfile=str(args.cert), ssl_keyfile=str(args.key),
                            access_log=False, proxy_headers=False)
            elif args.action == "pair-device":
                from .cloud.relay import instance_relay
                from .cloud.instance import read_private
                from .config import write_private_json
                from .connectors.remote.client import PairBundle
                inventory = json.loads(read_private(args.inventory))
                store = instance_relay(args.root)
                # First release has only the existing daily identity; names never imply app-account isolation.
                pending = store.pair_code("daily", inventory["resources"], inventory["tools"])
                bundle = PairBundle.model_validate({**pending,"endpoint":args.endpoint,"ca_pem":read_private(args.ca)})
                write_private_json(args.root / 'data/device-endpoint.json',
                                   {'endpoint':bundle.endpoint,'ca_pem':bundle.ca_pem})
                write_private_json(args.output,bundle.model_dump(mode="json"))
                write_private_json(args.root / "data/remote-devices.json",{"schema_version":1,"enabled":True})
                print("配对文件已私有保存，有效十分钟；已运行新版引擎会自动刷新设备工具。尚未装载设备代理的旧引擎，需先完成一次版本激活。")
            elif args.action == "revoke-device":
                from .cloud.relay import instance_relay
                instance_relay(args.root).revoke(args.connector_id)
                print("已撤销这台连接器的后续操作权限。")
            elif args.action == "review-device":
                from .cloud.relay import instance_relay
                instance_relay(args.root).acknowledge(args.command_id)
                print("已记录人工核对；不会重新执行原操作。")
            else:
                import uvicorn
                from .cloud.worker import create_tenant_app
                uvicorn.run(create_tenant_app(args.root, engine_autostart=not args.no_engine_autostart),
                            host="127.0.0.1", port=args.port, access_log=False, proxy_headers=False)
        except (InstanceError, ValueError, OSError):
            parser.error("实例初始化或启动未完成；请检查目录归属、配置与运行占用。原数据仍保留。")
        return
    if args.command == "engine":
        import asyncio
        from .runtime import HermesRuntime, RuntimeError
        runtime = HermesRuntime(Path(args.data_dir))
        try:
            if args.action == "model":
                raise SystemExit(runtime.model())
            result = asyncio.run(runtime.install()) if args.action == "install" else runtime.status()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result.get("error"):
                raise SystemExit(1)
        except RuntimeError as error:
            parser.error(str(error))
        return
    if args.command == "doctor":
        result = json.dumps(inspect_host(args.android), ensure_ascii=False, indent=2)
        if args.output:
            args.output.write_text(result + "\n", encoding="utf-8")
        else:
            print(result)
        return
    import uvicorn
    from .app import create_app
    os.environ["WEARING_DATA_DIR"] = args.data_dir
    settings = Settings.from_env()
    saved = settings.data_dir / "connection.json"
    if saved.exists() and not settings.hermes_key:
        try:
            data = json.loads(saved.read_text(encoding="utf-8"))
            settings = Settings(settings.data_dir, data["url"], data["key"])
        except (ValueError, TypeError, KeyError, OSError):
            parser.error("连接配置无法读取，请修复数据目录中的 connection.json，或使用环境变量指定连接；任务数据库已保留。")
    uvicorn.run(create_app(settings, engine_autostart=args.engine_autostart), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
