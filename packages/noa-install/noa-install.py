#!/usr/bin/env python3
#
# noa-install.py
#
# Provisions a new NixOS host with nixos-anywhere, bootstrapping its SSH host
# keys and sops age key in a companion secrets repo along the way.
#
# Run this from the root of your host-config flake (the one with
# `systems/<system>/<hostname>/`) - it builds `.#<hostname>` and drives
# nixos-anywhere against it.
#
# Settings can come from a config file instead of (or as well as) the command
# line - see load_layered_config() for the precedence order.
#
import argparse
import tempfile
import os
import sys
from contextlib import chdir
from pathlib import Path
import yaml
import delegator

# Fields settable via config file, and the CLI flag that can override each.
CONFIG_FIELDS = [
    "hostname", "ip", "user", "secrets_repo", "secrets_file", "secrets_input",
    "hardware_config", "system", "no_reboot", "ssh_port", "identity_file",
]

# Applied only after every config layer and the CLI have had a chance to set
# a field - so an unset field still gets this value, but any layer can
# override it (including a config file overriding a "false"/off default).
CONFIG_DEFAULTS = {
    "user": "root",
    "secrets_file": "secrets.yaml",
    "system": "x86_64-linux",
    "no_reboot": False,
}

# These paths are meant to be substituted by Nix during the build process.
# They allow the script to find the correct binaries in the Nix store.
NIX_BIN = "@nix@"
NIXOS_ANYWHERE_BIN = "@nixos_anywhere@"
SOPS_BIN = "@sops@"
CREATE_SSH_HOST_KEYS_BIN = "@create_ssh_host_keys@"
UPSERT_SOPS_AGE_KEY_BIN = "@upsert_sops_age_key@"

def run_command(command, input_data=None):
    """Helper function to run a command using delegator."""
    if isinstance(command, list):
        command = ' '.join(map(str, command))

    print(f"--- Running command: {command}", flush=True)

    # Use block=False to allow streaming if needed, though we primarily use it for simplicity here.
    c = delegator.run(command, block=False)

    if input_data:
        c.send(input_data)
        c.shutdown()

    # Stream output to console and capture it
    captured_output = []
    # In delegator, non-blocking commands use pexpect.PopenSpawn, which is iterable.
    for line in c.subprocess:
        print(line, end='', flush=True)
        captured_output.append(line)

    c.block()

    # Manually set the cached output to avoid delegator's buggy _pexpect_out
    out_str = "".join(captured_output)
    c._Command__out = out_str
    c._Command__err = out_str

    if c.return_code != 0:
        if c.err:
            print(c.err, file=sys.stderr, flush=True)
        print(f"Command failed with exit code {c.return_code}", file=sys.stderr, flush=True)
        sys.exit(1)

    return c


def parse_args():
    """Parses command-line arguments.

    Every field also settable via a config file (see CONFIG_FIELDS) defaults
    to None here, rather than its "real" default - that way, after parsing,
    we can tell "not passed on the CLI" (None) apart from "explicitly passed"
    and only let the CLI override a config-file value in the latter case.
    CONFIG_DEFAULTS supplies the real defaults once every layer has been
    merged.
    """
    parser = argparse.ArgumentParser(
        description="Provision a new NixOS machine using nixos-anywhere.",
        add_help=False  # Disable default help to avoid -h conflict
    )
    # Manually add arguments, including a non-conflicting help argument
    parser.add_argument(
        '--help',
        action='help',
        default=argparse.SUPPRESS,
        help='show this help message and exit'
    )
    parser.add_argument(
        "-h", "--hostname",
        default=None,
        help="Target hostname (required, unless set in a config file)"
    )
    parser.add_argument(
        "-i", "--ip",
        default=None,
        help="Target IP address (required, unless set in a config file)"
    )
    parser.add_argument(
        "-u", "--user",
        default=None,
        help="Target username (default: 'root')"
    )
    parser.add_argument(
        "-s", "--secrets-repo",
        default=None,
        help="Path to the sops secrets repository (must contain .sops.yaml, "
             "a secrets file, and systems/<hostname>/sshkeys/ once "
             "bootstrapped). Required, unless set in a config file"
    )
    parser.add_argument(
        "--secrets-file",
        default=None,
        help="Path, relative to --secrets-repo, of the file to run "
             "'sops updatekeys' against after adding a new age key "
             "(default: 'secrets.yaml')"
    )
    parser.add_argument(
        "--secrets-input",
        default=None,
        help="Name of the flake input, in the current directory's flake, that "
             "points at --secrets-repo. If set, 'nix flake update <name>' runs "
             "after bootstrapping so a freshly re-encrypted secrets file is "
             "picked up before nixos-anywhere evaluates the target config. "
             "Only useful when that input is a non-path (e.g. git) reference; "
             "omit if it's a local path input or you'll update it yourself."
    )
    parser.add_argument(
        "--hardware-config",
        default=None,
        help="Path to write the generated hardware config to (default: "
             "'./systems/<arch>/<hostname>/hardware.nix', matching a "
             "Snowfall-lib layout)"
    )
    parser.add_argument(
        "--system",
        default=None,
        help="Nix system/arch used to compute the default --hardware-config "
             "path (default: 'x86_64-linux')"
    )
    parser.add_argument(
        "--no-reboot",
        action="store_true",
        default=None,
        help="Skip rebooting the host after installation"
    )
    parser.add_argument(
        "-P", "--ssh-port",
        default=None,
        help="SSH port for the target host, if not 22 (passed to "
             "nixos-anywhere as --ssh-port)"
    )
    parser.add_argument(
        "-I", "--identity-file",
        default=None,
        help="SSH private key to authenticate to the target host with "
             "(passed to nixos-anywhere as -i). Omit to use your SSH "
             "agent/default keys"
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Extra config file to layer on top of the XDG and cwd config "
             "files (see load_layered_config), before command line arguments "
             "are applied. Errors if the given path doesn't exist."
    )
    return parser.parse_args()


