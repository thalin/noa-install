# Demo: install `demo-vm` onto `target-vm` with noa-install

This walks through a full, local, no-real-hardware run of `noa-install`: a
throwaway QEMU VM (`target-vm`) stands in for bare metal, and `noa-install`
provisions it with the `demo-vm` NixOS config, bootstrapping SSH host keys
and a sops age key in a demo secrets repo along the way.

Run everything below from the root of this repo (`noa-install/`).

## 1. Boot the target VM

```console
nix build .#nixosConfigurations.target-vm.config.system.build.vm
./result/bin/run-target-vm-vm
```

This opens in the current terminal (SeaBIOS -> GRUB -> NixOS boot). Leave it
running; open a new terminal for the rest of these steps. It creates
`target-vm.qcow2` in your current directory - delete it to reset the VM.

The VM forwards host port `2222` to its guest port `22`. Confirm it's up:

```console
ssh -i examples/demo-ssh-key -o StrictHostKeyChecking=no -p 2222 root@127.0.0.1 hostname
# -> target-vm
```

(`examples/demo-ssh-key` is a throwaway keypair checked in for this demo -
regenerate it with `ssh-keygen -t ed25519 -f examples/demo-ssh-key -N "" -C noa-install-demo`
if it's missing; it's gitignored on purpose.)

## 2. Create the demo secrets repo's encrypted files

`examples/secrets-repo/` ships `.sops.yaml` and a plaintext
`secrets.example.yaml`, but the actual encrypted `secrets.yaml` and the admin
age identity (`admin-key.txt`) are gitignored - generate your own:

```console
age-keygen -o examples/secrets-repo/admin-key.txt
```

It prints a public key (`age1...`). Open `examples/secrets-repo/.sops.yaml`
and replace the value on the `&admin` line under `keys:` with it, so the
demo repo's recipients match a key you actually hold.

Then encrypt the example secrets file for that key:

```console
cd examples/secrets-repo
SOPS_AGE_KEY_FILE=$PWD/admin-key.txt sops --config .sops.yaml encrypt --output secrets.yaml secrets.example.yaml
cd -
```

## 3. Run noa-install

```console
SOPS_AGE_KEY_FILE=$PWD/examples/secrets-repo/admin-key.txt \
nix run .#noa-install -- \
  -h demo-vm \
  -i 127.0.0.1 \
  -P 2222 \
  -I examples/demo-ssh-key \
  -u root \
  -s examples/secrets-repo
```

This will, in order:

1. Run `create-ssh-host-keys demo-vm` in `examples/secrets-repo`, generating
   `systems/demo-vm/sshkeys/{ed25519,rsa}.yaml` (sops-encrypted).
2. Run `upsert-sops-age-key demo-vm`, deriving an age key from the new
   ed25519 host key and adding it to `.sops.yaml` under `keys:` and the
   `secrets.yaml`/`sshkeys` creation rules.
3. Run `sops updatekeys secrets.yaml` so it's re-encrypted for the new key.
4. Decrypt the new SSH host keys and stage them as extra files.
5. Run `nixos-anywhere --flake .#demo-vm --target-host root@127.0.0.1
   --ssh-port 2222 -i examples/demo-ssh-key`, which kexecs `target-vm`,
   partitions its disk per `systems/x86_64-linux/demo-vm/disko.nix`, and
   installs+boots `demo-vm`.

When it finishes, `target-vm`'s VM window will reboot into `demo-vm`:

```console
ssh -i examples/demo-ssh-key -p 2222 root@127.0.0.1 hostname
# -> demo-vm
```

## Resetting

```console
rm -f target-vm.qcow2 examples/known_hosts \
      examples/secrets-repo/admin-key.txt examples/secrets-repo/secrets.yaml
rm -rf examples/secrets-repo/systems
```

then start again from step 1.
