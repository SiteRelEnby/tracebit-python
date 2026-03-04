import configparser
import pytest
from tracebit import aws as aws_mod


@pytest.fixture(autouse=True)
def tmp_aws(tmp_path, monkeypatch):
    """Redirect ~/.aws/ to a temp directory for every test."""
    aws_dir = tmp_path / ".aws"
    monkeypatch.setattr(aws_mod, "AWS_DIR", aws_dir)
    monkeypatch.setattr(aws_mod, "CREDENTIALS_FILE", aws_dir / "credentials")
    monkeypatch.setattr(aws_mod, "CONFIG_FILE", aws_dir / "config")


def deploy(**kwargs):
    defaults = dict(
        profile="staging",
        region="us-east-1",
        access_key_id="AKIAIOSFODNN7EXAMPLE",
        secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        session_token="AQoXnyc//token",
    )
    defaults.update(kwargs)
    aws_mod.deploy_aws_credentials(**defaults)


def test_deploy_creates_credentials_file():
    deploy()
    assert aws_mod.CREDENTIALS_FILE.exists()


def test_deploy_writes_profile():
    deploy(profile="myprofile", access_key_id="MYKEY")
    creds = configparser.ConfigParser()
    creds.read(str(aws_mod.CREDENTIALS_FILE))
    assert creds.has_section("myprofile")
    assert creds.get("myprofile", "aws_access_key_id") == "MYKEY"


def test_deploy_writes_session_token():
    deploy(session_token="mysessiontoken")
    creds = configparser.ConfigParser()
    creds.read(str(aws_mod.CREDENTIALS_FILE))
    assert creds.get("staging", "aws_session_token") == "mysessiontoken"


def test_deploy_writes_config():
    deploy(profile="myprofile", region="eu-west-1")
    cfg = configparser.ConfigParser()
    cfg.read(str(aws_mod.CONFIG_FILE))
    assert cfg.has_section("profile myprofile")
    assert cfg.get("profile myprofile", "region") == "eu-west-1"


def test_deploy_file_permissions():
    deploy()
    assert oct(aws_mod.CREDENTIALS_FILE.stat().st_mode)[-3:] == "600"
    assert oct(aws_mod.CONFIG_FILE.stat().st_mode)[-3:] == "600"


def test_deploy_dir_permissions():
    deploy()
    assert oct(aws_mod.AWS_DIR.stat().st_mode)[-3:] == "700"


def test_deploy_overwrites_existing_profile():
    deploy(access_key_id="OLDKEY")
    deploy(access_key_id="NEWKEY")
    creds = configparser.ConfigParser()
    creds.read(str(aws_mod.CREDENTIALS_FILE))
    assert creds.get("staging", "aws_access_key_id") == "NEWKEY"
    # should only be one section
    assert len(creds.sections()) == 1


def test_deploy_preserves_other_profiles():
    deploy(profile="staging")
    deploy(profile="production")
    creds = configparser.ConfigParser()
    creds.read(str(aws_mod.CREDENTIALS_FILE))
    assert creds.has_section("staging")
    assert creds.has_section("production")


def test_profile_exists_true():
    deploy(profile="staging")
    assert aws_mod.profile_exists("staging") is True


def test_profile_exists_false():
    assert aws_mod.profile_exists("nonexistent") is False


def test_remove_credentials():
    deploy(profile="staging")
    aws_mod.remove_aws_credentials("staging")
    creds = configparser.ConfigParser()
    creds.read(str(aws_mod.CREDENTIALS_FILE))
    assert not creds.has_section("staging")


def test_remove_leaves_other_profiles():
    deploy(profile="staging")
    deploy(profile="production")
    aws_mod.remove_aws_credentials("staging")
    creds = configparser.ConfigParser()
    creds.read(str(aws_mod.CREDENTIALS_FILE))
    assert not creds.has_section("staging")
    assert creds.has_section("production")


def test_remove_nonexistent_profile_is_safe():
    deploy(profile="staging")
    aws_mod.remove_aws_credentials("nonexistent")  # should not raise


def test_get_aws_credentials():
    deploy(profile="staging", access_key_id="MYKEY", secret_access_key="MYSECRET")
    cred = aws_mod.get_aws_credentials("staging")
    assert cred["aws_access_key_id"] == "MYKEY"
    assert cred["aws_secret_access_key"] == "MYSECRET"


def test_get_aws_credentials_missing():
    assert aws_mod.get_aws_credentials("missing") is None


def test_permissive_aws_dir_warns(tmp_path, monkeypatch, capsys):
    aws_dir = tmp_path / ".aws"
    aws_dir.mkdir(mode=0o755)
    monkeypatch.setattr(aws_mod, "AWS_DIR", aws_dir)
    monkeypatch.setattr(aws_mod, "CREDENTIALS_FILE", aws_dir / "credentials")
    monkeypatch.setattr(aws_mod, "CONFIG_FILE", aws_dir / "config")
    deploy()
    assert "chmod 700" in capsys.readouterr().err


def test_correct_aws_dir_no_warning(capsys):
    deploy()
    assert capsys.readouterr().err == ""
