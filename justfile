default:
    @just --list

# --impure is required: the ISO authorizes the builder's own ~/.ssh/*.pub for SSH access.

# Build the noa installer ISO (output in result/iso/)
iso:
    nix shell nixpkgs#nix-output-monitor -c nom build --impure .#nixosConfigurations.noa.config.system.build.isoImage