def xdg_config_home():
    """The base directory for user config files, per the XDG Base Directory
    spec: $XDG_CONFIG_HOME, or ~/.config if that's unset."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))


def read_config_file(path):
    """Loads a config file's fields, normalizing hyphenated keys (matching
    CLI flag spelling, e.g. `secrets-repo:`) to the underscored field names
    used internally. Returns {} if the file doesn't exist."""
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return {k.replace("-", "_"): v for k, v in data.items()}


def load_layered_config(explicit_config_path):
    """Merges config files in increasing precedence: the XDG base config,
    then a `.noa-install.yaml` in the current directory, then --config if
    given. Each layer's fields override any earlier layer's; fields absent
    from a layer fall through to the next one down. Command line arguments
    are applied on top of this by the caller."""
    merged = {}

    merged.update(read_config_file(xdg_config_home() / "noa-install" / "config.yaml"))
    merged.update(read_config_file(Path.cwd() / ".noa-install.yaml"))

    if explicit_config_path:
        explicit_path = Path(explicit_config_path)
        if not explicit_path.exists():
            print(f"Error: --config file '{explicit_path}' not found.", file=sys.stderr)
            sys.exit(1)
        merged.update(read_config_file(explicit_path))

    return merged


def resolve_settings(args):
    """Combines config files and CLI arguments (CLI wins whenever a field was
    actually passed) into a plain dict of settings, applying CONFIG_DEFAULTS
    for anything still unset, and validating the fields with no default."""
    settings = {field: None for field in CONFIG_FIELDS}
    settings.update(CONFIG_DEFAULTS)
    settings.update(load_layered_config(args.config))

    for field in CONFIG_FIELDS:
        cli_value = getattr(args, field)
        if cli_value is not None:
            settings[field] = cli_value

    required_flags = {
        "hostname": "-h/--hostname",
        "ip": "-i/--ip",
        "secrets_repo": "-s/--secrets-repo",
    }
    missing = [flag for field, flag in required_flags.items() if not settings.get(field)]
    if missing:
        print(
            f"Error: missing required option(s): {', '.join(missing)} "
            "(pass on the command line, or set in a config file)",
            file=sys.stderr,
        )
        sys.exit(1)

    return settings


def ensure_ssh_keys(hostname, secrets_repo_path, ed25519_key_path, rsa_key_path):
    """Checks if SSH keys exist and generates them if necessary."""
    keys_existed = ed25519_key_path.exists() and rsa_key_path.exists()
    if keys_existed:
        print("--- SSH host keys already exist. Skipping creation. ---", flush=True)
        return keys_existed

    print("--- SSH host keys not found. Will generate them. ---", flush=True)

    with chdir(secrets_repo_path):
        run_command([CREATE_SSH_HOST_KEYS_BIN, hostname])

    return keys_existed


