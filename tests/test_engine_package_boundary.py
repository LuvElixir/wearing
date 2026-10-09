"""Wheel installation must not leak another Python ABI into managed Hermes."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

from wearing import engine_runner


def test_managed_runner_loads_only_host_package(tmp_path):
    foreign = tmp_path / 'host-site-packages'
    package = foreign / 'wearing'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('')
    (package / 'bridge_marker.py').write_text("value = 'host bridge'\n")
    (foreign / 'runtime_dependency.py').write_text("raise RuntimeError('foreign ABI loaded')\n")
    managed = tmp_path / 'managed-site-packages'
    managed.mkdir()
    (managed / 'runtime_dependency.py').write_text("value = 'managed dependency'\n")
    runner = package / 'engine_runner.py'
    shutil.copyfile(Path(engine_runner.__file__), runner)
    script = '''import importlib.util, json, sys
sys.path.insert(0, sys.argv[2])
spec = importlib.util.spec_from_file_location('runner', sys.argv[1])
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner.load_host_package()
from wearing import bridge_marker
import runtime_dependency
print(json.dumps([bridge_marker.value, runtime_dependency.value, sys.path]))
'''
    result = subprocess.run([sys.executable, '-I', '-c', script, str(runner), str(managed)],
                            check=True, capture_output=True, text=True)
    bridge, dependency, paths = json.loads(result.stdout)
    assert bridge == 'host bridge'
    assert dependency == 'managed dependency'
    assert str(foreign) not in paths
