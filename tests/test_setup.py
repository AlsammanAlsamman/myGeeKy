import json

import pytest

from mygeeky import setup_api
from mygeeky.config import MyGeekyConfig, load_config, save_config


def test_save_profile_validates_and_saves():
    assert setup_api.save_profile({"github_username": ""})["ok"] is False
    assert setup_api.save_profile({"github_username": "me", "orcid_id": "not-an-orcid"})["ok"] is False
    r = setup_api.save_profile({"github_username": "me", "languages": "Python, R", "topics": ["gwas", " "]})
    assert r["ok"]
    cfg = load_config()
    assert (cfg.github_username, cfg.languages, cfg.topics) == ("me", ["Python", "R"], ["gwas"])


def test_store_token_refuses_someone_elses_token(monkeypatch):
    save_config(MyGeekyConfig(github_username="me"))
    from mygeeky import token_check
    monkeypatch.setattr(token_check, "capabilities", lambda token, user, **kw: {"valid": True, "login": "other",
                                                                               "kind": "fine-grained"})
    stored = []
    import keyring
    monkeypatch.setattr(keyring, "set_password", lambda *a: stored.append(a))
    r = setup_api.store_token({"token": "t"})
    assert r["ok"] is False and "other" in r["error"] and stored == []


def test_main_reads_stdin_and_never_dumps_tracebacks(monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO('{"github_username": ""}'))
    assert setup_api.main(["save_profile"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out == {"ok": False, "error": "Your GitHub username is required."}
    assert setup_api.main(["rm-rf"]) == 2


def test_folded_icon_migrates_from_old_default_only(tmp_path):
    import mygeeky.config as config_module
    raw = MyGeekyConfig().to_dict()
    raw.pop("config_version")
    raw.update(gui_folded_width=58, gui_folded_height=58)
    config_module.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config_module.CONFIG_FILE.write_text(json.dumps(raw), encoding="utf-8")
    cfg = load_config()
    assert (cfg.gui_folded_width, cfg.gui_folded_height, cfg.config_version) == (76, 76, MyGeekyConfig.config_version)
    raw.update(gui_folded_width=90, gui_folded_height=90)       # a size someone chose stays
    config_module.CONFIG_FILE.write_text(json.dumps(raw), encoding="utf-8")
    assert load_config().gui_folded_width == 90


def test_wizard_helpers():
    pytest.importorskip("PySide6")
    from pathlib import Path

    from mygeeky.gui import setup_wizard as sw
    assert sw.wheel_version(Path("mygeeky-0.4.0-py3-none-any.whl")) == "0.4.0"
    assert sw.wheel_version(None) is None
    paths = sw.shortcut_paths()
    assert paths["startup"].parent.name == "Startup" and paths["start_menu"].name == "myGeeKy.lnk"


def test_sync_without_git_says_so(monkeypatch):
    from mygeeky import sync
    monkeypatch.setattr(sync, "git_exe", lambda: None)
    with pytest.raises(sync.SyncError, match="git-scm.com"):
        sync.init("me/mygeeky-data")
    with pytest.raises(sync.SyncError, match="needs Git"):
        sync.push()


def test_setup_api_relays_a_clear_error_and_details(monkeypatch, capsys):
    import io
    from mygeeky import sync

    def missing_git(req):
        raise FileNotFoundError(2, "The system cannot find the file specified")
    monkeypatch.setitem(setup_api.ACTIONS, "sync_init", missing_git)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    setup_api.main(["sync_init"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and "details" in out and "Traceback" in out["details"]
    monkeypatch.setitem(setup_api.ACTIONS, "sync_init", lambda req: (_ for _ in ()).throw(sync.SyncError("Sync needs Git.")))
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    setup_api.main(["sync_init"])
    assert json.loads(capsys.readouterr().out)["error"] == "Sync needs Git."   # our own message, unchanged


def test_installer_sync_page_installs_git_when_you_choose_sync(monkeypatch):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from mygeeky.gui import setup_wizard as sw
    w = sw.SetupWizard()
    w.state = {"github_username": "me", "git": False, "gh": False, "sync_repo": "", "sync_initialized": False}
    page = w.page(w.pageIds()[4])
    page.initializePage()
    assert not page.enable.isChecked() and "Git" in page.note.text()
    assert "installs Git for you" in page.note.text()
    page.enable.setChecked(True)
    assert "Installing Git" in page.busy_text()
    # ticked without Git: setup installs Git first, then runs the sync step with it on PATH
    calls = []
    monkeypatch.setattr(sw, "find_git", lambda: None)
    monkeypatch.setattr(sw, "install_git", lambda say: calls.append("install") or r"C:\Git\cmd\git.exe")
    monkeypatch.setattr(sw, "api", lambda python, action, payload=None, timeout=600:
                        calls.append(action) or {"ok": True, "message": "synced"})
    assert page.job()(None)["ok"] and calls == ["install", "sync_init"]
    assert r"C:\Git\cmd" in os.environ["PATH"]
    monkeypatch.setattr(sw, "install_git", lambda say: None)
    assert "couldn't be installed" in page.job()(None)["error"]
    w.state.update(git=True, gh=True)
    page.initializePage()
    assert page.enable.isChecked()


def test_panel_height_grows_from_the_old_default_and_stays_within_limits(tmp_path):
    import mygeeky.config as config_module
    from mygeeky.gui import app as logic
    raw = MyGeekyConfig().to_dict()
    raw.update(config_version=2, gui_panel_height_fraction=0.25)          # the old default: grows
    config_module.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config_module.CONFIG_FILE.write_text(json.dumps(raw), encoding="utf-8")
    assert load_config().gui_panel_height_fraction == 0.6
    raw.update(gui_panel_height_fraction=0.45)                             # one someone chose: stays
    config_module.CONFIG_FILE.write_text(json.dumps(raw), encoding="utf-8")
    assert load_config().gui_panel_height_fraction == 0.45
    assert logic.clamp_panel_height(0.1) == logic.MIN_PANEL_HEIGHT and logic.clamp_panel_height(2) == logic.MAX_PANEL_HEIGHT
    cfg = MyGeekyConfig()
    assert logic.set_panel_height(cfg, 0.99) == 0.9 and load_config().gui_panel_height_fraction == 0.9


def test_dragging_the_grip_and_the_slider_change_the_height_within_limits(monkeypatch):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from mygeeky.gui import app as logic
    from mygeeky.gui.qt_panel import MyGeekyPanel

    for name, value in (("get_contributions", lambda cfg: []),
                        ("get_suggestions", lambda cfg: {"followback": [], "domain_highlights": []}),
                        ("get_activity", lambda cfg, force=False: {"events": []}),
                        ("get_model_history", lambda: []),
                        ("get_friend_stats", lambda cfg: {"total_friends": 0, "new_this_week": 0,
                                                          "follow_back_rate": None, "total_labeled": 0})):
        monkeypatch.setattr(logic, name, value)
    panel = MyGeekyPanel(MyGeekyConfig(github_username="me"))
    try:
        panel.show()
        start = panel.height()
        screen_h = panel._home_screen().availableGeometry().height()
        panel._resize_from_grip(screen_h * 0.05, 0.6, done=True)        # drag down: taller
        assert panel.cfg.gui_panel_height_fraction == 0.7 and panel.height() > start
        assert panel.height_slider.value() == 70 and load_config().gui_panel_height_fraction == 0.7
        panel._resize_from_grip(screen_h * 5, 0.6, done=True)           # way too far: stops at the limit
        assert panel.cfg.gui_panel_height_fraction == logic.MAX_PANEL_HEIGHT
        panel.height_slider.setValue(40)                                 # the ⚙ slider
        panel._on_height_committed()
        assert load_config().gui_panel_height_fraction == 0.4
    finally:
        panel.ticker.stop()
        for t in (panel._activity_timer, panel._signals_timer, panel._update_timer, panel._news_timer,
                  panel._dock_guard, panel._sync_timer):
            t.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.close()
        panel.deleteLater()
