#!/usr/bin/env python3
"""Re-encrypts sops files whose age recipients have drifted from .sops.yaml.

Run from the root of a secrets repo. For every sops-encrypted file in it,
works out which creation rule sops itself would apply (the first rule whose
path_regex matches the file's path relative to the config file) and compares
that rule's age recipients against the ones recorded in the file's own sops
metadata. Files that differ get `sops updatekeys`.

Both sides are read from plaintext - the config file, and the recipient list
sops stores unencrypted alongside the data - so finding stale files never
decrypts anything. Only `sops updatekeys` itself does, which needs whoever
runs this to be able to decrypt each file it touches.

Progress goes to stderr; the path of every re-encrypted file (relative to the
repo root) goes to stdout, one per line, so callers can stage them. With
--print-all, stdout lists every file considered instead, in sync or not - for
callers that also need to stage files an earlier, interrupted run already
re-encrypted.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

from ruamel.yaml import YAML

# Matches a recipient entry in sops metadata in every format sops writes:
# YAML `recipient: age1...`, JSON `"recipient": "age1..."`, dotenv
# `sops_age__list_0__map_recipient=age1...` and INI
# `age__list_0__map_recipient = age1...`. Binary files are stored as JSON.
RECIPIENT_RE = re.compile(r"recipient[\"']?\s*[:=]\s*[\"']?(age1[0-9a-z]+)")
# Every sops file carries an encrypted MAC in its metadata, in the same
# formats as above; plain files never do.
SOPS_MAC_RE = re.compile(r"mac[\"']?\s*[:=]\s*[\"']?ENC\[")


def split_keys(value) -> list[str]:
    """An `age:` value is either a YAML list or a comma-separated string."""
    if value is None:
        return []
    if isinstance(value, str):
        return [k.strip() for k in value.split(",") if k.strip()]
    return [str(k).strip() for k in value if str(k).strip()]


def rule_recipients(rule) -> set[str]:
    """Age recipients a creation rule asks for, in flat or key_groups form."""
    keys = split_keys(rule.get("age"))
    for group in rule.get("key_groups") or []:
        keys += split_keys(group.get("age"))
    return set(keys)


def matching_rule(creation_rules, rel_path: str):
    """The rule sops would use: the first whose path_regex matches (an absent
    path_regex matches everything), or None."""
    for rule in creation_rules:
        if re.search(rule.get("path_regex") or "", rel_path):
            return rule
    return None


def sops_compose_key(repo: Path, host: str) -> str:
    """The age key named `host` in sops-compose sources: `hosts.<host>` for a
    bare name, or any dotted key name (`workstations.laptop`)."""
    parts = host.split(".") if "." in host else ["hosts", host]
    file = repo / "sops" / "keys" / f"{parts[0]}.yaml"
    node = YAML(typ="safe").load(file) if file.exists() else None
    for part in parts[1:]:
        node = node.get(part) if isinstance(node, dict) else None
    if not isinstance(node, str):
        print(f"Error: no key named '{'.'.join(parts)}' in {file.relative_to(repo)}.", file=sys.stderr)
        sys.exit(1)
    return node.strip()


def host_key(data, host: str) -> str:
    """The age key anchored as `&host` under `keys:`."""
    for item in data.get("keys") or []:
        anchor = getattr(item, "anchor", None)
        if anchor is not None and anchor.value == host:
            return str(item).strip()
    print(f"Error: no key anchored as '&{host}' under 'keys:' in the sops config.", file=sys.stderr)
    sys.exit(1)


def find_files(repo: Path, config: Path, only_key: str | None):
    """Yields (rel_path, missing, extra) for every sops file with a creation
    rule; missing/extra are empty when its recipients already match. With
    only_key, limited to files whose rule includes that key."""
    yaml = YAML()
    with open(config) as f:
        data = yaml.load(f)
    creation_rules = data.get("creation_rules") or []

    for path in sorted(repo.rglob("*")):
        rel = path.relative_to(repo)
        if not path.is_file() or path.is_symlink() or ".git" in rel.parts or path == config:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        if not SOPS_MAC_RE.search(text):
            continue

        rule = matching_rule(creation_rules, rel.as_posix())
        if rule is None:
            continue
        wanted = rule_recipients(rule)
        if not wanted or (only_key and only_key not in wanted):
            continue

        actual = set(RECIPIENT_RE.findall(text))
        yield rel.as_posix(), wanted - actual, actual - wanted


def main():
    parser = argparse.ArgumentParser(
        description="Run 'sops updatekeys' on every file whose age recipients don't "
                    "match .sops.yaml. Run from the root of the secrets repo.")
    parser.add_argument("--host", help="Only files whose creation rule includes this host's "
                        "key: the '&host' anchor under 'keys:', or with sops-compose sources "
                        "(sops/rules.yaml) the key hosts.<host> (or a dotted key name)")
    parser.add_argument("--file", default=".sops.yaml",
                        help="The SOPS configuration file (default: .sops.yaml)")
    parser.add_argument("--dry-run", action="store_true",
                        help="List the stale files without re-encrypting them")
    parser.add_argument("--print-all", action="store_true",
                        help="Print every file considered, not just the re-encrypted ones")
    args = parser.parse_args()

    repo = Path.cwd()
    config = (repo / args.file).resolve()
    if not config.exists():
        print(f"Error: SOPS config '{args.file}' not found.", file=sys.stderr)
        sys.exit(1)

    only_key = None
    if args.host:
        if (repo / "sops" / "rules.yaml").is_file():
            only_key = sops_compose_key(repo, args.host)
        else:
            with open(config) as f:
                only_key = host_key(YAML().load(f), args.host)

    files = list(find_files(repo, config, only_key))
    stale = [f for f in files if f[1] or f[2]]
    if args.print_all:
        for rel, _, _ in files:
            print(rel)
    if not stale:
        print("All sops files already match their creation rules.", file=sys.stderr)
        return

    failed = []
    for rel, missing, extra in stale:
        print(f"{rel}: {len(missing)} recipient(s) to add, {len(extra)} to remove", file=sys.stderr)
        if args.dry_run:
            if not args.print_all:
                print(rel)
            continue

        cmd = ["sops"]
        if args.file != ".sops.yaml":
            cmd += ["--config", str(config)]
        cmd += ["updatekeys", "--yes", rel]
        # sops' own output is progress, not a result: keep it off stdout.
        result = subprocess.run(cmd, cwd=repo, stdout=sys.stderr, stderr=sys.stderr)
        if result.returncode != 0:
            failed.append(rel)
            continue
        if not args.print_all:
            print(rel, flush=True)

    if failed:
        print("Error: 'sops updatekeys' failed for: " + ", ".join(failed), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
