from urllib.parse import parse_qs, urlparse

import pytest

from mygeeky import admin, ideas
from mygeeky.config import MyGeekyConfig


# --------------------------------------------------------------------------- 💡 ideas
def test_issue_url_is_prefilled_labelled_and_safe():
    url = ideas.issue_url("problem", "Sync fails", "It said WinError 2.")
    parts = urlparse(url)
    assert parts.netloc == "github.com" and parts.path == f"/{ideas.IDEAS_REPO}/issues/new"
    q = parse_qs(parts.query)
    assert q["title"] == ["🐞 Sync fails"] and q["labels"] == ["problem"]
    assert "WinError 2" in q["body"][0] and "myGeeKy" in q["body"][0] and "Python" in q["body"][0]
    assert "token" not in q["body"][0].lower()


def test_issue_url_without_version_and_with_huge_text():
    q = parse_qs(urlparse(ideas.issue_url("idea", "x", "y", include_version=False)).query)
    assert "Python" not in q["body"][0]
    long = ideas.issue_url("idea", "Big idea", "word " * 5000)
    assert len(long) <= ideas.MAX_URL and "trimmed" in parse_qs(urlparse(long).query)["body"][0]


def test_kind_from_labels_or_title():
    assert ideas.kind_of({"labels": [{"name": "problem"}], "title": "x"}) == "problem"
    assert ideas.kind_of({"labels": [], "title": "❓ How do I"}) == "question"
    assert ideas.kind_of({"labels": [], "title": "plain"}) == "idea"


# --------------------------------------------------------------------------- 🛡 admin
def test_only_the_maker_is_admin():
    assert admin.is_admin(MyGeekyConfig(github_username="AlsammanAlsamman"))
    assert not admin.is_admin(MyGeekyConfig(github_username="someone"))


class FakeClient:
    def __init__(self, users, events=None):
        self.users, self.events = users, events or {}

    def list_stargazers(self, repo, max_pages=3):
        return ["fan"]

    def _get(self, path, params=None):
        data = ([{"created_at": t} for t in self.events.get(path.split("/")[2], [])] if "/events/public" in path
                else [{"owner": {"login": "forker"}}])

        class R:
            status_code = 200

            def json(self):
                return data
        return R()

    def get_user(self, login):
        return self.users.get(login, {})


def test_prospects_rank_reach_skip_orgs_and_track_joins(monkeypatch):
    from mygeeky import beacon, papers, storage
    monkeypatch.setattr(papers, "load_trends", lambda: {"tools": [{"repos": ["toolmaker/tool"]},
                                                                  {"repos": ["someorg/x"]}]})
    monkeypatch.setattr(storage, "last_suggestions", lambda n, list_type=None, exclude=None: [])
    monkeypatch.setattr(beacon, "load_cache", lambda: {"users": {}})
    recent = "2026-10-01T00:00:00Z"
    users = {"fan": {"type": "User", "email": "fan@uni.edu", "bio": "PhD student in genomics", "followers": 40,
                     "updated_at": recent},
             "forker": {"type": "User", "bio": "", "followers": 2, "updated_at": "2020-01-01T00:00:00Z"},
             "toolmaker": {"type": "User", "email": "not-an-email", "bio": "Bioinformatics lab", "followers": 300,
                           "updated_at": recent},
             "someorg": {"type": "Organization"}}
    from datetime import datetime, timedelta, timezone
    ago = lambda d: (datetime.now(timezone.utc) - timedelta(days=d)).isoformat()   # noqa: E731
    events = {"fan": [ago(1)] * 20,                       # busy this month
              "toolmaker": [ago(3), ago(40)],             # active, less so
              "forker": [ago(200)]}                       # quiet for months: never suggested
    cfg = MyGeekyConfig(github_username="AlsammanAlsamman")
    state = admin.refresh_prospects(FakeClient(users, events), cfg)
    ranked = [p["login"] for p in admin.prospects(state)]
    assert ranked[0] == "fan" and "someorg" not in ranked and set(ranked) == {"fan", "toolmaker"}
    fan = state["people"]["fan"]
    assert fan["events_30d"] == 20 and fan["features"]["active"] == 1.0
    assert state["people"]["toolmaker"]["features"]["active"] == round(1 / admin.BUSY_EVENTS, 3)
    assert state["people"]["forker"]["features"]["active"] == 0
    assert state["people"]["toolmaker"]["email"] == ""             # malformed email dropped
    assert admin.invite(state["people"]["fan"], cfg)["mailto"].startswith("mailto:fan@uni.edu?subject=")
    gmail = admin.invite(state["people"]["fan"], cfg)["gmail"]
    assert gmail.startswith("https://mail.google.com/mail/?view=cm&fs=1&to=fan%40uni.edu&su=") and "&body=Hi%20" in gmail
    assert "mailto" not in admin.invite(state["people"]["toolmaker"], cfg)
    # invited, then they turn up on Signals: counted as joined
    assert admin.mark("toolmaker", "invited")["ok"]
    monkeypatch.setattr(beacon, "load_cache", lambda: {"users": {"toolmaker": {}}})
    state = admin.refresh_prospects(FakeClient(users, events), cfg)
    assert state["people"]["toolmaker"]["status"] == "joined" and admin.funnel(state)["joined"] == 1


