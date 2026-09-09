import shutil
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from conftest import CREATE_SSH_HOST_KEYS, UPSERT_SOPS_AGE_KEY, load_noa_install_module


BASH = shutil.which("bash")


def make_stub(path, log_path, exit_code=0):
    """A recording stub binary: appends its argv to log_path and exits.
    Uses bash's resolved absolute path rather than `#!/usr/bin/env bash` -
    the pure Nix build sandbox has no /usr/bin/env."""
    path.write_text(f'#!{BASH}\necho "$@" >> "{log_path}"\nexit {exit_code}\n')
    path.chmod(0o755)


@pytest.fixture
def noa(tmp_path, sops_env, monkeypatch):
    """A noa-install module wired to the *real* create-ssh-host-keys,
    upsert-sops-age-key, and sops (so the sops-side bootstrap is exercised
    for real), with nixos-anywhere and nix replaced by recording stubs so no
    actual provisioning or flake update happens."""
    module = load_noa_install_module()

    module.nixos_anywhere_log = tmp_path / "nixos-anywhere.log"
    module.nix_log = tmp_path / "nix.log"
    nixos_anywhere_stub = tmp_path / "nixos-anywhere"
    nix_stub = tmp_path / "nix"
    make_stub(nixos_anywhere_stub, module.nixos_anywhere_log)
    make_stub(nix_stub, module.nix_log)

    module.NIXOS_ANYWHERE_BIN = str(nixos_anywhere_stub)
    module.NIX_BIN = str(nix_stub)
    module.SOPS_BIN = shutil.which("sops")
    module.CREATE_SSH_HOST_KEYS_BIN = f"{sys.executable} {CREATE_SSH_HOST_KEYS}"
    module.UPSERT_SOPS_AGE_KEY_BIN = f"{sys.executable} {UPSERT_SOPS_AGE_KEY}"

    for key, value in sops_env.items():
        monkeypatch.setenv(key, value)

    # Isolate config-file lookups from whatever the test-runner's real
    # machine happens to have under ~/.config or $XDG_CONFIG_HOME.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config-home"))

    return module


@pytest.fixture
def host_flake_dir(tmp_path):
    d = tmp_path / "host-flake"
    d.mkdir()
    return d


def run_main(module, argv, monkeypatch, cwd):
    monkeypatch.setattr(sys, "argv", ["noa-install", *argv])
    monkeypatch.chdir(cwd)
    module.main()


def test_parse_args_defaults_to_none_for_config_overridable_fields(monkeypatch):
    # parse_args() itself must leave every config-overridable field as None
    # when not passed - resolve_settings is what applies the real defaults,
    # so a config file value isn't clobbered by an argparse default.
    module = load_noa_install_module()
    monkeypatch.setattr(sys, "argv", ["noa-install", "-h", "myhost", "-i", "1.2.3.4", "-s", "/tmp/secrets"])

    args = module.parse_args()

    assert args.hostname == "myhost"
    assert args.ip == "1.2.3.4"
    assert args.secrets_repo == "/tmp/secrets"
    for field in module.CONFIG_FIELDS:
        if field not in ("hostname", "ip", "secrets_repo"):
            assert getattr(args, field) is None, field
    assert args.config is None


def test_resolve_settings_applies_defaults_with_no_config_files(monkeypatch, tmp_path):
    module = load_noa_install_module()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config-home"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["noa-install", "-h", "myhost", "-i", "1.2.3.4", "-s", "/tmp/secrets"])

    settings = module.resolve_settings(module.parse_args())

    assert settings["user"] == "root"
    assert settings["secrets_file"] == "secrets.yaml"
    assert settings["system"] == "x86_64-linux"
    assert settings["no_reboot"] is False
    assert settings["secrets_input"] is None
    assert settings["hardware_config"] is None
    assert settings["ssh_port"] is None
    assert settings["identity_file"] is None


def test_missing_required_fields_errors_with_helpful_message(monkeypatch, tmp_path):
    module = load_noa_install_module()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config-home"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["noa-install"])

    with pytest.raises(SystemExit) as exc_info:
        module.resolve_settings(module.parse_args())

    assert exc_info.value.code == 1


