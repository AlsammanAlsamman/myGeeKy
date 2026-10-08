import json

import pytest

from mygeeky import achievements as ach
from mygeeky.config import MyGeekyConfig


def _badge(cfg, bid):
    return next(b for b in ach.earned(cfg) if b["id"] == bid)


def test_tiers_follow_what_you_do():
    cfg = MyGeekyConfig(github_username="me")
    assert _badge(cfg, "clicker")["tier"] == "" and _badge(cfg, "clicker")["next"] == 10
    for _ in range(10):
        ach.log("click", "headline", "ai")
    for _ in range(5):
        ach.log("click", "paper", explore=True)
    for _ in range(3):
        ach.log("click", "model")
    c = ach.counts(cfg)
    assert (c["clicker"], c["reader"], c["analyst"], c["ai"], c["models"], c["explorer"]) == (18, 10, 5, 13, 3, 5)
    assert _badge(cfg, "clicker")["tier"] == "bronze" and _badge(cfg, "clicker")["next"] == 50
    assert _badge(cfg, "ai")["tier"] == "bronze" and _badge(cfg, "models")["tier"] == "bronze"
    assert _badge(cfg, "analyst")["tier"] == "bronze"


def test_days_of_use_count_once_per_day():
    cfg = MyGeekyConfig()
    for _ in range(3):
        ach.log_open_today()
    assert ach.counts(cfg)["active"] == 1


def test_settings_based_and_single_level_badges():
    cfg = MyGeekyConfig(keywords=["a1", "b2", "c3"], sync_repo="me/data")
    assert _badge(cfg, "wordsmith")["tier"] == "bronze"
    every = _badge(cfg, "everywhere")
    assert every["tier"] == "bronze" and every["single"] and every["next"] is None


def test_earned_only_sorted_best_first():
    cfg = MyGeekyConfig(keywords=[f"k{i}" for i in range(15)])       # gold wordsmith
    ach.log("idea")
    best = ach.earned_only(cfg)
    assert best[0]["id"] == "wordsmith" and best[0]["tier"] == "gold"
    assert any(b["id"] == "ideas" for b in best)


def test_past_clicks_from_interest_history_count(monkeypatch):
    from mygeeky import interests
    monkeypatch.setattr(interests, "load_events", lambda: [
        {"at": "2026-09-01T10:00:00+00:00", "kind": "repo"}, {"at": "2026-09-02T10:00:00+00:00", "kind": "news"},
        {"at": "2026-09-02T11:00:00+00:00", "kind": "follow"}])
    c = ach.counts(MyGeekyConfig())
    assert c["clicker"] == 2 and c["reader"] == 1 and c["networker"] == 1 and c["active"] == 2 and c["early"] == 1


PROFILE = """<div><img alt="Achievement: Pull Shark" src="https://github.githubassets.com/assets/pull-shark-default-498c279a747d.png" class="x">
<img src="https://github.githubassets.com/assets/quickdraw-default-39c6aec8ff89.png" alt="Achievement: Quickdraw">
<img alt="Achievement: Pull Shark" src="https://github.githubassets.com/assets/pull-shark-default-498c279a747d.png">
<img alt="Achievement: Evil" src="https://evil.example.com/x.png"></div>"""


def test_github_achievements_parsed_safely_and_cached(monkeypatch):
    items = ach.parse_achievements(PROFILE)
    assert [i["name"] for i in items] == ["Pull Shark", "Quickdraw"]          # deduped; other hosts ignored

    class R:
        status_code = 200
        text = PROFILE
    calls = []
    monkeypatch.setattr(ach.requests, "get", lambda url, **kw: calls.append(url) or R())
    assert [i["name"] for i in ach.github_achievements("me")] == ["Pull Shark", "Quickdraw"]
    ach.github_achievements("me")
    assert calls == ["https://github.com/me?tab=achievements"]                # cached for a week
    assert ach.github_achievements("bad/../user") == []


def test_strip_under_your_name_and_badges_tab(monkeypatch):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel
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
    cfg = MyGeekyConfig(github_username="me", keywords=[f"k{i}" for i in range(15)], sync_repo="me/data",
                        gui_expanded_width=380)
    for _ in range(12):
        ach.log("click", "headline", "ai")
    panel = MyGeekyPanel(cfg)
    try:
        assert "badges" in panel.tab_buttons and panel.width() == 380        # the row still fits
        icons = [w for w in panel.badge_strip.findChildren(QLabel) if w.text() and not w.text().startswith("+")]
        assert len(icons) >= 3 and not panel.badge_strip.isHidden()
        assert panel.tab_buttons["badges"].text().endswith("•")          # new badges to see
        panel._switch_tab("badges")
        assert panel.tab_buttons["badges"].text() == "\U0001f3c5"            # seen now
        assert set(cfg.badges_seen) >= {"wordsmith:gold", "clicker:bronze"}
        names = " ".join(w.text() for w in panel.badges_area.parentWidget().findChildren(QLabel))
        assert "Wordsmith" in names and "Builder" in names                   # locked ones show how to earn them
    finally:
        panel.ticker.stop()
        for t in (panel._activity_timer, panel._signals_timer, panel._update_timer, panel._news_timer,
                  panel._dock_guard, panel._sync_timer):
            t.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.close()
        panel.deleteLater()


def test_usage_log_never_keeps_titles_or_links():
    from mygeeky.gui import app as logic
    logic.record_click(MyGeekyConfig(), "headline", {"title": "Secret project X", "link": "https://www.nature.com/x",
                                                     "category": "science", "feed": "nature"})
    line = ach.USAGE_FILE.read_text(encoding="utf-8").strip().splitlines()[-1]
    entry = json.loads(line)
    assert entry["kind"] == "headline" and entry["cat"] == "science"
    assert "Secret" not in line and "nature.com" not in line
