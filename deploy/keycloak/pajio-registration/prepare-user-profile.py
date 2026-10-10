#!/usr/bin/env python3
"""Prepare a reviewed JSON candidate from an existing profile. No network or apply."""
import copy
import json
import pathlib
import sys


def prepare(profile):
    candidate = copy.deepcopy(profile)
    attributes = candidate.get("attributes")
    if not isinstance(attributes, list) or not all(isinstance(a, dict) for a in attributes):
        raise ValueError("profile attributes must be an array of objects")
    names = [a.get("name") for a in attributes]
    if not all(isinstance(n, str) for n in names) or len(set(names)) != len(names):
        raise ValueError("profile contains invalid or duplicate names")
    if not {"username", "email", "firstName", "lastName"} <= set(names):
        raise ValueError("expected existing core profile attributes")
    for attribute in attributes:
        if attribute["name"] in {"email", "firstName", "lastName"}:
            attribute.pop("required", None)
    for name, length in (("pajio_registration_id", 32), ("pajio_registration_fingerprint", 64)):
        existing = next((a for a in attributes if a["name"] == name), None)
        if existing is not None:
            raise ValueError("registration attributes already exist; review their existing semantics manually")
        attributes.append({
            "name": name,
            "permissions": {"view": ["admin"], "edit": ["admin"]},
            "validations": {"length": {"min": length, "max": length},
                            "pattern": {"pattern": "[a-f0-9]{%d}" % length}},
        })
    return candidate


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: prepare-user-profile.py existing-profile.json new-candidate.json")
    source, destination = map(pathlib.Path, sys.argv[1:])
    result = prepare(json.loads(source.read_text()))
    with destination.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
