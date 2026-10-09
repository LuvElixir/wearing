#!/usr/bin/python3
"""Metadata-only service continuity evidence. Never performs a model/tool task."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.request

STATE = Path('/var/lib/pajio-health')
SERVICES = {
    1100: ['nginx', 'pajio-gateway', 'pajio-identity', 'postgresql@16-main'],
    1101: ['nginx', 'wearing-tenant', 'pajio-device-relay'],
    1102: ['nginx', 'wearing-tenant', 'pajio-device-relay'],
    1111: ['nginx', 'pajio-private-media'],
    1112: ['nginx', 'pajio-private-media', 'pajio-phone-adb', 'docker'],
    1211: ['nginx', 'pajio-private-media'],
    1212: ['nginx', 'pajio-private-media', 'pajio-phone-adb', 'docker'],
}


def guest(vmid):
    try:
        result = subprocess.run(['qm', 'guest', 'exec', str(vmid), '--timeout', '8', '--',
            '/usr/bin/systemctl', 'is-active', *SERVICES[vmid]],
            capture_output=True, timeout=12, text=True, check=True)
        value = json.loads(result.stdout)
        states = value.get('out-data', '').splitlines()
        return {'vmid': vmid, 'healthy': value.get('exitcode') == 0
                and len(states) == len(SERVICES[vmid]) and all(s == 'active' for s in states),
                'services': dict(zip(SERVICES[vmid], states))}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {'vmid': vmid, 'healthy': False, 'code': 'guest_probe_unavailable'}


def oidc():
    try:
        url = 'https://id.pajio.luckyloading.com/realms/pajio/.well-known/openid-configuration'
        with urllib.request.urlopen(url, timeout=10) as response:
            value = json.loads(response.read(65536))
            return response.status == 200 and value.get('issuer') == 'https://id.pajio.luckyloading.com/realms/pajio'
    except (OSError, ValueError):
        return False


def uninterrupted_seconds(rows):
    """A missed timer, failed check or clock discontinuity breaks the evidence window."""
    start = previous = None
    scope = None
    for row in rows:
        at = row['at']
        if not row['healthy']:
            start = previous = None
            continue
        current_scope = row.get('scope_sha256')
        if previous is None or not 0 < at - previous <= 180 or current_scope != scope:
            start = at
        scope = current_scope
        previous = at
    return max(0, previous - start) if previous is not None else 0


def main():
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        guests = list(pool.map(guest, SERVICES))
        public_oidc = oidc()
    row = {'at': int(start), 'duration_seconds': round(time.time() - start, 2),
           'healthy': public_oidc and all(x['healthy'] for x in guests),
           'public_oidc_tls': public_oidc, 'guests': guests,
           'scope_sha256': hashlib.sha256(json.dumps(SERVICES, sort_keys=True).encode()).hexdigest(),
           'scope': 'infrastructure_only', 'model_or_app_acceptance': False}
    history = STATE / 'history.jsonl'
    try:
        rows = [json.loads(x) for x in history.read_text().splitlines()][-10079:]
    except (OSError, ValueError):
        rows = []
    rows.append(row)
    row['continuous_healthy_seconds'] = uninterrupted_seconds(rows)
    row['infrastructure_48h_observed'] = row['continuous_healthy_seconds'] >= 48 * 3600
    for path, text in [(history, ''.join(json.dumps(x) + '\n' for x in rows)),
                       (STATE / 'latest.json', json.dumps(row, indent=2))]:
        temporary = path.with_suffix('.tmp')
        temporary.write_text(text)
        temporary.chmod(0o600)
        temporary.replace(path)
    print(json.dumps({'healthy': row['healthy'], 'infrastructure_48h_observed': row['infrastructure_48h_observed']}))
    return 0 if row['healthy'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
