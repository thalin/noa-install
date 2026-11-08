# packages/

Five Snowfall-autodiscovered packages (each `<name>/default.nix` plus a Python source), exposed as `pkgs.noa-install.<name>` and built for x86_64-linux and aarch64-linux. What each tool does and the `noa-install` flags are in [../README.md](../README.md); don't duplicate that here.

## How they fit together

`noa-install` is the entry point. It shells out to `create-ssh-host-keys`, `upsert-sops-age-key` and `sync-sops-recipients` (plus `nix`, `nixos-anywhere`, `sops`, and `git`). `create-ssh-host-keys` imports the `sops-utils` library.

## Packaging patterns (differ per package)

- `noa-install`: `writeScriptBin`. `default.nix` reads `noa-install.py` and swaps the `@placeholder@` paths (`@nix@`, `@nixos_anywhere@`, `@sops@`, `@git@`, `@create_ssh_host_keys@`, `@upsert_sops_age_key@`, `@sync_sops_recipients@`) with `replaceStrings`. A new tool dependency needs the `*_BIN` constant in the .py plus an entry in both lists in `default.nix`, in the same order.
- `create-ssh-host-keys`, `upsert-sops-age-key`, `sync-sops-recipients`: `mkDerivation` + `makeWrapper`, script installed to `$out/libexec/<pname>/`, wrapper in `$out/bin` using a `python3.withPackages` env and a `--prefix PATH` of runtime tools.
- `upsert-sops-age-key` puts the `sops-compose` flake input on PATH (`inputs.sops-compose.packages.<system>.default`), so its function args include `inputs`.
- `sops-utils`: `buildPythonPackage` (setuptools, `doCheck = false`), a library, not a CLI. `create-ssh-host-keys` gets it via `pkgs.${namespace}.sops-utils` in its python env.
- Filenames use underscores (`create_ssh_host_keys.py`); package and binary names use hyphens.

## Tests

[../tests/](../tests/) (pytest, run by `nix flake check` as `checks/pytest`) run the `.py` files directly, not the Nix wrappers. `sops_utils` is found via `PYTHONPATH`, and `conftest.py` only loads the `noa-install.py` module (`load_noa_install_module`); the `noa` fixture in `tests/test_noa_install.py` overwrites its `@placeholder@` `*_BIN` constants. So a new placeholder constant needs a matching override in that fixture, and Nix-only wiring mistakes (wrong placeholder, runtime dep missing from PATH) are not caught by the tests.

## Where the logic lives

- `noa-install/noa-install.py` (~500 lines): config layering (`load_layered_config`, `CONFIG_FIELDS`, `CONFIG_DEFAULTS`), then the flow `ensure_ssh_keys`, `update_sops_config`, `sync_host_secrets`, `update_secrets_input`, `stage_ssh_keys`, `run_nixos_anywhere`. A new setting goes in `CONFIG_FIELDS`/`CONFIG_DEFAULTS` and `parse_args`. No separate doc: the file header and function docstrings cover it.
- `sync-sops-recipients`: reads recipients from plaintext (the sops config and each file's metadata), so detecting drift never decrypts; only the re-encrypt step does. Changed paths go to stdout and progress to stderr; `noa-install` relies on that to stage files.
- `upsert-sops-age-key`: derives an age key from `systems/<host>/sshkeys/ed25519.yaml` and writes it to sops-compose sources or `.sops.yaml`.

## Rules

These scripts invoke `sops` at runtime. The tests generate their own temporary age keys and secrets repos (see `conftest.py`), and the workspace allows `sops` inside `noa-install/` for demo secrets in `examples/secrets-repo/`. Never point these tools at the real `nix-secrets` repo from here.
