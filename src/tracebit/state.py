import json
import os
from datetime import datetime, timezone
from pathlib import Path


STATE_DIR = Path.home() / ".config" / "tracebit"
STATE_FILE = STATE_DIR / "state.json"


def _load_state():
    if not STATE_FILE.exists():
        return {"credentials": []}
    with open(STATE_FILE) as f:
        return json.load(f)


def _save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    os.chmod(STATE_FILE, 0o600)


def save_credential(data):
    """Save or update a deployed credential entry.

    data should contain: name, type, profile, region, expiration,
    confirmation_id, labels (dict).
    """
    state = _load_state()
    # replace existing entry with same name+type
    state["credentials"] = [
        c for c in state["credentials"]
        if not (c["name"] == data["name"] and c["type"] == data["type"])
    ]
    state["credentials"].append(data)
    _save_state(state)


def load_credentials():
    """Return list of all deployed credentials."""
    return _load_state().get("credentials", [])


def remove_credential(name, cred_type=None):
    """Remove a credential by name (and optionally type)."""
    state = _load_state()
    if cred_type:
        state["credentials"] = [
            c for c in state["credentials"]
            if not (c["name"] == name and c["type"] == cred_type)
        ]
    else:
        state["credentials"] = [
            c for c in state["credentials"] if c["name"] != name
        ]
    _save_state(state)


def get_credential(name, cred_type="aws"):
    """Get a specific credential by name and type."""
    for c in load_credentials():
        if c["name"] == name and c["type"] == cred_type:
            return c
    return None


def get_expiring_credentials(hours=2):
    """Return credentials expiring within the given number of hours."""
    now = datetime.now(timezone.utc)
    expiring = []
    for c in load_credentials():
        exp = c.get("expiration")
        if not exp:
            continue
        exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        diff = (exp_dt - now).total_seconds() / 3600
        if diff < hours:
            expiring.append(c)
    return expiring
