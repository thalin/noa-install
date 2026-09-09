import yaml
from ruamel.yaml import YAML

from conftest import CREATE_SSH_HOST_KEYS, UPSERT_SOPS_AGE_KEY, decrypt_yaml, run_py, write_sops_config

KEY_1 = "age1testkey0000000000000000000000000000000000000000000000000000"
KEY_2 = "age1differentkey1111111111111111111111111111111111111111111111"


def load(sops_yaml_path):
    return yaml.safe_load(sops_yaml_path.read_text())


def rule(data, path_regex):
    return next(r for r in data["creation_rules"] if r["path_regex"] == path_regex)


def test_adds_new_host_to_matching_target_only(secrets_repo, sops_env):
    sops_yaml = secrets_repo / ".sops.yaml"

    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_1, "--target", "secrets.yaml"],
                     cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert "added new entry under 'keys:'" in result.stdout

    data = load(sops_yaml)
    assert KEY_1 in data["keys"]
    assert KEY_1 in rule(data, "secrets\\.yaml")["age"]
    # the sshkeys rule was NOT targeted - old brittle "first age: group" logic
    # would have added it there too
    assert KEY_1 not in rule(data, "systems/.*/sshkeys/.*\\.yaml")["age"]

    # exactly one anchor definition, no stray duplicates
    assert sops_yaml.read_text().count("&demo-vm ") == 1


def test_new_host_lands_in_shared_keygroup_not_a_private_copy(secrets_repo, sops_env):
    # secrets.yaml's `age:` is `*all`, aliasing keygroups.all - appending must
    # mutate that shared list (so any other rule aliasing *all also picks up
    # the new host), not just the rule's own view of it.
    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_1, "--target", "secrets.yaml"],
                     cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr

    data = load(secrets_repo / ".sops.yaml")
    assert KEY_1 in data["keygroups"]["all"]


def test_rerun_identical_is_idempotent(secrets_repo, sops_env):
    args = ["demo-vm", KEY_1, "--target", "secrets.yaml"]
    run_py(UPSERT_SOPS_AGE_KEY, args, cwd=secrets_repo, env=sops_env)
    before = (secrets_repo / ".sops.yaml").read_text()

    result = run_py(UPSERT_SOPS_AGE_KEY, args, cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0
    assert "already referenced" in result.stdout
    assert "No change needed" in result.stdout

    after = (secrets_repo / ".sops.yaml").read_text()
    assert before == after
    assert after.count("demo-vm") == 2  # one anchor def, one alias - no duplication


def test_multiple_targets_in_one_call(secrets_repo, sops_env):
    result = run_py(UPSERT_SOPS_AGE_KEY, [
        "demo-vm", KEY_1,
        "--target", "secrets.yaml",
        "--target", "systems/demo-vm/sshkeys/ed25519.yaml",
    ], cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr

    data = load(secrets_repo / ".sops.yaml")
    assert KEY_1 in rule(data, "secrets\\.yaml")["age"]
    assert KEY_1 in rule(data, "systems/.*/sshkeys/.*\\.yaml")["age"]


def test_rotating_key_updates_value_and_every_alias(secrets_repo, sops_env):
    # reference the host from BOTH rules first, to prove rotation fixes every alias
    run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_1, "--target", "secrets.yaml"], cwd=secrets_repo, env=sops_env)
    run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_1, "--target", "systems/demo-vm/sshkeys/ed25519.yaml"],
           cwd=secrets_repo, env=sops_env)

    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_2, "--target", "secrets.yaml"],
                     cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert "updated key value" in result.stdout

    sops_yaml = secrets_repo / ".sops.yaml"
    data = load(sops_yaml)

    assert data["keys"].count(KEY_2) == 1
    assert KEY_1 not in data["keys"]

    # the admin identity from the fixture's .sops.yaml is always present too -
    # only demo-vm's own reference should have moved from KEY_1 to KEY_2
    secrets_rule = rule(data, "secrets\\.yaml")
    sshkeys_rule = rule(data, "systems/.*/sshkeys/.*\\.yaml")
    assert KEY_2 in secrets_rule["age"]
    assert KEY_1 not in secrets_rule["age"]
    assert KEY_2 in sshkeys_rule["age"]
    assert KEY_1 not in sshkeys_rule["age"]

    # exactly one anchor definition anywhere in the document - a buggy
    # rotation could leave a second, stale `&demo-vm` behind
    assert sops_yaml.read_text().count("&demo-vm ") == 1


