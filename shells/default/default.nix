# Dev shell for running the test suite locally: `nix develop -c pytest tests`
{ pkgs, ... }:
let
  pythonEnv = pkgs.python3.withPackages (ps: [
    ps.pytest
    ps.ruamel-yaml
    ps.pyyaml
    ps.delegator-py
  ]);
in
pkgs.mkShell {
  packages = [
    pythonEnv
    pkgs.sops
    pkgs.age
    pkgs.ssh-to-age
    pkgs.openssh
  ];
}
