import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from tracebit.state import (
    save_credential,
    load_credentials,
    remove_credential,
    get_credential,
    get_expiring_credentials,
)


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    """Redirect state file to a temp directory for every test."""
    import tracebit.state as state_mod
    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.json")


def make_cred(**kwargs):
    base = {
        "name": "test-server",
        "type": "aws",
        "profile": "staging",
        "region": "us-east-1",
        "expiration": "2099-01-01T00:00:00Z",
        "confirmation_id": "abc-123",
        "labels": {},
    }
    base.update(kwargs)
    return base


def test_save_and_load():
    cred = make_cred()
    save_credential(cred)
    creds = load_credentials()
    assert len(creds) == 1
    assert creds[0]["name"] == "test-server"
    assert creds[0]["profile"] == "staging"


def test_save_replaces_same_name_and_type():
    save_credential(make_cred(profile="old"))
    save_credential(make_cred(profile="new"))
    creds = load_credentials()
    assert len(creds) == 1
    assert creds[0]["profile"] == "new"


def test_save_keeps_different_type():
    save_credential(make_cred(type="aws"))
    save_credential(make_cred(type="ssh"))
    assert len(load_credentials()) == 2


def test_remove_by_name_and_type():
    save_credential(make_cred())
    remove_credential("test-server", "aws")
    assert load_credentials() == []


def test_remove_by_name_only():
    save_credential(make_cred(type="aws"))
    save_credential(make_cred(type="ssh"))
    remove_credential("test-server")
    assert load_credentials() == []


def test_remove_leaves_others():
    save_credential(make_cred(name="server-a"))
    save_credential(make_cred(name="server-b"))
    remove_credential("server-a", "aws")
    creds = load_credentials()
    assert len(creds) == 1
    assert creds[0]["name"] == "server-b"


def test_get_credential():
    save_credential(make_cred())
    c = get_credential("test-server", "aws")
    assert c is not None
    assert c["profile"] == "staging"


def test_get_credential_not_found():
    assert get_credential("missing", "aws") is None


def test_load_empty_state():
    assert load_credentials() == []


def test_state_file_permissions(tmp_path, monkeypatch):
    import tracebit.state as state_mod
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(state_mod, "STATE_FILE", state_file)
    save_credential(make_cred())
    assert oct(state_file.stat().st_mode)[-3:] == "600"


def test_get_expiring_soon():
    soon = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    save_credential(make_cred(expiration=soon))
    expiring = get_expiring_credentials(hours=2)
    assert len(expiring) == 1


def test_get_not_expiring():
    far = (datetime.now(timezone.utc) + timedelta(hours=10)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    save_credential(make_cred(expiration=far))
    assert get_expiring_credentials(hours=2) == []


def test_get_already_expired():
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    save_credential(make_cred(expiration=past))
    expiring = get_expiring_credentials(hours=2)
    assert len(expiring) == 1
