import subprocess

import yaml

from conftest import SYNC_SOPS_RECIPIENTS, UPSERT_SOPS_AGE_KEY, decrypt_yaml, run_py

SOPS_YAML = """\
keys:
  - &admin {admin}
  - &demo-vm {host}
keygroups:
  all: &all
    - *admin
    - *demo-vm
creation_rules:
  - path_regex: secrets\\.yaml
    age: *all
  - path_regex: 'systems/demo-vm/private/.*$'
    age:
      - *admin
  - path_regex: 'systems/demo-vm/.*$'
    age: *all
  - path_regex: 'admin-only/.*$'
    age:
      - *admin
"""


def encrypt(repo, rel, env, content="value: secret\n", age=None):
    """Writes and sops-encrypts rel. With age, encrypts to exactly those
    recipients instead of the ones .sops.yaml asks for - i.e. a file that
    has drifted from its creation rule."""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    cmd = ["sops", "encrypt", "-i"]
    if age:
        cmd += ["--age", ",".join(age)]
    subprocess.run([*cmd, rel], cwd=repo, env=env, check=True, capture_output=True, text=True)
    return path


def recipients(path):
    return {entry["recipient"] for entry in yaml.safe_load(path.read_text())["sops"]["age"]}


def setup_repo(tmp_path, age_identity, second_age_identity, sops_env):
    """A repo where demo-vm's key is in .sops.yaml, but the files were all
    encrypted before it was added (admin only)."""
    admin, host = age_identity["public_key"], second_age_identity["public_key"]
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".sops.yaml").write_text(SOPS_YAML.format(admin=admin, host=host))
    for rel in ["secrets.yaml", "systems/demo-vm/app.yaml",
                "systems/demo-vm/private/key.yaml", "admin-only/thing.yaml"]:
        encrypt(repo, rel, sops_env, age=[admin])
    (repo / "README.md").write_text("not a sops file: recipient: age1notreal\n")
    return repo, admin, host


def test_reencrypts_only_files_whose_rule_includes_the_host(tmp_path, age_identity, second_age_identity, sops_env):
    repo, admin, host = setup_repo(tmp_path, age_identity, second_age_identity, sops_env)
    untouched = {rel: (repo / rel).read_text() for rel in
                 ["systems/demo-vm/private/key.yaml", "admin-only/thing.yaml", "README.md"]}

    result = run_py(SYNC_SOPS_RECIPIENTS, ["--host", "demo-vm"], cwd=repo, env=sops_env)
    assert result.returncode == 0, result.stderr

    # stdout is exactly the re-encrypted files, for callers to stage
    assert result.stdout.splitlines() == ["secrets.yaml", "systems/demo-vm/app.yaml"]
    for rel in ["secrets.yaml", "systems/demo-vm/app.yaml"]:
        assert recipients(repo / rel) == {admin, host}
        assert decrypt_yaml(repo / rel, cwd=repo, env=sops_env) == {"value": "secret"}
    # systems/demo-vm/private/ matches the admin-only rule *first*, the way
    # sops applies rules, even though the broader systems/demo-vm/ rule
    # below it includes the host
    for rel, text in untouched.items():
        assert (repo / rel).read_text() == text


def test_rerun_is_a_no_op(tmp_path, age_identity, second_age_identity, sops_env):
    repo, _, _ = setup_repo(tmp_path, age_identity, second_age_identity, sops_env)
    run_py(SYNC_SOPS_RECIPIENTS, ["--host", "demo-vm"], cwd=repo, env=sops_env)
    before = (repo / "secrets.yaml").read_text()

    result = run_py(SYNC_SOPS_RECIPIENTS, ["--host", "demo-vm"], cwd=repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert "already match" in result.stderr
    assert (repo / "secrets.yaml").read_text() == before


def test_print_all_lists_in_sync_files_too(tmp_path, age_identity, second_age_identity, sops_env):
    repo, _, _ = setup_repo(tmp_path, age_identity, second_age_identity, sops_env)
    run_py(SYNC_SOPS_RECIPIENTS, ["--host", "demo-vm"], cwd=repo, env=sops_env)

    result = run_py(SYNC_SOPS_RECIPIENTS, ["--host", "demo-vm", "--print-all"], cwd=repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["secrets.yaml", "systems/demo-vm/app.yaml"]


def test_dry_run_lists_without_changing_anything(tmp_path, age_identity, second_age_identity, sops_env):
    repo, admin, _ = setup_repo(tmp_path, age_identity, second_age_identity, sops_env)

    result = run_py(SYNC_SOPS_RECIPIENTS, ["--host", "demo-vm", "--dry-run"], cwd=repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["secrets.yaml", "systems/demo-vm/app.yaml"]
    assert recipients(repo / "secrets.yaml") == {admin}


def test_without_host_syncs_every_file(tmp_path, age_identity, second_age_identity, sops_env):
    repo, admin, host = setup_repo(tmp_path, age_identity, second_age_identity, sops_env)
    # drift the other way too: an extra recipient the rule doesn't list
    encrypt(repo, "admin-only/thing.yaml", sops_env, age=[admin, host])

    result = run_py(SYNC_SOPS_RECIPIENTS, [], cwd=repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "admin-only/thing.yaml", "secrets.yaml", "systems/demo-vm/app.yaml"]
    assert recipients(repo / "admin-only/thing.yaml") == {admin}


def test_rotated_host_key_drops_the_old_one(tmp_path, age_identity, second_age_identity, sops_env):
    # The es1 reinstall case: the host's anchor gets a new key, and every file
    # still encrypted to the old one has to swap it for the new one.
    repo, admin, old_host = setup_repo(tmp_path, age_identity, second_age_identity, sops_env)
    run_py(SYNC_SOPS_RECIPIENTS, ["--host", "demo-vm"], cwd=repo, env=sops_env)

    from conftest import generate_age_identity
    new_host = generate_age_identity(tmp_path / "rotated-key.txt")["public_key"]
    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", new_host], cwd=repo, env=sops_env)
    assert result.returncode == 0, result.stderr

    result = run_py(SYNC_SOPS_RECIPIENTS, ["--host", "demo-vm"], cwd=repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["secrets.yaml", "systems/demo-vm/app.yaml"]
    assert recipients(repo / "secrets.yaml") == {admin, new_host}


def test_errors_when_host_has_no_key(tmp_path, age_identity, second_age_identity, sops_env):
    repo, _, _ = setup_repo(tmp_path, age_identity, second_age_identity, sops_env)
    result = run_py(SYNC_SOPS_RECIPIENTS, ["--host", "nope"], cwd=repo, env=sops_env)
    assert result.returncode == 1
    assert "no key anchored as '&nope'" in result.stderr


def test_fails_when_updatekeys_fails(tmp_path, age_identity, second_age_identity, sops_env):
    # A file the operator can't decrypt can't be re-keyed; that has to fail
    # loudly rather than leave the host unable to read it on first boot.
    repo, _, host = setup_repo(tmp_path, age_identity, second_age_identity, sops_env)
    encrypt(repo, "systems/demo-vm/app.yaml", sops_env, age=[host])

    result = run_py(SYNC_SOPS_RECIPIENTS, ["--host", "demo-vm"], cwd=repo, env=sops_env)
    assert result.returncode == 1
    assert "failed for: systems/demo-vm/app.yaml" in result.stderr
    assert result.stdout.splitlines() == ["secrets.yaml"]
