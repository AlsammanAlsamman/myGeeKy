import pytest

from mygeeky import uninstall as un
from mygeeky.config import MyGeekyConfig, save_config


def test_erase_removes_every_keyring_entry_and_the_data_folder(monkeypatch, tmp_path):
    keyring = pytest.importorskip("keyring")
    store = {(s, "me"): "secret" for s in un.KEYRING_SERVICES}
    store[("something-else", "me")] = "not ours"
    monkeypatch.setattr(keyring, "get_password", lambda s, u: store.get((s, u)))
    monkeypatch.setattr(keyring, "delete_password", lambda s, u: store.pop((s, u)))
    assert un.erase_tokens("me") == 4 and store == {("something-else", "me"): "not ours"}

    data = tmp_path / "data"
    (data / ".git" / "objects").mkdir(parents=True)
    obj = data / ".git" / "objects" / "ab"
    obj.write_text("x")
    obj.chmod(0o444)                               # git's read-only objects
    (data / "config.json").write_text("{}")
    assert un.erase_data(data) and not data.exists()


def test_erase_everything_uses_the_saved_username(monkeypatch):
    import mygeeky.config as config_module
    save_config(MyGeekyConfig(github_username="me"))
    seen = []
    monkeypatch.setattr(un, "erase_tokens", lambda user: seen.append(user) or 2)
    notes = un.erase_everything()
    assert seen == ["me"] and not config_module.DATA_DIR.exists()
    assert any("2 saved tokens" in n for n in notes) and any("not touched" in n for n in notes)
