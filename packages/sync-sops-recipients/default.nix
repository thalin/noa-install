{ lib, stdenv, python3, makeWrapper, sops }:

let
  python = python3.withPackages (ps: [
    ps.ruamel-yaml
  ]);
in
stdenv.mkDerivation rec {
  pname = "sync-sops-recipients";
  version = "0.1.0";

  src = ./.;

  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    mkdir -p $out/libexec/${pname}
    install -m 755 sync_sops_recipients.py $out/libexec/${pname}/

    mkdir -p $out/bin
    makeWrapper ${python}/bin/python $out/bin/sync-sops-recipients \
      --add-flags "$out/libexec/${pname}/sync_sops_recipients.py" \
      --prefix PATH : ${lib.makeBinPath [ sops ]}
  '';

  meta = with lib; {
    description = "Re-encrypt sops files whose age recipients have drifted from .sops.yaml";
    license = licenses.mit;
  };
}
