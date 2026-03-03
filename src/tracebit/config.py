import os
from pathlib import Path


DEFAULT_BASE_URL = "https://community.tracebit.com"
CONFIG_DIR = Path.home() / ".config" / "tracebit"
TOKEN_FILE = CONFIG_DIR / "token"


def get_base_url():
    return os.environ.get("TRACEBIT_URL", DEFAULT_BASE_URL).rstrip("/")


def load_token():
    """Load API token from env var or config file."""
    token = os.environ.get("TRACEBIT_API_TOKEN")
    if token:
        return token.strip()
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return None


def save_token(token):
    """Save API token to config file with restricted permissions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token.strip() + "\n")
    TOKEN_FILE.chmod(0o600)