def test_cwd_config_file_supplies_required_fields(monkeypatch, tmp_path):
    module = load_noa_install_module()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config-home"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".noa-install.yaml").write_text(
        "hostname: cfg-host\nip: 10.0.0.5\nsecrets-repo: /cfg/secrets\nuser: alice\n"
    )
    monkeypatch.setattr(sys, "argv", ["noa-install"])

    settings = module.resolve_settings(module.parse_args())

    assert settings["hostname"] == "cfg-host"
    assert settings["ip"] == "10.0.0.5"
    assert settings["secrets_repo"] == "/cfg/secrets"
    assert settings["user"] == "alice"


def test_xdg_config_file_supplies_required_fields(monkeypatch, tmp_path):
    module = load_noa_install_module()
    xdg_home = tmp_path / "xdg-config-home"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
    monkeypatch.chdir(tmp_path)  # no .noa-install.yaml here

    config_dir = xdg_home / "noa-install"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text(
        "hostname: xdg-host\nip: 10.0.0.9\nsecrets-repo: /xdg/secrets\n"
    )
    monkeypatch.setattr(sys, "argv", ["noa-install"])

    settings = module.resolve_settings(module.parse_args())

    assert settings["hostname"] == "xdg-host"
    assert settings["ip"] == "10.0.0.9"
    assert settings["secrets_repo"] == "/xdg/secrets"


def test_xdg_config_falls_back_to_home_config_when_xdg_config_home_unset(monkeypatch, tmp_path):
    module = load_noa_install_module()
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.chdir(tmp_path)

    config_dir = home / ".config" / "noa-install"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text("hostname: fallback-host\nip: 10.0.0.1\nsecrets-repo: /s\n")
    monkeypatch.setattr(sys, "argv", ["noa-install"])

    settings = module.resolve_settings(module.parse_args())

    assert settings["hostname"] == "fallback-host"


def test_cwd_config_overrides_xdg_config(monkeypatch, tmp_path):
    module = load_noa_install_module()
    xdg_home = tmp_path / "xdg-config-home"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
    monkeypatch.chdir(tmp_path)

    config_dir = xdg_home / "noa-install"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text(
        "hostname: xdg-host\nip: 10.0.0.9\nsecrets-repo: /xdg/secrets\nuser: xdg-user\n"
    )
    (tmp_path / ".noa-install.yaml").write_text("hostname: cwd-host\n")  # only overrides hostname
    monkeypatch.setattr(sys, "argv", ["noa-install"])

    settings = module.resolve_settings(module.parse_args())

    assert settings["hostname"] == "cwd-host"  # cwd wins
    assert settings["ip"] == "10.0.0.9"  # falls through from xdg
    assert settings["user"] == "xdg-user"  # falls through from xdg


def test_explicit_config_flag_overrides_cwd_and_xdg(monkeypatch, tmp_path):
    module = load_noa_install_module()
    xdg_home = tmp_path / "xdg-config-home"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
    monkeypatch.chdir(tmp_path)

    config_dir = xdg_home / "noa-install"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text("hostname: xdg-host\nip: 10.0.0.9\nsecrets-repo: /xdg/secrets\n")
    (tmp_path / ".noa-install.yaml").write_text("hostname: cwd-host\n")

    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("hostname: explicit-host\n")
    monkeypatch.setattr(sys, "argv", ["noa-install", "--config", str(explicit)])

    settings = module.resolve_settings(module.parse_args())

    assert settings["hostname"] == "explicit-host"  # --config wins
    assert settings["ip"] == "10.0.0.9"  # still falls through from xdg


def test_cli_args_override_every_config_layer(monkeypatch, tmp_path):
    module = load_noa_install_module()
    xdg_home = tmp_path / "xdg-config-home"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
    monkeypatch.chdir(tmp_path)

    config_dir = xdg_home / "noa-install"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text("hostname: xdg-host\nip: 10.0.0.9\nsecrets-repo: /xdg/secrets\n")
    (tmp_path / ".noa-install.yaml").write_text("hostname: cwd-host\n")

    monkeypatch.setattr(sys, "argv", ["noa-install", "-h", "cli-host"])

    settings = module.resolve_settings(module.parse_args())

    assert settings["hostname"] == "cli-host"  # CLI wins over every config layer
    assert settings["ip"] == "10.0.0.9"  # still falls through, CLI didn't set it


