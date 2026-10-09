"""Operator-provisioned mutual TLS for private tenant HTTP and voice traffic."""

import os
from pathlib import Path
import ssl


def upstream_tls_context():
    names = ('PAJIO_UPSTREAM_CA_FILE', 'PAJIO_UPSTREAM_CERT_FILE', 'PAJIO_UPSTREAM_KEY_FILE')
    values = [os.environ.get(name, '') for name in names]
    if not any(values):
        return None
    if not all(values):
        raise ValueError('Private upstream TLS requires a CA, client certificate and key.')
    for value in values:
        path = Path(value)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ValueError('Private upstream TLS files must be absolute regular files.')
    if Path(values[2]).stat().st_mode & 0o077:
        raise ValueError('Private upstream TLS key must only be accessible to its owner.')
    context = ssl.create_default_context(cafile=values[0])
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(values[1], values[2])
    return context
