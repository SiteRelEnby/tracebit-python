import configparser
import os
from pathlib import Path


AWS_DIR = Path.home() / ".aws"
CREDENTIALS_FILE = AWS_DIR / "credentials"
CONFIG_FILE = AWS_DIR / "config"


def _ensure_aws_dir():
    AWS_DIR.mkdir(mode=0o700, exist_ok=True)


def _read_ini(path):
    parser = configparser.ConfigParser()
    if path.exists():
        parser.read(str(path))
    return parser


def _write_ini(parser, path):
    with open(path, "w") as f:
        parser.write(f)
    os.chmod(path, 0o600)


def deploy_aws_credentials(profile, region, access_key_id, secret_access_key,
                            session_token):
    """Write canary AWS credentials to ~/.aws/credentials and ~/.aws/config."""
    _ensure_aws_dir()

    # credentials file
    creds = _read_ini(CREDENTIALS_FILE)
    if not creds.has_section(profile):
        creds.add_section(profile)
    creds.set(profile, "aws_access_key_id", access_key_id)
    creds.set(profile, "aws_secret_access_key", secret_access_key)
    creds.set(profile, "aws_session_token", session_token)
    _write_ini(creds, CREDENTIALS_FILE)

    # config file
    config = _read_ini(CONFIG_FILE)
    config_section = f"profile {profile}" if profile != "default" else "default"
    if not config.has_section(config_section):
        config.add_section(config_section)
    config.set(config_section, "region", region)
    _write_ini(config, CONFIG_FILE)


def remove_aws_credentials(profile):
    """Remove a profile from both AWS credential files."""
    for path, section in [
        (CREDENTIALS_FILE, profile),
        (CONFIG_FILE, f"profile {profile}" if profile != "default" else "default"),
    ]:
        if not path.exists():
            continue
        parser = _read_ini(path)
        if parser.has_section(section):
            parser.remove_section(section)
            _write_ini(parser, path)


def get_aws_credentials(profile):
    """Read back credentials for a profile, or None if not found."""
    creds = _read_ini(CREDENTIALS_FILE)
    if not creds.has_section(profile):
        return None
    return {
        "aws_access_key_id": creds.get(profile, "aws_access_key_id", fallback=None),
        "aws_secret_access_key": creds.get(profile, "aws_secret_access_key", fallback=None),
        "aws_session_token": creds.get(profile, "aws_session_token", fallback=None),
    }


def profile_exists(profile):
    """Check if a profile already exists in the credentials file."""
    creds = _read_ini(CREDENTIALS_FILE)
    return creds.has_section(profile)
