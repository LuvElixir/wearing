"""Daily notification quiet windows, evaluated in the user's explicit IANA zone."""
from datetime import datetime
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT = {"enabled": False, "start_minute": 1320, "end_minute": 480, "timezone": "Asia/Shanghai", "revision": 0}


def validate_quiet_hours(enabled, start_minute, end_minute, timezone):
    if type(enabled) is not bool or any(type(v) is not int or not 0 <= v < 1440 for v in (start_minute, end_minute)):
        raise ValueError("请设置有效的安静时段。")
    if start_minute == end_minute:
        raise ValueError("开始和结束时间不能相同；全天不接收请关闭通知。")
    if not isinstance(timezone, str) or len(timezone) > 80:
        raise ValueError("请设置有效的时区。")
    try:
        ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("请设置有效的时区。") from None


def quiet_until(policy, stamp):
    """Return first allowed UTC minute, including DST gaps and repeated hours."""
    if not policy["enabled"]:
        return None
    zone = ZoneInfo(policy["timezone"])
    start, end = policy["start_minute"], policy["end_minute"]
    def quiet(at):
        local = datetime.fromtimestamp(at, zone)
        minute = local.hour * 60 + local.minute
        return start <= minute < end if start < end else minute >= start or minute < end
    if not quiet(stamp):
        return None
    candidate = math.floor(stamp / 60) * 60 + 60
    for _ in range(2880):
        if not quiet(candidate):
            return candidate
        candidate += 60
    # Historical zone jumps may skip a whole day. Keep the message pending and
    # re-evaluate, rather than delivering inside a window or discarding it.
    return candidate
