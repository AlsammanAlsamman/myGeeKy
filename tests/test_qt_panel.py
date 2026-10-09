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

    from mygeeky.gui.qt_panel import _ClickableLabel

    opened = []
    card = RepoCard(_repo_item(), THEMES["midnight"], lambda u: opened.append(u) or True)
    issues = card.findChildren(_ClickableLabel)
    assert len(issues) == 2  # starter issues capped at 2
    for row in issues:
        row.mousePressEvent(None)
    buttons = card.findChildren(QPushButton)
    assert [b.text() for b in buttons] == ["Fork →", "Open →"]
    for b in buttons:
        b.click()
    assert opened == [
        "https://github.com/owner/tool/issues/1",
        "https://github.com/owner/tool/issues/2",
        "https://github.com/owner/tool/fork",
        "https://github.com/owner/tool",
    ]


def test_repo_card_with_long_names_fits_a_narrow_panel(qapp):
    from mygeeky.gui.app import THEMES
    from mygeeky.gui.qt_panel import RepoCard

    item = dict(_repo_item(), full_name="Some-Very-Long-Organisation-Name-Team/an-equally-long-repository-name",
                starter_issues=[{"title": "A really long issue title " * 6, "url": "u"}])
    card = RepoCard(item, THEMES["midnight"], lambda u: True)
    assert card.minimumSizeHint().width() <= 340


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


def test_model_tab_renders_history_and_weights(qapp, monkeypatch):
    from mygeeky.config import MyGeekyConfig
    from mygeeky.gui import app as logic
    from mygeeky.gui.qt_panel import MyGeekyPanel

    history = [{"timestamp": "2026-10-01T10:00:00+00:00", "n_train": 100, "n_pos": 10, "auc": 0.70},
               {"timestamp": "2026-10-02T10:00:00+00:00", "n_train": 120, "n_pos": 15, "auc": 0.81}]
    monkeypatch.setattr(logic, "get_contributions", lambda cfg: [])
    monkeypatch.setattr(logic, "get_suggestions", lambda cfg: {"followback": [], "domain_highlights": []})
    monkeypatch.setattr(logic, "get_activity", lambda cfg, force=False: {"events": []})
    monkeypatch.setattr(logic, "get_model_history", lambda: history)
    monkeypatch.setattr(logic, "get_model_weights", lambda: [
        {"feature": "follow_back_ratio", "label": "Follows people back", "weight": 1.2}])
    monkeypatch.setattr(logic, "get_friend_stats", lambda cfg: {
        "total_friends": 0, "new_this_week": 0, "follow_back_rate": None, "total_labeled": 0})

    panel = MyGeekyPanel(MyGeekyConfig())
    try:
        panel._switch_tab("model")
        assert panel.model_grade_label.text() == "Sharp"
        assert "+0.110" in panel.model_delta_label.text()
        panel.model_tiles["rate"].set_value(12.5, lambda v: f"{v:.0f}%")
        assert panel.model_tiles["rate"].value_label.text() == "12%"
        panel.chart.resize(300, 150)
        panel.chart.grab()  # paints without raising, hover tooltip included
        panel.chart._hover = 1
        panel.chart.grab()
    finally:
        panel.ticker.stop()


