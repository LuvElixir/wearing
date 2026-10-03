"""Small JSON bridge to the pinned Hermes model configuration implementation.

Runs under its managed Python; credentials arrive over stdin, never argv/logs.
"""

import contextlib
import io
import json
import os
from pathlib import Path
import sys


PROVIDERS = ("deepseek", "openai-api", "anthropic", "openrouter", "minimax-cn")


def provider_rows():
    from hermes_cli.auth import PROVIDER_REGISTRY
    from hermes_cli.models_detect import provider_has_credentials
    rows = []
    for name in PROVIDERS:
        config = PROVIDER_REGISTRY.get(name)
        env_names = config.api_key_env_vars if config else (("OPENROUTER_API_KEY",) if name == "openrouter" else ())
        if env_names:
            rows.append({"id": name, "name": config.name if config else "OpenRouter",
                         "configured": bool(provider_has_credentials(name)), "env": env_names[0]})
    return rows


def inspect():
    from hermes_cli.config import read_raw_config
    from hermes_cli.auth import get_active_provider
    config = read_raw_config()
    model = config.get("model", {})
    provider = model.get("provider") if isinstance(model, dict) else None
    return {"provider": provider or get_active_provider(),
            "model": model.get("default", "") if isinstance(model, dict) else str(model or ""),
            "providers": [{k: v for k, v in row.items() if k != "env"} for row in provider_rows()]}


def configure(body):
    from hermes_cli.config import read_raw_config, save_env_value
    from hermes_cli.web_server_config import _prepare_main_assignment, _apply_main_assignment_sync
    provider, model, key = body["provider"], body["model"].strip(), body.get("key", "")
    rows = {row["id"]: row for row in provider_rows()}
    if provider not in rows or not model or len(model) > 200 or any(ord(c) < 32 for c in model):
        return {"error": "请检查服务商和模型 ID。"}
    if len(key) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        return {"error": "API Key 不能包含空格、换行或非 ASCII 字符。"}
    if not key and not rows[provider]["configured"]:
        return {"error": "这个服务商还没有 API Key，请填写后保存。"}
    home = Path(os.environ["HERMES_HOME"])
    paths = [home / "config.yaml", home / ".env"]
    if any(path.is_symlink() for path in paths):
        return {"error": "模型配置不能使用符号链接。"}
    before = {path: path.read_bytes() if path.exists() else None for path in paths}
    env_name = rows[provider]["env"]
    if key:
        os.environ[env_name] = key
    config = read_raw_config()  # Preserve credential references, never expanded config.
    try:
        prepared = _prepare_main_assignment(config, provider, model, "", "")
    except Exception:
        return {"error": "模型配置校验未通过。请检查模型 ID、API Key 和网络，原设置未改动。"}
    try:
        if key:
            save_env_value(env_name, key)
        _apply_main_assignment_sync(config, provider, model, "", "", prepared=prepared)
        if os.name != "nt":
            for path in paths:
                if path.exists():
                    path.chmod(0o600)
    except Exception:
        for path, value in before.items():
            if value is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(value)
                if os.name != "nt":
                    path.chmod(0o600)
        return {"error": "保存模型设置失败，原设置已恢复。"}
    return inspect()


def main():
    sys.path.insert(0, sys.argv[1])
    # Dependency diagnostics can include provider data; expose only our safe envelope.
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from dotenv import load_dotenv
            load_dotenv(Path(os.environ["HERMES_HOME"]) / ".env", override=True)
            body = json.load(sys.stdin)
            result = configure(body) if body.get("action") == "configure" else inspect()
    except Exception:
        result = {"error": "暂时无法读取模型设置。请检查本地引擎安装。"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
