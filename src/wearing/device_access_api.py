"""Human handoff metadata, never a password, frame or input transport.

The application authentication/CSRF middleware and trusted worker storage scope
must run before these routes. Availability comes from the server-side relay;
neither a request body nor a client flag can enable private device access.
"""
from fastapi import HTTPException, Request
from pydantic import Field
from typing import Literal

from .cloud.commands import Identifier, Record
from .cloud.relay import RelayError
from .task_visibility import request_owner


class RequestAccess(Record):
    expected_generation: int = Field(ge=0, strict=True)
    request_id: Identifier


class SessionAccess(Record):
    session_id: Identifier
    epoch: int = Field(ge=1, strict=True)


class ReturnAccess(SessionAccess):
    safe_screen_confirmed: bool = Field(strict=True)
    scope_confirmed: bool = Field(strict=True)


class MediaOffer(SessionAccess):
    type: Literal['offer']
    sdp: str = Field(min_length=4, max_length=65536)


ERROR_COPY = {
    'private_gateway_unavailable': '这台设备尚未配置私密远程接入。',
    'human_return_confirmation_required': '请先退出登录验证页面，再确认交还设备。',
    'human_session_not_active': '设备尚未确认接管，请重新查看状态。',
    'human_session_busy': '设备已有接管会话，请先完成或关闭。',
    'device_private_or_paused': '设备正在接管或暂停中，请先完成交还。',
    'human_session_requires_explicit_return': '请先确认交还设备，再恢复任务。',
    'resource_not_paired': '当前身份没有接入这台设备。',
    'human_access_unavailable': '这台设备尚未配置私密远程接入。',
    'human_access_not_ready': '设备尚未准备好私密远程接入。',
    'human_session_not_found': '这次接管不存在或不属于当前账户。',
    'human_session_changed': '接管状态已变化，请重新查看设备。',
    'human_session_expired': '这次接管已过期，设备保持暂停。',
    'human_return_not_ready': '请先退出登录验证页面，再确认交还设备。',
    'control_changed': '设备状态已变化，请重新查看。',
}


def install_device_access_routes(app, relay_provider, *, local_devices=True):
    def context(request):
        # Scope is supplied by the authenticated worker, never by an HTTP header
        # accepted directly as the actor or by a client JSON field.
        actor = request_owner(request, local_devices=local_devices)
        return request.state.identity_id, actor

    def invoke(method, request, resource, **values):
        identity, actor = context(request)
        if local_devices:
            raise HTTPException(409, '当前入口尚未配置私密远程接入。')
        try:
            return getattr(relay_provider(), method)(identity, actor, resource, **values)
        except RelayError as error:
            raise HTTPException(error.status, ERROR_COPY.get(
                error.code, '设备接管尚未完成，请重新查看设备状态。')) from None

    @app.get('/api/devices/access/{resource_id}')
    def status(request: Request, resource_id: Identifier):
        context(request)
        if local_devices:
            # This describes this deployment's capability, not whether an
            # arbitrary client-supplied resource exists or is online.
            return {'supported': False, 'state': 'unavailable',
                    'unavailable_reason': 'private_gateway_not_configured'}
        return invoke('human_status', request, resource_id)

    @app.post('/api/devices/access/{resource_id}/request')
    def begin(request: Request, resource_id: Identifier, body: RequestAccess):
        return invoke('request_human', request, resource_id, **body.model_dump())

    @app.post('/api/devices/access/{resource_id}/close')
    def close(request: Request, resource_id: Identifier, body: SessionAccess):
        return invoke('close_human', request, resource_id, **body.model_dump())

    @app.post('/api/devices/access/{resource_id}/return')
    def give_back(request: Request, resource_id: Identifier, body: ReturnAccess):
        return invoke('return_human', request, resource_id, **body.model_dump())

    @app.get('/api/devices/access/{resource_id}/transport')
    def media_transport(request: Request, resource_id: Identifier):
        from .private_media_access import transport
        identity, actor = context(request)
        if local_devices:
            raise HTTPException(409, '当前入口尚未配置私密远程接入。')
        try:
            from fastapi.responses import JSONResponse
            return JSONResponse(transport(relay_provider(), identity, actor, resource_id),
                                headers={'Cache-Control': 'no-store'})
        except RelayError as error:
            raise HTTPException(error.status, ERROR_COPY.get(error.code, '远程画面尚未就绪，请重新连接。')) from None

    @app.post('/api/devices/access/{resource_id}/offer')
    async def media_offer(request: Request, resource_id: Identifier, body: MediaOffer):
        from .private_media_access import offer
        identity, actor = context(request)
        if local_devices:
            raise HTTPException(409, '当前入口尚未配置私密远程接入。')
        try:
            from fastapi.responses import JSONResponse
            answer = await offer(relay_provider(), identity, actor, resource_id, **body.model_dump())
            return JSONResponse(answer, headers={'Cache-Control': 'no-store'})
        except RelayError as error:
            raise HTTPException(error.status, ERROR_COPY.get(error.code, '远程画面尚未就绪，请重新连接。')) from None
