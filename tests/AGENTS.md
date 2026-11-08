# tests/

Pytest suite for the five packages in `../packages/`. It runs the Python scripts directly with `sys.executable` (not the Nix wrappers), so it tests the logic and its real interaction with sops/age/ssh, not the packaging. Crypto is real; each test generates its own throwaway age keys and temp secrets repos, so nothing touches real secrets.

## Running

- `nix flake check` runs it via `../checks/pytest/default.nix`. That environment has sops, age, ssh-to-age, openssh, git and the `sops-compose` CLI.
- `nix develop -c pytest tests` uses `../shells/default/default.nix`, which has sops, age, ssh-to-age and openssh but NOT `sops-compose`, and no `git` of its own (it only works if git is on the inherited PATH). Without `sops-compose` every test that uses the `compose_repo` fixture or calls `sops-compose render` fails (it errors, it does not skip). That covers `test_upsert_sops_compose.py`, the two sops-compose tests in `test_sync_sops_recipients.py`, and the `test_sops_compose_*` tests in `test_noa_install.py`. Tests that `git init` a secrets repo fail the same way if git is missing. Use `nix flake check` for a full run.

## Layout

- `conftest.py` holds the script path constants, `run_py` (run a script as a subprocess), `decrypt_yaml`, and the fixtures:
  - `age_identity` / `second_age_identity`: real age keypairs.
  - `sops_env`: env with `SOPS_AGE_KEY_FILE` and `PYTHONPATH` pointing at `packages/sops-utils` so scripts can `import sops_utils`.
  - `secrets_repo`: hand-kept `.sops.yaml` plus an encrypted `secrets.yaml`.
  - `compose_repo`: same shape but `.sops.yaml` is rendered by `sops-compose` from `sops/` sources (`keys/users.yaml`, `keys/hosts.yaml`, `groups.yaml`, `rules.yaml`).
  - `load_noa_install_module()`: loads `noa-install.py` fresh per test (hyphenated filename, `@placeholder@` BIN constants that tests overwrite).
- One test file per package: `test_sops_utils.py`, `test_create_ssh_host_keys.py`, `test_upsert_sops_age_key.py`, `test_sync_sops_recipients.py`, `test_noa_install.py`. `test_upsert_sops_compose.py` covers upsert-sops-age-key against `compose_repo`.

## noa-install tests

- The `noa` fixture in `test_noa_install.py` wires the module to the real create-ssh-host-keys, upsert-sops-age-key, sync-sops-recipients and sops, while `nixos-anywhere` and `nix` are replaced by recording stubs (`make_stub` logs argv). Assert on those logs to check the phases and flags passed. Stubs use bash's absolute path because the build sandbox has no `/usr/bin/env`.
- The fixture sets `HOME` and `XDG_CONFIG_HOME` to temp dirs so config-file lookup tests are isolated from the machine's real config.
- Drive the CLI with `run_main(noa, argv, monkeypatch, cwd)`. The `host_flake_dir` fixture provides the cwd.
- Git-related tests (`git init` the secrets repo, then check what is staged) cover the flake `path:` input only seeing staged files.

## Adding tests

New script tests go in the matching `test_<script>.py`. Use `secrets_repo` or `compose_repo` plus `sops_env` and `run_py`; use `age_identity` fixtures rather than fake key strings whenever sops must actually encrypt.