def test_activity_tab_groups_by_person_and_expands(qapp, monkeypatch):
    from mygeeky.config import MyGeekyConfig
    from mygeeky.gui import app as logic
    from mygeeky.gui.qt_panel import ActivityGroup, MyGeekyPanel

    events = [{"actor": "geek", "verb": f"pushed to 'b{i}'", "repo": "geek/x", "repo_url": "u",
               "profile_url": "p", "source": "match", "created_at": f"2026-10-0{i + 1}T00:00:00Z"}
              for i in range(3)]
    events.append({"actor": "friend", "verb": "starred the repo", "repo": "o/r", "source": "following",
                   "created_at": "2026-10-02T00:00:00Z"})
    monkeypatch.setattr(logic, "get_contributions", lambda cfg: [])
    monkeypatch.setattr(logic, "get_suggestions", lambda cfg: {"followback": [], "domain_highlights": []})
    monkeypatch.setattr(logic, "get_activity", lambda cfg, force=False: {"events": events, "cached": True})
    monkeypatch.setattr(logic, "get_model_history", lambda: [])
    monkeypatch.setattr(logic, "get_friend_stats", lambda cfg: {
        "total_friends": 0, "new_this_week": 0, "follow_back_rate": None, "total_labeled": 0})

    panel = MyGeekyPanel(MyGeekyConfig())
    try:
        panel._on_activity_ready({"events": events, "cached": True})
        cards = panel.activity_area.parentWidget().findChildren(ActivityGroup)
        assert [c.actor for c in cards] == ["geek", "friend"]
        assert not cards[0].expanded and cards[0].body.isHidden()
        cards[0].header.mousePressEvent(None)
        assert cards[0].expanded and "geek" in panel._expanded_actors
        panel._on_activity_ready({"events": events, "cached": True})  # a refresh keeps it open
        cards = panel.activity_area.parentWidget().findChildren(ActivityGroup)
        assert [c for c in cards if c.actor == "geek"][-1].expanded
    finally:
        panel.ticker.stop()


def test_market_tab_renders_board(qapp, monkeypatch):
    from mygeeky.config import MyGeekyConfig
    from mygeeky.gui import app as logic
    from mygeeky.gui.qt_panel import MarketRow, MyGeekyPanel

    rows = [{"repo": "rgcgithub/regenie", "rank": 1, "movement": 2, "stars": 270, "stars_week": 5,
             "downloads_week": None, "downloads_change": None, "commits_4w": 3, "spark": [1, 2, 3],
             "spark_kind": "commits", "url": "u"},
            {"repo": "scverse/scanpy", "rank": 2, "movement": "new", "stars": 2600, "stars_week": None,
             "downloads_week": 207000, "downloads_change": -0.1, "commits_4w": 40, "spark": [5, 4, 3],
             "spark_kind": "downloads", "url": "u2"}]
    monkeypatch.setattr(logic, "get_contributions", lambda cfg: [])
    monkeypatch.setattr(logic, "get_suggestions", lambda cfg: {"followback": [], "domain_highlights": []})
    monkeypatch.setattr(logic, "get_activity", lambda cfg, force=False: {"events": []})
    monkeypatch.setattr(logic, "get_model_history", lambda: [])
    monkeypatch.setattr(logic, "get_market", lambda cfg: {"rows": rows, "updated_at": "2026-10-05T00:00:00+00:00"})
    monkeypatch.setattr(logic, "get_friend_stats", lambda cfg: {
        "total_friends": 0, "new_this_week": 0, "follow_back_rate": None, "total_labeled": 0})

    panel = MyGeekyPanel(MyGeekyConfig())
    try:
        assert panel._tab_order.index("market") == 3
        panel._switch_tab("market")
        cards = panel.market_area.parentWidget().findChildren(MarketRow)
        assert [c.repo for c in cards] == ["rgcgithub/regenie", "scverse/scanpy"]
        for c in cards:
            c.grab()  # paints, sparkline included
    finally:
        panel.ticker.stop()