def test_config_file_boolean_field(monkeypatch, tmp_path):
    module = load_noa_install_module()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config-home"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".noa-install.yaml").write_text(
        "hostname: h\nip: 1.2.3.4\nsecrets-repo: /s\nno-reboot: true\n"
    )
    monkeypatch.setattr(sys, "argv", ["noa-install"])

    settings = module.resolve_settings(module.parse_args())
    assert settings["no_reboot"] is True


def test_missing_explicit_config_file_errors(monkeypatch, tmp_path):
    module = load_noa_install_module()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config-home"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "noa-install", "-h", "h", "-i", "1.2.3.4", "-s", "/s",
        "--config", str(tmp_path / "does-not-exist.yaml"),
    ])

    with pytest.raises(SystemExit) as exc_info:
        module.resolve_settings(module.parse_args())

    assert exc_info.value.code == 1


def test_full_run_using_only_a_cwd_config_file(noa, secrets_repo, monkeypatch, host_flake_dir):
    # every required field comes from .noa-install.yaml, none from argv
    (host_flake_dir / ".noa-install.yaml").write_text(
        f"hostname: demo-vm\nip: 127.0.0.1\nsecrets-repo: {secrets_repo}\n"
    )
    monkeypatch.setattr(sys, "argv", ["noa-install"])
    monkeypatch.chdir(host_flake_dir)

    noa.main()

    ed_path = secrets_repo / "systems" / "demo-vm" / "sshkeys" / "ed25519.yaml"
    assert ed_path.exists()
    log = noa.nixos_anywhere_log.read_text()
    assert "--flake .#demo-vm" in log
    assert "--target-host root@127.0.0.1" in log


def test_full_run_bootstraps_keys_and_calls_nixos_anywhere(noa, secrets_repo, monkeypatch, host_flake_dir):
    run_main(noa, ["-h", "demo-vm", "-i", "127.0.0.1", "-s", str(secrets_repo)], monkeypatch, host_flake_dir)

    ed_path = secrets_repo / "systems" / "demo-vm" / "sshkeys" / "ed25519.yaml"
    rsa_path = secrets_repo / "systems" / "demo-vm" / "sshkeys" / "rsa.yaml"
    assert ed_path.exists() and rsa_path.exists()

    data = yaml.safe_load((secrets_repo / ".sops.yaml").read_text())
    assert len(data["keys"]) == 2  # admin + demo-vm

    log = noa.nixos_anywhere_log.read_text()
    assert "--flake .#demo-vm" in log
    assert "--target-host root@127.0.0.1" in log
    assert "--generate-hardware-config nixos-generate-config ./systems/x86_64-linux/demo-vm/hardware.nix" in log


def test_ssh_port_and_identity_file_passthrough(noa, secrets_repo, monkeypatch, host_flake_dir, tmp_path):
    identity = tmp_path / "id_ed25519"
    identity.write_text("fake key material")

    run_main(noa, [
        "-h", "demo-vm", "-i", "127.0.0.1", "-s", str(secrets_repo),
        "-P", "2222", "-I", str(identity),
    ], monkeypatch, host_flake_dir)

    log = noa.nixos_anywhere_log.read_text()
    assert "--ssh-port 2222" in log
    assert f"-i {identity}" in log


def test_no_reboot_limits_phases(noa, secrets_repo, monkeypatch, host_flake_dir):
    run_main(noa, ["-h", "demo-vm", "-i", "127.0.0.1", "-s", str(secrets_repo), "--no-reboot"],
              monkeypatch, host_flake_dir)

    assert "--phases kexec,disko,install" in noa.nixos_anywhere_log.read_text()


def test_reboot_phases_omitted_by_default(noa, secrets_repo, monkeypatch, host_flake_dir):
    run_main(noa, ["-h", "demo-vm", "-i", "127.0.0.1", "-s", str(secrets_repo)], monkeypatch, host_flake_dir)

    assert "--phases" not in noa.nixos_anywhere_log.read_text()


