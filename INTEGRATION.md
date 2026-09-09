# Integrating noa-install into your own setup

This walks through wiring `noa-install` into an existing NixOS host-config flake and sops secrets
repo you already have, as opposed to the throwaway demo in [`examples/`](./examples). See the main
[README](./README.md) for what the tool does and the full flag reference — this doc is about how it
plugs into a real setup.

## Do you have the right shape of repos?

`noa-install` assumes two repos, which can be the same repo or two separate ones:

1. **A host-config flake** with a `nixosConfigurations.<hostname>` output per machine. If you use
   [Snowfall-lib](https://snowfall.org), that's just `systems/<system>/<hostname>/default.nix` and you're
   already set up correctly. If not, see [Non-Snowfall layouts](#non-snowfall-layouts) below.
2. **A sops secrets repo** with a `.sops.yaml` using the `keys:` + `creation_rules:` shape (anchors
   under `keys:`, referenced by alias from the `age:` field of each `creation_rules:` entry — either
   directly or via a named group under an optional `keygroups:` block) - this is the standard
   [sops](https://github.com/getsops/sops) config format, not something specific to this tool. If
   you don't have per-host SSH keys and age identities yet, `noa-install` will create the first one
   for you on its first run.

If your secrets repo doesn't have a `.sops.yaml` at all yet, create a minimal one first:

```yaml
# .sops.yaml
keys:
  - &admin age1...your own age public key...
keygroups:
  all: &all
    - *admin
creation_rules:
  - path_regex: secrets\.yaml
    age: *all
  - path_regex: 'systems/.*/sshkeys/.*\.yaml'
    age:
      - *admin
```

The second rule is what lets `create-ssh-host-keys` encrypt the SSH keys it generates for new hosts -
without a rule matching `systems/<hostname>/sshkeys/*.yaml`, `sops encrypt` has no recipients to
encrypt to and will fail. `upsert-sops-age-key` also still supports the legacy `key_groups:` shape if
that's what your existing repo already uses. See
[`examples/secrets-repo/.sops.yaml`](./examples/secrets-repo/.sops.yaml) for a copy of exactly this.

## 1. Run it directly (no flake changes needed)

The quickest way to use this needs no changes to your flake at all - `noa-install` is fully
self-contained, so you can just run it straight from GitHub against your existing host-config flake:

```console
nix run github:thalin/noa-install#noa-install -- \
  -h myhost \
  -i 192.168.1.50 \
  -s /path/to/your/secrets-repo
```

Run this from the root of your host-config flake (it builds `.#<hostname>` from the current
directory). That's the entire integration for most setups - the rest of this doc covers optional
niceties.

## 2. (Optional) Add it as a flake input for a shorter, pinned invocation

If you'd rather not depend on GitHub resolving `noa-install` fresh every time (and want it pinned in
your `flake.lock` like any other input), add it and re-export its package:

```nix
inputs = {
  # ...
  noa-install.url = "github:thalin/noa-install";
};

# in outputs, wherever you build packages.${system}:
packages.${system}.noa-install = inputs.noa-install.packages.${system}.noa-install;
```

With [Snowfall-lib](https://snowfall.org) this line isn't needed manually - Snowfall doesn't
auto-expose *other flakes'* packages, so you'd still add it yourself in your `flake.nix`'s
`outputs-builder` or a `packages/noa-install/default.nix` that re-exports it. Once exposed, you can
invoke it as `nix run .#noa-install -- ...` from your own flake.

Note that `--secrets-input` (below) doesn't require this step - it operates on an input already
declared in *your* flake, independent of whether `noa-install` itself is one.

## 3. (Optional) Add a justfile recipe

If your host-config flake already uses [`just`](https://github.com/casey/just) (as noa-install's own
predecessor did), wiring up a recipe makes this a one-liner:

```just
# Provision a new host. Target should be reachable via SSH as root
# (booted into any NixOS installer/rescue environment, or already NixOS).
install hostname ipaddr:
    nix run github:thalin/noa-install#noa-install -- -h {{hostname}} -i {{ipaddr}} -s ../nix-secrets
```

Adjust the `-s` path to wherever your secrets repo actually lives relative to your host-config repo.

## 4. (Optional) Use a config file instead of repeating flags

If you provision more than one host, most flags are the same every time - `--secrets-repo`,
`--secrets-input`, `--user`, and so on rarely change, only `--hostname` and `--ip` do. Rather than a
justfile recipe (or in addition to one), put the stable settings in
`~/.config/noa-install/config.yaml` (or `$XDG_CONFIG_HOME/noa-install/config.yaml`, if you've set
that elsewhere):

```yaml
secrets-repo: /home/me/projects/nix-secrets
secrets-input: nix-secrets
```

and per-repo overrides (say, a second host-config repo pointing at a different secrets repo) in a
`.noa-install.yaml` at that repo's root - it's checked into or gitignored from that repo same as any
other file, whichever you prefer:

```yaml
secrets-repo: ../nix-secrets
```

Command line flags still override both, so `-h`/`-i` per invocation plus a config file for
everything else is usually the sweet spot:

```console
nix run github:thalin/noa-install#noa-install -- -h myhost -i 192.168.1.50
```

See the main README's [Config file](./README.md#config-file) section for the full precedence order
(`$XDG_CONFIG_HOME` → cwd → `--config` → CLI flags) and key naming rules.

## Choosing `--secrets-input`

If your secrets repo is consumed by your host-config flake as a git/GitHub flake input (not a local
`path:` input), pass `--secrets-input <name>` so `noa-install` runs `nix flake update <name>` after
bootstrapping - otherwise your flake's lock file still points at the pre-bootstrap commit when
`nixos-anywhere` evaluates `.#<hostname>`, and the freshly-added age key/re-encrypted secrets won't
be visible yet:

```console
nix run github:thalin/noa-install#noa-install -- \
  -h myhost -i 192.168.1.50 -s /path/to/secrets-repo \
  --secrets-input nix-secrets
```

If it's a local `path:` input (or not a flake input of your host-config flake at all), omit
`--secrets-input` - there's nothing to update, since path inputs are read live.

## Non-Snowfall layouts

`noa-install` defaults to writing the generated hardware config to
`./systems/<system>/<hostname>/hardware.nix` and building `.#<hostname>` from the current directory.
If your flake doesn't use Snowfall's `systems/<arch>/<hostname>/` convention:

- Pass `--hardware-config <path>` to control where the generated hardware config is written. Make
  sure your `nixosConfigurations.<hostname>` actually imports it (or drop the flag if you don't
  want to use nixos-anywhere's generated one, e.g. because you maintain hardware config by hand).
- The `--system` flag only affects the *default* `--hardware-config` path computation
  (`./systems/<system>/<hostname>/hardware.nix`) - it doesn't need to match anything if you're
  already overriding `--hardware-config` explicitly.

## What happens on re-runs

`noa-install` is safe to re-run against the same host. If
`<secrets-repo>/systems/<hostname>/sshkeys/{ed25519,rsa}.yaml` already exist, it skips straight to
staging the existing keys and running `nixos-anywhere` again - it won't regenerate keys, touch
`.sops.yaml`, or re-run `sops updatekeys`. This makes it reasonable to use for reinstalls, not just
first-time provisioning.

## Troubleshooting

- **`sops encrypt`/`create-ssh-host-keys` fails for a new host** - almost always means your
  `.sops.yaml` has no `creation_rules` entry matching `systems/<hostname>/sshkeys/*.yaml`. Add the
  rule shown above.
- **`upsert-sops-age-key` warns `no creation_rules matched targets`** - your `--secrets-file` (default
  `secrets.yaml`) doesn't match any `path_regex` in `.sops.yaml`. Either add a matching rule, or pass
  `--secrets-file` pointing at whichever file's rule you want the new host referenced in - see the
  main README's flag table for `--secrets-file`/`--secrets-input`.
- **nixos-anywhere can't reach the target** - `-P/--ssh-port` and `-I/--identity-file` exist for
  targets on a non-standard port or requiring a specific key (see the [demo](./examples/README.md)
  for a concrete example using both against a local VM).
- **Fresh clone, want to test the whole flow without touching your real infra first** - run through
  [`examples/README.md`](./examples/README.md), which does the entire thing (key bootstrap, sops
  encryption, nixos-anywhere install) against a disposable local VM.
