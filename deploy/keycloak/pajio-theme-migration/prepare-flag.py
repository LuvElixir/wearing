#!/usr/bin/env python3
"""Prepare a local review flag only; never installs or contacts Keycloak."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

THEME_FILES = frozenset(('theme.properties', 'resources/img/pajio-wordmark.svg',
    'resources/js/pajio.js', 'resources/css/pajio-base.css', 'resources/css/pajio-identity.css',
    'messages/messages_zh_CN.properties', 'messages/messages_en.properties'))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def no_symlink(path):
    for part in (path.absolute(), *path.absolute().parents):
        if part.is_symlink():
            raise ValueError('symlink_input')


def read(path, *, private=False):
    no_symlink(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 262144
                or stat.S_IMODE(info.st_mode) & 0o022
                or private and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600)):
            raise ValueError('input_boundary')
        raw = os.read(fd, 262145)
        if len(raw) > 262144:
            raise ValueError('input_size')
        return raw
    finally:
        os.close(fd)


def theme_hash(root):
    no_symlink(root)
    if not root.is_dir():
        raise ValueError('theme_missing')
    manifest = {}
    for entry in root.rglob('*'):
        no_symlink(entry)
        if entry.is_dir():
            continue
        relative = entry.relative_to(root).as_posix()
        if relative not in THEME_FILES:
            raise ValueError('theme_extra_file')
        manifest[relative] = hashlib.sha256(read(entry)).hexdigest()
    if set(manifest) != THEME_FILES:
        raise ValueError('theme_file_set')
    return hashlib.sha256(canonical(manifest)).hexdigest()


def flag_for(theme, plan=None):
    value = {'mode': 'plan-v1', 'realm': 'pajio', 'theme_sha256': theme}
    if plan is not None:
        required = {'version', 'realm', 'realm_id', 'theme_sha256', 'before', 'after', 'guards'}
        if (not isinstance(plan, dict) or set(plan) != required or type(plan['version']) is not int
                or plan['version'] != 1 or plan['realm'] != 'pajio' or not isinstance(plan['realm_id'], str)
                or not plan['realm_id'] or plan['theme_sha256'] != theme):
            raise ValueError('observed_plan_scope')
        fields = {'login_theme', 'default_locale', 'internationalization', 'supported_locales'}
        before = plan['before']
        if (not isinstance(before, dict) or set(before) != fields
                or not isinstance(before['supported_locales'], list)
                or any(not isinstance(x, str) for x in before['supported_locales'])):
            raise ValueError('observed_presentation')
        expected = {'login_theme': 'pajio', 'default_locale': 'zh-CN', 'internationalization': True,
                    'supported_locales': sorted(set(before['supported_locales']) | {'zh-CN', 'en'})}
        guards = plan['guards']
        if (plan['after'] != expected or not isinstance(guards, dict)
                or set(guards) != {'profile_sha256', 'verify_email', 'reset_password', 'standard_flow',
                                  'security_headers_sha256', 'required_actions_sha256'}):
            raise ValueError('observed_target_or_guards')
        value.update(mode='apply-v1', plan_sha256=hashlib.sha256(canonical(plan)).hexdigest())
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--theme-dir', type=Path, required=True)
    parser.add_argument('--observed-plan', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(read(args.observed_plan, private=True)) if args.observed_plan else None
    value = flag_for(theme_hash(args.theme_dir), plan)
    raw = canonical(value)
    no_symlink(args.output.parent)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(raw); out.flush(); os.fsync(out.fileno())
    parent = os.open(args.output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    print(json.dumps({'mode': value['mode'], 'theme_sha256': value['theme_sha256'],
                      'flag_sha256': hashlib.sha256(raw).hexdigest(), 'installed': False}))


if __name__ == '__main__':
    main()
