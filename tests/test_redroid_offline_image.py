"""Offline image provenance and exact immutable Docker identity; no Docker calls."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'deploy/on-prem' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def verifier():
    return module('verify-redroid-image')


def archive_fixture(tmp_path, m, *, extra=False, wrong_tag=False, wrong_layer=False):
    layer = b'synthetic public layer\n'
    config = {'architecture': 'amd64', 'os': 'linux', 'rootfs': {'type': 'layers', 'diff_ids': ['sha256:' + 'a' * 64]},
              'config': {'Entrypoint': ['/init'], 'Env': ['PUBLIC=fixture']}}
    raw_config = json.dumps(config).encode()
    m.CONFIG_ID = 'sha256:' + m.sha(raw_config)
    layer_hash = m.sha(layer)
    official = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                'config': {'digest': m.CONFIG_ID, 'size': len(raw_config)},
                'layers': [{'digest': 'sha256:' + layer_hash, 'size': len(layer)}]}
    raw_official = json.dumps(official).encode()
    m.OFFICIAL_SHA256 = m.sha(raw_official)
    (tmp_path / 'redroid-oci-manifest.json').write_bytes(raw_official)
    config_name, layer_name = m.CONFIG_ID[7:] + '.json', layer_hash + '/layer.tar'
    manifest = [{'Config': config_name, 'RepoTags': ['foreign:tag' if wrong_tag else m.TAG], 'Layers': [layer_name]}]
    entries = [(config_name, raw_config), (layer_name, b'x' * len(layer) if wrong_layer else layer),
               ('manifest.json', json.dumps(manifest).encode())]
    if extra:
        entries.append(('extra-image.json', b'{}'))
    with tarfile.open(tmp_path / 'redroid-amd64.tar', 'w') as output:
        for name, raw in entries:
            entry = tarfile.TarInfo(name)
            entry.size = len(raw)
            output.addfile(entry, io.BytesIO(raw))
    raw = (tmp_path / 'redroid-amd64.tar').read_bytes()
    m.ARCHIVE_BYTES, m.ARCHIVE_SHA256 = len(raw), m.sha(raw)
    return official, config


def test_archive_official_config_and_layers_are_verified_without_extracting(tmp_path, verifier):
    official, config = archive_fixture(tmp_path, verifier)
    assert verifier.verify_archive(tmp_path) == (official, config)
    assert {v.name for v in tmp_path.iterdir()} == {'redroid-amd64.tar', 'redroid-oci-manifest.json'}


@pytest.mark.parametrize('bad,code', [('extra', 'archive_scope'), ('wrong_tag', 'archive_manifest'), ('wrong_layer', 'layer_changed')])
def test_unrelated_image_tag_entry_or_layer_rejected(tmp_path, verifier, bad, code):
    archive_fixture(tmp_path, verifier, **{bad: True})
    with pytest.raises(ValueError, match=code):
        verifier.verify_archive(tmp_path)


def test_corrupt_archive_cannot_trigger_docker_load(tmp_path, verifier):
    archive_fixture(tmp_path, verifier)
    path = tmp_path / 'redroid-amd64.tar'
    raw = bytearray(path.read_bytes());raw[-1] ^= 1;path.write_bytes(raw)
    calls = []
    with pytest.raises(ValueError, match='archive_changed'):
        verifier.ensure_loaded(tmp_path, runner=lambda *a, **k: calls.append(a))
    assert not calls


def loaded_fixture(m, official, config, *, classic=False):
    actual = copy.deepcopy(official)
    actual['mediaType'] = 'application/vnd.docker.distribution.manifest.v2+json'
    raw = json.dumps(actual).encode()
    m.MANIFEST_ID = 'sha256:' + m.sha(raw)
    image = {'Id': m.CONFIG_ID if classic else m.MANIFEST_ID,
             'Descriptor': {'digest': m.MANIFEST_ID}, 'Architecture': 'amd64', 'Os': 'linux',
             'RootFS': {'Layers': config['rootfs']['diff_ids']}, 'Config': copy.deepcopy(config['config'])}
    calls = []
    def runner(args, **kwargs):
        calls.append(args)
        if args[:3] == ['docker', 'image', 'inspect']:
            return json.dumps([image]).encode()
        if args[0] == 'ctr':
            return raw
        if args[:2] == ['docker', 'load']:
            return b'loaded'
        raise AssertionError('Unexpected command')
    return image, runner, calls


@pytest.mark.parametrize('classic', [True, False])
def test_classic_config_and_containerd_manifest_ids_verify(tmp_path, verifier, classic):
    official, config = archive_fixture(tmp_path, verifier)
    image, runner, calls = loaded_fixture(verifier, official, config, classic=classic)
    assert verifier.ensure_loaded(tmp_path, runner=runner) == image['Id']
    assert calls[0][:3] == ['docker', 'load', '--input']
    assert not any('pull' in c for call in calls for c in call)
    assert any(call[0] == 'ctr' for call in calls) is (not classic)


@pytest.mark.parametrize('field', ['Config', 'RootFS', 'Architecture', 'Id', 'Descriptor'])
def test_loaded_runtime_substitution_fails(tmp_path, verifier, field):
    official, config = archive_fixture(tmp_path, verifier)
    image, runner, _ = loaded_fixture(verifier, official, config)
    image[field] = {} if field in ('Config', 'RootFS', 'Descriptor') else 'foreign'
    with pytest.raises(ValueError, match='redroid_'):
        verifier.verify_loaded_image(official, config, runner=runner)


def test_changed_containerd_layers_fail_even_if_actual_manifest_hash_matches(tmp_path, verifier):
    official, config = archive_fixture(tmp_path, verifier)
    other = copy.deepcopy(official);other['layers'][0]['digest'] = 'sha256:' + 'b' * 64
    _, runner, _ = loaded_fixture(verifier, other, config)
    with pytest.raises(ValueError, match='loaded_content_changed'):
        verifier.verify_loaded_image(official, config, runner=runner)


def test_missing_containerd_manifest_does_not_accept_only_a_tag(tmp_path, verifier):
    official, config = archive_fixture(tmp_path, verifier)
    _, runner, _ = loaded_fixture(verifier, official, config)
    def missing(args, **kw):
        if args[0] == 'ctr':raise ValueError('unavailable')
        return runner(args, **kw)
    with pytest.raises(ValueError, match='loaded_manifest_changed'):
        verifier.verify_loaded_image(official, config, runner=missing)


def test_builder_uses_explicit_pinned_wheel_over_old_assets(tmp_path):
    builder, installer = module('build-device-runtime-bundle'), module('install-device-runtime')
    assets = tmp_path / 'assets';assets.mkdir()
    for name in installer.COMMON:
        (assets / name).write_text('fixture public asset')
    (assets / 'wearing-0.1.0-py3-none-any.whl').write_bytes(b'old')
    (assets / 'dep-1-py3-none-any.whl').write_bytes(b'dep')
    wheel = tmp_path / 'wearing-0.2.0-py3-none-any.whl';wheel.write_bytes(b'new approved bytes')
    out = tmp_path / 'built'
    result = builder.build('linux', assets, out, wheel=wheel, wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest())
    assert (out / wheel.name).read_bytes() == wheel.read_bytes()
    assert not (out / 'wearing-0.1.0-py3-none-any.whl').exists()
    assert installer.verify_bundle(out, result['artifact_sha256'])[1] == wheel.name
    with pytest.raises(ValueError, match='wheel_changed'):
        builder.build('linux', assets, tmp_path / 'wrong', wheel=wheel, wheel_sha256='0' * 64)


def test_only_fixed_official_tar_can_exceed_general_file_limit(tmp_path):
    installer = module('install-device-runtime')
    manifest = {'version': 1, 'kind': 'android', 'files': {}}
    for name in installer.ANDROID | installer.COMMON | {'wearing-0.2.0-py3-none-any.whl'}:
        raw = b'fixture';(tmp_path / name).write_bytes(raw)
        manifest['files'][name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    def verify():
        (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
        return installer.verify_bundle(tmp_path, installer.digest(manifest))
    with pytest.raises(ValueError, match='unapproved_redroid_archive'):
        verify()
    manifest['files']['redroid-amd64.tar'] = {'bytes': installer.REDROID_ARCHIVE_BYTES, 'sha256': installer.REDROID_ARCHIVE_SHA256}
    # Still rejects even approved metadata unless exact bytes are present.
    with pytest.raises(ValueError, match='runtime_file_changed'):
        verify()
    manifest['files']['redroid-amd64.tar']['bytes'] += 1
    with pytest.raises(ValueError, match='invalid_runtime_file_manifest'):
        verify()


def test_setup_never_implicitly_pulls_a_missing_image():
    source = (ROOT / 'deploy/on-prem/setup-android-phone.sh').read_text()
    assert 'docker run --pull=never ' in source
    assert source.index('docker image inspect "$image"') < source.index('docker run --pull=never ')
    assert 'docker pull' not in source


def test_only_absent_null_optional_config_fields_are_equivalent(tmp_path, verifier):
    official, config = archive_fixture(tmp_path, verifier)
    image, runner, _ = loaded_fixture(verifier, official, config, classic=True)
    image['Config']['User'] = None
    assert verifier.verify_loaded_image(official, config, runner=runner) == verifier.CONFIG_ID
    image['Config']['User'] = 'root'
    with pytest.raises(ValueError, match='loaded_config_changed'):
        verifier.verify_loaded_image(official, config, runner=runner)
