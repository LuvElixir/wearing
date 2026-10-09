#!/usr/bin/env python3
"""Disposable chat-import UI fixture. Synthetic records only; localhost:8892.

Reuses the bounded UI fixture with no model, real device or external transport.
The imported text is also synthetic. Never point this script at an existing DB.
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

import uvicorn
from fastapi.responses import FileResponse
from wearing.chat_imports import ChatImports
from wearing.chat_imports_api import install_chat_import_routes
from wearing.device_access_api import install_device_access_routes

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / 'pajio-core-20261007'
sys.path.insert(0, str(BASE))
spec = importlib.util.spec_from_file_location('pajio_core_qa_fixture', BASE / 'qa-server.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def build_app(root):
    app, manifest = base.build_app(root)
    store = app.state.store
    # Disable only this new fixture's seeded active jobs so deletion can be tried.
    with store.connection() as db:
        db.execute("UPDATE tasks SET status='cancelled' WHERE status IN ('running','starting','waiting_confirmation','stopping','unknown')")
    app.state.service = SimpleNamespace(lock=asyncio.Lock())
    fallback = app.router.routes.pop()
    assert fallback.path == '/api/{path:path}'
    install_chat_import_routes(app, ChatImports(store))
    install_device_access_routes(app, lambda: None, local_devices=True)

    @app.get('/qa-fixture/chat.zip')
    def sample_archive():
        return FileResponse(HERE / 'fixtures/合成选定聊天.zip', filename='合成选定聊天.zip', media_type='application/zip')

    app.router.routes.append(fallback)
    manifest.update(endpoint='http://127.0.0.1:8892/', pid=os.getpid(),
                    limitations=manifest['limitations'] + ['Private remote login remains unavailable'])
    (root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return app, manifest


if __name__ == '__main__':
    root = Path(tempfile.mkdtemp(prefix='pajio-context-qa-', dir='/tmp')).resolve()
    app, manifest = build_app(root)
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    uvicorn.run(app, host='127.0.0.1', port=8892, log_level='warning', access_log=False)
