# target-vm
#
# Stands in for "bare metal" in the noa-install demo: a plain NixOS VM,
# reachable over SSH, with nothing installed by this flake yet. nixos-anywhere
# kexecs it into an installer environment and formats its disk according to
# systems/x86_64-linux/demo-vm/disko.nix, replacing it with `demo-vm` in place.
#
# Build & run with:
#   nix build .#nixosConfigurations.target-vm.config.system.build.vm
#   ./result/bin/run-target-vm-vm
#
# `virtualisation.useBootLoader` makes this boot exactly like real hardware
# would (BIOS -> disk's own bootloader) on every run, including after
# nixos-anywhere installs and reboots it - not the direct-kernel-boot shortcut
# `nix build .#nixosConfigurations.<x>.config.system.build.vm` normally takes.
{ modulesPath, ... }:
{
  imports = [ (modulesPath + "/virtualisation/qemu-vm.nix") ];

  virtualisation.useBootLoader = true;
  virtualisation.diskSize = 4096;
  virtualisation.memorySize = 2048;
  virtualisation.graphics = false;
  virtualisation.forwardPorts = [
    { from = "host"; host.port = 2222; guest.port = 22; }
  ];

  networking.hostName = "target-vm";
  services.openssh.enable = true;
  services.openssh.settings.PermitRootLogin = "yes";
  # Demo-only key so the operator can SSH in as root to kick off nixos-anywhere.
  # See examples/demo-ssh-key{,.pub} - throwaway, not a secret.
  users.users.root.openssh.authorizedKeys.keyFiles = [ ../../../examples/demo-ssh-key.pub ];

  system.stateVersion = "25.05";
}
