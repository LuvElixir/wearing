"""Local configuration. Credentials stay on the server and out of API responses."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    hermes_url: str = "http://127.0.0.1:8642"
    hermes_key: str = ""
    poll_seconds: float = 2.0

    @classmethod
    def from_env(cls):
        return cls(
            data_dir=Path(os.environ.get("WEARING_DATA_DIR", ".wearing")).resolve(),
            hermes_url=os.environ.get("WEARING_HERMES_URL", "http://127.0.0.1:8642").rstrip("/"),
            hermes_key=os.environ.get("WEARING_HERMES_KEY", ""),
        )

    def __post_init__(self):
        url = urlparse(self.hermes_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("Hermes 地址必须是无内嵌凭据的 HTTP(S) 地址")
        if url.path not in {"", "/"} or url.query or url.fragment:
            raise ValueError("Hermes 地址填写服务根地址，不带 /v1 或查询参数")
        try:
            port = url.port
        except ValueError:
            raise ValueError("Hermes 地址的端口应为 1 到 65535 的整数") from None
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("Hermes 地址的端口应为 1 到 65535 的整数")
        if any(ord(char) < 33 or ord(char) > 126 for char in self.hermes_key):
            raise ValueError("连接密钥请使用可见的 ASCII 字符，不含空格或换行")
        if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("远程 Hermes 请使用 HTTPS 或本地 SSH 隧道")


def private_directory(path: Path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        path.chmod(0o700)


def write_private_json(path: Path, data: dict):
    private_directory(path.parent)
    temp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
    temp.replace(path)