def test_signals_tab_renders_incoming_and_people_and_sends(qapp, monkeypatch):
    from PySide6.QtWidgets import QLabel

    from mygeeky.config import MyGeekyConfig
    from mygeeky.gui import app as logic
    from mygeeky.gui.qt_panel import MyGeekyPanel, SignalCard

    monkeypatch.setattr(logic, "get_contributions", lambda cfg: [])
    monkeypatch.setattr(logic, "get_suggestions", lambda cfg: {"followback": [], "domain_highlights": []})
    monkeypatch.setattr(logic, "get_activity", lambda cfg, force=False: {"events": []})
    monkeypatch.setattr(logic, "get_model_history", lambda: [])
    monkeypatch.setattr(logic, "get_friend_stats", lambda cfg: {
        "total_friends": 0, "new_this_week": 0, "follow_back_rate": None, "total_labeled": 0})
    data = {
        "enabled": True, "can_send": True, "fetched_at": None, "error": None,
        "incoming": [{"from": "alice", "avatar_url": "", "profile_url": "https://github.com/alice",
                      "type": "thanks", "emoji": "🙏", "text": "🙏 thanked you for your work", "repo": "",
                      "at": "2026-10-06T00:00:00+00:00", "mutual": False},
                     {"from": "carol", "avatar_url": "", "profile_url": "https://github.com/carol",
                      "type": "collab", "emoji": "🤝", "text": "🤝 you both want to collaborate", "repo": "",
                      "at": "2026-10-05T00:00:00+00:00", "mutual": True}],
        "people": [{"login": "<b>bob</b>", "avatar_url": "", "profile_url": "https://github.com/bob",
                    "status": "", "interests": ["gwas"], "shared": ["gwas"], "can_receive": True,
                    "signalled_you": False, "you_signalled": False},
                   {"login": "quietq", "avatar_url": "", "profile_url": "", "status": "🔕 not taking signals right now",
                    "interests": [], "shared": [], "can_receive": False,
                    "signalled_you": False, "you_signalled": False}],
    }
    monkeypatch.setattr(logic, "get_signals", lambda cfg, force=False: data)
    sent = []
    monkeypatch.setattr(logic, "send_signal", lambda cfg, to, g: sent.append((to, g)) or {"ok": True})

    panel = MyGeekyPanel(MyGeekyConfig())
    try:
        assert "signals" in panel.tab_buttons
        for w in list(panel._workers):
            w.wait(2000)
        qapp.processEvents()
        cards = panel.signals_area.parentWidget().findChildren(SignalCard)
        assert [c.login for c in cards] == ["alice", "carol", "<b>bob</b>", "quietq"]
        texts = [lbl.text() for lbl in cards[0].findChildren(QLabel)]
        assert any("no reply needed" in t for t in texts)                  # appreciation, never a request
        assert "🤝 match" in [lbl.text() for lbl in cards[1].findChildren(QLabel)]
        assert not cards[3].gesture_buttons                                  # quiet: no buttons at all
        assert "only find out if they choose it" in cards[0].gesture_buttons["collab"].toolTip()
        name = next(lbl for lbl in cards[2].findChildren(QLabel) if lbl.text() == "<b>bob</b>")
        from PySide6.QtCore import Qt
        assert name.textFormat() == Qt.PlainText            # beacon data is never rendered as HTML
        cards[0].gesture_buttons["learn"].click()
        for w in list(panel._workers):
            w.wait(2000)
        qapp.processEvents()
        assert sent == [("alice", "learn")]
        assert panel.ticker._items[0]["kind"] == "signal"   # signals lead the Live rotation
    finally:
        panel.ticker.stop()
        panel._activity_timer.stop()
        panel._signals_timer.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.deleteLater()


def test_signal_card_without_send_token_has_no_gesture_buttons(qapp):
    from mygeeky.gui.app import THEMES
    from mygeeky.gui.qt_panel import SignalCard

    card = SignalCard({"login": "bob", "profile_url": "https://github.com/bob"}, THEMES["midnight"],
                      lambda u: True, None)
    assert card.gesture_buttons == {}


def test_hearts_rise_fade_and_hide(qapp):
    from PySide6.QtCore import QRect, Qt

    from mygeeky.gui.qt_panel import HeartsOverlay

    h = HeartsOverlay()
    assert h.testAttribute(Qt.WA_TransparentForMouseEvents)   # never steals a click
    h.puff(QRect(500, 500, 76, 76), "right", count=3)
    assert h.is_active() and h.isVisible()
    for _ in range(200):                                        # ~6.6 s of frames
        h._tick()
        if not h.is_active():
            break
    assert not h.is_active() and not h.isVisible()
    h.close()


