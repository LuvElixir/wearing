"""Durable local intent: scheduler restarts never override an explicit stop."""
import json
from pathlib import Path
from filelock import FileLock

from ...cloud.instance import read_private
from ...config import write_private_json


def desired(root):
    path = Path(root) / 'service-desired.json'
    if not path.exists():
        return 'running'  # Existing foreground/first-trial connector compatibility.
    value = json.loads(read_private(path))
    if value.get('mode') not in ('running', 'stopped'):
        raise ValueError('invalid_connector_service_intent')
    return value['mode']


def set_desired(root, mode):
    if mode not in ('running', 'stopped'):
        raise ValueError('invalid_connector_service_intent')
    root = Path(root)
    with FileLock(root / 'service-control.lock', timeout=2):
        write_private_json(root / 'service-desired.json', {'mode':mode})
