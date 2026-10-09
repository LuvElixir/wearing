import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from wearing.native_runtime import driver_runtime
from wearing.runtime import HERMES_REVISION,SOURCE_SHA256
from wearing.config import write_private_json


def test_native_driver_is_not_a_model_runtime(tmp_path,monkeypatch):
    monkeypatch.setattr('wearing.native_runtime.sys.platform','linux')
    root=tmp_path/'runtime';root.mkdir()
    source=tmp_path/('hermes-agent-'+HERMES_REVISION);source.mkdir()
    (source/'.wearing-source-verified').write_text(SOURCE_SHA256)
    interpreter=tmp_path/'python';interpreter.touch()
    runtime=SimpleNamespace(root=root,python=root/'not-installed',source=root/'absent')
    marker={'version':1,'revision':HERMES_REVISION,'source_sha256':SOURCE_SHA256,
            'python':str(interpreter),'source':str(source)}
    write_private_json(root/'native-driver.json',marker)
    assert driver_runtime(runtime)==(interpreter,source)
    assert not (root/'installed.json').exists()
    marker['source_sha256']='wrong';write_private_json(root/'native-driver.json',marker)
    with pytest.raises(ValueError):driver_runtime(runtime)


def test_normal_managed_runtime_unchanged(tmp_path):
    runtime=SimpleNamespace(root=tmp_path,python=tmp_path/'managed',source=tmp_path/'source')
    assert driver_runtime(runtime)==(runtime.python,runtime.source)


def test_native_marker_symlink_rejected(tmp_path):
    runtime=SimpleNamespace(root=tmp_path,python=tmp_path/'managed',source=tmp_path/'source')
    (tmp_path/'target').write_text('{}');(tmp_path/'native-driver.json').symlink_to(tmp_path/'target')
    with pytest.raises(ValueError):driver_runtime(runtime)
