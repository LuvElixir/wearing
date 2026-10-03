"""Versioned device command boundary for the future cloud relay.

These are validation and authorization contracts, NOT authentication or a relay.
Authority records must come from authenticated, tenant-scoped server storage (or
the connector's paired state), never from a request body. The caller must hold
the resource lease while checking and dispatching. Durable deduplication, atomic
lease allocation, token verification and device execution remain separate work.
"""

from datetime import datetime, timedelta, timezone
import json
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator


Identifier = Annotated[str, Field(strict=True, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")]
Method = Annotated[str, Field(strict=True, pattern=r"^[a-z][a-z0-9_.]{0,127}$")]
Generation = Annotated[int, Field(strict=True, ge=1)]
MAX_COMMAND_TTL = timedelta(minutes=5)
MAX_PARAMS_BYTES = 65536


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Scope(Record):
    tenant_id: Identifier
    identity_id: Identifier


class TaskAuthority(Record):
    scope: Scope
    task_id: Identifier


class ResourceGrant(Record):
    scope: Scope
    resource_id: Identifier
    connector_id: Identifier
    pairing_generation: Generation
    policy_revision: Generation
    methods: frozenset[Method]
    revoked: bool = False


class ConnectionAuthority(Record):
    tenant_id: Identifier
    connector_id: Identifier
    connection_id: Identifier
    pairing_generation: Generation
    capabilities: frozenset[Method]
    expires_at: AwareDatetime
    revoked: bool = False


class LeaseAuthority(Record):
    scope: Scope
    resource_id: Identifier
    task_id: Identifier
    connection_id: Identifier
    epoch: Generation
    expires_at: AwareDatetime
    revoked: bool = False


class DeviceCommand(Record):
    protocol_version: Literal["1"]
    command_id: Identifier
    scope: Scope
    task_id: Identifier
    resource_id: Identifier
    connector_id: Identifier
    connection_id: Identifier
    pairing_generation: Generation
    policy_revision: Generation
    lease_epoch: Generation
    method: Method
    params: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def bounded_command(self):
        lifetime = self.expires_at - self.created_at
        if not timedelta(0) < lifetime <= MAX_COMMAND_TTL:
            raise ValueError("command lifetime must be between zero and five minutes")
        # No screen pixels or file contents in command envelopes; use scoped
        # artifact references. NaN/Infinity are not valid interoperable JSON.
        encoded = json.dumps(self.params, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_PARAMS_BYTES:
            raise ValueError("command params exceed 64 KiB")
        return self


class CommandRejected(PermissionError):
    def __init__(self, code: str):
        self.code = code
        # Do not echo tenant data, identifiers or command payloads into errors.
        super().__init__(code)


def authorize_command(
    command: DeviceCommand,
    *,
    task: TaskAuthority,
    grant: ResourceGrant,
    connection: ConnectionAuthority,
    lease: LeaseAuthority,
    now: datetime,
) -> None:
    """Fail closed against CURRENT trusted records, immediately before dispatch.

    Success permits only this bounded command. It does not attest authentication,
    durable exactly-once delivery, execution, or business success. Recheck on the
    device immediately before each action, including after reconnect/takeover.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    now = now.astimezone(timezone.utc)
    if grant.revoked or connection.revoked or lease.revoked:
        raise CommandRejected("authorization_revoked")
    if not (command.scope == task.scope == grant.scope == lease.scope):
        raise CommandRejected("scope_mismatch")
    if command.scope.tenant_id != connection.tenant_id:
        raise CommandRejected("scope_mismatch")
    if command.task_id != task.task_id or command.task_id != lease.task_id:
        raise CommandRejected("task_mismatch")
    if command.resource_id != grant.resource_id or command.resource_id != lease.resource_id:
        raise CommandRejected("resource_mismatch")
    if command.connector_id != grant.connector_id or command.connector_id != connection.connector_id:
        raise CommandRejected("connector_mismatch")
    if command.connection_id != connection.connection_id or command.connection_id != lease.connection_id:
        raise CommandRejected("connection_stale")
    if not (command.pairing_generation == grant.pairing_generation == connection.pairing_generation):
        raise CommandRejected("pairing_stale")
    if command.policy_revision != grant.policy_revision:
        raise CommandRejected("policy_stale")
    if command.lease_epoch != lease.epoch:
        raise CommandRejected("lease_stale")
    if command.method not in grant.methods or command.method not in connection.capabilities:
        raise CommandRejected("capability_denied")
    if command.created_at > now + timedelta(seconds=5):
        raise CommandRejected("command_from_future")
    if min(command.expires_at, connection.expires_at, lease.expires_at) <= now:
        raise CommandRejected("authorization_expired")
    if command.expires_at > min(connection.expires_at, lease.expires_at):
        raise CommandRejected("command_outlives_authorization")
