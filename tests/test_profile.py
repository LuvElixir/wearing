import json
import os

import pytest
import yaml

from wearing.profile import ProfileError, identity_text, prepare_profile


def upstream(tmp_path):
    source = tmp_path / "source"
    (source / "hermes_cli").mkdir(parents=True)
    (source / "hermes_cli/default_soul.py").write_text('DEFAULT_SOUL_MD = "Upstream default identity"\n')
    return source


def test_migration_preserves_credentials_memory_and_user_config(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    source = upstream(tmp_path)
    original = "model:\n  provider: deepseek\n  default: chosen-model\n  api_key: private-test-value\ncustom_field: keep-me\nmemory:\n  user_char_limit: 1900\n  user_profile_enabled: false\n  memory_enabled: false\n"
    (home / "config.yaml").write_text(original)
    (home / "SOUL.md").write_text("Upstream default identity")
    (home / ".env").write_text("SECRET=keep-me")
    (home / "memories").mkdir()
    (home / "memories/USER.md").write_text("用户原有偏好")
    result = prepare_profile(home, source)
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert config["model"] == {"provider": "deepseek", "default": "chosen-model", "api_key": "private-test-value"}
    assert config["memory"]["user_char_limit"] == 1900
    assert config["memory"]["user_profile_enabled"] is False
    assert config["memory"]["memory_enabled"] is False
    assert config["platform_toolsets"]["api_server"] == ["memory", "session_search"]
    assert config["custom_field"] == "keep-me"
    assert (home / ".env").read_text() == "SECRET=keep-me"
    assert (home / "memories/USER.md").read_text() == "用户原有偏好"
    assert (home / "SOUL.md").read_text().strip() == identity_text()
    assert "private-test-value" not in json.dumps(result)
    assert any(p.read_text() == original for p in (home / "wearing-backups").iterdir())
    if os.name != "nt":
        for path in (home / "config.yaml", home / "SOUL.md", *list((home / "wearing-backups").iterdir())):
            assert path.stat().st_mode & 0o077 == 0


def test_reapply_is_idempotent_and_does_not_overwrite_custom_identity(tmp_path):
    source, home = upstream(tmp_path), tmp_path / "home"
    first = prepare_profile(home, source)
    config = (home / "config.yaml").read_bytes()
    backups = list((home / "wearing-backups").glob("*"))
    assert prepare_profile(home, source) == first
    assert config == (home / "config.yaml").read_bytes()
    assert backups == list((home / "wearing-backups").glob("*"))
    (home / "SOUL.md").write_text("用户自定义身份")
    with pytest.raises(ProfileError, match="未覆盖"):
        prepare_profile(home, source)
    assert (home / "SOUL.md").read_text() == "用户自定义身份"
    assert config == (home / "config.yaml").read_bytes()


@pytest.mark.parametrize("contents", ["not-a-map", "model: [broken", "auxiliary: not-a-map"])
def test_invalid_configuration_does_not_partially_migrate(tmp_path, contents):
    source, home = upstream(tmp_path), tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(contents)
    with pytest.raises(ProfileError):
        prepare_profile(home, source)
    assert (home / "config.yaml").read_text() == contents
    assert not (home / "SOUL.md").exists()


def test_profile_refuses_config_symlinks(tmp_path):
    source, home = upstream(tmp_path), tmp_path / "home"
    home.mkdir()
    target = tmp_path / "other-config"
    target.write_text("{}")
    (home / "config.yaml").symlink_to(target)
    with pytest.raises(ProfileError):
        prepare_profile(home, source)
    assert target.read_text() == "{}"
