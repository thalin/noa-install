import subprocess
import sys

from conftest import decrypt_yaml


def run_snippet(code, cwd, env):
    """Runs a short python snippet with sops_utils importable (via PYTHONPATH
    in `sops_env`)."""
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd, env=env, capture_output=True, text=True,
    )


def test_ensure_sops_file_creates_new_encrypted_file(secrets_repo, sops_env):
    target = secrets_repo / "systems" / "demo-vm" / "sshkeys" / "ed25519.yaml"
    code = f"import sops_utils; sops_utils.ensure_sops_file({str(target)!r})"

    result = run_snippet(code, cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr
    assert target.exists()

    data = decrypt_yaml(target, cwd=secrets_repo, env=sops_env)
    assert "created" in data


def test_ensure_sops_file_verifies_existing_valid_file_without_changing_it(secrets_repo, sops_env):
    target = secrets_repo / "secrets.yaml"  # already sops-encrypted by the fixture
    before = target.read_text()

    code = f"import sops_utils; sops_utils.ensure_sops_file({str(target)!r})"
    result = run_snippet(code, cwd=secrets_repo, env=sops_env)

    assert result.returncode == 0, result.stderr
    assert target.read_text() == before
    data = decrypt_yaml(target, cwd=secrets_repo, env=sops_env)
    assert data["example_secret"] == "replace-me"


def test_ensure_sops_file_rejects_invalid_existing_file(secrets_repo, sops_env):
    target = secrets_repo / "garbage.yaml"
    target.write_text("this is not a sops file at all\n")

    code = f"import sops_utils; sops_utils.ensure_sops_file({str(target)!r})"
    result = run_snippet(code, cwd=secrets_repo, env=sops_env)

    assert result.returncode == 1
    assert "valid sops file" in result.stderr


def test_sopsfile_set_writes_nested_dotted_keys(secrets_repo, sops_env):
    # must match one of the fixture .sops.yaml's creation_rules or `sops
    # encrypt` has no recipients to encrypt to and silently no-ops
    target = secrets_repo / "systems" / "testhost" / "sshkeys" / "nested.yaml"
    code = f"import sops_utils; sops_utils.SopsFile({str(target)!r}).set('a.b.c', 'hello')"

    result = run_snippet(code, cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr

    # `ensure_sops_file` seeds new files with a `created` field alongside
    # whatever `.set()` adds - only assert on the keys we actually wrote
    data = decrypt_yaml(target, cwd=secrets_repo, env=sops_env)
    assert data["a"] == {"b": {"c": "hello"}}


def test_sopsfile_set_twice_merges_rather_than_overwrites(secrets_repo, sops_env):
    # must match one of the fixture .sops.yaml's creation_rules or `sops
    # encrypt` has no recipients to encrypt to and silently no-ops
    target = secrets_repo / "systems" / "testhost" / "sshkeys" / "nested.yaml"
    run_snippet(f"import sops_utils; sops_utils.SopsFile({str(target)!r}).set('a.b', 'one')",
                cwd=secrets_repo, env=sops_env)
    result = run_snippet(f"import sops_utils; sops_utils.SopsFile({str(target)!r}).set('a.c', 'two')",
                          cwd=secrets_repo, env=sops_env)
    assert result.returncode == 0, result.stderr

    data = decrypt_yaml(target, cwd=secrets_repo, env=sops_env)
    assert data["a"] == {"b": "one", "c": "two"}


def test_run_command_returns_failed_result_instead_of_raising(secrets_repo, sops_env):
    # sops_utils.run_command (unlike noa-install's own run_command) logs and
    # returns the failed Command rather than exiting the process.
    code = (
        "import sops_utils; "
        "c = sops_utils.run_command('sops decrypt /nonexistent-file.yaml'); "
        "print('RC=' + str(c.return_code))"
    )
    result = run_snippet(code, cwd=secrets_repo, env=sops_env)

    assert result.returncode == 0
    assert "RC=0" not in result.stdout
    assert "Error: command failed" in result.stderr
