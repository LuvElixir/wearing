"""Account-deletion admission and status-only recovery credentials.

No provider deletion runs here. Ownership and durable freezing belong to the
control plane; the receipt can only retrieve one already selected request.
"""
import json
import re
import secrets
import time

from itsdangerous import BadData, URLSafeTimedSerializer
from starlette.responses import JSONResponse
from starlette.routing import Route

from .account_deletion_control import DeletionError

FRESH_SECONDS = 300
RECEIPT_SECONDS = 90 * 24 * 3600
PREFIX = '/auth/account-deletion'


class ReceiptCodec:
    def __init__(self, secret):
        self.codec = URLSafeTimedSerializer(secret, salt='pajio-account-deletion-receipt-v1')

    def issue(self, user_id, request_key, revision):
        return 'pdr1.' + self.codec.dumps({'v': 1, 'user': user_id, 'key': request_key, 'revision': revision})

    def read(self, value):
        if not isinstance(value, str) or not value.startswith('pdr1.') or len(value) > 2048:
            return None
        try:
            body = self.codec.loads(value[5:], max_age=RECEIPT_SECONDS)
        except BadData:
            return None
        if (not isinstance(body, dict) or set(body) != {'v', 'user', 'key', 'revision'} or body['v'] != 1
                or not isinstance(body['user'], str) or not re.fullmatch(r'user_[a-f0-9]{32}', body['user'])
                or not isinstance(body['key'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', body['key'])
                or not isinstance(body['revision'], str) or not re.fullmatch(r'[a-f0-9]{64}', body['revision'])):
            return None
        return body


def fresh_auth(value, *, started=None, now=None):
    now = int(time.time()) if now is None else now
    return (type(value) is int and now - FRESH_SECONDS <= value <= now + 30
            and (started is None or value >= started - 30))


async def small_json(request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 4096:
            raise ValueError('请求内容过大。')
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise ValueError('请求格式不正确。')
    return body


def deletion_routes(control, codec, session, unsafe_allowed, *, reauth):
    async def plan(request):
        current = session(request)
        if current is None:
            return JSONResponse({'detail': '请先登录 Pajio。'}, status_code=401)
        result = control.preview(current)
        key = secrets.token_urlsafe(32)
        return JSONResponse({**result, 'request_key': key,
                             'receipt_token': codec.issue(current.user_id, key, result['revision']),
                             'receipt_expires_in': RECEIPT_SECONDS,
                             'reauth_required': not fresh_auth(current.auth_time)})

    async def submit(request):
        current = session(request)
        if current is None:
            return JSONResponse({'detail': '登录已失效；可使用已保存的注销凭证查询状态。'}, status_code=401)
        if not unsafe_allowed(request, current, portal=True):
            return JSONResponse({'detail': '请求来源未通过验证。'}, status_code=403)
        if not fresh_auth(current.auth_time):
            return JSONResponse({'code': 'reauth_required', 'detail': '请重新验证身份后注销。'}, status_code=401)
        try:
            body = await small_json(request)
            if set(body) != {'request_key', 'plan_revision', 'receipt_token', 'confirm'} or body['confirm'] != 'DELETE':
                raise ValueError('请确认账户注销范围。')
            proof = codec.read(body['receipt_token'])
            if (proof is None or proof['user'] != current.user_id or proof['key'] != body['request_key']
                    or proof['revision'] != body['plan_revision']):
                raise ValueError('注销计划已失效，请重新查看。')
            latest = session(request)
            if (latest is None or latest.user_id != current.user_id or latest.tenant_id != current.tenant_id
                    or not fresh_auth(latest.auth_time)):
                return JSONResponse({'code': 'reauth_required', 'detail': '身份验证已失效。'}, status_code=401)
            result = control.request(latest, body['request_key'], body['plan_revision'])
        except DeletionError as error:
            return JSONResponse({'code': error.code, 'detail': '注销计划无法提交，请重新检查账户范围。'}, status_code=error.status)
        except (ValueError, TypeError):
            return JSONResponse({'detail': '请核对注销计划与确认信息。'}, status_code=422)
        request.session.clear()
        return JSONResponse({**result, 'receipt_token': body['receipt_token']}, status_code=202)

    async def status(request):
        # Do not fall back to business cookies, or accept arbitrary user/job IDs.
        headers = request.headers.getlist('authorization')
        if request.url.query or len(headers) != 1 or not headers[0].startswith('Bearer '):
            return JSONResponse({'detail': '注销查询凭证无效。'}, status_code=401)
        proof = codec.read(headers[0][7:])
        if proof is None:
            return JSONResponse({'detail': '注销查询凭证无效。'}, status_code=401)
        result = control.status(proof['user'], request_key=proof['key'])
        return JSONResponse(result or {'state': 'not_submitted', 'code': 'not_submitted'})

    return [Route(PREFIX + '/plan', plan), Route(PREFIX + '/request', submit, methods=['POST']),
            Route(PREFIX + '/status', status), Route(PREFIX + '/reauth', reauth, methods=['POST'])]
