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


def test_withdrawing_publishes_an_empty_beacon():
    from mygeeky import beacon
    written = {}

    class W:
        def publish(self, b):
            written["beacon"] = b

        def write(self, path, text, message):
            written[path] = text
    beacon.withdraw(MyGeekyConfig(github_username="me"), writer=W())
    b = written["beacon"]
    assert b["keys"] == [] and b["sealed"] == [] and b["interests"] == [] and b["withdrawn"] is True
    assert "withdrawn" in written["README.md"]


def test_the_steps_withdraw_the_beacon_before_the_tokens_go(monkeypatch):
    pytest.importorskip("PySide6")
    from mygeeky.gui import setup_wizard, uninstall_wizard as uw
    from mygeeky import beacon
    order = []
    monkeypatch.setattr(setup_wizard, "stop_running_panels", lambda: order.append("panels") or 0)
    monkeypatch.setattr(beacon, "withdraw", lambda cfg: order.append("beacon"))
    monkeypatch.setattr(un, "erase_tokens", lambda user: order.append("tokens") or 3)
    monkeypatch.setattr(un, "erase_data", lambda d: order.append("data") or True)
    monkeypatch.setattr(uw, "uninstall", lambda python, erase=False: order.append("program") or ["Removed the myGeeKy package."])
    said = []
    inv = {"user": "me", "sync": "me/data"}
    result = uw.run_steps({"beacon": True, "tokens": True, "data": True, "beacon_repo": True, "sync_repo": False},
                          inv, "python", said.append)
    assert order == ["panels", "beacon", "tokens", "data", "program"]
    assert result["open"] == ["https://github.com/me/mygeeky-beacon/settings"]
    order.clear()
    uw.run_steps({}, inv, "python", said.append)                         # nothing chosen: only the program goes
    assert order == ["panels", "program"]
