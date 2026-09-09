import subprocess

from conftest import CREATE_SSH_HOST_KEYS, decrypt_yaml, run_py


def key_paths(repo, hostname="demo-vm"):
    base = repo / "systems" / hostname / "sshkeys"
    return base / "ed25519.yaml", base / "rsa.yaml"


def test_generates_both_key_types(secrets_repo, sops_env):
    result = run_py(CREATE_SSH_HOST_KEYS, ["demo-vm"], cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr

    ed_path, rsa_path = key_paths(secrets_repo)
    assert ed_path.exists() and rsa_path.exists()

    ed = decrypt_yaml(ed_path, cwd=secrets_repo, env=sops_env)
    assert ed["public_key"].startswith("ssh-ed25519 ")
    assert "PRIVATE KEY" in ed["private_key"]

    rsa = decrypt_yaml(rsa_path, cwd=secrets_repo, env=sops_env)
    assert rsa["public_key"].startswith("ssh-rsa ")
    assert "PRIVATE KEY" in rsa["private_key"]


def test_rerun_without_overwrite_is_a_noop(secrets_repo, sops_env):
    run_py(CREATE_SSH_HOST_KEYS, ["demo-vm"], cwd=secrets_repo, env=sops_env)
    ed_path, _ = key_paths(secrets_repo)
    before = decrypt_yaml(ed_path, cwd=secrets_repo, env=sops_env)

    result = run_py(CREATE_SSH_HOST_KEYS, ["demo-vm"], cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert "Skipping generation" in result.stdout

    after = decrypt_yaml(ed_path, cwd=secrets_repo, env=sops_env)
    assert before == after


def test_overwrite_flag_regenerates_keys(secrets_repo, sops_env):
    run_py(CREATE_SSH_HOST_KEYS, ["demo-vm"], cwd=secrets_repo, env=sops_env)
    ed_path, _ = key_paths(secrets_repo)
    before = decrypt_yaml(ed_path, cwd=secrets_repo, env=sops_env)

    result = run_py(CREATE_SSH_HOST_KEYS, ["demo-vm", "--overwrite"], cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr

    after = decrypt_yaml(ed_path, cwd=secrets_repo, env=sops_env)
    assert before["public_key"] != after["public_key"]


def test_short_overwrite_flag(secrets_repo, sops_env):
    run_py(CREATE_SSH_HOST_KEYS, ["demo-vm"], cwd=secrets_repo, env=sops_env)
    ed_path, _ = key_paths(secrets_repo)
    before = decrypt_yaml(ed_path, cwd=secrets_repo, env=sops_env)

    result = run_py(CREATE_SSH_HOST_KEYS, ["demo-vm", "-o"], cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr

    after = decrypt_yaml(ed_path, cwd=secrets_repo, env=sops_env)
    assert before["public_key"] != after["public_key"]


def test_partial_keys_trigger_regeneration(secrets_repo, sops_env):
    ed_path, _ = key_paths(secrets_repo)
    ed_path.parent.mkdir(parents=True)
    ed_path.write_text("private_key: only-this-field-is-set\n")
    subprocess.run(
        ["sops", "encrypt", "-i", str(ed_path)],
        cwd=secrets_repo, env=sops_env, check=True, capture_output=True, text=True,
    )

    result = run_py(CREATE_SSH_HOST_KEYS, ["demo-vm"], cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert "Regenerating to ensure consistency" in result.stdout

    after = decrypt_yaml(ed_path, cwd=secrets_repo, env=sops_env)
    assert after["public_key"].startswith("ssh-ed25519 ")


def test_two_hosts_get_independent_keys(secrets_repo, sops_env):
    run_py(CREATE_SSH_HOST_KEYS, ["host-a"], cwd=secrets_repo, env=sops_env)
    run_py(CREATE_SSH_HOST_KEYS, ["host-b"], cwd=secrets_repo, env=sops_env)

    a_ed, _ = key_paths(secrets_repo, "host-a")
    b_ed, _ = key_paths(secrets_repo, "host-b")
    a = decrypt_yaml(a_ed, cwd=secrets_repo, env=sops_env)
    b = decrypt_yaml(b_ed, cwd=secrets_repo, env=sops_env)
    assert a["public_key"] != b["public_key"]
