import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'deploy/on-prem'))
import operations_scope as scope


def valid():
    return {'version': 1, 'guests': {'1411': {'config_sha256': 'a'*64, 'services': ['nginx']}}}


@pytest.mark.parametrize('value', [{}, {'version': 1, 'guests': {}},
    {'version': 1, 'guests': {'../1411': {'config_sha256': 'a'*64, 'services': ['nginx']}}},
    {'version': 1, 'guests': {'1411': {'config_sha256': 'a'*64, 'services': ['--help']}}}])
def test_invalid_or_empty_scope_fails_closed(value):
    with pytest.raises(ValueError):
        scope.validate(value)


def test_scope_permissions_and_symlink_are_rejected(tmp_path):
    source = tmp_path / 'scope.json'
    source.write_text(json.dumps(valid()))
    source.chmod(0o644)
    with pytest.raises(ValueError):
        scope.load_scope(source)
    link = tmp_path / 'link'
    link.symlink_to(source)
    with pytest.raises(OSError):
        scope.load_scope(link)
    source.chmod(0o600)
    info = source.stat()
    with patch.object(scope.os, 'fstat', return_value=type('Stat', (), {'st_mode': info.st_mode, 'st_uid': 0})()):
        assert scope.load_scope(source) == valid()
