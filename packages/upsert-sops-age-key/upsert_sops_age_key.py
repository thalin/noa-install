#!/usr/bin/env python3
import argparse
import os
import re
import sys
import subprocess

import delegator
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import PlainScalarString


def get_age_key_from_ssh(host: str) -> str:
    """Derives an age key from an existing SSH host key."""
    ssh_sops_file = f"systems/{host}/sshkeys/ed25519.yaml"
    if not os.path.exists(ssh_sops_file):
        print(f"Error: SSH host key file '{ssh_sops_file}' not found for host '{host}'.", file=sys.stderr)
        return None

    print(f"Deriving age key from SSH host key in '{ssh_sops_file}'...")

    cmd = f"sops decrypt --extract '[\"public_key\"]' {ssh_sops_file}"
    c = delegator.run(cmd)
    if c.return_code != 0:
        print(f"Error: Failed to extract public key from {ssh_sops_file}", file=sys.stderr)
        return None

    ssh_pub_key = c.out.strip()
    if not ssh_pub_key:
        print(f"Error: Public key extracted from {ssh_sops_file} is empty", file=sys.stderr)
        return None

    result = subprocess.run(["ssh-to-age"], input=ssh_pub_key, text=True, capture_output=True)
    if result.returncode != 0:
        print(f"Error: Failed to convert SSH key to age key: {result.stderr}", file=sys.stderr)
        return None

    return result.stdout.strip()


def find_anchor(keys_seq: CommentedSeq, name: str):
    """Finds the existing `keys:` entry anchored as `name`, if any."""
    for item in keys_seq:
        anchor = getattr(item, "anchor", None)
        if anchor is not None and anchor.value == name:
            return item
    return None


def replace_node(container, old, new):
    """Replaces every occurrence of `old` (by identity) with `new`, walking
    the whole document. Needed because ruamel's anchored scalars are
    immutable strings: rotating a host's key means building a new node and
    re-pointing every existing alias at it, not editing the old one in place.
    """
    if isinstance(container, CommentedSeq):
        for i, item in enumerate(container):
            if item is old:
                container[i] = new
            else:
                replace_node(item, old, new)
    elif isinstance(container, CommentedMap):
        for key, value in container.items():
            if value is old:
                container[key] = new
            else:
                replace_node(value, old, new)


def upsert_key_anchor(data: CommentedMap, host: str, age_key: str):
    """Adds or updates the `&host age1...` entry under `keys:`, returning the
    node to reuse (by identity) everywhere `*host` should appear."""
    if data.get("keys") is None:
        data["keys"] = CommentedSeq()
    keys_seq = data["keys"]

    node = PlainScalarString(age_key)
    node.yaml_set_anchor(host, always_dump=True)

    existing = find_anchor(keys_seq, host)
    if existing is not None:
        idx = next(i for i, item in enumerate(keys_seq) if item is existing)
        keys_seq[idx] = node
        replace_node(data, existing, node)
        print(f"Host '{host}' key definition found, updated key value.")
    else:
        keys_seq.append(node)
        print(f"Host '{host}' key definition not found, added new entry under 'keys:'.")

    return node


def ensure_alias_in_targets(data: CommentedMap, host: str, node, targets: list[str]):
    """Ensures `*host` is referenced in the age recipients of every
    creation_rule whose path_regex matches one of `targets` - the actual
    secrets file(s) this host's key should grant access to, not just
    whichever `age:` group happens to appear first in the file.

    Supports both the flat `age:` list form and the legacy `key_groups:`
    form. For the flat form, appending directly to the rule's `age` list
    is enough even when it's an alias (e.g. `age: *all` referencing a
    named group under `keygroups:`) - ruamel constructs one shared object
    per anchor, so mutating the alias mutates the anchor's list too, and
    every other rule aliasing the same group picks up the change as well.
    """
    creation_rules = data.get("creation_rules") or []
    matched_any = False

    def already_present(age_list):
        return any(
            item is node or (getattr(item, "anchor", None) and item.anchor.value == host)
            for item in age_list
        )

    for rule in creation_rules:
        path_regex = rule.get("path_regex", "")
        if not any(re.search(path_regex, target) for target in targets):
            continue
        matched_any = True

        age_list = rule.get("age")
        if isinstance(age_list, CommentedSeq):
            if already_present(age_list):
                print(f"Host '{host}' already referenced in rule '{path_regex}'. No change needed.")
            else:
                age_list.append(node)
                print(f"Added '{host}' reference to rule '{path_regex}'.")
            continue

        key_groups = rule.get("key_groups")
        if not key_groups:
            print(f"WARNING: creation rule '{path_regex}' matched but has no 'age:' list or "
                  f"key_groups; add '{host}' to it manually.", file=sys.stderr)
            continue

        for group in key_groups:
            group_age = group.get("age")
            if group_age is None:
                continue

            if already_present(group_age):
                print(f"Host '{host}' already referenced in rule '{path_regex}'. No change needed.")
                continue

            group_age.append(node)
            print(f"Added '{host}' reference to rule '{path_regex}'.")

    if not matched_any:
        print(f"WARNING: no creation_rules matched targets {targets}; "
              f"add '{host}' to the relevant rule(s) manually.", file=sys.stderr)


def upsert_age_key(host: str, age_key: str, sops_file: str, targets: list[str]):
    if not os.path.exists(sops_file):
        print(f"Error: SOPS file '{sops_file}' not found in the current directory.", file=sys.stderr)
        sys.exit(1)

    if not age_key:
        age_key = get_age_key_from_ssh(host)
        if not age_key:
            print(f"Error: No age key provided and could not derive one from SSH host keys for '{host}'.", file=sys.stderr)
            sys.exit(1)
        print(f"Derived age key: {age_key}")

    print(f"Updating SOPS age key for host '{host}' in '{sops_file}'...")

    yaml = YAML()
    yaml.preserve_quotes = True
    # Matches the dominant indent style already used in .sops.yaml files in
    # this ecosystem (2-space mapping indent, sequences indented 2 further
    # with the dash offset by 2). Deeply-nested sequences that were hand
    # written flush against their key will get reformatted to this on first
    # write - a one-time cosmetic diff, not a functional change.
    yaml.indent(mapping=2, sequence=4, offset=2)

    with open(sops_file) as f:
        data = yaml.load(f)

    node = upsert_key_anchor(data, host, age_key)
    ensure_alias_in_targets(data, host, node, targets)

    with open(sops_file, "w") as f:
        yaml.dump(data, f)

    print(f"SOPS file '{sops_file}' processing complete for host '{host}'.")


def main():
    parser = argparse.ArgumentParser(description="Upsert a SOPS age key into .sops.yaml")
    parser.add_argument("host", help="The host name (anchor name)")
    parser.add_argument("agekey", nargs="?", help="The age public key (optional, will try to derive from SSH host keys if omitted)")
    parser.add_argument("--file", default=".sops.yaml", help="The SOPS configuration file (default: .sops.yaml)")
    parser.add_argument(
        "--target",
        action="append",
        default=None,
        help="Path whose creation_rules should reference this host's key, matched "
             "against each rule's path_regex. Repeatable. Default: 'secrets.yaml'"
    )

    args = parser.parse_args()
    targets = args.target or ["secrets.yaml"]
    upsert_age_key(args.host, args.agekey, args.file, targets)


if __name__ == "__main__":
    main()
