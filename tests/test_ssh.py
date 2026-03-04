import base64
import os
import subprocess
import pytest
from tracebit import ssh as ssh_mod


FAKE_PRIVATE_KEY = b"-----BEGIN OPENSSH PRIVATE KEY-----\nfakekey\n-----END OPENSSH PRIVATE KEY-----\n"
FAKE_KEY_B64 = base64.b64encode(FAKE_PRIVATE_KEY).decode()


@pytest.fixture(autouse=True)
def tmp_ssh(tmp_path, monkeypatch):
    """Redirect ~/.ssh/ to a temp directory for every test."""
    ssh_dir = tmp_path / ".ssh"
    monkeypatch.setattr(ssh_mod, "SSH_DIR", ssh_dir)


def test_deploy_creates_key_file():
    ssh_mod.deploy_ssh_key("id_backup", FAKE_KEY_B64)
    assert (ssh_mod.SSH_DIR / "id_backup").exists()


def test_deploy_writes_correct_content():
    ssh_mod.deploy_ssh_key("id_backup", FAKE_KEY_B64)
    content = (ssh_mod.SSH_DIR / "id_backup").read_bytes()
    assert content == FAKE_PRIVATE_KEY


def test_deploy_file_permissions():
    ssh_mod.deploy_ssh_key("id_backup", FAKE_KEY_B64)
    mode = oct(os.stat(ssh_mod.SSH_DIR / "id_backup").st_mode)[-3:]
    assert mode == "600"


def test_deploy_creates_ssh_dir():
    assert not ssh_mod.SSH_DIR.exists()
    ssh_mod.deploy_ssh_key("id_backup", FAKE_KEY_B64)
    assert ssh_mod.SSH_DIR.exists()


def test_deploy_ssh_dir_permissions():
    ssh_mod.deploy_ssh_key("id_backup", FAKE_KEY_B64)
    mode = oct(os.stat(ssh_mod.SSH_DIR).st_mode)[-3:]
    assert mode == "700"


def test_remove_key_file():
    ssh_mod.deploy_ssh_key("id_backup", FAKE_KEY_B64)
    ssh_mod.remove_ssh_key("id_backup")
    assert not (ssh_mod.SSH_DIR / "id_backup").exists()


def test_remove_nonexistent_is_safe():
    ssh_mod.remove_ssh_key("id_does_not_exist")  # should not raise


def test_key_exists_true():
    ssh_mod.deploy_ssh_key("id_backup", FAKE_KEY_B64)
    assert ssh_mod.key_exists("id_backup") is True


def test_key_exists_false():
    assert ssh_mod.key_exists("id_backup") is False


def test_permissive_ssh_dir_warns(tmp_path, monkeypatch, capsys):
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir(mode=0o755)
    monkeypatch.setattr(ssh_mod, "SSH_DIR", ssh_dir)
    ssh_mod.deploy_ssh_key("id_backup", FAKE_KEY_B64)
    assert "chmod 700" in capsys.readouterr().err


def test_correct_ssh_dir_no_warning(capsys):
    ssh_mod.deploy_ssh_key("id_backup", FAKE_KEY_B64)
    assert capsys.readouterr().err == ""


def test_trigger_ssh_runs_subprocess(monkeypatch):
    ssh_mod.deploy_ssh_key("id_backup", FAKE_KEY_B64)

    completed = subprocess.CompletedProcess(
        args=[], returncode=255, stdout="", stderr="Permission denied (publickey)."
    )
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return completed

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = ssh_mod.trigger_ssh("id_backup", "1.2.3.4")
    assert result.returncode == 255
    assert any("1.2.3.4" in str(a) for a in calls[0])
    assert any("id_backup" in str(a) for a in calls[0])
