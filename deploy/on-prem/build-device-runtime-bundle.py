#!/usr/bin/env python3
"""Assemble reviewed source + offline wheelhouse into the bootstrap artifact.

Downloads and credentials do not belong here. Supply official verified archives
and the exact requirements-media.txt/wheels produced for Ubuntu 24.04 x86_64.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil


def build(kind,assets,output,*,wheel=None,wheel_sha256=None,android_image_assets=None):
    source=Path(__file__).resolve().parent
    definition=importlib.util.spec_from_file_location('runtime_installer',source/'install-device-runtime.py')
    installer=importlib.util.module_from_spec(definition);definition.loader.exec_module(installer)
    assets,output=Path(assets),Path(output)
    if output.is_symlink() or (output.exists() and any(output.iterdir())):raise ValueError('empty_runtime_output_required')
    output.mkdir(mode=0o700,parents=True,exist_ok=True);output.chmod(0o700)
    required=installer.COMMON|(installer.LINUX if kind=='linux' else installer.ANDROID)
    selected={}
    for name in required:
        if (source/name).is_file():selected[name]=source/name
        elif name=='scrcpy-5.0.1-LICENSE':selected[name]=source/'notices'/name
        elif name=='scrcpy-notices.json':selected[name]=source/'notices/manifest.json'
        elif name in {'redroid-amd64.tar','redroid-oci-manifest.json'} and android_image_assets is not None:
            selected[name]=Path(android_image_assets)/('oci-manifest.json' if name=='redroid-oci-manifest.json' else name)
        else:selected[name]=assets/name
    selected.update({p.name:p for p in assets.glob('*.whl') if wheel is None or not p.name.startswith('wearing-')})
    if (wheel is None)!=(wheel_sha256 is None):raise ValueError('runtime_wheel_pin_required')
    if wheel is not None:
        wheel=Path(wheel)
        if wheel.is_symlink() or not wheel.is_file() or not wheel.name.startswith('wearing-') or not wheel.name.endswith('.whl'):
            raise ValueError('runtime_wheel_invalid')
        with wheel.open('rb') as f:
            if hashlib.file_digest(f,'sha256').hexdigest()!=wheel_sha256:raise ValueError('runtime_wheel_changed')
        selected[wheel.name]=wheel
    manifest={'version':1,'kind':kind,'files':{}}
    for name,path in sorted(selected.items()):
        if path.is_symlink() or not path.is_file():raise ValueError('runtime_input_missing_or_symlink')
        destination=output/name;shutil.copyfile(path,destination);destination.chmod(0o600)
        with destination.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
        manifest['files'][name]={'sha256':sha,'bytes':destination.stat().st_size}
    (output/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n');(output/'manifest.json').chmod(0o600)
    sha=installer.digest(manifest);installer.verify_bundle(output,sha)
    return {'kind':kind,'artifact_sha256':sha,'files':len(selected),'bytes':sum(v['bytes'] for v in manifest['files'].values()),'bundle':str(output.absolute()),'product_ready':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--kind',choices=['linux','android'],required=True);p.add_argument('--assets',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--wheel',type=Path);p.add_argument('--wheel-sha256');p.add_argument('--android-image-assets',type=Path);a=p.parse_args()
    try:print(json.dumps(build(a.kind,a.assets,a.output,wheel=a.wheel,wheel_sha256=a.wheel_sha256,android_image_assets=a.android_image_assets)))
    except Exception:raise SystemExit('Runtime bundle incomplete; preserve inputs and check required files.')
