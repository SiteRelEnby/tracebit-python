import base64
import os
import subprocess
from pathlib import Path


SSH_DIR = Path.home() / ".ssh"


def _ensure_ssh_dir():
    SSH_DIR.mkdir(mode=0o700, exist_ok=True)
    mode = SSH_DIR.stat().st_mode & 0o777
    if mode != 0o700:
        import sys
        print(
            f"Warning: ~/.ssh/ has permissions {oct(mode)} (expected 0700). "
            f"Consider running: chmod 700 ~/.ssh",
            file=sys.stderr,
        )


def deploy_ssh_key(key_filename, private_key_b64):
    """Write a canary SSH private key to ~/.ssh/<key_filename>."""
    _ensure_ssh_dir()
    key_path = SSH_DIR / key_filename
    private_key = base64.b64decode(private_key_b64).decode()
    key_path.write_text(private_key)
    os.chmod(key_path, 0o600)
    return key_path


def remove_ssh_key(key_filename):
    """Remove a canary SSH private key file."""
    key_path = SSH_DIR / key_filename
    if key_path.exists():
        key_path.unlink()


def key_exists(key_filename):
    """Check if a key file already exists."""
    return (SSH_DIR / key_filename).exists()


def trigger_ssh(key_filename, ssh_ip):
    """Attempt SSH connection to Tracebit's honeypot to fire the canary."""
    key_path = SSH_DIR / key_filename
    result = subprocess.run(
        [
            "ssh",
            "-i", str(key_path),
            "-o", "StrictHostKeyChecking=no",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            ssh_ip,
        ],
        capture_output=True, text=True, timeout=15,
    )
    # SSH to a honeypot will always "fail" auth-wise — that's expected.
    # The canary fires on the server side when the key is presented.
    return result
