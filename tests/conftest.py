import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES = REPO_ROOT / "packages"

SOPS_UTILS_DIR = PACKAGES / "sops-utils"
CREATE_SSH_HOST_KEYS = PACKAGES / "create-ssh-host-keys" / "create_ssh_host_keys.py"
UPSERT_SOPS_AGE_KEY = PACKAGES / "upsert-sops-age-key" / "upsert_sops_age_key.py"
NOA_INSTALL = PACKAGES / "noa-install" / "noa-install.py"

DEFAULT_SOPS_YAML = """\
keys:
  - &admin {admin_pubkey}
keygroups:
  all: &all
    - *admin
creation_rules:
  - path_regex: secrets\\.yaml
    age: *all
  - path_regex: 'systems/.*/sshkeys/.*\\.yaml'
    age:
      - *admin
"""


def run_py(script, args, cwd, env):
    """Runs one of this repo's scripts (not executable, no shebang wrapper in
    the source tree) the same way the Nix-built wrapper eventually would."""
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd, env=env, capture_output=True, text=True,
    )


def decrypt_yaml(path, cwd, env):
    """Decrypts a sops file and parses it as YAML."""
    result = subprocess.run(
        ["sops", "decrypt", str(path)],
        cwd=cwd, env=env, capture_output=True, text=True, check=True,
    )
    return yaml.safe_load(result.stdout)


def write_sops_config(path, admin_pubkey):
    """Writes a minimal .sops.yaml matching the shape used throughout this
    ecosystem: one admin identity, a `secrets.yaml` rule, and a
    `systems/*/sshkeys/*.yaml` rule."""
    path.write_text(DEFAULT_SOPS_YAML.format(admin_pubkey=admin_pubkey))


def load_noa_install_module():
    """Loads a fresh copy of noa-install.py as an importable module, despite
    the hyphen in its filename and its `@placeholder@` BIN constants (which
    tests overwrite directly on the returned module object). A fresh load
    per call avoids cross-test state leaking through monkeypatched globals."""
    spec = importlib.util.spec_from_file_location("noa_install_under_test", NOA_INSTALL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate_age_identity(key_file):
    """Generates a real age keypair at key_file, valid enough for sops to
    actually encrypt to (unlike the placeholder KEY_1/KEY_2 strings tests use
    when only exercising upsert-sops-age-key's YAML editing, not real crypto)."""
    subprocess.run(["age-keygen", "-o", str(key_file)], capture_output=True, text=True, check=True)

    pubkey = None
    for line in key_file.read_text().splitlines():
        if line.startswith("# public key:"):
            pubkey = line.split(":", 1)[1].strip()
    assert pubkey, f"could not find public key comment in {key_file}"

    return {"private_key_file": key_file, "public_key": pubkey}


@pytest.fixture
def age_identity(tmp_path):
    """A fresh age keypair to use as a secrets repo's admin identity."""
    return generate_age_identity(tmp_path / "admin-key.txt")


@pytest.fixture
def second_age_identity(tmp_path):
    """A second, independent real age keypair - e.g. to stand in for a newly
    bootstrapped host's key in tests that need sops to actually encrypt to it."""
    return generate_age_identity(tmp_path / "second-key.txt")


@pytest.fixture
def sops_env(age_identity):
    """Environment for subprocess calls that need to decrypt/encrypt as the
    admin identity and, for scripts that `import sops_utils`, find it."""
    env = os.environ.copy()
    env["SOPS_AGE_KEY_FILE"] = str(age_identity["private_key_file"])
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in [str(SOPS_UTILS_DIR), env.get("PYTHONPATH")] if p
    )
    return env


@pytest.fixture
def secrets_repo(tmp_path, age_identity, sops_env):
    """A minimal secrets repo: .sops.yaml plus an actual sops-encrypted
    secrets.yaml, closely mirroring the real nix-secrets layout."""
    repo = tmp_path / "secrets-repo"
    repo.mkdir()
    write_sops_config(repo / ".sops.yaml", age_identity["public_key"])

    (repo / "secrets.yaml").write_text("example_secret: replace-me\n")
    subprocess.run(
        ["sops", "encrypt", "-i", "secrets.yaml"],
        cwd=repo, env=sops_env, check=True, capture_output=True, text=True,
    )
    return repo
