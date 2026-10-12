# `nix flake check` entry point for the test suite in ./tests. Runs the
# scripts under packages/ directly (not through the Nix-wrapped binaries) -
# it's exercising the Python logic and its real interaction with sops/age/ssh,
# not the packaging. Needs network-free crypto tooling only, so it's fine
# inside the build sandbox.
{ pkgs, inputs, ... }:
let
  pythonEnv = pkgs.python3.withPackages (ps: [
    ps.pytest
    ps.ruamel-yaml
    ps.pyyaml
    ps.delegator-py
  ]);
in
pkgs.runCommand "noa-install-pytest"
{
  nativeBuildInputs = [
    pythonEnv
    pkgs.sops
    pkgs.age
    pkgs.ssh-to-age
    pkgs.openssh
    pkgs.git
    inputs.sops-compose.packages.${pkgs.stdenv.hostPlatform.system}.default
  ];
}
''
  export HOME="$TMPDIR"
  cp -r ${../../.} source
  chmod -R u+w source
  cd source

  pytest tests -v

  touch $out
''
