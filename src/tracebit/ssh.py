import base64
import os
import subprocess
from pathlib import Path


SSH_DIR = Path.home() / ".ssh"
SSH_CONFIG = SSH_DIR / "config"


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


def _remove_host_block(text, ssh_host):
    """Remove a Host block matching ssh_host from ssh config text."""
    lines = text.splitlines(keepends=True)
    result = []
    in_block = False
    for line in lines:
        parts = line.strip().split()
        if parts and parts[0].lower() == "host":
            in_block = len(parts) > 1 and parts[1] == ssh_host
            if in_block:
                continue
        if not in_block:
            result.append(line)
    return "".join(result)


def validate_ssh_host(ssh_host):
    """Raise ValueError if ssh_host contains characters unsafe for ssh config."""
    if any(c in str(ssh_host) for c in ("\n", "\r", " ", "\t")):
        raise ValueError(
            f"Invalid --ssh-host value {ssh_host!r}: "
            f"must not contain whitespace or newlines."
        )


def write_ssh_config(ssh_host, key_path, ssh_ip, config_file=None):
    """Append a Host block to an ssh config file for the canary."""
    validate_ssh_host(ssh_host)
    if config_file is None:
        config_file = SSH_CONFIG
    config_file = Path(config_file)

    if not config_file.parent.exists():
        raise OSError(
            f"Parent directory of ssh config file does not exist: {config_file.parent}"
        )

    existing = config_file.read_text() if config_file.exists() else ""
    cleaned = _remove_host_block(existing, ssh_host).rstrip("\n")

    lines = [f"Host {ssh_host}"]
    if str(ssh_host) != str(ssh_ip):
        lines.append(f"    HostName {ssh_ip}")
    lines.append(f"    IdentityFile {key_path}")
    lines.append(f"    PasswordAuthentication no")
    new_block = "\n".join(lines) + "\n"

    content = (cleaned + "\n\n" + new_block) if cleaned else new_block
    config_file.write_text(content)
    os.chmod(config_file, 0o600)


def remove_ssh_config(ssh_host, config_file=None):
    """Remove a Host block from an ssh config file."""
    if config_file is None:
        config_file = SSH_CONFIG
    config_file = Path(config_file)
    if not config_file.exists():
        return
    text = config_file.read_text()
    cleaned = _remove_host_block(text, ssh_host).rstrip("\n")
    config_file.write_text(cleaned + "\n" if cleaned else "")
    os.chmod(config_file, 0o600)


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
