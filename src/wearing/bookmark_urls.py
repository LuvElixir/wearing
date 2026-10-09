"""Literal bookmark URLs. Validation never resolves or requests the address."""
import re
from urllib.parse import urlsplit


def bookmark_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("请填写不超过 4096 字的完整网页链接")
    if re.search(r"[\x00-\x20\x7f\\]|%(?:0[0-9a-f]|1[0-9a-f]|7f)", value, re.I):
        raise ValueError("网页链接不能包含空白、控制字符或反斜线")
    if not re.match(r"^https?://", value, re.I):
        raise ValueError("收藏仅支持 http 或 https 网页链接")
    try:
        parsed = urlsplit(value)
        if (not parsed.hostname or parsed.username is not None or parsed.password is not None
                or '%' in parsed.netloc or '@' in parsed.netloc
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
            raise ValueError()
        parsed.hostname.encode('idna')
    except (ValueError, UnicodeError) as error:
        raise ValueError("请使用完整、不带登录凭据的网页链接") from error
    return value
