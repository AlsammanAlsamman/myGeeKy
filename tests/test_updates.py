import json
from datetime import datetime, timedelta, timezone

import pytest

from mygeeky import updates


def test_version_comparison():
    assert updates.is_newer("0.4.10", "0.4.9")
    assert updates.is_newer("1.0", "0.9.9")
    assert not updates.is_newer("0.4.3", "0.4.3")
    assert not updates.is_newer("0.4.2", "0.4.3")
    assert not updates.is_newer(None, "0.4.3")


def test_check_uses_a_fresh_cache_and_refreshes_a_stale_one(monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "latest_version", lambda timeout=4.0: calls.append(1) or "99.0.0")
    first = updates.check()
    assert first["newer"] and first["latest"] == "99.0.0" and calls == [1]
    updates.check()                       # within a day: no second request
    assert calls == [1]
    stale = {"latest": "99.0.0", "checked_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()}
    updates.UPDATE_CHECK_FILE.write_text(json.dumps(stale), encoding="utf-8")
    updates.check()
    assert calls == [1, 1]


def test_a_failed_request_keeps_the_last_answer(monkeypatch):
    monkeypatch.setattr(updates, "latest_version", lambda timeout=4.0: "99.0.0")
    updates.check(force=True)
    monkeypatch.setattr(updates, "latest_version", lambda timeout=4.0: None)
    assert updates.check(force=True)["latest"] == "99.0.0"


def test_developer_installs_are_never_pip_upgraded(monkeypatch):
    monkeypatch.setattr(updates, "is_editable", lambda: True)
    monkeypatch.setattr(updates.subprocess, "run", lambda *a, **k: pytest.fail("pip must not run"))
    ok, message = updates.run_upgrade()
    assert not ok and "git pull" in message


def test_upgrade_runs_pip_for_this_python(monkeypatch):
    monkeypatch.setattr(updates, "is_editable", lambda: False)
    monkeypatch.setattr(updates, "installed_version", lambda: "99.0.0")
    seen = []

    class Done:
        returncode, stdout, stderr = 0, "Successfully installed mygeeky-99.0.0", ""
    monkeypatch.setattr(updates.subprocess, "run", lambda cmd, **k: seen.append(cmd) or Done())
    ok, message = updates.run_upgrade()
    assert ok and "99.0.0" in message
    assert seen[0][1:] == ["-m", "pip", "install", "--upgrade", "--disable-pip-version-check", "mygeeky"]


def test_update_command(monkeypatch):
    from click.testing import CliRunner

    import mygeeky.cli as cli
    monkeypatch.setattr(updates, "check", lambda force=False, **k: {"current": "0.4.3", "latest": "0.5.0",
                                                                    "newer": True, "checked_at": "x"})
    monkeypatch.setattr(updates, "run_upgrade", lambda: (True, "Updated to myGeeKy 0.5.0."))
    result = CliRunner().invoke(cli.main, ["update"])
    assert result.exit_code == 0 and "Updated to myGeeKy 0.5.0." in result.output
    result = CliRunner().invoke(cli.main, ["update", "--check"])
    assert "0.5.0 is available" in result.output and "Updating" not in result.output
    monkeypatch.setattr(updates, "check", lambda force=False, **k: {"current": "0.4.3", "latest": "0.4.3",
                                                                    "newer": False, "checked_at": "x"})
    assert "latest myGeeKy" in CliRunner().invoke(cli.main, ["update"]).output


def test_update_notice_never_appears_in_scripts(monkeypatch, capsys):
    import mygeeky.cli as cli
    monkeypatch.setattr(updates, "check", lambda **k: pytest.fail("no check outside a terminal"))
    monkeypatch.setattr("sys.argv", ["mygeeky", "run", "--json"])
    cli._maybe_announce_update()     # not a tty, and --json: silent, no network
    assert capsys.readouterr().err == ""


def test_banner_shows_hides_and_remembers_later(monkeypatch):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    from mygeeky.config import MyGeekyConfig, load_config, save_config
    from mygeeky.gui import app as logic
    from mygeeky.gui.qt_panel import MyGeekyPanel

    monkeypatch.setattr(logic, "get_contributions", lambda cfg: [])
    monkeypatch.setattr(logic, "get_suggestions", lambda cfg: {"followback": [], "domain_highlights": []})
    monkeypatch.setattr(logic, "get_activity", lambda cfg, force=False: {"events": []})
    monkeypatch.setattr(logic, "get_model_history", lambda: [])
    monkeypatch.setattr(logic, "get_friend_stats", lambda cfg: {
        "total_friends": 0, "new_this_week": 0, "follow_back_rate": None, "total_labeled": 0})
    save_config(MyGeekyConfig())
    panel = MyGeekyPanel(load_config())
    try:
        info = {"show": True, "latest": "0.5.0", "current": "0.4.3", "editable": False,
                "releases_url": updates.RELEASES_URL}
        panel._on_update_info(info)
        assert not panel.update_banner.isHidden() and "0.5.0" in panel.update_label.text()
        assert not panel.update_btn.isHidden()
        panel._on_update_info({**info, "editable": True})
        assert panel.update_btn.isHidden() and "git pull" in panel.update_label.text()
        panel._on_update_later()
        assert panel.update_banner.isHidden() and load_config().update_dismissed == "0.5.0"
        panel._on_update_done({"ok": False, "message": "no internet"})
        assert "no internet" in panel.update_label.text() and panel.update_btn.text() == "Try again"
    finally:
        panel.ticker.stop()
        for t in (panel._activity_timer, panel._signals_timer, panel._update_timer):
            t.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.close()
        panel.deleteLater()
