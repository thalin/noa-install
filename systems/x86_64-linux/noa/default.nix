# Minimal bootable installer ISO for bare-metal targets that don't already
# have SSH-reachable Linux running (nixos-anywhere can kexec from any such
# box, so this is only needed when there's nothing to SSH into yet).
#
# SSH access is granted to whichever pubkeys exist in the *builder's* own
# ~/.ssh/*.pub at build time, not to a fixed key baked into this repo -
# there's no single "owner" of a generic install tool. Reading $HOME requires
# impure evaluation, so build this with:
#
#   nix build --impure .#nixosConfigurations.noa.config.system.build.isoImage
{
  lib,
  pkgs,
  modulesPath,
  ...
}:
let
  inherit (lib) mkForce filterAttrs hasSuffix;
  locale = "en_US.UTF-8";

  home = builtins.getEnv "HOME";
  sshDir = home + "/.ssh";
  authorizedKeyFiles =
    if home != "" && builtins.pathExists sshDir then
      map (name: sshDir + "/" + name) (
        builtins.attrNames (
          filterAttrs (
            name: type: (type == "regular" || type == "symlink") && hasSuffix ".pub" name
          ) (builtins.readDir sshDir)
        )
      )
    else
      [ ];
in
{
  imports = [
    "${modulesPath}/installer/cd-dvd/installation-cd-minimal.nix"
  ];

  assertions = [
    {
      assertion = authorizedKeyFiles != [ ];
      message = ''
        No ~/.ssh/*.pub found for builder $HOME ("${home}") - the installer
        ISO would have no SSH access. Add a pubkey to ~/.ssh/ (or build as a
        user who has one) before building this ISO.
      '';
    }
  ];

  # Strip stuff out of the ISO
  hardware.enableRedistributableFirmware = mkForce false;
  documentation.enable = mkForce false;
  documentation.nixos.enable = mkForce false;

  networking.hostName = "noa";

  environment.systemPackages = with pkgs; [
    vim
    wget
    mtr
    unzip
  ];

  i18n.defaultLocale = locale;

  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  services.openssh.enable = true;

  users.users.root.openssh.authorizedKeys.keyFiles = authorizedKeyFiles;
  users.users.nixos = {
    isNormalUser = true;
    openssh.authorizedKeys.keyFiles = authorizedKeyFiles;
    group = "users";
  };

  system.stateVersion = "25.05";
}
