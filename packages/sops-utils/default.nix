{ lib
, python3
, sops
}:

python3.pkgs.buildPythonPackage rec {
  pname = "sops-utils";
  version = "0.1.0";
  format = "setuptools";

  src = ./.;

  propagatedBuildInputs = [
    sops
    python3.pkgs.delegator-py
  ];

  doCheck = false;

  meta = with lib; {
    description = "A utility library for sops operations.";
  };
}
