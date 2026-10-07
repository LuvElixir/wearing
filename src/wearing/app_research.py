"""Project phone observations into run receipts; never infer a post or a fact."""

import json
import re

PHONE_READ = "mcp__wearing_phone__mobile_list_elements_on_screen"
PHONE_FRAME = "mcp__wearing_phone__mobile_take_screenshot"
APP_TOOLS = frozenset({PHONE_READ, PHONE_FRAME})
MAX_TEXT = 6000
MAX_LINES = 60
APP_NAMES = {
    "com.xingin.xhs": "小红书", "com.ss.android.ugc.aweme": "抖音",
    "ctrip.android.view": "携程", "com.sankuai.meituan": "美团",
    "com.sankuai.meituan.takeoutnew": "美团外卖", "me.ele": "淘宝闪购",
    "com.tencent.mm": "微信", "com.eg.android.AlipayGphone": "支付宝",
    "com.sdu.didi.psnger": "滴滴", "com.umetrip.android.msky.app": "航旅纵横",
}


def observation_data(value):
    """Unwrap only Hermes' JSON result envelope, not arbitrary prose or paths."""
    for _ in range(5):
        if isinstance(value, str):
            if len(value) > 2_000_000:
                return None
            try:
                value, _ = json.JSONDecoder().raw_decode(value.lstrip())
            except ValueError:
                return None
        elif isinstance(value, dict):
            if "_wearing_observation" in value:
                return value
            value = value.get("result")
        else:
            return None
    return None


def app_receipt_items(tool, event, result=None, failed=False):
    if tool not in APP_TOOLS or event != "tool.completed":
        return []
    data = observation_data(result)
    meta = data.get("_wearing_observation") if data else None
    if not isinstance(meta, dict):
        return [{"kind": "app", "status": "observation_unavailable", "title": "这次手机观察未留下可回看的内容"}]
    rid, oid, stamp = (meta.get(k) for k in ("resource_id", "id", "observed_at"))
    if not isinstance(rid, str) or not re.fullmatch(r"phone_[a-f0-9]{20}", rid):
        return []
    if not isinstance(oid, str) or not re.fullmatch(r"[a-f0-9]{32}", oid) or not isinstance(stamp, str):
        return []
    base = {"kind": "app", "tool": tool, "resource_id": rid, "observation_id": oid, "observed_at": stamp[:40]}
    if failed or data.get("ok") is False:
        return [{**base, "status": "observation_failed", "title": "这次手机界面未能读取"}]
    if tool == PHONE_FRAME:
        return [{**base, "status": "frame", "title": "手机截图", "detail": "已取得一张画面；不代表已理解图片或完整视频。"}]
    rows = data.get("elements")
    if not isinstance(rows, list):
        return [{**base, "status": "observation_unavailable", "title": "界面返回格式暂不支持回看"}]
    # Preserve each app's own text without merging a system prompt/keyboard into it.
    groups = {}
    for row in rows[:400]:
        if not isinstance(row, dict):
            continue
        package = row.get("package")
        if not isinstance(package, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]{0,199}", package):
            continue
        if package in {"android", "com.android.systemui"} or "inputmethod" in package.lower() or row.get("password") or str(row.get("type", "")).endswith("EditText"):
            continue
        group = groups.setdefault(package, {"lines": [], "seen": set(), "size": 0, "omitted": 0})
        for field in ("text", "label"):
            raw = row.get(field)
            if not isinstance(raw, str):
                continue
            value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", raw).strip()
            if not value or value == "[password]" or value in group["seen"]:
                continue
            group["seen"].add(value)
            remaining = MAX_TEXT - group["size"]
            if len(group["lines"]) >= MAX_LINES or remaining <= 0:
                group["omitted"] += 1
                continue
            group["lines"].append(value[:remaining])
            group["size"] += min(len(value), remaining)
            if len(value) > remaining:
                group["omitted"] += 1
    items = []
    for package, group in list(groups.items())[:4]:
        if not group["lines"]:
            continue
        items.append({**base, "status": "observed", "package": package,
                      "title": APP_NAMES.get(package, package), "lines": group["lines"],
                      "truncated": bool(data.get("truncated") or group["omitted"]),
                      "detail": "当时屏幕上返回的文字与控件说明；不代表已读完整正文、评论或视频。"})
    return items or [{**base, "status": "observation_empty", "title": "没有读到可回看的 App 文字", "detail": "可使用截图进一步观察，不能据此判断页面没有内容。"}]
