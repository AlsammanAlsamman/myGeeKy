"""Tests for the pure business-logic functions in mygeeky.gui.app.

These deliberately do NOT require a live QApplication/widget tree -- only
`test_open_profile_accepts_github_url` and `test_panel_geometry_docks_to_configured_side`
need PySide6 importable at all (for QDesktopServices/QRect), guarded by
importorskip so the rest of the suite still runs without the 'gui' extra
installed.
"""

from datetime import datetime, timezone

import pytest

from mygeeky.config import MyGeekyConfig, save_config
from mygeeky.gui import app as logic


def _isolate_state(monkeypatch, tmp_path):
    import mygeeky.config as config_module
    import mygeeky.storage as storage_module

    monkeypatch.setattr(config_module, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(storage_module, "SUGGESTIONS_LOG", tmp_path / "suggestions_history.jsonl")
    monkeypatch.setattr(storage_module, "MODEL_HISTORY_LOG", tmp_path / "model_history.jsonl")
    monkeypatch.setattr(storage_module, "ACTIVITY_CACHE_FILE", tmp_path / "activity_cache.json")


def test_get_status_not_configured():
    status = logic.get_status(MyGeekyConfig())
    assert status["configured"] is False
    assert status["github_username"] == ""
    assert status["theme"] == "midnight"


def test_set_theme_persists_and_rejects_unknown(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    cfg = MyGeekyConfig(github_username="me")
    save_config(cfg)

    assert logic.set_theme(cfg, "aurora") is True
    assert cfg.gui_theme == "aurora"
    assert logic.get_status(cfg)["theme"] == "aurora"

    assert logic.set_theme(cfg, "not-a-real-theme") is False
    assert cfg.gui_theme == "aurora"  # unchanged by the rejected call


def test_get_suggestions_reads_local_log_only(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    cfg = MyGeekyConfig(github_username="me")

    from mygeeky.storage import log_suggestions
    log_suggestions([
        {"username": "friend", "score": 0.5, "list": "followback"},
        {"username": "expert", "domain_fit": 0.8, "list": "domain"},
    ])

    data = logic.get_suggestions(cfg)
    assert [r["username"] for r in data["followback"]] == ["friend"]
    assert [r["username"] for r in data["domain_highlights"]] == ["expert"]


def test_open_profile_rejects_non_github_urls():
    assert logic.open_profile("https://evil.example.com/phish") is False
    assert logic.open_profile(123) is False  # not even a string -- never reaches Qt


def test_open_profile_accepts_github_url(monkeypatch):
    pytest.importorskip("PySide6", reason="PySide6 (the 'gui' extra) is not installed")
    from PySide6.QtGui import QDesktopServices

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString())))
    assert logic.open_profile("https://github.com/someone") is True
    assert opened == ["https://github.com/someone"]


def test_refresh_suggestions_without_username_errors_cleanly():
    result = logic.refresh_suggestions(MyGeekyConfig())
    assert "error" in result


def test_get_activity_uses_cache_within_refresh_window(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    cfg = MyGeekyConfig(github_username="me", gui_activity_refresh_minutes=60)

    from mygeeky.storage import save_activity_cache
    save_activity_cache([{"actor": "cached-friend"}], datetime.now(timezone.utc).isoformat())

    calls = []
    monkeypatch.setattr(logic, "get_recent_activity", lambda client, username, limit: calls.append(1) or [])

    result = logic.get_activity(cfg, force=False)
    assert result["cached"] is True
    assert result["events"] == [{"actor": "cached-friend"}]
    assert calls == []  # network path never touched


def test_get_activity_force_bypasses_cache(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    cfg = MyGeekyConfig(github_username="me", gui_activity_refresh_minutes=60)

    from mygeeky.storage import save_activity_cache
    save_activity_cache([{"actor": "stale-friend"}], datetime.now(timezone.utc).isoformat())

    monkeypatch.setattr(logic, "_build_client", lambda cfg: object())
    monkeypatch.setattr(logic, "get_recent_activity", lambda client, username, limit: [{"actor": "fresh-friend"}])

    result = logic.get_activity(cfg, force=True)
    assert result["cached"] is False
    assert result["events"] == [{"actor": "fresh-friend"}]


def test_panel_geometry_docks_to_configured_side():
    pytest.importorskip("PySide6", reason="PySide6 (the 'gui' extra) is not installed")
    from PySide6.QtCore import QRect

    cfg = MyGeekyConfig(gui_dock_side="left", gui_expanded_width=300, gui_folded_width=40,
                         gui_panel_height_fraction=0.5)
    screen_rect = QRect(0, 0, 1920, 1080)

    x, y, w, h = logic._panel_geometry(cfg, folded=False, screen_rect=screen_rect)
    assert x == 0  # docked left -> flush to x=0
    assert w == 300

    cfg.gui_dock_side = "right"
    x2, y2, w2, h2 = logic._panel_geometry(cfg, folded=True, screen_rect=screen_rect)
    assert w2 == 40
    assert x2 > 0  # docked right -> pushed to the right edge
