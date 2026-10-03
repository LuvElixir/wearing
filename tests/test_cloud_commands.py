"""Adversarial contract tests; no cloud, real identities or devices are touched."""

from datetime import datetime, timedelta, timezone
import json

from pydantic import ValidationError
import pytest

from wearing.cloud.commands import (
    CommandRejected, ConnectionAuthority, DeviceCommand, LeaseAuthority,
    ResourceGrant, Scope, TaskAuthority, authorize_command,
)


@pytest.fixture
def command_context():
    now = datetime(2026, 10, 3, tzinfo=timezone.utc)
    scope = Scope(tenant_id="tenant_alice", identity_id="daily")
    command = DeviceCommand(
        protocol_version="1", command_id="command_one", scope=scope, task_id="task_one", resource_id="phone_one",
        connector_id="mac_one", connection_id="connection_one", pairing_generation=2,
        policy_revision=3, lease_epoch=4, method="phone.tap", params={"x": 100, "y": 200},
        created_at=now, expires_at=now + timedelta(seconds=30),
    )
    context = dict(
        task=TaskAuthority(scope=scope, task_id="task_one"),
        grant=ResourceGrant(scope=scope, resource_id="phone_one", connector_id="mac_one",
                            pairing_generation=2, policy_revision=3, methods={"phone.tap"}),
        connection=ConnectionAuthority(tenant_id="tenant_alice", connector_id="mac_one",
                                       connection_id="connection_one", pairing_generation=2,
                                       capabilities={"phone.tap"}, expires_at=now + timedelta(minutes=1)),
        lease=LeaseAuthority(scope=scope, resource_id="phone_one", task_id="task_one",
                             connection_id="connection_one", epoch=4, expires_at=now + timedelta(minutes=1)),
        now=now,
    )
    return command, context


def test_authorized_command_round_trip(command_context):
    command, context = command_context
    parsed = DeviceCommand.model_validate_json(command.model_dump_json())
    assert parsed == command
    assert authorize_command(parsed, **context) is None


@pytest.mark.parametrize("record", ["task", "grant", "lease", "connection"])
def test_cannot_mix_records_from_two_tenants(command_context, record):
    command, context = command_context
    current = context[record]
    changes = {"tenant_id": "tenant_bob"} if record == "connection" else {
        "scope": Scope(tenant_id="tenant_bob", identity_id="daily")}
    context[record] = current.model_copy(update=changes)
    with pytest.raises(CommandRejected, match="scope_mismatch"):
        authorize_command(command, **context)


def test_forged_tenant_in_command_does_not_select_authority(command_context):
    command, context = command_context
    forged = command.model_copy(update={"scope": Scope(tenant_id="tenant_bob", identity_id="daily")})
    with pytest.raises(CommandRejected, match="scope_mismatch"):
        authorize_command(forged, **context)


def test_identity_switch_does_not_rebind_an_inflight_task(command_context):
    command, context = command_context
    switched = command.model_copy(update={"scope": Scope(tenant_id="tenant_alice", identity_id="overseas")})
    with pytest.raises(CommandRejected, match="scope_mismatch"):
        authorize_command(switched, **context)


@pytest.mark.parametrize("record", ["grant", "connection", "lease"])
def test_revocation_blocks_even_previously_valid_commands(command_context, record):
    command, context = command_context
    context[record] = context[record].model_copy(update={"revoked": True})
    with pytest.raises(CommandRejected, match="authorization_revoked"):
        authorize_command(command, **context)


@pytest.mark.parametrize("record,changes,reason", [
    ("task", {"task_id": "task_two"}, "task_mismatch"),
    ("lease", {"task_id": "task_two"}, "task_mismatch"),
    ("grant", {"resource_id": "phone_two"}, "resource_mismatch"),
    ("lease", {"resource_id": "phone_two"}, "resource_mismatch"),
    ("connection", {"connector_id": "mac_two"}, "connector_mismatch"),
    ("connection", {"connection_id": "connection_two"}, "connection_stale"),
    ("lease", {"connection_id": "connection_two"}, "connection_stale"),
    ("connection", {"pairing_generation": 3}, "pairing_stale"),
    ("grant", {"pairing_generation": 3}, "pairing_stale"),
    ("grant", {"policy_revision": 4}, "policy_stale"),
    ("lease", {"epoch": 5}, "lease_stale"),
    ("grant", {"methods": frozenset({"phone.screenshot"})}, "capability_denied"),
    ("connection", {"capabilities": frozenset()}, "capability_denied"),
])
def test_changed_authority_invalidates_old_command(command_context, record, changes, reason):
    command, context = command_context
    context[record] = context[record].model_copy(update=changes)
    with pytest.raises(CommandRejected, match=reason):
        authorize_command(command, **context)


@pytest.mark.parametrize("record", ["connection", "lease"])
def test_expired_authority_is_rejected_at_exact_deadline(command_context, record):
    command, context = command_context
    context[record] = context[record].model_copy(update={"expires_at": context["now"]})
    with pytest.raises(CommandRejected, match="authorization_expired"):
        authorize_command(command, **context)


def test_command_expiry_and_future_start(command_context):
    command, context = command_context
    with pytest.raises(CommandRejected, match="authorization_expired"):
        authorize_command(command, **{**context, "now": command.expires_at})
    with pytest.raises(CommandRejected, match="command_from_future"):
        authorize_command(command, **{**context, "now": command.created_at - timedelta(seconds=6)})


def test_command_cannot_outlive_lease(command_context):
    command, context = command_context
    context["lease"] = context["lease"].model_copy(update={"expires_at": context["now"] + timedelta(seconds=10)})
    with pytest.raises(CommandRejected, match="command_outlives_authorization"):
        authorize_command(command, **context)


@pytest.mark.parametrize("change", [
    {"protocol_version": "2"}, {"lease_epoch": True}, {"lease_epoch": 0},
    {"connector_id": "../phone"}, {"unexpected": "ignored?"},
    {"created_at": "2026-10-03T00:00:00"}, {"params": {"x": float("nan")}},
    {"params": {"text": "a" * 65536}}, {"expires_at": "2026-10-03T00:10:00Z"},
    {"expires_at": "2026-10-03T00:00:00Z"},
])
def test_malformed_or_unbounded_wire_commands_are_rejected(command_context, change):
    command, _ = command_context
    with pytest.raises(ValidationError):
        DeviceCommand.model_validate({**command.model_dump(), **change})


def test_wire_schema_has_required_scope_and_no_extra_properties():
    schema = DeviceCommand.model_json_schema()
    assert "scope" in schema["required"]
    assert "protocol_version" in schema["required"]
    assert schema["additionalProperties"] is False
    assert json.loads(json.dumps(schema)) == schema
