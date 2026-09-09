#!/usr/bin/env python3
import argparse
import os
import json
import tempfile

from enum import Enum
from pathlib import Path
from typing import Optional

import delegator

from sops_utils import run_command, ensure_sops_file, SopsFile

class Keytype(Enum):
    ED25519 = ["-t", "ed25519"]
    RSA = ["-t", "rsa", "-b", "4096"]

def generate_keypair(keytype: Keytype) -> tuple[Optional[str], Optional[str]]:
    with tempfile.TemporaryDirectory() as td:
        tpath = Path(td)
        tempkey = tpath / 'key'
        temppub = tpath / 'key.pub'
        os.mkfifo(tempkey)
        os.mkfifo(temppub)
        keyout = delegator.run(['cat', tempkey])
        pubout = delegator.run(['cat', temppub])
        keygen_cmd = ['ssh-keygen'] + keytype.value + ['-f', str(tempkey)]
        makekey = delegator.run(keygen_cmd)
        makekey.send('y')
    if makekey.return_code == 0:
        key = keyout.out
        pubkey = pubout.out
    else:
        raise Exception("Failed to create key:", " ".join(keygen_cmd))
    return key, pubkey


def check_key_exists(sops_file: str, key_name: str) -> bool:
    """Checks if a key exists in a SOPS file."""
    if not os.path.exists(sops_file):
        return False

    # Try to decrypt and check for the key
    # We use sops decrypt --extract to check for existence
    # If it fails, the key doesn't exist or the file is invalid
    cmd = f"sops decrypt --extract '[\"{key_name}\"]' {sops_file}"
    c = delegator.run(cmd)
    return c.return_code == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Create SSH host keys (RSA and Ed25519) and store them in sops files.")
    parser.add_argument("hostname", help="The hostname for which to generate SSH keys (e.g., 'my-server').")
    parser.add_argument("--overwrite", "-o", default=False, action="store_true", help="Overwrite existing keys")
    args = parser.parse_args()

    output_dir = os.path.abspath(os.path.join("systems", args.hostname, "sshkeys"))
    print(f"Ensuring output directory exists: {output_dir}")
    os.makedirs(output_dir, exist_ok=True)

    key_types = {
        "rsa": ["-t", "rsa", "-b", "4096"],
        "ed25519": ["-t", "ed25519"],
    }

    for key_type, key_opts in key_types.items():
        print(f"\n--- Processing {key_type.upper()} key for {args.hostname} ---")
        sops_file = os.path.join(output_dir, f"{key_type}.yaml")

        # Check if keys already exist
        if not args.overwrite:
            private_exists = check_key_exists(sops_file, "private_key")
            public_exists = check_key_exists(sops_file, "public_key")

            if private_exists and public_exists:
                print(f"Keys already exist in {sops_file}. Skipping generation.")
                continue
            elif private_exists or public_exists:
                print(f"Partial keys found in {sops_file}. Regenerating to ensure consistency.")

        ensure_sops_file(sops_file)

        with tempfile.TemporaryDirectory() as tempdir:
            key_path = os.path.join(tempdir, f"ssh_host_{key_type}_key")
            comment = f"root@{args.hostname}"

            # Generate SSH key
            print(f"Generating {key_type} SSH key...")
            opts_str = " ".join(key_opts)
            keygen_command = f"ssh-keygen {opts_str} -f {key_path} -N '' -C {comment}"
            run_command(keygen_command)

            # Read the private and public keys
            with open(key_path, 'r') as f:
                private_key = f.read()
            with open(f"{key_path}.pub", 'r') as f:
                public_key = f.read()

        # Store keys in the SOPS file
        print(f"Storing private key in {sops_file}...")
        private_val = json.dumps(private_key)
        run_command(f"sops --set '[\"private_key\"] {private_val}' {sops_file}")

        print(f"Storing public key in {sops_file}...")
        public_val = json.dumps(public_key)
        run_command(f"sops --set '[\"public_key\"] {public_val}' {sops_file}")

        print(f"Successfully stored {key_type.upper()} keys in {sops_file}")

    print("\nSuccess!")
    print(f"SSH host keys for {args.hostname} have been processed.")

if __name__ == "__main__":
    main()
