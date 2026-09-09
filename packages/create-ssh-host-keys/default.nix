{
  lib,
  stdenv,
  python3,
  sops,
  openssh,
  makeWrapper,
  namespace,
  pkgs,
  ...
}:

let
  python = python3.withPackages (ps: [
    pkgs.${namespace}.sops-utils
    ps.delegator-py
  ]);
  buildInputs = [ sops openssh ];
in
stdenv.mkDerivation rec {
  pname = "create-ssh-host-keys";
  version = "0.1.0";

  src = ./.;

  nativeBuildInputs = [
    makeWrapper
  ];

  installPhase = ''
    runHook preInstall

    mkdir -p $out/libexec/${pname}
    install -m 755 create_ssh_host_keys.py $out/libexec/${pname}/

    mkdir -p $out/bin
    makeWrapper ${python}/bin/python $out/bin/create-ssh-host-keys \
      --add-flags "$out/libexec/${pname}/create_ssh_host_keys.py" \
      --prefix PATH ":" "${lib.makeBinPath buildInputs}"

    runHook postInstall
  '';

  meta = with lib; {
    description = "A script to create SSH host keys using sops.";
  };
}
