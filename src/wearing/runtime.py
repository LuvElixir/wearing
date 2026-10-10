"""Own a project-local Hermes process; use upstream PM for its dependencies."""

import asyncio
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

import httpx
import psutil
import yaml
from filelock import FileLock, Timeout

from .config import private_directory, write_private_json
from .profile import ENGINE_MODE, PROFILE_VERSION, ProfileError, prepare_profile
from . import computer
from .filesystem import PACKAGE, VERSION as FILESYSTEM_VERSION, configuration as filesystem_configuration
from . import android, mobile
from .store import DEFAULT_IDENTITY
from .usage_guard import UsageGuardConfig

HERMES_REVISION = "367441274c48a03d12ee9f8d3d9ccd9bc1585392"
SOURCE_SHA256 = "2edfd027b3c76489dd9e4324ba67237b5883914408f795472da5aac4dcb032f9"
SOURCE_URL = f"https://codeload.github.com/NousResearch/hermes-agent/tar.gz/{HERMES_REVISION}"


class RuntimeError(Exception):
    pass


def unpack_source(archive: Path, destination: Path):
    """Pinned release has only regular files/directories; reject paths or links escaping it."""
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Hermes 下载校验失败，请重新下载；没有执行安装。")
    with tarfile.open(archive) as source:
        members = source.getmembers()
        for member in members:
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination.resolve()) or not (member.isfile() or member.isdir()):
                raise RuntimeError("Hermes 源码包包含不支持的路径。")
        for member in members:
            target = destination / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as incoming, target.open("wb") as out:
                    shutil.copyfileobj(incoming, out)
                target.chmod(member.mode & 0o755)


def fetch_source(root: Path):
    private_directory(root)
    archive = root / "hermes-source.tar.gz"
    if not archive.exists():
        partial = root / "hermes-source.download"
        with urllib.request.urlopen(SOURCE_URL, timeout=60) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)
        partial.replace(archive)
    unpack_source(archive, root)


def stop_owned_process(process: subprocess.Popen):
    """Only signal a Popen handle we own, never a persisted/reused PID."""
    if process.poll() is not None:
        return
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        parent.terminate()
        _, alive = psutil.wait_procs([parent], timeout=8)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        _, rest = psutil.wait_procs(children, timeout=3)
        for item in alive + rest:
            try:
                item.kill()
            except psutil.NoSuchProcess:
                pass
        process.wait(timeout=5)
    except psutil.NoSuchProcess:
        process.wait(timeout=5)


