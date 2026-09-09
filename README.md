# noa-install

Provisions a new NixOS host with [nixos-anywhere](https://github.com/nix-community/nixos-anywhere),
bootstrapping that host's SSH host keys and [sops-nix](https://github.com/Mic92/sops-nix) age key
in a companion secrets repo along the way.

This started as a helper script buried in a private host-config flake; it's split out here so it's
easy to reuse against any [Snowfall-lib](https://snowfall.org)-shaped flake and any sops secrets repo.

See [INTEGRATION.md](./INTEGRATION.md) for a walkthrough of wiring this into your own host-config
flake and secrets repo, or [examples/](./examples) for a self-contained local demo you can run
end-to-end against a disposable VM before touching real infrastructure.

## What it does

Given a hostname, an IP, and a path to a sops secrets repo, `noa-install`:

1. Checks whether `<secrets-repo>/systems/<hostname>/sshkeys/{ed25519,rsa}.yaml` already exist.
2. If not, runs `create-ssh-host-keys` to generate them and store them sops-encrypted at that path.
3. Runs `upsert-sops-age-key` to derive an age key from the new ed25519 host key and add/update it
   under `keys:` in the secrets repo's `.sops.yaml`, then ensures it's referenced in the `age:` group(s)
   of every `creation_rules:` entry whose `path_regex` matches `--secrets-file` (default `secrets.yaml`).
4. Runs `sops updatekeys` on the secrets file so it's re-encrypted for the new key.
5. Optionally runs `nix flake update <name>` in the current directory, in case the secrets repo is
   consumed as a non-path flake input that needs to pick up the change (see `--secrets-input` below).
6. Decrypts the new SSH host keys and stages them as extra files.
7. Runs `nixos-anywhere` against `.#<hostname>` in the current directory, installing NixOS on the
   target and pre-seeding it with the same SSH host keys that were just registered in the secrets repo
   (so the target's age identity matches what was just added to `.sops.yaml`).

## Requirements

**The flake you run this from** (your host-config repo, passed as cwd — this is `nix run`'s
working directory, not an argument):

- A `nixosConfigurations.<hostname>` output buildable via `.#<hostname>`.
- A hardware config path at `./systems/<system>/<hostname>/hardware.nix` (Snowfall-lib convention),
  or pass `--hardware-config`/`--system` to override.

**The secrets repo** (passed via `--secrets-repo`):

- A `.sops.yaml` with a top-level `keys:` list of `&anchor age1...` entries and a `creation_rules:`
  list containing at least one `- age:` key group — `upsert-sops-age-key` edits this file in place.
- A secrets file to re-encrypt (default `secrets.yaml` at the repo root; override with
  `--secrets-file` if yours lives elsewhere, e.g. `users/foo/secrets.yaml`).
- `systems/<hostname>/sshkeys/` need not exist yet; it's created on first run.

Both `create-ssh-host-keys` and `upsert-sops-age-key` are vendored here as their own flake packages
(originally split out of a private `nix-secrets`-style repo) so this flake has no dependency on any
private inputs.

## Usage

```console
nix run github:<you>/noa-install#noa-install -- \
  -h myhost \
  -i 192.168.1.50 \
  -s /path/to/secrets-repo
```

Run this from the root of your host-config flake. The target machine should be reachable over SSH
as root (e.g. booted into any NixOS installer/rescue ISO, or already running NixOS) — nixos-anywhere
handles the kexec/partition/install flow from there.

### Flags

Every flag except `--config` can also be set from a config file instead (see [Config file](#config-file)
below) - "required" below means required by *some* combination of CLI flags and config files, not that
it must be passed on the command line specifically.

| Flag | Required | Default | Description |
|---|---|---|---|
| `-h, --hostname` | yes* | | Target hostname; must match a `nixosConfigurations.<hostname>` output and a `<secrets-repo>/systems/<hostname>/` directory |
| `-i, --ip` | yes* | | Target IP address |
| `-s, --secrets-repo` | yes* | | Path to the sops secrets repo |
| `-u, --user` | no | `root` | SSH user on the target |
| `--secrets-file` | no | `secrets.yaml` | File, relative to `--secrets-repo`, to run `sops updatekeys` on |
| `--secrets-input` | no | (unset) | Name of a flake input in the current flake pointing at the secrets repo; if set, runs `nix flake update <name>` after bootstrapping. Skip this if the input is a local path (nothing to update) |
| `--hardware-config` | no | `./systems/<system>/<hostname>/hardware.nix` | Where nixos-anywhere writes the generated hardware config |
| `--system` | no | `x86_64-linux` | Used only to compute the default `--hardware-config` path |
| `--no-reboot` | no | off | Skip the reboot phase (`--phases kexec,disko,install`) |
| `-P, --ssh-port` | no | `22` | SSH port on the target (passed to nixos-anywhere as `--ssh-port`) |
| `-I, --identity-file` | no | (unset) | SSH private key to authenticate to the target with (passed to nixos-anywhere as `-i`); omit to use your agent/default keys |
| `--config` | no | (unset) | Extra config file layered on top of the XDG and cwd config files - see below |

\* required overall, but can come from a config file instead of the command line.

## Config file

Any flag above (except `--config` itself) can be set in a YAML config file instead, using the same
name with or without dashes - both `secrets-repo:` and `secrets_repo:` work, since keys are
normalized on load. Command-line flags always take precedence over every config file.

Config files are looked up and layered in this order, each one overriding fields set by the ones
before it (fields it doesn't mention fall through):

1. `$XDG_CONFIG_HOME/noa-install/config.yaml` (or `~/.config/noa-install/config.yaml` if
   `$XDG_CONFIG_HOME` is unset) - a good place for things that are the same across every host you
   provision, like `secrets-repo` and `user`.
2. `.noa-install.yaml` in the current directory (i.e. your host-config flake's root).
3. `--config <path>`, if passed.
4. Command line flags.

Example `~/.config/noa-install/config.yaml` for someone who provisions several hosts against the
same secrets repo:

```yaml
secrets-repo: /home/me/projects/nix-secrets
secrets-input: nix-secrets
user: root
```

With that in place, provisioning a new host only needs the two things that actually change:

```console
nix run github:<you>/noa-install#noa-install -- -h myhost -i 192.168.1.50
```

## Packages

- `noa-install` — the script described above.
- `create-ssh-host-keys` — generates ed25519+rsa SSH host keys for a hostname and stores them sops-encrypted at `systems/<hostname>/sshkeys/{ed25519,rsa}.yaml` (skips existing keys unless `--overwrite`).
- `upsert-sops-age-key` — adds/updates a host's `&anchor age1...` entry in `.sops.yaml` (deriving it from the host's ed25519 SSH key if not passed explicitly) and references it from the `age:` group(s) of every `creation_rules` entry matching `--target` (repeatable, default `secrets.yaml`). Edits the file with [ruamel.yaml](https://yaml.readthedocs.io/) so existing anchors/aliases, comments, and other entries survive round-tripping intact.
- `sops-utils` — small Python library shared by the above (sops file helpers, command runner).
