import argparse
import json
import os
from pathlib import Path

from .config import Settings
from .doctor import inspect_host


def main():
    parser = argparse.ArgumentParser(prog="wearing", description="Wearing 个人 Agent")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="启动 Wearing，仅监听本机")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--data-dir", default=".wearing")
    doctor = sub.add_parser("doctor", help="检测运行命令的电脑和 USB 手机")
    doctor.add_argument("--android", action="store_true")
    doctor.add_argument("--output", type=Path)
    engine = sub.add_parser("engine", help="安装、检查本地 Hermes，或设置模型")
    engine.add_argument("action", choices=["install", "status", "model"])
    engine.add_argument("--data-dir", default=".wearing")
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
        from .cloud.instance import InstanceError, initialize_instance, instance_status
        try:
            if args.action == "init":
                initialize_instance(args.root, args.tenant_id, args.origin)
                print(json.dumps(instance_status(args.root), ensure_ascii=False, indent=2))
            elif args.action == "status":
                print(json.dumps(instance_status(args.root), ensure_ascii=False, indent=2))
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
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
