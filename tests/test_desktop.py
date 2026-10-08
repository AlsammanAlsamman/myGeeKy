import sys

import pytest

from mygeeky.gui import desktop


@pytest.fixture
def linux_home(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)   # no menu-refresh tools needed
    return tmp_path


def test_menu_entry_with_icon_and_optional_autostart(linux_home):
    changed = desktop.install_menu_entry()
    entry = desktop.entry_path().read_text()
    assert changed and "Name=myGeeKy" in entry and "Icon=mygeeky" in entry and "Terminal=false" in entry
    assert "-m mygeeky.gui.app" in entry and sys.executable.split("/")[-1] in entry
    assert (linux_home / "share/icons/hicolor/256x256/apps/mygeeky.png").exists()
    assert desktop.install_menu_entry() == []                 # already there: nothing to do
    assert not desktop.autostart_path().exists()              # sign-in is opt-in
    desktop.install_menu_entry(autostart=True)
    assert "X-GNOME-Autostart-enabled=true" in desktop.autostart_path().read_text()
    desktop.install_menu_entry(autostart=False)
    assert not desktop.autostart_path().exists()
    assert len(desktop.remove_menu_entry()) == 4 and not desktop.entry_path().exists()


def test_not_on_other_systems(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert desktop.install_menu_entry() == []


def test_launch_detached_frees_the_terminal(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda cmd, **kw: seen.update(cmd=cmd, **kw))
    desktop.launch_detached(tmp_path / "logs" / "panel.log")
    assert seen["cmd"][-2:] == ["-m", "mygeeky.gui.app"] and seen["stdin"] is desktop.subprocess.DEVNULL
    if sys.platform == "win32":
        assert seen["creationflags"] & 0x00000008                # DETACHED_PROCESS
    else:
        assert seen["start_new_session"] is True


def test_gui_command_runs_in_the_background(monkeypatch):
    from click.testing import CliRunner
    import mygeeky.cli as cli
    import mygeeky.gui.bootstrap as bootstrap
    launched = []
    monkeypatch.setattr(bootstrap, "ensure_qt", lambda *a, **k: None)
    monkeypatch.setattr(desktop, "launch_detached", lambda log: launched.append(log))
    monkeypatch.setattr(desktop, "install_menu_entry", lambda *a, **k: [])
    monkeypatch.setattr(cli, "_panel_running", lambda: False)
    result = CliRunner().invoke(cli.main, ["gui"])
    assert result.exit_code == 0 and launched and "background" in result.output
    monkeypatch.setattr(cli, "_panel_running", lambda: True)
    launched.clear()
    result = CliRunner().invoke(cli.main, ["gui"])
    assert "already running" in result.output and not launched


def test_panel_sync_pulls_other_computers_settings(monkeypatch):
    from mygeeky.gui import app as logic
    from mygeeky import sync
    heads = iter(["aaa", "bbb"])

    class R:
        def __init__(self):
            self.stdout = next(heads)
    monkeypatch.setattr(sync, "is_initialized", lambda: True)
    monkeypatch.setattr(sync, "git_exe", lambda: "git")
    monkeypatch.setattr(sync, "_git", lambda *a, **k: R())
    monkeypatch.setattr(sync, "push", lambda: "Pushed to GitHub.")
    from mygeeky.config import MyGeekyConfig
    cfg = MyGeekyConfig(sync_repo="me/data")
    assert logic.sync_now(cfg) == {"ok": True, "changed": True, "message": "Pushed to GitHub."}
    assert logic.sync_now(MyGeekyConfig()) == {"ok": False, "skipped": True}
