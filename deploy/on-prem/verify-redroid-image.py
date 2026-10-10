#!/usr/bin/python3
"""Verify the fixed official Android image before a dedicated-VM offline load.

No registry requests or tar extraction. Docker's manifest ID and classic config
ID are distinct formats; each is checked against the same approved OCI bytes.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

ARCHIVE_SHA256 = '113191519c4e5aa9864fbe15b79d816ed3d77f4fabc4c4a33840afeb9806a4ce'
ARCHIVE_BYTES = 873349120
OFFICIAL_SHA256 = '11d58a64bfbde2253d1cce81bff409ff58174980222d1bada232d9ef59181191'
CONFIG_ID = 'sha256:639792975c26fa2920562c5b8dfbb808405f4a6ecce8fb65005e07b484d4d392'
MANIFEST_ID = 'sha256:1426149f9c830c53572eb89bd9f2ade07838eb21be06edd98830aa9f4ef634fb'
TAG = 'redroid/redroid:14.0.0-latest'


def require(ok, code):
    if not ok:
        raise ValueError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def checked_file(path, size=None):
    require(not path.is_symlink() and path.is_file() and path.stat().st_nlink == 1,
            'redroid_source_unsafe')
    if size is not None:
        require(path.stat().st_size == size, 'redroid_source_changed')


def verify_archive(directory):
    directory = Path(directory)
    path = directory / 'redroid-amd64.tar'
    checked_file(path, ARCHIVE_BYTES)
    with path.open('rb') as stream:
        require(hashlib.file_digest(stream, 'sha256').hexdigest() == ARCHIVE_SHA256,
                'redroid_archive_changed')
    official_path = directory / 'redroid-oci-manifest.json'
    checked_file(official_path)
    raw = official_path.read_bytes()
    require(len(raw) < 16384 and sha(raw) == OFFICIAL_SHA256, 'redroid_official_manifest_changed')
    official = json.loads(raw)
    require(official['schemaVersion'] == 2 and official['mediaType'] == 'application/vnd.oci.image.manifest.v1+json'
            and official['config']['digest'] == CONFIG_ID and len(official['layers']) == 1,
            'redroid_official_manifest_invalid')
    config_name = CONFIG_ID.removeprefix('sha256:') + '.json'
    layer_names = [v['digest'].removeprefix('sha256:') + '/layer.tar' for v in official['layers']]
    with tarfile.open(path) as archive:
        entries = archive.getmembers()
        require(len(entries) == 3 and {v.name for v in entries} == {'manifest.json', config_name, *layer_names}
                and all(v.isfile() and not v.issym() and not v.islnk() for v in entries),
                'redroid_archive_scope_changed')
        require(archive.getmember('manifest.json').size < 16384, 'redroid_archive_manifest_invalid')
        manifest = json.load(archive.extractfile('manifest.json'))
        require(manifest == [{'Config': config_name, 'RepoTags': [TAG], 'Layers': layer_names}],
                'redroid_archive_manifest_invalid')
        require(archive.getmember(config_name).size == official['config']['size'], 'redroid_config_changed')
        raw_config = archive.extractfile(config_name).read()
        require('sha256:' + sha(raw_config) == CONFIG_ID, 'redroid_config_changed')
        config = json.loads(raw_config)
        require(config.get('architecture') == 'amd64' and config.get('os') == 'linux'
                and config.get('rootfs', {}).get('type') == 'layers', 'redroid_platform_changed')
        for name, expected in zip(layer_names, official['layers']):
            require(archive.getmember(name).size == expected['size'], 'redroid_layer_changed')
            with archive.extractfile(name) as stream:
                require('sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest() == expected['digest'],
                        'redroid_layer_changed')
    return official, config


def command(args, *, timeout=180):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    require(result.returncode == 0, 'redroid_native_unconfirmed')
    return result.stdout


def verify_loaded_image(official, config, *, runner=command):
    rows = json.loads(runner(['docker', 'image', 'inspect', TAG]))
    require(isinstance(rows, list) and len(rows) == 1, 'redroid_image_scope_changed')
    image = rows[0]
    ident = image.get('Id')
    require(ident in (CONFIG_ID, MANIFEST_ID), 'redroid_image_id_changed')
    if ident == MANIFEST_ID:
        require(image.get('Descriptor', {}).get('digest') == ident, 'redroid_descriptor_changed')
        raw = None
        for address in ('/run/containerd/containerd.sock', '/var/run/docker/containerd/containerd.sock'):
            try:
                raw = runner(['ctr', '--address', address, '--namespace', 'moby', 'content', 'get', ident], timeout=15)
                break
            except (ValueError, subprocess.TimeoutExpired):
                continue
        require(raw is not None and len(raw) < 16384 and 'sha256:' + sha(raw) == ident,
                'redroid_loaded_manifest_changed')
        actual = json.loads(raw)
        require(actual.get('schemaVersion') == 2 and actual.get('mediaType') == 'application/vnd.docker.distribution.manifest.v2+json',
                'redroid_loaded_manifest_changed')
        require(all(actual['config'][k] == official['config'][k] for k in ('digest', 'size'))
                and [(v['digest'], v['size']) for v in actual['layers']] == [(v['digest'], v['size']) for v in official['layers']],
                'redroid_loaded_content_changed')
    require(image.get('Architecture') == 'amd64' and image.get('Os') == 'linux'
            and image.get('RootFS', {}).get('Layers') == config['rootfs']['diff_ids'], 'redroid_loaded_rootfs_changed')
    # Docker may serialize absent optional configuration keys as JSON null.
    # Only absent/null is equivalent; every non-null value must match exactly.
    require(isinstance(image.get('Config'), dict) and all(
        image['Config'].get(k) == config['config'].get(k)
        for k in set(image['Config']) | set(config['config'])), 'redroid_loaded_config_changed')
    return ident


def ensure_loaded(directory, *, runner=command):
    official, config = verify_archive(directory)
    # Re-loading only the same public, fully verified image is idempotent. No
    # containers or user volumes are created or removed here.
    runner(['docker', 'load', '--input', str(Path(directory) / 'redroid-amd64.tar')], timeout=1800)
    return verify_loaded_image(official, config, runner=runner)
