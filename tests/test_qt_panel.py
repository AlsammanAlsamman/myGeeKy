import pytest

pytest.importorskip("PySide6", reason="PySide6 (the 'gui' extra) is not installed")

from mygeeky.gui.qt_panel import _build_spotlight_items


@pytest.fixture(scope="module")
def qapp():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_build_spotlight_items_interleaves_activity_and_suggestions():
    activity = [
        {"actor": "a1", "actor_avatar": "u1", "profile_url": "p1", "verb": "pushed 2 commits",
         "repo": "a1/tool", "created_at": "2026-01-01T00:00:00Z"},
        {"actor": "a2", "actor_avatar": "u2", "profile_url": "p2", "verb": "starred the repo",
         "repo": "", "created_at": "2026-01-01T00:00:00Z"},
    ]
    suggestions = [
        {"username": "s1", "avatar_url": "su1", "profile_url": "sp1", "score": 0.81, "bio": "bio1"},
    ]

    items = _build_spotlight_items(activity, suggestions)

    assert [i["kind"] for i in items] == ["activity", "suggestion", "activity"]
    assert items[0]["username"] == "a1"
    assert "pushed 2 commits in a1/tool" == items[0]["headline"]
    assert items[1]["username"] == "s1"
    assert "0.81" in items[1]["headline"]
    assert items[2]["username"] == "a2"
    assert items[2]["headline"] == "starred the repo"  # no repo name -> no "in ..." suffix


def test_build_spotlight_items_empty_inputs():
    assert _build_spotlight_items([], []) == []


def _repo_item() -> dict:
    return {
        "full_name": "owner/tool", "owner": "owner", "owner_avatar_url": "",
        "repo_url": "https://github.com/owner/tool", "fork_url": "https://github.com/owner/tool/fork",
        "description": "A tool", "language": "Python", "stars": 120, "score": 0.734,
        "reasons": ["matches 'gwas'"],
        "starter_issues": [{"title": "Fix typo", "url": "https://github.com/owner/tool/issues/1"},
                           {"title": "Add test", "url": "https://github.com/owner/tool/issues/2"},
                           {"title": "Third", "url": "https://github.com/owner/tool/issues/3"}],
    }


def test_repo_card_buttons_only_open_github_pages(qapp):
    from PySide6.QtWidgets import QPushButton

    from mygeeky.gui.app import THEMES
    from mygeeky.gui.qt_panel import RepoCard

    opened = []
    card = RepoCard(_repo_item(), THEMES["midnight"], lambda u: opened.append(u) or True)
    buttons = card.findChildren(QPushButton)
    assert len(buttons) == 4  # 2 starter issues (capped) + Fork + Open
    for b in buttons:
        b.click()
    assert opened == [
        "https://github.com/owner/tool/issues/1",
        "https://github.com/owner/tool/issues/2",
        "https://github.com/owner/tool/fork",
        "https://github.com/owner/tool",
    ]


def test_panel_has_repos_tab_and_renders_logged_results(qapp, monkeypatch):
    from mygeeky.config import MyGeekyConfig
    from mygeeky.gui import app as logic
    from mygeeky.gui.qt_panel import MyGeekyPanel, RepoCard

    monkeypatch.setattr(logic, "get_contributions", lambda cfg: [_repo_item()])
    monkeypatch.setattr(logic, "get_suggestions", lambda cfg: {"followback": [], "domain_highlights": []})
    monkeypatch.setattr(logic, "get_activity", lambda cfg, force=False: {"events": []})
    monkeypatch.setattr(logic, "get_model_history", lambda: [])
    monkeypatch.setattr(logic, "get_friend_stats", lambda cfg: {
        "total_friends": 0, "new_this_week": 0, "follow_back_rate": None, "total_labeled": 0})

    panel = MyGeekyPanel(MyGeekyConfig())
    try:
        assert "repos" in panel.tab_buttons
        panel._switch_tab("repos")
        assert panel.content_stack.currentIndex() == panel._tab_order.index("repos")
        assert len(panel.repos_area.parentWidget().findChildren(RepoCard)) == 1
    finally:
        panel.ticker.stop()
        panel._activity_timer.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.deleteLater()


def test_suggestion_card_has_no_open_button_and_click_reports_item(qapp):
    from PySide6.QtWidgets import QPushButton

    from mygeeky.gui.app import THEMES
    from mygeeky.gui.qt_panel import SuggestionCard

    item = {"username": "alice", "profile_url": "https://github.com/alice", "score": 0.5, "bio": ""}
    clicked = []
    card = SuggestionCard(item, "score", THEMES["midnight"], clicked.append)
    assert card.findChildren(QPushButton) == []
    card.mousePressEvent(None)
    assert clicked == [item]


def test_panel_fits_its_screen_expanded_and_folds_to_a_small_tab(qapp, monkeypatch):
    from mygeeky.config import MyGeekyConfig
    from mygeeky.gui import app as logic
    from mygeeky.gui.qt_panel import MyGeekyPanel

    monkeypatch.setattr(logic, "get_contributions", lambda cfg: [])
    monkeypatch.setattr(logic, "get_suggestions", lambda cfg: {"followback": [], "domain_highlights": []})
    monkeypatch.setattr(logic, "get_activity", lambda cfg, force=False: {"events": []})
    monkeypatch.setattr(logic, "get_model_history", lambda: [])
    monkeypatch.setattr(logic, "get_friend_stats", lambda cfg: {
        "total_friends": 0, "new_this_week": 0, "follow_back_rate": None, "total_labeled": 0})

    cfg = MyGeekyConfig(gui_expanded_width=380, gui_folded_width=58, gui_folded_height=58, gui_opacity=0.9)
    panel = MyGeekyPanel(cfg)
    try:
        area = panel.screen().availableGeometry()
        assert panel.width() == 380                     # 5 tabs no longer force it wider
        assert area.contains(panel.geometry())
        panel.fold()
        assert (panel.width(), panel.height()) == (58, 58)
        assert panel.windowOpacity() == pytest.approx(0.5, abs=0.01)
        assert area.contains(panel.geometry())
        panel.unfold()
        assert panel.width() == 380 and area.contains(panel.geometry())
        assert panel.windowOpacity() == pytest.approx(0.9, abs=0.01)
    finally:
        panel.ticker.stop()
        panel._activity_timer.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.deleteLater()
