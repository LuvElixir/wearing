"""Bridge boot policy survives editable dotenv without a provider/network call."""
import io
import os
import sys
from types import SimpleNamespace

import pytest

from wearing import capture_bridge, engine_runner, usage_guard
from wearing.usage import UsageError


@pytest.mark.parametrize('bridge', [capture_bridge, engine_runner])
@pytest.mark.parametrize('enabled', [True, False])
@pytest.mark.parametrize('consent_required', [True, False])
def test_bridge_captures_authority_before_provider_dotenv(tmp_path, monkeypatch, bridge, enabled, consent_required):
    root, home = tmp_path / 'tenant-data', tmp_path / 'hermes'
    root.mkdir(); home.mkdir()
    identity = 'id_' + 'a' * 32
    initial = dict(PAJIO_TRIAL_LIMITS='1' if enabled else '0', PAJIO_USAGE_DATA_DIR=str(root),
                   PAJIO_USAGE_IDENTITY=identity, HERMES_HOME=str(home),
                   PAJIO_AI_CONSENT_REQUIRED='1' if consent_required else '0',
                   PAJIO_RECALL_DATA_DIR=str(root), PAJIO_RECALL_IDENTITY=identity, PAJIO_RECALL_LOCAL='0')
    for key, value in initial.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv('WEARING_MODEL_ENV', raising=False)
    monkeypatch.setattr(sys, 'argv', ['bridge', str(tmp_path / 'pinned-source')])
    monkeypatch.setattr(sys, 'path', list(sys.path))
    captured = []

    def provider_dotenv(path, *, override):
        assert path == home / '.env' and override
        monkeypatch.setenv('PAJIO_TRIAL_LIMITS', '0' if enabled else '1')
        monkeypatch.setenv('PAJIO_USAGE_DATA_DIR', str(tmp_path / 'foreign'))
        monkeypatch.setenv('PAJIO_USAGE_IDENTITY', 'foreign')
        monkeypatch.setenv('PAJIO_AI_CONSENT_REQUIRED', '0' if consent_required else '1')

    def install(config):
        assert os.environ['PAJIO_USAGE_IDENTITY'] == 'foreign'
        captured.append(config)
        return config.enabled

    monkeypatch.setitem(sys.modules, 'dotenv', SimpleNamespace(load_dotenv=provider_dotenv, dotenv_values=lambda _: {}))
    monkeypatch.setattr(usage_guard, 'install_usage_guard', install)
    if bridge is engine_runner:
        async def serve():
            assert len(captured) == 1
        monkeypatch.setattr(bridge, 'serve', serve)
        monkeypatch.setattr('wearing.confirmation_guard.install_confirmation_guard', lambda: True)
        monkeypatch.setattr('wearing.session_recall_guard.install_session_recall_guard', lambda _: True)
    else:
        monkeypatch.setattr(sys, 'stdin', io.StringIO('{}'))
        monkeypatch.setattr(bridge, 'organize', lambda _: {'output': 'synthetic'})
    bridge.main()
    assert captured == [usage_guard.UsageGuardConfig(enabled, root, identity, consent_required)]


@pytest.mark.parametrize('change', [{'PAJIO_USAGE_DATA_DIR': ''}, {'PAJIO_USAGE_DATA_DIR': 'relative'},
                                  {'PAJIO_USAGE_IDENTITY': ''}, {'PAJIO_USAGE_IDENTITY': '../foreign'}])
def test_enabled_policy_requires_host_root_and_identity_before_install(tmp_path, monkeypatch, change):
    for key, value in dict(PAJIO_TRIAL_LIMITS='1', PAJIO_USAGE_DATA_DIR=str(tmp_path),
                           PAJIO_USAGE_IDENTITY='daily').items():
        monkeypatch.setenv(key, value)
    for key, value in change.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(UsageError) as error:
        usage_guard.UsageGuardConfig.from_env()
    assert error.value.code == 'quota_unavailable'