def test_the_panel_never_lifts_itself_over_its_own_dialogs(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QDialog
    QApplication.instance() or QApplication([])
    from mygeeky.config import MyGeekyConfig
    from mygeeky.gui import topmost
    from mygeeky.gui.qt_panel import MyGeekyPanel
    seen = {}
    monkeypatch.setattr(topmost, "keep_on_top", lambda hwnd, ignore=None: seen.update(ignore=set(ignore or ())) or False)
    panel = MyGeekyPanel(MyGeekyConfig(github_username="me"))
    try:
        panel.show()
        dialog = QDialog(panel)
        dialog.show()
        panel._ensure_docked()
        assert int(dialog.winId()) in seen["ignore"]
        dialog.close()
    finally:
        panel.ticker.stop()
        for t in (panel._activity_timer, panel._signals_timer, panel._update_timer, panel._news_timer,
                  panel._dock_guard, panel._sync_timer):
            t.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.close()
        panel.deleteLater()


def test_clicking_a_person_unfolds_their_card_in_place_and_again_folds_it(monkeypatch):
    pytest.importorskip("PySide6")
    import time
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
    app = QApplication.instance() or QApplication([])
    from mygeeky.config import MyGeekyConfig
    from mygeeky.gui import app as logic
    from mygeeky.gui.qt_panel import MyGeekyPanel, ProfileView
    monkeypatch.setattr(logic, "person_card", lambda login: {
        "login": login, "name": "Someone", "avatar": "", "bio": "", "company": "", "location": "", "followers": 1,
        "public_repos": 1, "since": "2020", "url": f"https://github.com/{login}", "active": [], "top": None,
        "daily": [0] * 30, "interests": ["gwas"], "links": []})
    opened = []
    monkeypatch.setattr(logic, "open_profile", lambda url: opened.append(url) or True)
    panel = MyGeekyPanel(MyGeekyConfig(github_username="me"))
    try:
        host = QWidget()
        lay = QVBoxLayout(host)
        item = QLabel("a person")
        lay.addWidget(item)
        lay.addWidget(QLabel("the next one"))
        assert panel._open_github("https://github.com/someone", anchor=(lay, item))
        view = lay.itemAt(1).widget()
        assert isinstance(view, ProfileView) and view.login == "someone" and not opened
        end = time.time() + 2
        while time.time() < end and view.loading.isVisible():
            app.processEvents()
        panel._open_github("https://github.com/someone", anchor=(lay, item))   # same person again: folds
        assert panel._profile_view is None
        panel._open_github("https://github.com/someone/repo")                  # a repo still opens in the browser
        assert opened == ["https://github.com/someone/repo"]
    finally:
        panel.ticker.stop()
        for t in (panel._activity_timer, panel._signals_timer, panel._update_timer, panel._news_timer,
                  panel._dock_guard, panel._sync_timer):
            t.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.close()
        panel.deleteLater()


def test_the_idea_window_never_locks_the_panel_and_opens_once(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from mygeeky.config import MyGeekyConfig
    from mygeeky.gui.qt_panel import MyGeekyPanel
    panel = MyGeekyPanel(MyGeekyConfig(github_username="me"))
    try:
        panel._open_idea_dialog()
        first = panel._idea_dialog
        assert first.isVisible() and QApplication.activeModalWidget() is None   # the panel stays usable
        panel._open_idea_dialog()
        assert panel._idea_dialog is first                                    # one window, brought forward
        first.close()
    finally:
        panel.ticker.stop()
        for t in (panel._activity_timer, panel._signals_timer, panel._update_timer, panel._news_timer,
                  panel._dock_guard, panel._sync_timer):
            t.stop()
        for w in list(panel._workers):
            w.wait(3000)
        panel.close()
        panel.deleteLater()
