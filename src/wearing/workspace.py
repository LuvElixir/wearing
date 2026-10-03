"""Download/list surface for the dedicated file space. Agent I/O is owned by MCP."""

import os
from pathlib import Path


class WorkspaceError(Exception):
    pass


def workspace_file(root: Path, name: str):
    relative = Path(name)
    if not name or relative.is_absolute() or ".." in relative.parts or "\\" in name:
        raise WorkspaceError("文件路径不在 Wearing 文件空间内。")
    target = root / relative
    if root.is_symlink() or any(path.is_symlink() for path in (target, *target.parents) if path != root.parent):
        raise WorkspaceError("文件下载不跟随符号链接。")
    try:
        if not target.resolve(strict=True).is_relative_to(root.resolve()) or not target.is_file():
            raise WorkspaceError("文件不存在。")
    except OSError:
        raise WorkspaceError("文件不存在。") from None
    return target


def list_files(root: Path, limit=200):
    if not root.exists():
        return {"files": [], "truncated": False}
    if root.is_symlink():
        raise WorkspaceError("文件空间不能使用符号链接。")
    files = []
    visited = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            visited += 1
            if visited > 2000:
                return {"files": files, "truncated": True}
            try:
                path = workspace_file(root, str((Path(directory) / name).relative_to(root)))
                info = path.stat()
            except (OSError, WorkspaceError):
                continue
            files.append({"path": path.relative_to(root).as_posix(), "size": info.st_size, "modified": info.st_mtime})
            if len(files) >= limit:
                return {"files": files, "truncated": True}
        visited += len(dirs)
        if visited > 2000:
            return {"files": files, "truncated": True}
    return {"files": files, "truncated": False}
