#!/bin/sh
set -eu
umask 077
# A fresh cookie each X server start; never put it in argv, env or logs.
/usr/bin/python3 - <<'PY'
import os, secrets, subprocess
path = os.environ['XAUTHORITY']
fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
os.close(fd)
subprocess.run(['/usr/bin/xauth', '-f', path, 'source', '-'],
    input='add :10 MIT-MAGIC-COOKIE-1 '+secrets.token_hex(16)+'\n',
    text=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
PY
exec /usr/bin/Xvfb :10 -screen 0 1280x800x24 -auth "$XAUTHORITY" -nolisten tcp -noreset