class HermesRuntime:
    def __init__(self, data_dir: Path, identity_id=DEFAULT_IDENTITY, *, local_devices=True):
        if identity_id != DEFAULT_IDENTITY and not re.fullmatch(r"id_[0-9a-f]{32}", identity_id):
            raise RuntimeError("身份编号无效。")
        self.data_dir = data_dir.resolve()
        self.identity_id = identity_id
        self.local_devices = local_devices
        self.usage_config = UsageGuardConfig(os.environ.get("PAJIO_TRIAL_LIMITS") == "1",
                                             self.data_dir, identity_id, not local_devices)
        self.root = self.data_dir / "runtime"
        self.source = self.root / f"hermes-agent-{HERMES_REVISION}"
        self.identity_dir = self.data_dir if identity_id == DEFAULT_IDENTITY else self.data_dir / "identities" / identity_id
        self.home = self.identity_dir / "hermes"
        self.workspace = self.identity_dir / "workspace"
        self.process = None
        self.install_process = None
        self.install_task = None
        self.phase = "idle"
        self.error = None
        self.port = None
        self.lock = asyncio.Lock()
        self.model_state = {"state": "unchecked", "provider": None}
        self.model_checked_at = 0.0
        self.profile = None
        self.files_phase = "idle"
        self.files_error = None
        self.phone_phase, self.phone_error = "idle", None
        self.computer_phase, self.computer_error = "idle", None
        self.computer_checked_at, self.computer_probe = 0.0, None

    @property
    def python(self):
        try:
            recorded = json.loads((self.root / "installed.json").read_text())
            path = Path(recorded["python"])
            if recorded["revision"] == HERMES_REVISION and path.is_relative_to(self.data_dir / "hermes" / "installs"):
                return path
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return self.root / "not-installed"

    def env(self):
        env = dict(os.environ)
        for name in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
            env.pop(name, None)
        env.update(HERMES_HOME=str(self.home), HERMES_RUNTIME_DIR=str(self.root / "tools"),
                   PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
                   PAJIO_TRIAL_LIMITS="1" if self.usage_config.enabled else "0",
                   PAJIO_USAGE_DATA_DIR=str(self.usage_config.data_dir), PAJIO_USAGE_IDENTITY=self.usage_config.identity,
                   PAJIO_AI_CONSENT_REQUIRED='1' if self.usage_config.consent_required else '0',
                   PAJIO_CONFIRMATION_DATA_DIR=str(self.data_dir.resolve()), PAJIO_CONFIRMATION_IDENTITY=self.identity_id,
                   PAJIO_RECALL_DATA_DIR=str(self.data_dir.resolve()), PAJIO_RECALL_IDENTITY=self.identity_id,
                   PAJIO_RECALL_LOCAL='1' if self.local_devices else '0')
        if self.identity_id != DEFAULT_IDENTITY:
            env["WEARING_MODEL_ENV"] = str(self.data_dir / "hermes" / ".env")
        else:
            env.pop("WEARING_MODEL_ENV", None)
        return env

    def status(self):
        alive = self.process is not None and self.process.poll() is None
        if self.phase == "running" and not alive:
            self.phase, self.error = "failed", "本地引擎已退出；可重新启动，原对话仍然保留。"
        model_command = [sys.executable, "-m", "wearing.cli", "engine", "model", "--data-dir", str(self.data_dir)]
        return {"installed": self.python.is_file(),
                "running": alive and self.phase == "running", "phase": self.phase,
                "error": self.error, "revision": HERMES_REVISION[:12],
                "product": {"name": "Pajio", "profile_version": PROFILE_VERSION,
                            "mode": ENGINE_MODE, "applied": self.profile is not None},
                "model": self.model_state,
                "files": {"installed": filesystem_configuration(self.root, self.workspace) is not None,
                          "phase": self.files_phase, "error": self.files_error,
                          "path": str(self.workspace),
                          "active": bool(alive and self.profile and "wearing_files" in self.profile["toolsets"])},
                "phone": {"installed": mobile.installed(self.root) is not None and android.adb_path(self.root) is not None,
                          "native_input_installed": mobile.u2_installed(self.root),
                          "phase": self.phone_phase, "error": self.phone_error,
                          "active": bool(alive and self.profile and "wearing_phone" in self.profile["toolsets"])},
                "computer": {"enrolled": self.identity_id == DEFAULT_IDENTITY and computer.enrolled(self.data_dir), "phase": self.computer_phase,
                             "error": self.computer_error,
                             "active": bool(alive and self.profile and "computer_use" in self.profile["toolsets"])},
                "model_setup_command": subprocess.list2cmdline(model_command) if os.name == "nt" else shlex.join(model_command),
                "url": f"http://127.0.0.1:{self.port}" if alive and self.port else None}

    async def computer_command(self, action, timeout=35):
        if not self.python.is_file():
            raise RuntimeError("请先准备 Pajio 的本地引擎。")
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                str(self.python), str(Path(__file__).with_name("computer_bridge.py")), str(self.source), action,
                cwd=self.source, env=self.env(), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            output, _ = await asyncio.wait_for(process.communicate(), timeout)
            if process.returncode:
                raise RuntimeError("电脑连接器未完成操作，请重新检测权限。")
            return json.loads(output) if action in {"status", "takeover", "resume", "control"} else {}
        except (OSError, ValueError, TimeoutError) as error:
            raise RuntimeError("电脑连接器暂时没有响应，请重新检测；已发出的动作不要重复提交。") from error
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.communicate()

    async def computer_status(self, force=False):
        if not self.python.is_file():
            return {"installed": False, "ready": False, "connector": self.status()["computer"]}
        if force or self.computer_probe is None or time.monotonic() - self.computer_checked_at > 20:
            try:
                self.computer_probe = await self.computer_command("status")
            except RuntimeError as error:
                self.computer_probe = {"installed": None, "ready": False, "error": str(error)}
            self.computer_checked_at = time.monotonic()
        result = dict(self.computer_probe)
        result["control"] = await self.computer_command("control")
        result["connector"] = self.status()["computer"]
        result["resource_id"] = "computer_local"
        return result

    async def install_computer(self):
        async with self.lock:
            self.computer_phase, self.computer_error = "installing", None
            try:
                await self.computer_command("install", timeout=240)
                self.computer_phase = "ready"
                self.computer_checked_at = 0
            except RuntimeError as error:
                self.computer_phase, self.computer_error = "failed", str(error)
                raise

    async def bind_computer(self):
        status = await self.computer_status(force=True)
        if status.get("ready") is not True:
            raise RuntimeError("电脑权限尚未就绪，请先允许 CuaDriver 的辅助功能和屏幕录制，再重新检测。")
        # Never release an existing human takeover as a side effect of enrollment.
        computer.enroll(self.data_dir)

    async def inspect_model(self, force=False):
        if not self.status()["installed"] or (not force and time.monotonic() - self.model_checked_at < 10):
            return self.model_state
        script = (
            "import json, os; from pathlib import Path; from dotenv import load_dotenv, dotenv_values; "
            "shared=dotenv_values(os.environ['WEARING_MODEL_ENV']) if os.environ.get('WEARING_MODEL_ENV') else {}; "
            "os.environ.update({k:v for k,v in shared.items() if k in ('DEEPSEEK_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY','OPENROUTER_API_KEY','MINIMAX_API_KEY') and v}); "
            "from hermes_constants import get_hermes_home; load_dotenv(get_hermes_home()/'.env'); "
            "from hermes_cli.auth import get_active_provider, get_auth_status, PROVIDER_REGISTRY; "
            "from hermes_cli.config import load_config; c=load_config().get('model',{}); "
            "p=(c.get('provider') if isinstance(c,dict) else None) or get_active_provider(); "
            "s=get_auth_status(p); known=p in PROVIDER_REGISTRY; "
            "state='configured' if s.get('logged_in') or s.get('configured') else ('needs_login' if not p or known else 'unchecked'); "
            "print(json.dumps({'state':state,'provider':p}))"
        )
        try:
            result = await asyncio.to_thread(subprocess.run, [str(self.python), "-c", script],
                cwd=self.source, env=self.env(), capture_output=True, text=True, timeout=12, check=True)
            value = json.loads(result.stdout.strip())
            self.model_state = {"state": value["state"], "provider": value["provider"]}
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            self.model_state = {"state": "unchecked", "provider": None}
        self.model_checked_at = time.monotonic()
        return self.model_state

    async def model_settings(self, body=None):
        if not self.python.is_file():
            raise RuntimeError("请先准备 Pajio，再设置模型。")
        async with self.lock:
            try:
                result = await asyncio.to_thread(subprocess.run,
                    [str(self.python), str(Path(__file__).with_name("model_bridge.py")), str(self.source)],
                    input=json.dumps(body or {"action": "inspect"}), cwd=self.workspace,
                    env=self.env(), capture_output=True, text=True, timeout=90, check=True)
                response = json.loads(result.stdout)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                raise RuntimeError("模型设置未完成，请检查网络和本地引擎后重试。") from error
            if response.get("error"):
                raise RuntimeError(response["error"])
            self.model_checked_at = 0
            return response

    async def install_filesystem(self):
        """Let official Hermes PM own Python extras; npm owns the locked MCP package."""
        async with self.lock:
            self.files_phase, self.files_error = "installing", None
            self.prepare_home()
            directory = self.root / "filesystem"
            private_directory(directory)
            try:
                with FileLock(self.root / "install.lock", timeout=0):
                    fd = os.open(directory / "install.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                    with os.fdopen(fd, "a", encoding="utf-8") as log:
                        command = [sys.executable, "-m", "pm.cli", "install", "--extra", "web", "--extra", "messaging", "--extra", "mcp"]
                        self.install_process = subprocess.Popen(command, cwd=self.source, env=self.env(), stdout=log, stderr=log)
                        if await asyncio.to_thread(self.install_process.wait):
                            raise RuntimeError("文件能力的运行环境安装失败，可重试。详情保存在 runtime/filesystem/install.log。")
                        query = "import json,shutil; from pm.environments import project_python; from pm.paths import repo_root; from pm.install import env_for; e=env_for('node','npm',base_env={}); print(json.dumps({'python':str(project_python(repo_root())),'node':shutil.which('node',path=e.get('PATH','')),'npm':shutil.which('npm',path=e.get('PATH',''))}))"
                        result = await asyncio.to_thread(subprocess.run, [sys.executable, "-c", query], cwd=self.source,
                            env=self.env(), capture_output=True, text=True, timeout=20, check=True)
                        paths = json.loads(result.stdout)
                        interpreter = Path(paths["python"])
                        if not interpreter.is_file() or not interpreter.is_relative_to(self.home / "installs"):
                            raise RuntimeError("未找到文件能力所需的运行环境。")
                        write_private_json(self.root / "installed.json", {"revision": HERMES_REVISION, "source_sha256": SOURCE_SHA256, "python": str(interpreter)})
                        if not paths["node"] or not paths["npm"]:
                            raise RuntimeError("未找到 Node.js，请先重新准备 Pajio 运行环境。")
                        # npm's JS entry point is portable; no cmd.exe/shell argument interpolation.
                        npm = Path(paths["npm"]).resolve()
                        if npm.suffix == ".cmd":
                            npm = npm.parent / "node_modules/npm/bin/npm-cli.js"
                        for name in ("package.json", "package-lock.json"):
                            shutil.copyfile(PACKAGE / name, directory / name)
                        env = self.env()
                        env["PATH"] = str(Path(paths["node"]).parent) + os.pathsep + env.get("PATH", "")
                        self.install_process = subprocess.Popen([paths["node"], str(npm), "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=directory, env=env, stdout=log, stderr=log)
                        if await asyncio.to_thread(self.install_process.wait):
                            raise RuntimeError("文件连接器安装失败，可重试。详情保存在 runtime/filesystem/install.log。")
                        write_private_json(directory / "installed.json", {"version": FILESYSTEM_VERSION, "node": paths["node"]})
                if not filesystem_configuration(self.root, self.workspace):
                    raise RuntimeError("文件连接器安装结果不完整，请重试。")
                self.files_phase = "ready"
            except asyncio.CancelledError:
                if self.install_process:
                    await asyncio.to_thread(stop_owned_process, self.install_process)
                self.files_phase = "idle"
                raise
            except Exception as error:
                self.files_phase = "failed"
                self.files_error = str(error) if isinstance(error, RuntimeError) else "文件能力准备失败，详情保存在本机安装日志。"
                raise RuntimeError(self.files_error) from error
            finally:
                self.install_process = None

    async def install_phone(self):
        async with self.lock:
            self.phone_phase, self.phone_error = "installing", None
            directory = self.root / "mobile"
            private_directory(directory)
            try:
                with FileLock(self.root / "install.lock", timeout=0):
                    await asyncio.to_thread(android.install, self.root)
                    query = "import json,shutil; from pm.install import env_for,uv_launcher; e=env_for('node','npm',base_env={}); print(json.dumps({**{n:shutil.which(n,path=e.get('PATH','')) for n in ('node','npm')},'uv':str(uv_launcher('uv')) if uv_launcher('uv') else None}))"
                    result = await asyncio.to_thread(subprocess.run, [sys.executable, "-c", query], cwd=self.source,
                        env=self.env(), capture_output=True, text=True, timeout=20, check=True)
                    paths = json.loads(result.stdout)
                    if not all(paths.values()):
                        raise RuntimeError("请先准备 Pajio 的运行环境，再安装手机连接器。")
                    npm = Path(paths["npm"]).resolve()
                    if npm.suffix == ".cmd":
                        npm = npm.parent / "node_modules/npm/bin/npm-cli.js"
                    for name in ("package.json", "package-lock.json"):
                        shutil.copyfile(mobile.PACKAGE / name, directory / name)
                    env = self.env()
                    env["PATH"] = str(Path(paths["node"]).parent) + os.pathsep + env.get("PATH", "")
                    fd = os.open(directory / "install.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                    with os.fdopen(fd, "a") as log:
                        self.install_process = subprocess.Popen([paths["node"], str(npm), "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=directory, env=env, stdout=log, stderr=log)
                        if await asyncio.to_thread(self.install_process.wait):
                            raise RuntimeError("手机连接器安装未完成，可重试。详情保存在 runtime/mobile/install.log。")
                    write_private_json(directory / "installed.json", {"version": mobile.VERSION, "node": paths["node"]})
                    if not mobile.u2_installed(self.root):
                        commands = []
                        if not mobile.u2_python(self.root).is_file():
                            commands.append([paths["uv"], "venv", "--python", sys.executable, str(self.root / "android-u2")])
                        commands.append([paths["uv"], "pip", "install", "--python", str(mobile.u2_python(self.root)),
                                         "--require-hashes", "-r", str(mobile.U2_PACKAGE / "requirements.txt")])
                        with (directory / "install.log").open("a") as log:
                            for command in commands:
                                self.install_process = subprocess.Popen(command, env=env, stdout=log, stderr=log)
                                if await asyncio.to_thread(self.install_process.wait):
                                    raise RuntimeError("基础连接器已保留，中文输入环境准备失败，可重新准备。")
                        write_private_json(self.root / "android-u2/installed.json", {"version": mobile.U2_VERSION,
                            "requirements_sha256": hashlib.sha256((mobile.U2_PACKAGE / "requirements.txt").read_bytes()).hexdigest()})
                self.phone_phase = "ready"
            except asyncio.CancelledError:
                if self.install_process:
                    await asyncio.to_thread(stop_owned_process, self.install_process)
                self.phone_phase = "idle"
                raise
            except Exception as error:
                self.phone_phase = "failed"
                self.phone_error = str(error) if isinstance(error, RuntimeError) else "手机连接器准备失败，请检查网络后重试。"
                raise RuntimeError(self.phone_error) from error
            finally:
                self.install_process = None

    async def phone_status(self):
        state = await asyncio.to_thread(android.devices, self.root)
        bound = mobile.binding(self.data_dir)
        selected = next((d for d in state["devices"] if bound and d["serial"] == bound["serial"]), None)
        connected = {d["serial"]: d for d in state["devices"]}
        resources = []
        for record in mobile.registry(self.data_dir)["devices"].values():
            live = connected.get(record["serial"], {})
            proof = mobile.read_capabilities(self.data_dir, record["resource_id"])
            resources.append({**record, "online": live.get("state") == "device", "connection_state": live.get("state", "disconnected"), "capabilities": proof})
        return {**state, "connector": self.status()["phone"], "binding": bound,
                "resources": resources,
                "selected_online": bool(selected and selected["state"] == "device")}

    async def bind_phone(self, serial):
        state = await self.phone_status()
        phone = next((d for d in state["devices"] if d["serial"] == serial and d["state"] == "device"), None)
        if not phone:
            raise RuntimeError("这部手机尚未通过 USB 调试授权，请先在手机上允许连接。")
        if not mobile.installed(self.root):
            raise RuntimeError("请先准备手机连接器。")
        data = mobile.registry(self.data_dir)
        rid = mobile.resource_id(serial)
        data["devices"][rid] = {"serial": serial, "resource_id": rid, "name": phone["model"], "platform": "android",
                                "android_version": phone.get("android_version"), "sdk_level": phone.get("sdk_level"), "enabled": True}
        data["selected"] = rid
        write_private_json(self.data_dir / "phone.json", data)

    def pause_phone(self, resource_id=None):
        self.set_phone_enabled(resource_id, False)

    def set_phone_enabled(self, resource_id, enabled):
        data = mobile.registry(self.data_dir)
        rid = resource_id or data["selected"]
        if rid not in data["devices"]:
            raise RuntimeError("没有找到这部已接入的手机。")
        data["devices"][rid]["enabled"] = enabled
        write_private_json(self.data_dir / "phone.json", data)

    def prepare_home(self):
        for path in (self.root, self.home, self.workspace):
            if path.is_symlink():
                raise RuntimeError("身份目录不能使用符号链接。")
            private_directory(path)
        config = self.home / "config.yaml"
        if not config.exists():
            # JSON is valid YAML. Preserve every user/provider edit on later launches.
            write_private_json(config, {
                "terminal": {"backend": "local", "cwd": str(self.workspace)},
                "platform_toolsets": {"api_server": [], "cli": []},
                "gateway": {"api_server": {"max_concurrent_runs": 1}},
            })
        if self.identity_id != DEFAULT_IDENTITY:
            # Share only model selection. Sessions, memory, tools and accounts are
            # never copied from the default identity. Credentials load at runtime.
            try:
                source = yaml.safe_load((self.data_dir / "hermes/config.yaml").read_text()) or {}
                local = yaml.safe_load(config.read_text()) or {}
                local["model"] = source.get("model", {})
                write_private_json(config, local)
            except (OSError, ValueError, yaml.YAMLError) as error:
                raise RuntimeError("共享模型设置暂时无法读取，请先在日常身份中配置模型。") from error

    def connection_key(self):
        """Keep the auth namespace stable so upstream durable runs survive restart."""
        path = (self.root if self.identity_id == DEFAULT_IDENTITY else self.home) / "api-credential.json"
        with FileLock(self.root / "credential.lock"):
            if path.is_symlink():
                raise RuntimeError("执行引擎的连接凭据不能使用符号链接。")
            if path.exists():
                try:
                    key = json.loads(path.read_text(encoding="utf-8"))["key"]
                    if not isinstance(key, str) or len(key) < 32 or not all(c.isascii() and (c.isalnum() or c in "-_") for c in key):
                        raise ValueError()
                    return key
                except (ValueError, KeyError, TypeError, OSError) as error:
                    raise RuntimeError("本地引擎连接凭据无法读取；原记录已保留，请先修复凭据文件。") from error
            key = secrets.token_urlsafe(36)
            write_private_json(path, {"key": key})
            return key

    async def install(self):
        async with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise RuntimeError("先结束当前运行，再安装引擎。")
            self.error, self.phase = None, "downloading"
            self.prepare_home()
            guard = FileLock(self.root / "install.lock")
            try:
                guard.acquire(timeout=0)
            except Timeout:
                self.phase, self.error = "failed", "另一个进程正在安装 Hermes，请等待它结束。"
                return self.status()
            log_path = self.root / "install.log"
            try:
                # A completed marker allows retry without re-extracting an active venv.
                if not (self.source / ".wearing-source-verified").exists():
                    await asyncio.to_thread(fetch_source, self.root)
                    (self.source / ".wearing-source-verified").write_text(SOURCE_SHA256)
                self.phase = "installing"
                # Official PM owns interpreter, hashes, locks and environment activation.
                # The first command prepares required tools; the second only API dependencies.
                commands = [
                    [sys.executable, "-m", "pm.cli", "install", "--tools-only", "--without", "agent-browser", "--without", "cua-driver"],
                    [sys.executable, "-m", "pm.cli", "install", "--extra", "web", "--extra", "messaging", "--extra", "mcp"],
                ]
                fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8") as log:
                    for command in commands:
                        self.install_process = subprocess.Popen(command, cwd=self.source, env=self.env(), stdout=log, stderr=log)
                        code = await asyncio.to_thread(self.install_process.wait)
                        if code:
                            raise RuntimeError("Hermes 安装未完成，可以重试。详细原因保存在本机 runtime/install.log。")
                resolved = await asyncio.to_thread(subprocess.run,
                    [sys.executable, "-c", "from pm.environments import project_python; from pm.paths import repo_root; print(project_python(repo_root()))"],
                    cwd=self.source, env=self.env(), capture_output=True, text=True, timeout=15, check=True)
                interpreter = Path(resolved.stdout.strip())
                if not interpreter.is_file() or not interpreter.is_relative_to(self.home / "installs"):
                    raise RuntimeError("安装命令结束，但尚未找到 Hermes 运行环境。")
                write_private_json(self.root / "installed.json", {"revision": HERMES_REVISION, "source_sha256": SOURCE_SHA256, "python": str(interpreter)})
                self.phase = "ready"
            except asyncio.CancelledError:
                if self.install_process:
                    await asyncio.to_thread(stop_owned_process, self.install_process)
                self.phase = "idle"
                raise
            except Exception as error:
                self.phase = "failed"
                self.error = str(error) if isinstance(error, RuntimeError) else "下载或安装失败，请检查网络后重试。"
            finally:
                self.install_process = None
                guard.release()
        return self.status()

    def begin_install(self):
        if self.lock.locked() or (self.install_task and not self.install_task.done()):
            raise RuntimeError("引擎正在准备，请稍候。")
        self.phase, self.error = "downloading", None
        self.install_task = asyncio.create_task(self.install())
        return self.status()

    async def start(self):
        if self.install_task and not self.install_task.done():
            raise RuntimeError("引擎正在安装，请稍候。")
        async with self.lock:
            if not self.status()["installed"]:
                raise RuntimeError("请先安装本地 Hermes 引擎。")
            if self.process is not None and self.process.poll() is None:
                raise RuntimeError("本地引擎已经启动。")
            self.prepare_home()
            model = await self.inspect_model(force=True)
            if model["state"] == "needs_login":
                raise RuntimeError("请先在模型设置向导中选择服务并完成登录，再启动 Pajio。")
            self.prepare_home()
            try:
                remote = None
                if not self.local_devices:
                    from .cloud.instance import load_instance
                    load_instance(self.data_dir.parent)
                    # Keep discovery connected before the first enrollment. The proxy
                    # checks the private enable flag on every list/call; tools/list_changed
                    # updates Hermes' registry without restarting an active task.
                    remote = {"command": sys.executable, "args": [str(Path(__file__).with_name("remote_proxy.py")),
                              str(self.data_dir.parent), self.identity_id], "timeout": 180,
                              "elicitation": {"enabled": True, "timeout": 90}}
                self.profile = prepare_profile(self.home, self.source, filesystem_configuration(self.root, self.workspace),
                                               mobile.configuration(self.root, self.python) if self.local_devices and self.identity_id == DEFAULT_IDENTITY else None,
                                               self.local_devices and self.identity_id == DEFAULT_IDENTITY and computer.enrolled(self.data_dir), remote,
                                               life={"command": sys.executable,
                                                     "args": [str(Path(__file__).with_name("life_proxy.py")), str(self.data_dir), self.identity_id],
                                                     "timeout": 30})
            except ProfileError as error:
                raise RuntimeError(str(error)) from error
            self.phase, self.error = "starting", None
            # Ask the OS for a free loopback port; an authenticated probe guards reuse/races.
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                self.port = reservation.getsockname()[1]
            key = self.connection_key()
            env = self.env()
            env.update(API_SERVER_ENABLED="true", API_SERVER_HOST="127.0.0.1",
                       API_SERVER_PORT=str(self.port), API_SERVER_KEY=key,
                       HERMES_GATEWAY_NO_SUPERVISE="1")
            try:
                log_dir = self.root if self.identity_id == DEFAULT_IDENTITY else self.home
                fd = os.open(log_dir / "gateway.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8") as log:
                    self.process = subprocess.Popen([str(self.python), str(Path(__file__).with_name("engine_runner.py")), str(self.source)],
                                                    cwd=self.workspace, env=env, stdout=log, stderr=log)
                async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
                    for _ in range(45):
                        if self.process.poll() is not None:
                            break
                        try:
                            response = await client.get(f"http://127.0.0.1:{self.port}/v1/capabilities", headers={"Authorization": f"Bearer {key}"})
                            capabilities = response.json() if response.status_code == 200 else {}
                            if (isinstance(capabilities, dict) and capabilities.get("object") == "hermes.api_server.capabilities"
                                    and capabilities.get("runtime", {}).get("mode") == ENGINE_MODE):
                                self.phase = "running"
                                return {"url": f"http://127.0.0.1:{self.port}", "key": key}
                        except (httpx.HTTPError, ValueError):
                            pass
                        await asyncio.sleep(1)
                raise RuntimeError("本地引擎未就绪，请检查模型设置和已启用的连接器。启动详情在本机 runtime/gateway.log。")
            except BaseException as error:
                if self.process:
                    await asyncio.to_thread(stop_owned_process, self.process)
                self.phase, self.error = "failed", "引擎未就绪，请检查模型设置和连接器后重试。"
                if isinstance(error, OSError):
                    raise RuntimeError("无法启动 Hermes 进程，请检查安装或重新安装。") from error
                raise

    async def stop(self):
        async with self.lock:
            if self.process:
                await asyncio.to_thread(stop_owned_process, self.process)
                self.process = None
            self.phase = "ready" if self.status()["installed"] else "idle"
            return self.status()

    async def close(self):
        if self.install_task and not self.install_task.done():
            self.install_task.cancel()
            try:
                await self.install_task
            except asyncio.CancelledError:
                pass
        await self.stop()

    def model(self):
        if not self.status()["installed"]:
            raise RuntimeError("请先运行 wearing engine install。")
        self.prepare_home()
        # User enters credentials directly into the official local model wizard.
        return subprocess.call([str(self.python), str(self.source / "hermes"), "model"], cwd=self.workspace, env=self.env())
