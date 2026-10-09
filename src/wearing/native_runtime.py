"""A connector-only runtime: pinned driver sources, without a model engine.

Operators install this private marker on isolated execution hosts. Normal local
installations retain their existing managed Hermes runtime.
"""
import json
from pathlib import Path
import sys

from .cloud.instance import read_private
from .runtime import HERMES_REVISION, SOURCE_SHA256


def driver_runtime(runtime):
    marker = runtime.root / 'native-driver.json'
    if not marker.exists():
        return runtime.python, runtime.source
    value = json.loads(read_private(marker))
    if (not sys.platform.startswith('linux') or value.get('version') != 1
            or value.get('revision') != HERMES_REVISION
            or value.get('source_sha256') != SOURCE_SHA256):
        raise ValueError('native_driver_not_verified')
    python, source = Path(value['python']), Path(value['source'])
    if (not python.is_absolute() or not python.is_file() or not source.is_absolute()
            or not source.is_dir() or source.name != 'hermes-agent-' + HERMES_REVISION
            or (source / '.wearing-source-verified').read_text().strip() != SOURCE_SHA256):
        raise ValueError('native_driver_not_verified')
    return python, source
