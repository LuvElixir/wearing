"""Small native-field adapter over pinned openatx/uiautomator2, not an IME.

Runs in an isolated interpreter. JSON arrives on stdin; input text is never a
process argument. One setText attempt, followed by exact readback, no submit.
"""
import json
import re
import signal
import sys
import time
from xml.etree import ElementTree as ET


def focused_field(xml, expected_text):
    nodes = [n.attrib for n in ET.fromstring(xml).iter("node")
             if n.get("focused") == "true" and n.get("class", "").endswith("EditText")]
    if len(nodes) != 1:
        raise ValueError("请先点击一个可编辑输入框，再读取界面。当前没有唯一可确认的输入框。")
    node = nodes[0]
    if node.get("password") == "true":
        raise ValueError("密码输入请交给用户本人完成。")
    if node.get("enabled") != "true" or node.get("text", "") != expected_text:
        raise ValueError("输入框内容已经变化，尚未输入。请重新读取界面后再试。")
    if not node.get("resource-id") or not node.get("package"):
        raise ValueError("这个输入框缺少稳定标识，暂不能可靠填写。请改用其他输入方式。")
    return node


def replace_text(request):
    import uiautomator2 as u2
    from uiautomator2.core import _jsonrpc_call
    # A separate port avoids adopting a normal uiautomator2 session at 9008.
    device = None
    attempted = False
    try:
        device = u2.connect(request["serial"], port=19008)
        node = focused_field(device.dump_hierarchy(), request["expected_text"])
        field = device(resourceId=node["resource-id"], className=node["class"],
                       packageName=node["package"], focused=True)
        if field.get_text(timeout=1) != request["expected_text"]:
            raise ValueError("输入框内容已经变化，尚未输入。请重新观察。")
        attempted = True
        # Public jsonrpc_call auto-retries writes on a lost connection. Use the
        # pinned library's single-attempt transport to keep uncertain writes visible.
        returned = _jsonrpc_call(device._dev, 19008, "setText", [field.selector, request["text"]], 10, False)
        value = field.get_text(timeout=1)
        if not returned or value != request["text"]:
            result = {"ok": False, "unknown": True, "input_readback_verified": False,
                      "message": "已尝试填写一次，但读回与目标文字不完全一致。请重新观察界面或截图；可能含控件装饰文字，不要自动重复输入或提交。"}
            # Revalidate the same non-password field before disclosing its value.
            try:
                current = focused_field(device.dump_hierarchy(), value)
                if all(current.get(k) == node.get(k) for k in ("resource-id", "package", "class")):
                    result["observed_text"] = value[:12000]
            except ValueError:
                pass
            return result
        return {"ok": True, "input_readback_verified": True, "message": "已填写输入框并读回确认文字完全一致；没有点击提交。",
                "element_id": node["resource-id"], "package": node["package"]}
    except ValueError as error:
        return {"ok": False, "unknown": attempted, "message": str(error)}
    except Exception:
        return {"ok": False, "unknown": attempted, "message": "中文输入通道未得到完整结果。请检查手机授权与当前输入框，再重新观察；不要直接重试输入。"}
    finally:
        if device is not None:
            device.stop_uiautomator()


def describe_hierarchy(xml):
    """Return grounded labels and coordinates without copying entire XML trees."""
    rows = []
    for node in ET.fromstring(xml).iter("node"):
        a = node.attrib
        if not (a.get("text") or a.get("content-desc") or a.get("clickable") == "true" or a.get("focused") == "true"):
            continue
        bounds = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", a.get("bounds", ""))
        if not bounds:
            continue
        x1, y1, x2, y2 = map(int, bounds.groups())
        if x2 <= x1 or y2 <= y1:
            continue
        row = {"type": a.get("class", ""), "text": "[password]" if a.get("password") == "true" else a.get("text", ""),
               "label": "" if a.get("password") == "true" else a.get("content-desc", ""),
               "password": a.get("password") == "true", "id": a.get("resource-id", ""), "package": a.get("package", ""),
               "x": (x1+x2)//2, "y": (y1+y2)//2,
               "focused": a.get("focused") == "true", "clickable": a.get("clickable") == "true", "enabled": a.get("enabled") == "true"}
        rows.append(row)
    if not rows:
        raise ValueError("界面没有可读取的元素，请使用截图观察。")
    return {"elements": rows[:400], "truncated": len(rows) > 400}


def observe(request):
    import uiautomator2 as u2
    from uiautomator2.core import _jsonrpc_call
    device = None
    try:
        device = u2.connect(request["serial"], port=19008)
        # Dynamic pages may never become idle. The public helper can retry a
        # failed read several times; bound this observation and request a
        # screenshot instead of holding the device indefinitely.
        deadline = time.monotonic() + 10
        data = None
        for attempt in range(3):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            xml = _jsonrpc_call(device._dev, 19008, "dumpWindowHierarchy", [False, 50], min(8, remaining), False)
            try:
                data = describe_hierarchy(xml)
            except ValueError:
                data = None
            limited = not data or all(row["package"] == "com.android.systemui" for row in data["elements"])
            if not limited or attempt == 2:
                break
            time.sleep(min(.35, max(0, deadline - time.monotonic())))
        if data is None:
            raise ValueError("empty screen")
        return {"ok": True, "source": "uiautomator2", **data, "limited": limited,
                "observation_attempts": attempt + 1,
                **({"message": "只读到系统控件，未确认应用内容。请使用截图观察当前页面，再决定下一步。"} if limited else {})}
    except Exception:
        return {"ok": False, "message": "界面读取未取得结果，请使用截图观察；不要重复之前的点击或输入。"}
    finally:
        if device is not None:
            device.stop_uiautomator()


def main():
    def interrupted(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    request = json.load(sys.stdin)
    if request.get("operation") == "observe":
        print(json.dumps(observe(request), ensure_ascii=False))
        return
    if not isinstance(request.get("text"), str) or len(request["text"]) > 12000 or not isinstance(request.get("expected_text"), str) or len(request["expected_text"]) > 12000:
        raise ValueError("Invalid text input")
    print(json.dumps(replace_text(request), ensure_ascii=False))


if __name__ == "__main__":
    main()
