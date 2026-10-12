"""upsert-sops-age-key against a secrets repo whose .sops.yaml is rendered by
sops-compose from sources under sops/ (see test_upsert_sops_age_key.py for
repos that keep .sops.yaml by hand)."""
import yaml

from conftest import CREATE_SSH_HOST_KEYS, UPSERT_SOPS_AGE_KEY, run_py

KEY_1 = "age1testkey0000000000000000000000000000000000000000000000000000"
KEY_2 = "age1differentkey1111111111111111111111111111111111111111111111"


def load(path):
    return yaml.safe_load(path.read_text())


def rendered_rule(repo, path_regex):
    return next(r for r in load(repo / ".sops.yaml")["creation_rules"] if r["path_regex"] == path_regex)


def test_adds_key_to_hosts_file_and_renders(compose_repo, sops_env):
    rules_before = (compose_repo / "sops" / "rules.yaml").read_text()

    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_1], cwd=compose_repo, env=sops_env)
    assert result.returncode == 0, result.stderr

    hosts = (compose_repo / "sops" / "keys" / "hosts.yaml").read_text()
    assert f"demo-vm: {KEY_1}" in hosts
    assert "# Host keys, managed by noa-install" in hosts  # comments survive
    # secrets.yaml's rule uses `all`, so the host is already a recipient
    # once its key exists: no rule edit needed.
    assert KEY_1 in rendered_rule(compose_repo, r"^secrets\.yaml$")["age"]
    assert KEY_1 not in rendered_rule(compose_repo, r"systems/.*/sshkeys/.*\.yaml$")["age"]
    assert (compose_repo / "sops" / "rules.yaml").read_text() == rules_before
    # .sops.yaml is never edited directly any more: anchors don't appear.
    assert "keys" not in load(compose_repo / ".sops.yaml")


def test_rerun_is_idempotent(compose_repo, sops_env):
    run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_1], cwd=compose_repo, env=sops_env)
    files = ["sops/keys/hosts.yaml", "sops/rules.yaml", ".sops.yaml"]
    before = {f: (compose_repo / f).read_text() for f in files}

    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_1], cwd=compose_repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert {f: (compose_repo / f).read_text() for f in files} == before


def test_rotated_key_replaces_the_old_one(compose_repo, sops_env):
    run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_1], cwd=compose_repo, env=sops_env)
    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_2], cwd=compose_repo, env=sops_env)
    assert result.returncode == 0, result.stderr

    age = rendered_rule(compose_repo, r"^secrets\.yaml$")["age"]
    assert KEY_2 in age and KEY_1 not in age


def test_target_without_a_rule_gets_one_with_the_with_recipients(compose_repo, sops_env, age_identity):
    result = run_py(UPSERT_SOPS_AGE_KEY,
                    ["demo-vm", KEY_1, "--target", "systems/demo-vm/app.env", "--with", "admin"],
                    cwd=compose_repo, env=sops_env)
    assert result.returncode == 0, result.stderr

    rules = load(compose_repo / "sops" / "rules.yaml")
    assert rules[-1] == {"path_regex": r"^systems/demo-vm/app\.env$", "age": ["hosts.demo-vm", "admin"]}
    assert "# added by upsert-sops-age-key for demo-vm" in (compose_repo / "sops" / "rules.yaml").read_text()
    assert set(rendered_rule(compose_repo, r"^systems/demo-vm/app\.env$")["age"]) == {
        KEY_1, age_identity["public_key"],
    }


def test_target_under_a_broad_rule_is_refused(compose_repo, sops_env):
    # Another host's ssh keys already sit under the shared sshkeys rule;
    # granting demo-vm its own keys' path must not hand it those too.
    other = compose_repo / "systems" / "other" / "sshkeys"
    other.mkdir(parents=True)
    (other / "ed25519.yaml").write_text("x: 1\n")
    rules_before = (compose_repo / "sops" / "rules.yaml").read_text()

    result = run_py(UPSERT_SOPS_AGE_KEY,
                    ["demo-vm", KEY_1, "--target", "systems/demo-vm/sshkeys/ed25519.yaml"],
                    cwd=compose_repo, env=sops_env)
    assert result.returncode != 0
    assert "--allow-broad" in result.stderr
    assert (compose_repo / "sops" / "rules.yaml").read_text() == rules_before

    result = run_py(UPSERT_SOPS_AGE_KEY,
                    ["demo-vm", KEY_1, "--target", "systems/demo-vm/sshkeys/ed25519.yaml", "--allow-broad"],
                    cwd=compose_repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert KEY_1 in rendered_rule(compose_repo, r"systems/.*/sshkeys/.*\.yaml$")["age"]


def test_custom_namespace(compose_repo, sops_env):
    result = run_py(UPSERT_SOPS_AGE_KEY, ["laptop", KEY_1, "--namespace", "workstations"],
                    cwd=compose_repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert load(compose_repo / "sops" / "keys" / "workstations.yaml") == {"laptop": KEY_1}


def test_derives_key_from_ssh_host_key_when_omitted(compose_repo, sops_env):
    run_py(CREATE_SSH_HOST_KEYS, ["demo-vm"], cwd=compose_repo, env=sops_env)

    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm"], cwd=compose_repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert "Deriving age key from SSH host key" in result.stdout
    assert load(compose_repo / "sops" / "keys" / "hosts.yaml")["demo-vm"].startswith("age1")


def test_with_is_ignored_with_a_warning_without_sops_compose(secrets_repo, sops_env):
    result = run_py(UPSERT_SOPS_AGE_KEY, ["demo-vm", KEY_1, "--with", "admin"],
                    cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert "only apply to sops-compose repos" in result.stderr
    assert KEY_1 in load(secrets_repo / ".sops.yaml")["keys"]
