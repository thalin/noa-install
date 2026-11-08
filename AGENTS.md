# noa-install

Provisions a new NixOS host with nixos-anywhere and bootstraps that host's SSH host keys and
sops-nix age key in a companion secrets repo. In this workspace, nixos-snowzen hosts are
installed with it against `nix-secrets/`; see the workspace doc `../docs/host-provisioning.md`
(relative to the main checkout, i.e. `/home/thalin/projects/nix/docs/host-provisioning.md`).

What the tool does, every flag and the config-file layering are in [README.md](README.md).
Wiring it into another host-config flake / secrets repo, re-run behaviour and troubleshooting
are in [INTEGRATION.md](INTEGRATION.md). The local VM demo is [examples/README.md](examples/README.md).

## Layout

A Snowfall-lib flake (`flake.nix`: namespace `noa-install`, `supportedSystems` limited to
`x86_64-linux` and `aarch64-linux`). Everything is auto-discovered; `flake.nix` only declares inputs.

- `packages/`: the five packages (`noa-install` plus the helper scripts it calls). Packages refer to
  each other as `pkgs.${namespace}.<name>`.
- `systems/x86_64-linux/`: three nixosConfigurations.
  - `noa`: the minimal installer ISO for bare metal. Its SSH keys come from the *builder's*
    `~/.ssh/*.pub`, so it needs `--impure`; an assertion fails the build if none are found.
    Build with `just iso`.
  - `target-vm`: QEMU VM that stands in for bare metal in the demo (host port 2222 -> 22).
  - `demo-vm`: the config the demo installs onto `target-vm`, with disko layout in `disko.nix`.
  - Both demo systems authorize `examples/demo-ssh-key.pub`, a throwaway demo key.
- `checks/pytest/`: `nix flake check` entry point; runs `pytest tests -v` in the sandbox.
- `shells/default/`: dev shell for `nix develop -c pytest tests`.
- `examples/`: the demo. `examples/secrets-repo/` holds sops-compose sources (`sops/`), the rendered
  `.sops.yaml` and a plaintext `secrets.example.yaml`. Running the demo generates `admin-key.txt`,
  `secrets.yaml` and `systems/` there; all three are gitignored, as are `examples/demo-ssh-key`,
  `*.qcow2` and `examples/known_hosts`.

## Inputs and couplings

- `sops-compose` (github:thalin/sops-compose, also `../sops-compose/` in this workspace) is put on
  `upsert-sops-age-key`'s PATH and on the pytest check's PATH. A secrets repo counts as
  sops-compose-managed when it has `sops/rules.yaml`. Then `.sops.yaml` is generated
  ("Do not edit"): change `sops/` and re-render, never hand-edit it.
- `disko` is used only by `demo-vm`.
- nixos-snowzen still carries an older copy at its own `packages/noa-install/`, behind its
  `just install`. Changes here don't reach that copy (see the workspace host-provisioning doc).

## Commands

- `nix flake check`: runs the test suite (`checks/pytest`).
- `nix develop -c pytest tests`: the same suite, locally. The dev shell lacks `sops-compose` and
  `git`, so the sops-compose and git-staging tests error there. Use `nix flake check` for a full run.
- `just iso`: build the `noa` ISO (impure, output in `result/iso/`).
- `nix run .#noa-install -- -h <host> -i <ip> -s <secrets-repo>`: run from the root of the
  *host-config* flake being installed, not from this repo (except for the demo).

## Rules for agents

- Workspace rule: `sops` may be run here, but only against the demo secrets in
  `examples/secrets-repo/`. Never point anything at `nix-secrets/`.
- When behaviour or flags change, update README.md (the flag table and the "What it does" steps)
  and INTEGRATION.md. Both describe each step in detail.

## Subdirectories

- [packages/](packages/AGENTS.md) — Five Snowfall packages (noa-install, create-ssh-host-keys, upsert-sops-age-key, sync-sops-recipients, sops-utils): packaging patterns, placeholder wiring, test coupling
- [tests/](tests/AGENTS.md) — Pytest suite running the package scripts directly against real sops/age/ssh crypto in temp secrets repos
