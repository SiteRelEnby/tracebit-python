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


def cfg(tmp_path):
    """Helper: path to a temp ssh config file."""
    return tmp_path / ".ssh" / "config"


def test_validate_ssh_host_rejects_space():
    with pytest.raises(ValueError, match="whitespace"):
        ssh_mod.validate_ssh_host("bad host")


def test_validate_ssh_host_rejects_newline():
    with pytest.raises(ValueError, match="whitespace"):
        ssh_mod.validate_ssh_host("bad\nhost")


def test_validate_ssh_host_accepts_valid():
    ssh_mod.validate_ssh_host("backup-server.internal")  # should not raise
    ssh_mod.validate_ssh_host("1.2.3.4")


def test_write_config_missing_parent_raises(tmp_path):
    cf = tmp_path / "no-such-dir" / "config"
    with pytest.raises(OSError, match="does not exist"):
        ssh_mod.write_ssh_config("backup-server.internal", "/key", "1.2.3.4", config_file=cf)


def test_write_config_creates_host_block(tmp_path):
    cf = cfg(tmp_path)
    cf.parent.mkdir(parents=True)
    ssh_mod.write_ssh_config("backup-server.internal", "/home/user/.ssh/id_backup",
                             "1.2.3.4", config_file=cf)
    text = cf.read_text()
    assert "Host backup-server.internal" in text
    assert "HostName 1.2.3.4" in text
    assert "IdentityFile /home/user/.ssh/id_backup" in text
    assert "PasswordAuthentication no" in text


def test_write_config_ip_as_host_omits_hostname(tmp_path):
    cf = cfg(tmp_path)
    cf.parent.mkdir(parents=True)
    ssh_mod.write_ssh_config("1.2.3.4", "/home/user/.ssh/id_backup", "1.2.3.4", config_file=cf)
    text = cf.read_text()
    assert "Host 1.2.3.4" in text
    assert "HostName" not in text


def test_write_config_preserves_existing_blocks(tmp_path):
    cf = cfg(tmp_path)
    cf.parent.mkdir(parents=True)
    cf.write_text("Host other-server\n    HostName 9.9.9.9\n    User ubuntu\n")
    ssh_mod.write_ssh_config("backup-server.internal", "/home/user/.ssh/id_backup",
                             "1.2.3.4", config_file=cf)
    text = cf.read_text()
    assert "Host other-server" in text
    assert "Host backup-server.internal" in text


def test_write_config_replaces_existing_entry(tmp_path):
    cf = cfg(tmp_path)
    cf.parent.mkdir(parents=True)
    ssh_mod.write_ssh_config("backup-server.internal", "/old/key", "1.1.1.1", config_file=cf)
    ssh_mod.write_ssh_config("backup-server.internal", "/new/key", "2.2.2.2", config_file=cf)
    text = cf.read_text()
    assert text.count("Host backup-server.internal") == 1
    assert "2.2.2.2" in text
    assert "1.1.1.1" not in text


def test_write_config_file_permissions(tmp_path):
    cf = cfg(tmp_path)
    cf.parent.mkdir(parents=True)
    ssh_mod.write_ssh_config("backup-server.internal", "/home/user/.ssh/id_backup",
                             "1.2.3.4", config_file=cf)
    assert oct(cf.stat().st_mode)[-3:] == "600"


def test_remove_config_removes_block(tmp_path):
    cf = cfg(tmp_path)
    cf.parent.mkdir(parents=True)
    ssh_mod.write_ssh_config("backup-server.internal", "/home/user/.ssh/id_backup",
                             "1.2.3.4", config_file=cf)
    ssh_mod.remove_ssh_config("backup-server.internal", config_file=cf)
    assert "backup-server.internal" not in cf.read_text()


def test_remove_config_leaves_other_blocks(tmp_path):
    cf = cfg(tmp_path)
    cf.parent.mkdir(parents=True)
    cf.write_text("Host other-server\n    HostName 9.9.9.9\n")
    ssh_mod.write_ssh_config("backup-server.internal", "/home/user/.ssh/id_backup",
                             "1.2.3.4", config_file=cf)
    ssh_mod.remove_ssh_config("backup-server.internal", config_file=cf)
    assert "other-server" in cf.read_text()


def test_remove_config_nonexistent_file_is_safe(tmp_path):
    cf = tmp_path / "no-such-config"
    ssh_mod.remove_ssh_config("backup-server.internal", config_file=cf)  # should not raise


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
