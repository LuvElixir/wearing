#!/usr/bin/env python3
"""Prepare private flags only. Does not contact or change Keycloak."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat


def private_read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        meta = os.fstat(fd)
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid()
                or meta.st_nlink != 1 or stat.S_IMODE(meta.st_mode) != 0o600 or meta.st_size > 1024 * 1024):
            raise ValueError('private_input_boundary')
        raw = os.read(fd, 1024 * 1024 + 1)
        return raw, json.loads(raw)
    finally:
        os.close(fd)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--fence-proof', type=Path, required=True)
    parser.add_argument('--observed-plan', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    inventory_raw, inventory = private_read(args.inventory)
    fence_raw, fence = private_read(args.fence_proof)
    names = ['pajio_acceptance_a', 'pajio_acceptance_b', 'pajio_acceptance_c']
    if set(inventory) != set(names) | {'_counts'} or set(fence['fenced_tenants']) != set(names) or fence['sessions_revoked'] is not True:
        raise ValueError('exact_qa_fence_required')
    subjects = []
    for name in names:
        row = inventory[name]
        if (len(row['users']) != 1 or len(row['members']) != 1 or row['other_membership_count'] != 0
                or row['owner']['owner_user_id'] != row['users'][0]['id']
                or row['members'][0]['user_id'] != row['users'][0]['id']
                or row['members'][0]['tenant_id'] != name
                or row['users'][0]['issuer'] != 'https://id.pajio.luckyloading.com/realms/pajio'):
            raise ValueError('qa_identity_scope_changed')
        subjects.append(row['users'][0]['subject'])
    if len(set(subjects)) != 3:
        raise ValueError('qa_subjects_not_unique')
    value = {'mode': 'plan-v1', 'realm': 'pajio', 'subjects': sorted(subjects),
             'controller_inventory_sha256': hashlib.sha256(inventory_raw).hexdigest(),
             'controller_fence_sha256': hashlib.sha256(fence_raw).hexdigest()}
    if args.observed_plan:
        _, plan = private_read(args.observed_plan)
        if (plan['version'] != 1 or plan['realm'] != 'pajio' or plan['subjects'] != value['subjects']
                or any(plan[k] != value[k] for k in ('controller_inventory_sha256', 'controller_fence_sha256'))):
            raise ValueError('observed_plan_scope_changed')
        value.update(mode='apply-v1', plan_sha256=hashlib.sha256(canonical(plan)).hexdigest(),
                     accounts=[{k: row[k] for k in ('subject', 'username')} for row in plan['accounts']])
    data = canonical(value)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(data); out.flush(); os.fsync(out.fileno())
    parent = os.open(args.output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    print(json.dumps({'mode': value['mode'], 'account_count': 3, 'flag_sha256': hashlib.sha256(data).hexdigest(), 'installed': False}))


if __name__ == '__main__':
    main()