def update_sops_config(hostname, secrets_repo_path, secrets_file):
    """Adds the new host's age key to .sops.yaml and reencrypts secrets."""
    with chdir(secrets_repo_path):
        print("--- Adding new host age key to SOPS configuration ---", flush=True)
        run_command([UPSERT_SOPS_AGE_KEY_BIN, hostname, "--target", secrets_file])
        print(f"--- Reencrypting {secrets_file} for new age keys ---", flush=True)
        run_command([SOPS_BIN, "updatekeys", "--yes", secrets_file])


def update_secrets_input(secrets_input):
    """Updates the secrets flake input in the current directory's flake."""
    print(f"--- Updating flake input '{secrets_input}' ---", flush=True)
    run_command([NIX_BIN, "flake", "update", secrets_input])


def stage_ssh_keys(temp_path, ed25519_key_path, rsa_key_path):
    """Stages SSH keys in the temporary directory for nixos-anywhere."""
    ssh_dir = temp_path / "etc" / "ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)

    print("--- Staging SSH host keys for nixos-anywhere ---", flush=True)

    # Decrypt keys using SOPS and write to temp dir
    res_ed25519 = run_command([SOPS_BIN, "-d", str(ed25519_key_path)])
    ed25519_keys = yaml.safe_load(res_ed25519.out)

    res_rsa = run_command([SOPS_BIN, "-d", str(rsa_key_path)])
    rsa_keys = yaml.safe_load(res_rsa.out)

    # Write ed25519 keys
    (ssh_dir / "ssh_host_ed25519_key").write_text(ed25519_keys['private_key'])
    (ssh_dir / "ssh_host_ed25519_key.pub").write_text(ed25519_keys['public_key'])

    # Write rsa keys
    (ssh_dir / "ssh_host_rsa_key").write_text(rsa_keys['private_key'])
    (ssh_dir / "ssh_host_rsa_key.pub").write_text(rsa_keys['public_key'])

    # Set correct permissions for private keys
    (ssh_dir / "ssh_host_ed25519_key").chmod(0o600)
    (ssh_dir / "ssh_host_rsa_key").chmod(0o600)


def run_nixos_anywhere(hostname, user, ip, hw_cfg, temp_path, no_reboot=False, ssh_port=None, identity_file=None):
    """Runs the nixos-anywhere command to provision the system."""
    print("--- Running nixos-anywhere ---", flush=True)
    nixos_anywhere_cmd = [
        NIXOS_ANYWHERE_BIN,
        "--extra-files", str(temp_path),
        "--flake", f".#{hostname}",
        "--target-host", f"{user}@{ip}",
        "--generate-hardware-config", "nixos-generate-config", hw_cfg
    ]

    if ssh_port:
        nixos_anywhere_cmd.extend(["--ssh-port", str(ssh_port)])

    if identity_file:
        nixos_anywhere_cmd.extend(["-i", identity_file])

    if no_reboot:
        nixos_anywhere_cmd.extend(["--phases", "kexec,disko,install"])

    run_command(nixos_anywhere_cmd)


def main():
    """Main function for the noa-install script."""
    args = parse_args()
    settings = resolve_settings(args)

    hw_cfg = settings["hardware_config"] or \
        f"./systems/{settings['system']}/{settings['hostname']}/hardware.nix"

    print("--- Configuration ---")
    print(f"Target Hostname: {settings['hostname']}")
    print(f"Target IP:       {settings['ip']}")
    print(f"Target User:     {settings['user']}")
    print(f"Secrets Repo:    {settings['secrets_repo']}")
    print(f"Hardware Config: {hw_cfg}")
    print("---------------------", flush=True)

    secrets_repo_path = Path(settings["secrets_repo"])
    keys_base_path = secrets_repo_path / "systems" / settings["hostname"] / "sshkeys"
    ed25519_key_path = keys_base_path / "ed25519.yaml"
    rsa_key_path = keys_base_path / "rsa.yaml"

    keys_existed = ensure_ssh_keys(settings["hostname"], secrets_repo_path, ed25519_key_path, rsa_key_path)

    if not keys_existed:
        update_sops_config(settings["hostname"], secrets_repo_path, settings["secrets_file"])

    if settings["secrets_input"]:
        update_secrets_input(settings["secrets_input"])

    # Use a temporary directory to stage the keys for nixos-anywhere
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        stage_ssh_keys(temp_path, ed25519_key_path, rsa_key_path)
        run_nixos_anywhere(
            settings["hostname"], settings["user"], settings["ip"], hw_cfg, temp_path,
            no_reboot=settings["no_reboot"],
            ssh_port=settings["ssh_port"],
            identity_file=settings["identity_file"],
        )

    print("--- Installation complete! ---", flush=True)


if __name__ == "__main__":
    main()
