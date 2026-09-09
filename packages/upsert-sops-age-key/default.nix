{ lib, stdenv, python3, makeWrapper, ssh-to-age, sops }:

let
  python = python3.withPackages (ps: [
    ps.delegator-py
    ps.ruamel-yaml
  ]);
in
stdenv.mkDerivation rec {
  pname = "upsert-sops-age-key";
  version = "0.1.0";

  src = ./.;

  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    mkdir -p $out/libexec/${pname}
    install -m 755 upsert_sops_age_key.py $out/libexec/${pname}/

    mkdir -p $out/bin
    makeWrapper ${python}/bin/python $out/bin/upsert-sops-age-key \
      --add-flags "$out/libexec/${pname}/upsert_sops_age_key.py" \
      --prefix PATH : ${lib.makeBinPath [
        ssh-to-age
        sops
      ]}
  '';

  meta = with lib; {
    description = "A script to upsert a SOPS age key into .sops.yaml";
    license = licenses.mit; # Or appropriate license
  };
}
