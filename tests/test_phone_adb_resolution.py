"""Real discovery subprocess coverage for native guests without a local SDK."""
import os
from pathlib import Path

import pytest

from wearing.phone_proxy import device_states, driver_environment


pytestmark = pytest.mark.skipif(os.name=='nt',reason='POSIX execution-guest fixture')


def executable(path,serial):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('#!/bin/sh\n[ "$1" = "devices" ] || exit 2\nprintf "List of devices attached\\n'+serial+'\\tdevice\\n"\n')
    path.chmod(0o755)


async def test_system_adb_is_used_by_discovery_and_both_driver_environments(tmp_path,monkeypatch):
    data=tmp_path/'phone';system=tmp_path/'system-bin/adb'
    executable(system,'127.0.0.1:21212')
    monkeypatch.setenv('PATH',str(system.parent))
    assert not (data/'runtime/android/platform-tools/adb').exists()
    env=driver_environment(data)
    assert env['ADBUTILS_ADB_PATH']==str(system)
    assert env['PATH'].split(os.pathsep)[0]==str(system.parent)
    assert await device_states(data,env)=={'127.0.0.1:21212':'device'}


async def test_reviewed_local_sdk_keeps_precedence(tmp_path,monkeypatch):
    data=tmp_path/'phone';system=tmp_path/'system-bin/adb'
    local=data/'runtime/android/platform-tools/adb'
    executable(system,'wrong-system-phone');executable(local,'selected-local-phone')
    monkeypatch.setenv('PATH',str(system.parent))
    env=driver_environment(data)
    assert env['ADBUTILS_ADB_PATH']==str(local)
    assert await device_states(data,env)=={'selected-local-phone':'device'}


def test_missing_adb_fails_before_mobile_mcp_starts(tmp_path,monkeypatch):
    monkeypatch.setenv('PATH',str(tmp_path/'empty'))
    with pytest.raises(ValueError,match='Android'):
        driver_environment(tmp_path/'phone')
