import json
import sys

import pytest

from wearing.cli import main
from wearing.cloud.control import ControlStore
from wearing.cloud.gateway import initialize_gateway, load_gateway


def run(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, 'argv', ['wearing', 'gateway', 'invite', *args])
    main()
    return json.loads(capsys.readouterr().out)


def test_cli_reserve_issue_retry_status_revoke_without_printing_code(tmp_path, monkeypatch, capsys):
    root = tmp_path / 'entry'
    initialize_gateway(root, 'https://pajio.example', 'https://identity.example', 'test', development=True)
    # Runtime factory remains gateway-owned; the CLI always requests its operator
    # factory and never obtains privileged credentials from argv.
    monkeypatch.setattr('wearing.cloud.gateway.operator_store', lambda config: ControlStore(config.database_url.get_secret_value(), operator=True))
    common = ['--root', str(root)]
    assert run(monkeypatch, capsys, 'reserve', *common, '--tenant-id', 'new')['status'] == 'reserved'
    ops = ControlStore(load_gateway(root).database_url.get_secret_value(), operator=True)
    try:
        ops.bind('new', 'instance_new', 'https://worker.example', 'new.json')
    finally:
        ops.close()
    output = root / 'invite.json'
    first = run(monkeypatch, capsys, 'issue', *common, '--tenant-id', 'new', '--output', str(output), '--expires-in', '3600')
    raw = output.read_bytes()
    assert first['status']=='issued' and 'code' not in first
    assert run(monkeypatch, capsys, 'issue', *common, '--tenant-id', 'new', '--output', str(output), '--expires-in', '3600') == first
    assert output.read_bytes() == raw
    assert run(monkeypatch, capsys, 'status', *common, '--invitation-id', first['id']) == first
    assert run(monkeypatch, capsys, 'revoke', *common, '--invitation-id', first['id'])['status']=='revoked'