def test_custom_hardware_config_path(noa, secrets_repo, monkeypatch, host_flake_dir):
    run_main(noa, [
        "-h", "demo-vm", "-i", "127.0.0.1", "-s", str(secrets_repo),
        "--hardware-config", "./custom-hw.nix",
    ], monkeypatch, host_flake_dir)

    assert "nixos-generate-config ./custom-hw.nix" in noa.nixos_anywhere_log.read_text()


def test_custom_system_changes_default_hardware_config_path(noa, secrets_repo, monkeypatch, host_flake_dir):
    run_main(noa, [
        "-h", "demo-vm", "-i", "127.0.0.1", "-s", str(secrets_repo),
        "--system", "aarch64-linux",
    ], monkeypatch, host_flake_dir)

    assert "./systems/aarch64-linux/demo-vm/hardware.nix" in noa.nixos_anywhere_log.read_text()


def test_rerun_with_existing_keys_skips_bootstrap_but_still_installs(noa, secrets_repo, monkeypatch, host_flake_dir):
    run_main(noa, ["-h", "demo-vm", "-i", "127.0.0.1", "-s", str(secrets_repo)], monkeypatch, host_flake_dir)
    before = (secrets_repo / ".sops.yaml").read_text()

    run_main(noa, ["-h", "demo-vm", "-i", "127.0.0.1", "-s", str(secrets_repo)], monkeypatch, host_flake_dir)
    after = (secrets_repo / ".sops.yaml").read_text()

    assert before == after  # no re-bootstrap, no changes
    assert noa.nixos_anywhere_log.read_text().count("--flake .#demo-vm") == 2  # ran install both times


def test_secrets_input_triggers_nix_flake_update(noa, secrets_repo, monkeypatch, host_flake_dir):
    run_main(noa, [
        "-h", "demo-vm", "-i", "127.0.0.1", "-s", str(secrets_repo),
        "--secrets-input", "nix-secrets",
    ], monkeypatch, host_flake_dir)

    assert "flake update nix-secrets" in noa.nix_log.read_text()


def test_secrets_input_omitted_by_default(noa, secrets_repo, monkeypatch, host_flake_dir):
    run_main(noa, ["-h", "demo-vm", "-i", "127.0.0.1", "-s", str(secrets_repo)], monkeypatch, host_flake_dir)

    assert not noa.nix_log.exists()


def test_failing_nixos_anywhere_aborts_with_exit_1(noa, secrets_repo, monkeypatch, host_flake_dir, tmp_path):
    make_stub(Path(noa.NIXOS_ANYWHERE_BIN), noa.nixos_anywhere_log, exit_code=1)

    with pytest.raises(SystemExit) as exc_info:
        run_main(noa, ["-h", "demo-vm", "-i", "127.0.0.1", "-s", str(secrets_repo)], monkeypatch, host_flake_dir)

    assert exc_info.value.code == 1


def test_staged_extra_files_contain_the_bootstrapped_ssh_keys(noa, secrets_repo, monkeypatch, host_flake_dir, tmp_path):
    # stage_ssh_keys' temp dir is cleaned up before main() returns, so inspect
    # it from inside the nixos-anywhere stub, at the moment it'd actually be used.
    inspect_log = tmp_path / "extra-files-contents.log"
    stub = Path(noa.NIXOS_ANYWHERE_BIN)
    stub.write_text(textwrap.dedent(f"""\
        #!{BASH}
        prev=""
        for arg in "$@"; do
          if [ "$prev" = "--extra-files" ]; then
            find "$arg" -type f >> "{inspect_log}"
          fi
          prev="$arg"
        done
        exit 0
        """))
    stub.chmod(0o755)

    run_main(noa, ["-h", "demo-vm", "-i", "127.0.0.1", "-s", str(secrets_repo)], monkeypatch, host_flake_dir)

    contents = inspect_log.read_text()
    assert "etc/ssh/ssh_host_ed25519_key" in contents
    assert "etc/ssh/ssh_host_ed25519_key.pub" in contents
    assert "etc/ssh/ssh_host_rsa_key" in contents
    assert "etc/ssh/ssh_host_rsa_key.pub" in contents