def test_invites_are_paced():
    for i in range(admin.INVITE_DAILY_LIMIT):
        assert admin.mark(f"p{i}", "invited")["ok"]
    over = admin.mark("one-more", "invited")
    assert not over["ok"] and "tomorrow" in over["message"]


@pytest.mark.parametrize("user, has_tab", [("AlsammanAlsamman", True), ("someone", False)])
def test_admin_tab_only_for_the_maker(monkeypatch, user, has_tab):
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
    panel = MyGeekyPanel(MyGeekyConfig(github_username=user, gui_expanded_width=380))
    try:
        assert ("admin" in panel.tab_buttons) is has_tab
        assert panel.idea_btn.toolTip().startswith("Send an idea")        # the lamp is for everyone
        assert panel.width() == 380                                         # still fits with the extra tab
    finally:
        panel.ticker.stop()
        for t in (panel._activity_timer, panel._signals_timer, panel._update_timer, panel._news_timer):
            t.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.close()
        panel.deleteLater()


def test_panel_returns_to_its_edge_after_windows_moves_it(monkeypatch):
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
    panel = MyGeekyPanel(MyGeekyConfig(github_username="someone"))
    try:
        panel.show()
        for folded in (False, True):
            panel._dock(folded)
            home = panel.geometry()
            panel.move(home.x() - 500, home.y() + 120)              # what Windows does after sleep/unplug
            assert panel.geometry() != home
            panel._ensure_docked()
            assert panel.geometry() == home
            panel._ensure_docked()                                     # already home: nothing changes
            assert panel.geometry() == home
        assert panel._dock_guard.isActive()
    finally:
        panel.ticker.stop()
        for t in (panel._activity_timer, panel._signals_timer, panel._update_timer, panel._news_timer,
                  panel._dock_guard):
            t.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.close()
        panel.deleteLater()


def test_the_invite_opens_in_plain_words_and_tells_why_it_exists():
    cfg = MyGeekyConfig(github_username="AlsammanAlsamman")
    body = admin.invite({"name": "Ada Lovelace", "why": ["builds lab/tool (published)"]}, cfg)["body"]
    assert body.startswith("Hi Ada,\n\nI came across lab/tool on GitHub, the tool behind your published paper.")
    assert "Facebook or LinkedIn" in body and "install it and give it a try" in body
    assert "(published)" not in body and "works in your field" not in body
    assert admin.invite({"login": "fan", "why": ["starred myGeeKy"]}, cfg)["body"].split("\n")[2].startswith("Thank you")