def test_derives_key_from_ssh_host_key_when_omitted(secrets_repo, sops_env, age_identity):
    run_py(CREATE_SSH_HOST_KEYS, ["demo-vm"], cwd=secrets_repo, env=sops_env)

    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm"], cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert "Deriving age key from SSH host key" in result.stdout

    data = load(secrets_repo / ".sops.yaml")
    assert len(data["keys"]) == 2
    derived = [k for k in data["keys"] if k != age_identity["public_key"]][0]
    assert derived.startswith("age1")
    assert derived in rule(data, "secrets\\.yaml")["age"]


def test_errors_when_no_key_given_and_no_ssh_host_key_exists(secrets_repo, sops_env):
    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm"], cwd=secrets_repo, env=sops_env)
    assert result.returncode == 1
    assert "not found for host" in result.stderr


def test_errors_when_sops_file_missing(tmp_path, sops_env):
    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_1], cwd=tmp_path, env=sops_env)
    assert result.returncode == 1
    assert "not found in the current directory" in result.stderr


def test_warns_but_still_adds_anchor_when_no_target_matches(secrets_repo, sops_env):
    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_1, "--target", "nowhere/matches.yaml"],
                     cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0
    assert "no creation_rules matched targets" in result.stderr

    data = load(secrets_repo / ".sops.yaml")
    assert KEY_1 in data["keys"]


def test_warns_when_matching_rule_has_no_key_groups(secrets_repo, sops_env):
    sops_yaml = secrets_repo / ".sops.yaml"
    with sops_yaml.open("a") as f:
        f.write("  - path_regex: no-groups\\.yaml\n    key_groups: []\n")

    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_1, "--target", "no-groups.yaml"],
                     cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert "matched but has no 'age:' list or key_groups" in result.stderr


def test_legacy_key_groups_format_still_supported(secrets_repo, sops_env):
    sops_yaml = secrets_repo / ".sops.yaml"
    with sops_yaml.open("a") as f:
        f.write("  - path_regex: legacy\\.yaml\n    key_groups:\n      - age:\n          - *admin\n")

    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_1, "--target", "legacy.yaml"],
                     cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr

    data = load(sops_yaml)
    assert KEY_1 in rule(data, "legacy\\.yaml")["key_groups"][0]["age"]


def test_custom_file_flag(tmp_path, age_identity, sops_env):
    custom = tmp_path / "custom.sops.yaml"
    write_sops_config(custom, age_identity["public_key"])

    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_1, "--file", str(custom), "--target", "secrets.yaml"],
                     cwd=tmp_path, env=sops_env)
    assert result.returncode == 0, result.stderr

    data = load(custom)
    assert KEY_1 in data["keys"]


def test_default_target_is_secrets_yaml(secrets_repo, sops_env):
    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_1], cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr

    data = load(secrets_repo / ".sops.yaml")
    assert KEY_1 in rule(data, "secrets\\.yaml")["age"]
    assert KEY_1 not in rule(data, "systems/.*/sshkeys/.*\\.yaml")["age"]


def test_output_parses_with_both_pyyaml_and_ruamel(secrets_repo, sops_env):
    run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_1], cwd=secrets_repo, env=sops_env)
    text = (secrets_repo / ".sops.yaml").read_text()

    yaml.safe_load(text)  # raises on structural corruption
    YAML().load(text)  # independently, ruamel must also parse it back cleanly


def test_secrets_yaml_content_still_decrypts_after_updatekeys(secrets_repo, sops_env, second_age_identity):
    # end-to-end: upsert a *real* key (sops must actually be able to encrypt
    # to it, unlike the placeholder KEY_1/KEY_2 used elsewhere in this file),
    # then actually run `sops updatekeys` (as noa-install does) and confirm
    # the file is still readable afterwards.
    import subprocess

    run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", second_age_identity["public_key"]],
           cwd=secrets_repo, env=sops_env)
    subprocess.run(["sops", "updatekeys", "--yes", "secrets.yaml"],
                    cwd=secrets_repo, env=sops_env, check=True, capture_output=True, text=True)

    data = decrypt_yaml(secrets_repo / "secrets.yaml", cwd=secrets_repo, env=sops_env)
    assert data["example_secret"] == "replace-me"
