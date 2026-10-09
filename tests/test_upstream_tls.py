import ssl

import pytest

from wearing.cloud.upstream_tls import upstream_tls_context


NAMES = ('PAJIO_UPSTREAM_CA_FILE', 'PAJIO_UPSTREAM_CERT_FILE', 'PAJIO_UPSTREAM_KEY_FILE')


def test_upstream_tls_defaults_to_public_trust(monkeypatch):
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    assert upstream_tls_context() is None


def test_partial_mtls_configuration_fails_closed(monkeypatch, tmp_path):
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(NAMES[0], str(tmp_path / 'ca'))
    with pytest.raises(ValueError, match='requires a CA'):
        upstream_tls_context()


def test_mtls_does_not_allow_readable_private_key(monkeypatch, tmp_path):
    for name in NAMES:
        path = tmp_path / name
        path.write_text('not a certificate')
        path.chmod(0o644)
        monkeypatch.setenv(name, str(path))
    with pytest.raises(ValueError, match='owner'):
        upstream_tls_context()


def test_mtls_context_enforces_hostnames_and_verification(monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'test')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    for variable, data in zip(NAMES, [cert.public_bytes(serialization.Encoding.PEM)] * 2 + [
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())]):
        path = tmp_path / variable
        path.write_bytes(data)
        path.chmod(0o600)
        monkeypatch.setenv(variable, str(path))
    context = upstream_tls_context()
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
