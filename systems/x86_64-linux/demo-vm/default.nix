# demo-vm
#
# The config noa-install actually installs, onto target-vm's disk, over SSH.
# Built with `nix run .#noa-install -- -h demo-vm -i 127.0.0.1 ...` per
# examples/README.md.
{ inputs, ... }:
{
  imports = [
    inputs.disko.nixosModules.disko
    ./disko.nix
  ];

  networking.hostName = "demo-vm";

  # disko already wires boot.loader.grub.devices from the disk's `boot`
  # (EF02) partition in ./disko.nix - setting it again here duplicates it.
  # Matches what `nixos-generate-config` would detect for a QEMU/virtio guest;
  # kept inline so this config evaluates before nixos-anywhere ever runs and
  # generates ./hardware.nix for real.
  boot.initrd.availableKernelModules = [ "ahci" "xhci_pci" "virtio_pci" "virtio_blk" "virtio_scsi" "sr_mod" ];

  services.openssh.enable = true;
  # Demo-only key, see examples/demo-ssh-key{,.pub} - throwaway, not a secret.
  users.users.root.openssh.authorizedKeys.keyFiles = [ ../../../examples/demo-ssh-key.pub ];

  system.stateVersion = "25.05";
}
