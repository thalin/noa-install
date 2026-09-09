{
  description = "Provision new NixOS hosts via nixos-anywhere, wired up to a sops-nix secrets repo";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";

    snowfall-lib = {
      url = "github:snowfallorg/lib";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # Only used by the systems/x86_64-linux/demo-vm example.
    disko = {
      url = "github:nix-community/disko";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs:
    inputs.snowfall-lib.mkFlake {
      inherit inputs;
      src = ./.;

      # This only ships Linux packages (nixos-anywhere targets); restricting
      # supported systems avoids evaluating pkgs for unrelated platforms.
      supportedSystems = [ "x86_64-linux" "aarch64-linux" ];

      snowfall = {
        namespace = "noa-install";
        meta = {
          name = "noa-install";
          title = "NixOS-anywhere host provisioning + sops-nix key bootstrap";
        };
      };
    };
}
