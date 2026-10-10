"""One-use, PKCE-bound handoff from the system browser to the native client.

The app receives only a disposable code in its fixed scheme. Provider tokens
never leave the callback; our own opaque session is exchanged over HTTPS.
"""
import base64
import hashlib
import json
import re
import secrets
from urllib.parse import urlencode

CALLBACK = "pajio://auth"


def session_storage_scope(user_id, tenant_id):
    """Stable opaque namespace for browser drafts, never a credential.

    These identifiers come only from the gateway's verified server session.
    Include the user as well as the tenant: shared memberships must not share
    unsent device-local drafts. Session rotation intentionally keeps this scope.
    """
    value = json.dumps(["pajio-storage-v1", user_id, tenant_id], separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def mobile_request(params):
    challenge, state = params.get("challenge"), params.get("state")
    if (not isinstance(challenge, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge)
            or not isinstance(state, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", state)):
        raise ValueError("登录关联不完整，请重新开始。")
    return {"challenge": challenge, "state": state}


def handoff_key(code, challenge, state):
    # Wrong verifiers/states cannot consume the legitimate client's handoff.
    return "mobile:" + code + ":" + challenge + ":" + state


async def issue_handoff(cache, request, subject, *, auth_time=None, tenant_id=None, enrollment_operation=None):
    code = secrets.token_urlsafe(32)
    value = {"subject": subject, "auth_time": auth_time, "tenant_id": tenant_id}
    if enrollment_operation is not None:
        if not isinstance(enrollment_operation, str) or not re.fullmatch(r'[a-f0-9]{32}', enrollment_operation):
            raise ValueError('Invalid enrollment operation')
        value['enrollment_operation'] = enrollment_operation
    await cache.set(handoff_key(code, request["challenge"], request["state"]), json.dumps(value), 120)
    return CALLBACK + "?" + urlencode({"code": code, "state": request["state"]})


async def exchange_handoff(cache, body):
    if not isinstance(body, dict) or set(body) != {"code", "verifier", "state"}:
        return None
    code, verifier, state = (body.get(k) for k in ("code", "verifier", "state"))
    if (not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", code)
            or not isinstance(verifier, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
            or not isinstance(state, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", state)):
        return None
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    value = await cache.get(handoff_key(code, challenge, state))
    return json.loads(value) if value else None
