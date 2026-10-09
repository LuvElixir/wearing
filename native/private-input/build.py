#!/usr/bin/env python3
"""Build a tiny auditable companion with an existing authorized Android SDK.

No Gradle/network dependency resolution. Signing key and password file remain in
operator-owned storage; only the signed APK and public build manifest are output.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

p = argparse.ArgumentParser()
p.add_argument('--sdk', type=Path, required=True)
p.add_argument('--java-home', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--signing-directory', type=Path, required=True)
a = p.parse_args()
root = Path(__file__).resolve().parent
out = a.output.resolve(); out.mkdir(parents=True, exist_ok=True)
signing = a.signing_directory.resolve(); signing.mkdir(parents=True, mode=0o700, exist_ok=True)
signing.chmod(0o700)
key, secret = signing / 'private-input.p12', signing / 'password'
if key.exists() != secret.exists(): raise SystemExit('Incomplete signing key storage')
if not secret.exists():
    import secrets
    fd = os.open(secret, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as f: f.write(secrets.token_urlsafe(36))
env = {**os.environ, 'JAVA_HOME': str(a.java_home), 'PAJIO_IME_STOREPASS': secret.read_text()}
env['PATH'] = str(a.java_home / 'bin') + os.pathsep + env.get('PATH','')
tools = a.sdk / 'build-tools/36.0.0'; jar = a.sdk / 'platforms/android-36/android.jar'
def run(*args): subprocess.run([str(x) for x in args], env=env, check=True)
if not key.exists():
    run(a.java_home/'bin/keytool','-genkeypair','-keystore',key,'-storetype','PKCS12',
        '-storepass:env','PAJIO_IME_STOREPASS','-keypass:env','PAJIO_IME_STOREPASS',
        '-alias','pajio-private-input','-keyalg','RSA','-keysize','3072','-validity','3650',
        '-dname','CN=Pajio Private Input,OU=Execution Host')
    key.chmod(0o600)
classes = out/'classes'
if classes.exists():
    import shutil
    shutil.rmtree(classes)
classes.mkdir()
run(tools/'aapt2','compile','--dir',root/'res','-o',out/'resources.zip')
run(tools/'aapt2','link','-o',out/'base.apk','-I',jar,'--manifest',root/'AndroidManifest.xml',out/'resources.zip')
run(a.java_home/'bin/javac','-source','8','-target','8','-classpath',jar,'-d',classes,*sorted((root/'src').rglob('*.java')))
run(tools/'d8','--min-api','26','--lib',jar,'--output',out,*sorted(classes.rglob('*.class')))
with zipfile.ZipFile(out/'base.apk','a') as z: z.write(out/'classes.dex','classes.dex')
run(tools/'zipalign','-f','4',out/'base.apk',out/'aligned.apk')
apk = out/'pajio-private-input.apk'
run(tools/'apksigner','sign','--ks',key,'--ks-pass','env:PAJIO_IME_STOREPASS','--key-pass','env:PAJIO_IME_STOREPASS','--out',apk,out/'aligned.apk')
run(tools/'apksigner','verify','--verbose','--print-certs',apk)
manifest = {'schema':1,'package':'io.pajio.privateinput','version_code':1,
            'apk_sha256':hashlib.sha256(apk.read_bytes()).hexdigest(),
            'sources':{str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest()
                       for f in [root/'AndroidManifest.xml',root/'res/xml/method.xml',*sorted((root/'src').rglob('*.java'))]}}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
