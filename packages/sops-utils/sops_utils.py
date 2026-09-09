import delegator
import sys
import os
from datetime import datetime, timezone
import json

def run_command(command):
    """Runs a command and returns the result object."""
    c = delegator.run(command)
    if c.return_code != 0:
        print(f"Error: command failed: {command}", file=sys.stderr)
        if c.out:
            print("--- stdout ---", file=sys.stderr)
            print(c.out, file=sys.stderr)
        if c.err:
            print("--- stderr ---", file=sys.stderr)
            print(c.err, file=sys.stderr)
        c.block() # block on failing command to get more output
    return c

def ensure_sops_file(sops_file):
    """Ensures a sops file exists, creating it if necessary."""
    if not os.path.exists(sops_file):
        print(f"Creating new sops file: {sops_file}")
        dirname = os.path.dirname(sops_file)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(sops_file, 'w') as f:
            json.dump({"created": datetime.now(timezone.utc).isoformat()}, f)
        run_command(f"sops encrypt -i {sops_file}")
    else:
        print(f"Verifying existing sops file: {sops_file}")
        c = run_command(f"sops decrypt {sops_file}")
        if c.return_code != 0:
            print(f"Error: Failed to decrypt existing sops file {sops_file}. Is it a valid sops file?", file=sys.stderr)
            sys.exit(1)

class SopsFile:
    def __init__(self, filepath):
        self.filepath = filepath

    def set(self, key, value):
        ensure_sops_file(self.filepath)

        # sops --set takes a chain of bracketed, individually JSON-encoded
        # path components followed by the JSON-encoded value, e.g.
        # '["a"]["b"] "value"' - NOT a single nested JSON object.
        path = ''.join(f'[{json.dumps(k)}]' for k in key.split('.'))
        value_json = json.dumps(value)

        run_command(f"sops --set '{path} {value_json}' {self.filepath}")
