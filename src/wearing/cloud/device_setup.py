"""User device offers contain scopes only, never executable or model tool schemas."""
import copy
import json
from pathlib import Path

from pydantic import Field, model_validator

from .commands import Record
from .relay import ResourceSpec, RelayError, encoded, fingerprint
from .instance import read_private
from ..connectors.remote.client import PairBundle
from ..connectors.remote.schemas import COMPUTER_METHODS, COMPUTER_TOOLS


PHONE_TOOLS = json.loads(Path(__file__).with_name('phone-tools.json').read_text())
PHONE_METHODS = frozenset('phone.' + t['name'] for t in PHONE_TOOLS)


def tools_for(specs):
    methods = {m for r in specs for m in r['methods']}
    tools = [copy.deepcopy(t) for t in PHONE_TOOLS if 'phone.' + t['name'] in methods]
    if methods.intersection(COMPUTER_METHODS):
        tools += [copy.deepcopy(t) for t in COMPUTER_TOOLS if t['name']=='wearing_computer_observe' or 'computer.input' in methods]
    return tools


class DeviceOffer(Record):
    schema_version: int = Field(ge=1, le=1, strict=True)
    resources: list[ResourceSpec] = Field(min_length=1, max_length=32)

    @model_validator(mode='after')
    def scopes(self):
        if len({r.resource_id for r in self.resources}) != len(self.resources):
            raise ValueError('duplicate_resource')
        for r in self.resources:
            allowed = PHONE_METHODS if r.kind == 'android' else frozenset(COMPUTER_METHODS)
            if not r.methods <= allowed:
                raise ValueError('unsupported_device_capability')
        return self


class PairDevices(Record):
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    offer: DeviceOffer


def create_pairing(store, root, identity, request):
    """Recover a lost response with the same request ID; endpoint is operator-owned."""
    config = json.loads(read_private(root / 'data/device-endpoint.json'))
    # Validate the fixed destination BEFORE minting a pairing code.
    endpoint = PairBundle.model_validate({**config, 'code':'a'*43, 'connector_id':'connector_'+'a'*32,
        'tenant_id':store.tenant, 'identity_id':identity, 'pairing_generation':1, 'policy_revision':1,
        'resources':request.offer.resources})
    specs = request.offer.model_dump(mode='json')['resources']
    tools = tools_for(specs)
    digest = fingerprint(encoded({'identity':identity, 'resources':specs}))
    with store.tx() as db:
        row = db.execute('SELECT * FROM pairing_requests WHERE id=?', (request.request_id,)).fetchone()
        if row:
            if row['digest'] != digest:
                raise RelayError('pairing_request_changed')
            from .relay import utc
            if row['expires'] <= utc().timestamp():
                raise RelayError('pairing_expired')
            return json.loads(row['bundle'])
        # pair_code uses its own atomic transaction; do not hold a nested write lock.
    pending = store.pair_code(identity, specs, tools)
    bundle = {**pending, 'endpoint':endpoint.endpoint, 'ca_pem':endpoint.ca_pem}
    from .relay import utc
    with store.tx() as db:
        # A concurrent retry may have minted an unused code. Only the winner is returned.
        db.execute('INSERT OR IGNORE INTO pairing_requests VALUES (?,?,?,?)',
                   (request.request_id, digest, encoded(bundle), utc().timestamp()+600))
        row = db.execute('SELECT * FROM pairing_requests WHERE id=?', (request.request_id,)).fetchone()
        if row['digest'] != digest:
            raise RelayError('pairing_request_changed')
        return json.loads(row['bundle'])


def download_pairing(store, identity, request_id):
    from .relay import utc
    with store.tx() as db:
        row = db.execute('SELECT * FROM pairing_requests WHERE id=?', (request_id,)).fetchone()
        if not row or row['expires'] <= utc().timestamp():
            raise RelayError('pairing_expired', 404)
        bundle = json.loads(row['bundle'])
        if bundle.get('identity_id') != identity:
            raise RelayError('pairing_expired', 404)
        return bundle
