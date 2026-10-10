import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import pytest

spec = importlib.util.spec_from_file_location('theme_flag', Path(__file__).with_name('prepare-flag.py'))
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


def fixture(tmp_path):
    root = tmp_path / 'theme'; root.mkdir()
    for name in module.THEME_FILES:
        path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(name.encode()); path.chmod(0o644)
    return root


def plan(theme):
    return dict(version=1, realm='pajio', realm_id='synthetic', theme_sha256=theme,
        before=dict(login_theme=None, default_locale='en', internationalization=False, supported_locales=['ja']),
        after=dict(login_theme='pajio', default_locale='zh-CN', internationalization=True, supported_locales=['en','ja','zh-CN']),
        guards=dict(profile_sha256='a'*64,verify_email=False,reset_password=False,standard_flow=True,
                    security_headers_sha256='b'*64,required_actions_sha256='c'*64))


def test_canonical_theme_hash_and_modified_asset(tmp_path):
    root = fixture(tmp_path)
    expected = hashlib.sha256(module.canonical({name:hashlib.sha256(name.encode()).hexdigest() for name in module.THEME_FILES})).hexdigest()
    assert module.theme_hash(root) == expected
    (root/'theme.properties').write_bytes(b'changed')
    assert module.theme_hash(root) != expected


@pytest.mark.parametrize('change', ['extra','missing','symlink','hardlink','writable'])
def test_theme_boundary(tmp_path, change):
    root=fixture(tmp_path); target=root/'theme.properties'
    if change=='extra': (root/'unexpected.ftl').write_text('x')
    if change=='missing': target.unlink()
    if change=='symlink': target.unlink();target.symlink_to(root/'resources/js/pajio.js')
    if change=='hardlink': target.unlink();target.hardlink_to(root/'resources/js/pajio.js')
    if change=='writable': target.chmod(0o666)
    with pytest.raises(ValueError):module.theme_hash(root)


def test_apply_exact_plan_keeps_extra_locale():
    value=plan('a'*64); result=module.flag_for('a'*64,value)
    assert result==dict(mode='apply-v1',realm='pajio',theme_sha256='a'*64,plan_sha256=hashlib.sha256(module.canonical(value)).hexdigest())
    value['after']['supported_locales'].remove('ja')
    with pytest.raises(ValueError):module.flag_for('a'*64,value)


def test_changed_theme_or_scope_cannot_apply():
    with pytest.raises(ValueError):module.flag_for('b'*64,plan('a'*64))
    value=plan('a'*64);value['unexpected']=True
    with pytest.raises(ValueError):module.flag_for('a'*64,value)


def test_observed_plan_private(tmp_path):
    p=tmp_path/'plan.json';p.write_text('{}');p.chmod(0o644)
    with pytest.raises(ValueError):module.read(p,private=True)
    p.chmod(0o600);assert json.loads(module.read(p,private=True))=={}
