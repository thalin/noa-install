# default.nix
# This file defines how to build the noa-install script using Nix.
{
  pkgs,
  namespace,
  ...
}:

let
  # Create a python environment with the pyyaml library, so it's available
  # when the script runs.
  pythonEnv = pkgs.python3.withPackages (ps: [ ps.pyyaml ps.delegator-py ]);

  # Read the python script into a string.
  scriptContent = builtins.readFile ./noa-install.py;

  # Manually substitute the placeholders using a standard library function.
  # This is more robust than relying on higher-level helpers that may change.
  substitutedContent = pkgs.lib.strings.replaceStrings
    [ "@nix@" "@nixos_anywhere@" "@sops@" "@create_ssh_host_keys@" "@upsert_sops_age_key@" ]
    [
      "${pkgs.nix}/bin/nix"
      "${pkgs.nixos-anywhere}/bin/nixos-anywhere"
      "${pkgs.sops}/bin/sops"
      "${pkgs.${namespace}.create-ssh-host-keys}/bin/create-ssh-host-keys"
      "${pkgs.${namespace}.upsert-sops-age-key}/bin/upsert-sops-age-key"
    ]
    scriptContent;

in
# This function creates a final executable script.
# The shebang uses the specific pythonEnv to ensure dependencies are found,
# and the body of the script is the string with all variables substituted.
pkgs.writeScriptBin "noa-install" ''
  #!${pythonEnv}/bin/python
  ${substitutedContent}
''
