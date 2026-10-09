"""Privacy-safe diagnostics behind the application's existing auth boundary."""
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from .diagnostics import Diagnostics
from .store import IdentityError


def install_diagnostic_routes(app, store, runtime_for, *, probe_for=None, devices_for=None, deployment="local", require_owner=False):
    diagnostics = Diagnostics(store, runtime_for, probe_for=probe_for, devices_for=devices_for, require_owner=require_owner)
    app.state.diagnostics = diagnostics

    @app.get("/api/diagnostics")
    async def snapshot(request: Request):
        try:
            owner_scope = diagnostics.owner(request.scope.get('pajio.storage_scope'))
            value = await diagnostics.snapshot(request.state.identity_id, deployment, owner_scope=owner_scope)
        except PermissionError as error:
            raise HTTPException(401, "账户关联不可用，请重新登录。") from error
        except IdentityError as error:
            raise HTTPException(404, "当前身份不可用，请重新连接。") from error
        except Exception as error:
            raise HTTPException(503, "暂时无法整理服务诊断，可以先导出本机诊断。") from error
        return JSONResponse(value, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
    return diagnostics
