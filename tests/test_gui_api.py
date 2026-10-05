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
    monkeypatch.setattr(storage_module, "FOLLOWING_SNAPSHOT", tmp_path / "following_snapshot.json")
    monkeypatch.setattr(storage_module, "TRAINING_LOG", tmp_path / "training_data.jsonl")
    monkeypatch.setattr(storage_module, "CONTRIBUTE_LOG", tmp_path / "contribute_history.jsonl")
    monkeypatch.setattr(storage_module, "EXCLUDED_FILE", tmp_path / "excluded.json")


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


def test_set_opacity_persists_and_rejects_out_of_range(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    cfg = MyGeekyConfig(github_username="me")
    save_config(cfg)

    assert logic.set_opacity(cfg, 0.6) is True
    assert cfg.gui_opacity == 0.6

    assert logic.set_opacity(cfg, 0.0) is True  # fully transparent is allowed
    assert cfg.gui_opacity == 0.0

    assert logic.set_opacity(cfg, -0.1) is False  # below MIN_OPACITY
    assert logic.set_opacity(cfg, 1.5) is False  # above MAX_OPACITY
    assert cfg.gui_opacity == 0.0  # unchanged by the rejected calls


def test_get_friend_stats_reads_local_data_only(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    cfg = MyGeekyConfig(github_username="me")

    from mygeeky.storage import log_training_example, save_following_snapshot
    save_following_snapshot(["a", "b", "c"])

    recent = datetime.now(timezone.utc).isoformat()
    stale = "2020-01-01T00:00:00+00:00"
    log_training_example({"username": "a", "features": [0] * 5, "label": 1, "timestamp": recent})
    log_training_example({"username": "b", "features": [0] * 5, "label": 0, "timestamp": recent})
    log_training_example({"username": "c", "features": [0] * 5, "label": 1, "timestamp": stale})

    stats = logic.get_friend_stats(cfg)
    assert stats["total_friends"] == 3
    assert stats["new_this_week"] == 2  # only the two "recent" entries
    assert stats["total_labeled"] == 3
    assert abs(stats["follow_back_rate"] - (2 / 3)) < 1e-9


def test_get_friend_stats_no_data_yet(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    stats = logic.get_friend_stats(MyGeekyConfig())
    assert stats["total_friends"] == 0
    assert stats["new_this_week"] == 0
    assert stats["follow_back_rate"] is None


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


def test_get_contributions_returns_latest_run_only(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    cfg = MyGeekyConfig(github_username="me", contribute_max_returned=2)

    from mygeeky.storage import log_contributions
    log_contributions([{"full_name": "old/repo", "timestamp": "2026-01-01T00:00:00+00:00"}])
    log_contributions([{"full_name": f"new/r{i}", "timestamp": "2026-02-01T00:00:00+00:00"} for i in range(3)])

    assert [r["full_name"] for r in logic.get_contributions(cfg)] == ["new/r0", "new/r1"]


def test_get_contributions_empty_without_log(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    assert logic.get_contributions(MyGeekyConfig(github_username="me")) == []


def test_refresh_contributions_without_username_errors_cleanly():
    assert "error" in logic.refresh_contributions(MyGeekyConfig())


def test_refresh_contributions_surfaces_failures_as_error(monkeypatch):
    def boom(cfg):
        raise RuntimeError("rate limited")
    monkeypatch.setattr(logic, "_run_contribute", boom)
    assert logic.refresh_contributions(MyGeekyConfig(github_username="me")) == {"error": "rate limited"}


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
    monkeypatch.setattr(logic, "get_recent_activity", lambda client, username, limit, following=None: calls.append(1) or [])

    result = logic.get_activity(cfg, force=False)
    assert result["cached"] is True
    assert result["events"] == [{"actor": "cached-friend"}]
    assert calls == []  # network path never touched


def test_get_activity_force_bypasses_cache(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    cfg = MyGeekyConfig(github_username="me", gui_activity_refresh_minutes=60)

    from mygeeky.storage import save_activity_cache
    save_activity_cache([{"actor": "stale-friend"}], datetime.now(timezone.utc).isoformat())

    class FakeClient:
        def list_following(self, username):
            return ["NewFollow"]

    monkeypatch.setattr(logic, "_build_client", lambda cfg: FakeClient())
    monkeypatch.setattr(logic, "get_recent_activity", lambda client, username, limit, following=None: [{"actor": "fresh-friend"}])

    result = logic.get_activity(cfg, force=True)
    assert result["cached"] is False
    assert result["events"] == [{"actor": "fresh-friend", "source": "following"}]
    from mygeeky.storage import load_activity_cache, load_following_snapshot
    assert load_activity_cache()["following"] == ["NewFollow"]
    assert load_following_snapshot() == set()  # `learn`'s baseline is never touched by the panel


def test_clicked_and_followed_people_drop_out_of_suggestions(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    cfg = MyGeekyConfig(github_username="me")

    from mygeeky.storage import load_excluded, log_suggestions, save_activity_cache
    log_suggestions([{"username": u, "score": 0.5, "list": "followback"} for u in ("Alice", "Bob", "Carol")]
                    + [{"username": "Bob", "domain_fit": 0.9, "list": "domain"}])

    logic.mark_suggestion_seen("Alice")
    assert "alice" in load_excluded()  # future `mygeeky run`s skip her too
    save_activity_cache([], datetime.now(timezone.utc).isoformat(), following=["bob"])

    data = logic.get_suggestions(cfg)
    assert [r["username"] for r in data["followback"]] == ["Carol"]
    assert data["domain_highlights"] == []


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


def test_panel_geometry_never_spills_onto_neighbouring_screen():
    pytest.importorskip("PySide6", reason="PySide6 (the 'gui' extra) is not installed")
    from PySide6.QtCore import QRect

    cfg = MyGeekyConfig(gui_dock_side="right", gui_expanded_width=380)
    primary = QRect(0, 0, 2560, 1392)            # a second monitor starts at x=2560
    x, y, w, h = logic._panel_geometry(cfg, folded=False, screen_rect=primary, min_width=461)
    assert w == 461 and x + w == 2560            # content needed 461px: right edge stays on this screen

    left_monitor = QRect(-1920, -151, 1920, 1080)  # negative origin, e.g. a screen left of the primary
    x, y, w, h = logic._panel_geometry(cfg, folded=False, screen_rect=left_monitor)
    assert x + w == 0 and y >= -151

    cfg.gui_dock_side = "left"
    x, y, w, h = logic._panel_geometry(cfg, folded=False, screen_rect=left_monitor)
    assert x == -1920                            # not clamped to 0, which is on another screen


def test_folded_tab_is_small():
    pytest.importorskip("PySide6", reason="PySide6 (the 'gui' extra) is not installed")
    from PySide6.QtCore import QRect

    cfg = MyGeekyConfig(gui_folded_width=48, gui_folded_height=120)
    x, y, w, h = logic._panel_geometry(cfg, folded=True, screen_rect=QRect(0, 0, 2560, 1392))
    assert (w, h) == (48, 120) and x == 2560 - 48


def test_get_suggestions_backfills_from_older_runs_when_newest_are_hidden(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    from mygeeky.storage import add_excluded, log_suggestions
    log_suggestions([{"username": u, "score": 0.5, "list": "followback"} for u in ("old1", "old2", "Bob")])
    log_suggestions([{"username": u, "score": 0.5, "list": "followback"} for u in ("new1", "new2", "Bob")])
    add_excluded(["new1", "new2"])

    cfg = MyGeekyConfig(github_username="me", max_suggestions_returned=2)
    names = [r["username"] for r in logic.get_suggestions(cfg)["followback"]]
    assert names == ["old2", "Bob"]  # newest-first fill, Bob only once


def test_suggestions_auto_refresh_due(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    from mygeeky.storage import add_excluded, log_suggestions
    t0 = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    log_suggestions([{"username": "a", "score": 0.5, "list": "followback", "timestamp": t0.isoformat()}])
    cfg = MyGeekyConfig(github_username="me", gui_suggestions_auto_refresh_hours=6)
    later = datetime(2026, 10, 1, 20, tzinfo=timezone.utc)

    assert logic.suggestions_auto_refresh_due(cfg, now=later) is False  # list not empty
    add_excluded(["a"])
    assert logic.suggestions_auto_refresh_due(cfg, now=datetime(2026, 10, 1, 15, tzinfo=timezone.utc)) is False
    assert logic.suggestions_auto_refresh_due(cfg, now=later) is True
    cfg.gui_suggestions_auto_refresh_hours = 0
    assert logic.suggestions_auto_refresh_due(cfg, now=later) is False


def test_get_activity_cache_drops_unfollowed_actors(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    cfg = MyGeekyConfig(github_username="me", gui_activity_refresh_minutes=60)

    from mygeeky.storage import save_activity_cache
    save_activity_cache([{"actor": "Friend"}, {"actor": "stranger"}],
                        datetime.now(timezone.utc).isoformat(), ["friend"])

    result = logic.get_activity(cfg, force=False)
    assert result["events"] == [{"actor": "Friend"}]


def test_get_activity_merges_profile_matches(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    cfg = MyGeekyConfig(github_username="me", gui_activity_match_people=5)

    from mygeeky.storage import log_suggestions
    log_suggestions([{"username": "geek", "score": 0.9, "list": "domain", "timestamp": "2026-10-01T00:00:00+00:00"},
                     {"username": "friend", "score": 0.8, "list": "followback", "timestamp": "2026-10-01T00:00:00+00:00"}])

    class FakeClient:
        def list_following(self, username):
            return ["friend"]

    asked = []
    monkeypatch.setattr(logic, "_build_client", lambda cfg: FakeClient())
    monkeypatch.setattr(logic, "get_recent_activity",
                        lambda client, username, limit, following=None: [{"actor": "friend", "created_at": "2026-10-02"}])
    monkeypatch.setattr(logic, "get_matched_activity",
                        lambda client, logins: asked.append(list(logins)) or [{"actor": "geek", "source": "match", "created_at": "2026-10-03"}])

    result = logic.get_activity(cfg, force=True)
    assert asked == [["geek"]]  # people you already follow aren't fetched twice
    assert [(e["actor"], e["source"]) for e in result["events"]] == [("geek", "match"), ("friend", "following")]
