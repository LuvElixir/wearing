"""Server-only speech configuration; never downloads local model weights."""
import getpass
import importlib.util
import json
import os
from pathlib import Path

from .config import write_private_json

PROVIDER = "doubao-seedasr-2"


def speech_key(data_dir):
    key = os.environ.get("WEARING_SPEECH_API_KEY", "").strip()
    if not key:
        try:
            config = json.loads((Path(data_dir) / "speech.json").read_text())
            if config.get("provider") != PROVIDER:
                return ""
            key = config.get("api_key", "")
        except (OSError, ValueError, AttributeError):
            return ""
    if not isinstance(key, str) or not 16 <= len(key) <= 512 or any(not 33 <= ord(c) <= 126 for c in key):
        return ""
    return key


def prepare(data_dir):
    """Legacy command now returns readiness; it cannot reinstall Whisper."""
    configured = bool(speech_key(data_dir))
    decoder = importlib.util.find_spec("av") is not None
    return {"provider": PROVIDER, "mode": "recorded-utterance", "configured": configured,
            "prepared": configured and decoder, "audio_decoder": decoder}


def configure(data_dir):
    key = getpass.getpass("Speech API Key (hidden): ").strip()
    return save_key(data_dir, key)


def save_key(data_dir, key):
    if not 16 <= len(key) <= 512 or any(not 33 <= ord(c) <= 126 for c in key):
        raise ValueError("语音 API Key 格式无效；请使用豆包语音控制台的凭据。")
    path = Path(data_dir).resolve() / "speech.json"
    if path.is_symlink() or path.with_suffix(".json.tmp").is_symlink():
        raise ValueError("语音配置不可使用符号链接。")
    write_private_json(path, {"provider": PROVIDER, "api_key": key})
    path.chmod(0o600)
    return prepare(data_dir)


def configure_browser(data_dir):
    """One-use loopback form keeps credentials out of shell history/tool output."""
    import html
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import secrets
    import time
    from urllib.parse import parse_qs
    nonce = secrets.token_urlsafe(32)
    route = "/" + nonce
    completed = False

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass

        def reply(self, status, body):
            encoded = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; form-action 'self'; frame-ancestors 'none'")
            self.send_header("Referrer-Policy", "same-origin")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            if self.path != route:
                return self.reply(404, "Not found")
            self.reply(200, '<meta name="viewport" content="width=device-width,initial-scale=1">'
                       '<h1>Wearing 语音配置</h1><p>凭据仅存入这台 Mac 的 Wearing 私有配置。</p>'
                       '<form method="post"><input type="hidden" name="nonce" value="'+html.escape(nonce)+'">'
                       '<label>语音 API Key <input name="key" type="password" autocomplete="off" required></label>'
                       '<button type="submit">保存到 Wearing</button></form>')

        def do_POST(self):
            nonlocal completed
            origin = f"http://127.0.0.1:{self.server.server_port}"
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if self.path != route or self.headers.get("Origin") != origin or not 1 <= length <= 2048:
                    return self.reply(403, "Forbidden")
                data = parse_qs(self.rfile.read(length).decode())
                if not secrets.compare_digest(data.get("nonce", [""])[0], nonce):
                    return self.reply(403, "Forbidden")
                save_key(data_dir, data.get("key", [""])[0].strip())
                completed = True
                self.reply(200, "<h1>凭据已保存</h1><p>此临时配置入口已关闭。接下来验证实际识别。</p>")
            except (ValueError, OSError):
                self.reply(400, "<h1>配置未保存</h1><p>请检查凭据格式后重试。</p>")

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        server.timeout = 1
        server.socket.settimeout(5)
        print(f"http://127.0.0.1:{server.server_port}{route}", flush=True)
        deadline = time.monotonic() + 300
        while not completed and time.monotonic() < deadline:
            server.handle_request()
    if not completed:
        raise ValueError("配置入口已过期，未保存凭据。")
    return prepare(data_dir)
