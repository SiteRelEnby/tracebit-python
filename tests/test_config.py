import pytest
from tracebit import config as config_mod


@pytest.fixture(autouse=True)
def tmp_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "TOKEN_FILE", tmp_path / "token")
    monkeypatch.delenv("TRACEBIT_API_TOKEN", raising=False)
    monkeypatch.delenv("TRACEBIT_URL", raising=False)


def test_load_token_from_env(monkeypatch):
    monkeypatch.setenv("TRACEBIT_API_TOKEN", "my-token")
    assert config_mod.load_token() == "my-token"


def test_load_token_strips_whitespace(monkeypatch):
    monkeypatch.setenv("TRACEBIT_API_TOKEN", "  my-token  ")
    assert config_mod.load_token() == "my-token"


def test_load_token_from_file(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("file-token\n")
    config_mod.TOKEN_FILE.__class__  # already patched via fixture
    import tracebit.config as cm
    cm.TOKEN_FILE = token_file
    assert cm.load_token() == "file-token"


def test_load_token_env_takes_priority(monkeypatch, tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("file-token\n")
    import tracebit.config as cm
    cm.TOKEN_FILE = token_file
    monkeypatch.setenv("TRACEBIT_API_TOKEN", "env-token")
    assert cm.load_token() == "env-token"


def test_load_token_missing():
    assert config_mod.load_token() is None


def test_save_token(tmp_path):
    import tracebit.config as cm
    cm.CONFIG_DIR = tmp_path
    cm.TOKEN_FILE = tmp_path / "token"
    cm.save_token("saved-token")
    assert cm.TOKEN_FILE.read_text().strip() == "saved-token"
    assert oct(cm.TOKEN_FILE.stat().st_mode)[-3:] == "600"


def test_get_base_url_default():
    assert config_mod.get_base_url() == "https://community.tracebit.com"


def test_get_base_url_from_env(monkeypatch):
    monkeypatch.setenv("TRACEBIT_URL", "https://my-tracebit.example.com/")
    assert config_mod.get_base_url() == "https://my-tracebit.example.com"
