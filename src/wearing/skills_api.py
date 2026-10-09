"""Identity-scoped skill management for the native client.

The catalog is the already-pinned runtime source. Installing a skill copies its
package; it never runs package scripts, installs dependencies or fetches URLs.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sys
import tempfile
import uuid
from typing import Literal

from fastapi import HTTPException, Request
from filelock import FileLock, Timeout
from pydantic import BaseModel, ConfigDict, Field
import yaml


MAX_TEXT = 256 * 1024
MAX_PACKAGE = 20 * 1024 * 1024
EXCLUDED = {"references", "templates", "assets", "scripts", "tests", "node_modules", "__pycache__", "venv"}
ESSENTIAL = {"hermes-agent"}


def fail(message, status=422):
    raise HTTPException(status_code=status, detail=message)


def _safe(root: Path, relative: str) -> Path:
    if not relative or len(relative) > 512 or "\\" in relative or any(ord(c) < 32 for c in relative):
        fail("技能路径无效。")
    parts = relative.split("/")
    if any(not part or part.startswith(".") for part in parts):
        fail("技能路径无效。")
    _directory(root)
    target = root.joinpath(*parts)
    if any(p.is_symlink() for p in (target, *target.parents) if p == root or root in p.parents):
        fail("技能目录包含链接，未读取或修改。")
    if not target.resolve().is_relative_to(root.resolve()):
        fail("技能路径无效。")
    return target


def _directory(path):
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        fail("技能目录包含链接，未读取或修改。")


def _text(path):
    if not path.is_file() or path.stat().st_size > MAX_TEXT:
        fail("技能说明不存在或过大，请刷新目录。", 404)
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        fail("这份技能说明暂时无法读取。")


def _metadata(text):
    if not text.startswith("---\n"):
        return {}
    header, found, _ = text[4:32768].partition("\n---")
    if not found:
        return {}
    try:
        value = yaml.safe_load(header)
        return value if isinstance(value, dict) else {}
    except yaml.YAMLError:
        return {}


def _names(value):
    if isinstance(value, str):
        value = [value]
    return {str(item).strip() for item in value if isinstance(item, str) and item.strip()} if isinstance(value, list) else set()


class SkillLibrary:
    def __init__(self, runtime, *, store=None, identity=None):
        self.home = Path(runtime.home)
        self.installed = self.home / "skills"
        self.catalog = Path(runtime.source) / "skills"
        self.config_path = self.home / "config.yaml"
        self.store, self.identity = store, identity

    def _package_revision(self, path):
        """Bind removal to the whole package, including scripts and dotfiles."""
        _directory(path)
        digest, total, count, read_bytes = hashlib.sha256(), 0, 0, 0
        for current, dirs, files in os.walk(path, followlinks=False):
            for name in sorted(dirs + files):
                target = Path(current) / name
                if target.is_symlink():
                    fail("技能包包含链接，未移除。")
                relative = target.relative_to(path).as_posix()
                if target.is_dir():
                    digest.update(json.dumps(["directory", relative]).encode())
                    continue
                if not target.is_file():
                    fail("技能包包含特殊文件，未移除。")
                if name == "SKILL.md" and target.parent != path:
                    fail("目录内还包含其他技能，请分别整理后再移除。", 409)
                count += 1
                total += target.stat().st_size
                if total > MAX_PACKAGE or count > 1000:
                    fail("技能包过大，未移除。", 413)
                mode, content = target.stat().st_mode & 0o777, hashlib.sha256()
                with target.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(65536), b""):
                        read_bytes += len(chunk)
                        if read_bytes > MAX_PACKAGE:
                            fail("技能包在读取时变大，未移除。", 413)
                        content.update(chunk)
                digest.update(json.dumps(["file", relative, mode, content.hexdigest()]).encode())
            dirs.sort()
        return digest.hexdigest()

    def removal_preview(self, skill_id):
        item = self.detail("installed", skill_id)
        path = _safe(self.installed, skill_id)
        if item["essential"] or path.name in ESSENTIAL:
            fail("这是运行必需的技能，不能移除。")
        if any((parent / "SKILL.md").exists() for parent in path.parents if parent != self.installed and self.installed in parent.parents):
            fail("这项技能位于另一技能包内，请先整理目录。", 409)
        installed, catalog = self.installed.resolve(), self.catalog.resolve()
        if installed.is_relative_to(catalog) or catalog.is_relative_to(installed):
            fail("内建技能源目录不能移除。")
        config, revision = self._config()
        refs = _names(config.get("skills", {}).get("auto_load"))
        if refs & {item["name"], skill_id, path.name, str(path), str(path / "SKILL.md"), skill_id + "/SKILL.md"}:
            fail("这项技能被自动加载设置引用，请先解除引用。", 423)
        return {"id": skill_id, "name": item["name"], "revision": revision,
                "package_revision": self._package_revision(path), "operation_id": uuid.uuid4().hex}

    def remove(self, skill_id, revision, package_revision, operation_id):
        if not all(isinstance(value, str) and re.fullmatch(pattern, value) for value, pattern in (
                (revision, r"[a-f0-9]{64}"), (package_revision, r"[a-f0-9]{64}"), (operation_id, r"[a-f0-9]{32}"))):
            fail("技能移除凭据无效。")
        if not self.store or not self.identity:
            fail("暂时无法确认任务状态，未移除技能。", 503)
        self.store.identity(self.identity)
        try:
            with self._lock(), self.store.connection() as db:
                # Task admission writes the same Store. Holding this transaction
                # closes the check/start gap while the package is moved.
                db.execute("BEGIN IMMEDIATE")
                from .service import ACTIVE
                marks = ",".join("?" for _ in ACTIVE)
                if db.execute(f"SELECT 1 FROM tasks WHERE identity_id=? AND status IN ({marks}) LIMIT 1", (self.identity, *ACTIVE)).fetchone():
                    fail("当前身份有任务正在执行或等待处理，结束后再移除技能。", 423)
                if any(item["identity_id"] == self.identity for item in self.store._queued_messages(db)):
                    fail("当前身份还有排队任务，处理后再移除技能。", 423)
                source = _safe(self.installed, skill_id)
                recovery = self.home / ".pajio-skill-recovery" / operation_id
                _directory(recovery)
                manifest, package = recovery / "receipt.json", recovery / "package"
                if manifest.is_symlink() or package.is_symlink():
                    fail("技能恢复目录包含链接，未移除。")
                if package.exists() and not manifest.exists():
                    fail("技能恢复位置已有文件，未覆盖。", 409)
                expected = {"id": skill_id, "revision": revision, "package_revision": package_revision,
                            "operation_id": operation_id, "identity_id": self.identity}
                if manifest.exists():
                    if manifest.is_symlink() or _text(manifest) != json.dumps(expected, ensure_ascii=False, sort_keys=True):
                        fail("移除凭据不一致，请刷新目录。", 409)
                    if package.exists():
                        _directory(package)
                        if source.exists():
                            fail("技能已重新安装，请重新查看后移除。", 409)
                        return {"removed": True, "id": skill_id, "operation_id": operation_id,
                                "recovery_id": operation_id, "snapshot": self.list()}
                preview = self.removal_preview(skill_id)
                if preview["revision"] != revision or preview["package_revision"] != package_revision:
                    fail("技能内容或设置刚刚有变化，请重新查看后移除。", 409)
                recovery.mkdir(parents=True, exist_ok=True, mode=0o700)
                if not manifest.exists():
                    with manifest.open("x", encoding="utf-8") as output:
                        output.write(json.dumps(expected, ensure_ascii=False, sort_keys=True))
                        output.flush()
                        os.fsync(output.fileno())
                    manifest.chmod(0o600)
                # No recursive delete and no mutation of catalog/config. A crash
                # after rename is recovered by the manifest + package above.
                source.rename(package)
                # Runtime discovery caches the root/category directory mtimes.
                # Bump the root even when a deeply nested package was removed.
                os.utime(self.installed, None)
                return {"removed": True, "id": skill_id, "operation_id": operation_id,
                        "recovery_id": operation_id, "snapshot": self.list()}
        except Timeout:
            fail("技能设置正在保存，请稍后重试。", 409)

    def _config(self):
        _directory(self.home)
        if self.config_path.is_symlink():
            fail("技能配置包含链接，未修改。")
        if self.config_path.exists() and self.config_path.stat().st_size > 1024 * 1024:
            fail("技能配置过大，未修改。")
        original = self.config_path.read_text() if self.config_path.exists() else "{}"
        try:
            config = yaml.safe_load(original) or {}
        except yaml.YAMLError:
            fail("技能配置无法读取，原配置已保留。")
        if not isinstance(config, dict) or not isinstance(config.get("skills", {}), dict):
            fail("技能配置格式不正确，原配置已保留。")
        return config, hashlib.sha256(original.encode()).hexdigest()

    def _scan(self, root, config):
        _directory(root)
        result = []
        skills = config.get("skills", {})
        platform_disabled = skills.get("platform_disabled") or {}
        if not isinstance(platform_disabled, dict):
            fail("技能平台设置格式不正确，原配置已保留。")
        disabled = (_names(skills.get("disabled")) | _names(platform_disabled.get("api_server"))) - ESSENTIAL
        for current, dirs, files in os.walk(root, followlinks=False):
            current = Path(current)
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in EXCLUDED and not (current / d).is_symlink())
            if "SKILL.md" not in files or (current / "SKILL.md").is_symlink():
                continue
            if len(result) >= 1000:
                fail("技能目录过大，请先整理目录。")
            text = _text(current / "SKILL.md")
            data = _metadata(text)
            name = str(data.get("name") or current.name)[:200]
            platforms = _names(data.get("platforms"))
            aliases = {"macos": "darwin", "linux": "linux", "windows": "win32"}
            compatible = not platforms or any(sys.platform.startswith(aliases.get(item, item)) for item in platforms)
            required = _names(data.get("required_environment_variables"))
            result.append({"id": current.relative_to(root).as_posix(), "name": name,
                           "description": str(data.get("description") or "打开查看技能说明")[:1000],
                           "category": current.relative_to(root).parts[0] if current.parent != root else "其他",
                           "enabled": name not in disabled, "essential": name in ESSENTIAL,
                           "compatible": compatible, "requirements": sorted(required),
                           "revision": hashlib.sha256(text.encode()).hexdigest()})
        return result

    def list(self):
        config, revision = self._config()
        installed, catalog = self._scan(self.installed, config), self._scan(self.catalog, config)
        names = {item["name"] for item in installed}
        return {"revision": revision, "installed": installed,
                "catalog": [{**item, "installed": item["name"] in names} for item in catalog]}

    def detail(self, source, skill_id):
        root = self.installed if source == "installed" else self.catalog
        path = _safe(root, skill_id)
        text = _text(_safe(root, skill_id + "/SKILL.md"))
        config, _ = self._config()
        item = next((item for item in self._scan(root, config) if item["id"] == skill_id), None)
        if item is None or not path.is_dir():
            fail("这个技能已移动，请刷新目录。", 404)
        return {**item, "content": text, "source": source}

    def _lock(self):
        _directory(self.home)
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = self.home / ".pajio-skills.lock"
        if lock_path.is_symlink():
            fail("技能配置锁无效，未修改。")
        return FileLock(lock_path, timeout=5)

    def enabled(self, skill_id, enabled, revision):
        try:
            with self._lock():
                config, current = self._config()
                if current != revision:
                    fail("技能设置刚刚有变化，请刷新后再试。", 409)
                item = self.detail("installed", skill_id)
                if item["essential"] and not enabled:
                    fail("这是运行必需的技能，需保持启用。")
                skills = config.setdefault("skills", {})
                disabled = _names(skills.get("disabled")) - ESSENTIAL
                if enabled:
                    disabled.discard(item["name"])
                    # Global and api_server disables are unioned by the runtime.
                    platforms = skills.get("platform_disabled") or {}
                    if isinstance(platforms, dict) and "api_server" in platforms:
                        platforms["api_server"] = sorted(_names(platforms["api_server"]) - {item["name"]})
                else:
                    disabled.add(item["name"])
                skills["disabled"] = sorted(disabled)
                if self._config()[1] != revision:
                    fail("技能设置刚刚有变化，请刷新后再试。", 409)
                fd, temp = tempfile.mkstemp(prefix=".skills-", dir=self.home)
                try:
                    with os.fdopen(fd, "w") as output:
                        yaml.safe_dump(config, output, allow_unicode=True, sort_keys=False)
                    os.replace(temp, self.config_path)
                finally:
                    Path(temp).unlink(missing_ok=True)
                return self.list()
        except Timeout:
            fail("技能设置正在保存，请稍后重试。", 409)

    def install(self, skill_id, revision):
        try:
            with self._lock():
                item = self.detail("catalog", skill_id)
                if item["revision"] != revision:
                    fail("技能说明已有更新，请重新查看后安装。", 409)
                if not item["compatible"]:
                    fail("这项技能不支持当前执行设备。")
                listing = self.list()
                if any(other["name"] == item["name"] for other in listing["installed"]):
                    return listing
                source, destination = _safe(self.catalog, skill_id), _safe(self.installed, skill_id)
                if destination.exists():
                    fail("技能安装位置已有文件，未覆盖。", 409)
                total, files = 0, []
                for current, dirs, names in os.walk(source, followlinks=False):
                    for name in dirs + names:
                        path = Path(current) / name
                        if path.is_symlink():
                            fail("这个技能包包含链接，未安装。")
                    dirs[:] = [name for name in dirs if not name.startswith(".") and name not in {"node_modules", "__pycache__", "venv"}]
                    for name in names:
                        path = Path(current) / name
                        if name.startswith("."):
                            continue
                        if not path.is_file():
                            fail("这个技能包包含特殊文件，未安装。")
                        total += path.stat().st_size
                        files.append(path)
                        if total > MAX_PACKAGE or len(files) > 1000:
                            fail("这个技能包过大，未安装。", 413)
                self.installed.mkdir(parents=True, exist_ok=True, mode=0o700)
                temporary = Path(tempfile.mkdtemp(prefix=".install-", dir=self.installed))
                try:
                    copied = 0
                    for path in files:
                        target = temporary / path.relative_to(source)
                        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                        # Recheck links after enumeration; copy only regular files.
                        _safe(self.catalog, path.relative_to(self.catalog).as_posix())
                        with path.open("rb") as input_file, target.open("xb") as output:
                            while chunk := input_file.read(min(65536, MAX_PACKAGE - copied + 1)):
                                copied += len(chunk)
                                if copied > MAX_PACKAGE:
                                    fail("这个技能包在安装时变大，未安装。", 413)
                                output.write(chunk)
                        target.chmod(0o600)
                    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    temporary.rename(destination)
                finally:
                    if temporary.exists():
                        shutil.rmtree(temporary)
                return self.list()
        except Timeout:
            fail("另一项技能正在安装，请稍后重试。", 409)


class EnableSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=512)
    enabled: bool
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class InstallSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=512)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class RemoveSkill(InstallSkill):
    package_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    operation_id: str = Field(pattern=r"^[a-f0-9]{32}$")


def install_skill_routes(app, runtime_for):
    """Register behind the application's existing identity/token/origin middleware."""
    def library(request):
        return SkillLibrary(runtime_for(request.state.identity_id), store=getattr(app.state, "store", None), identity=request.state.identity_id)

    @app.get("/api/skills")
    def skills(request: Request):
        return library(request).list()

    @app.get("/api/skills/detail")
    def detail(request: Request, id: str, source: Literal["installed", "catalog"] = "installed"):
        return library(request).detail(source, id)

    @app.patch("/api/skills/enabled")
    def enabled(request: Request, body: EnableSkill):
        return library(request).enabled(body.id, body.enabled, body.revision)

    @app.post("/api/skills/install")
    def install(request: Request, body: InstallSkill):
        return library(request).install(body.id, body.revision)

    @app.get("/api/skills/removal")
    def removal(request: Request, id: str):
        return library(request).removal_preview(id)

    @app.post("/api/skills/remove")
    def remove(request: Request, body: RemoveSkill):
        return library(request).remove(body.id, body.revision, body.package_revision, body.operation_id)
