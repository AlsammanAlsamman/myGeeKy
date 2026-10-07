import json
from datetime import date, datetime, timedelta, timezone

import pytest

from mygeeky import interests, news
from mygeeky.config import MyGeekyConfig

NOW = datetime.now(timezone.utc)


def _cfg(**kw):
    return MyGeekyConfig(github_username="me", **kw)


# --------------------------------------------------------------------------- interests
def test_extract_terms_keeps_topics_whole_and_drops_noise():
    terms = interests.extract_terms("A fast Python toolkit for GWAS fine-mapping", ["fine-mapping", "gwas"])
    assert "fine mapping" in terms and "gwas" in terms
    assert terms["fine mapping"] > terms.get("python", 0)          # topics outweigh words in the text
    assert not {"fast", "toolkit", "for", "a"} & set(terms)
    assert abs(sum(terms.values()) - 1) < 0.01


def test_events_fade_and_one_stray_click_is_not_enough():
    cfg = _cfg(interest_half_life_days=30)
    interests.record("repo", "single cell atlas", topics=["single-cell"], cfg=cfg)
    assert interests.learned_terms(cfg) == []                       # one click: below the threshold
    for _ in range(3):
        interests.record("fork", "single cell atlas", topics=["single-cell"], cfg=cfg)
    assert interests.learned_terms(cfg)[0][0] == "single cell"
    later = NOW + timedelta(days=300)                                # ten half-lives later
    faded = interests.learned_weights(cfg, now=later).get("single cell", 0)
    assert faded < interests.learned_weights(cfg)["single cell"] / 500


def test_learning_can_be_turned_off():
    cfg = _cfg(interest_learning=False)
    interests.record("fork", "protein design", topics=["protein-design"], cfg=cfg)
    assert interests.load_events() == [] and interests.learned_terms(cfg) == []


def test_explore_terms_rotate_daily_and_skip_what_you_know():
    cfg = _cfg(topics=["climate", "statistics"])
    day1 = interests.explore_terms(cfg, 3, today=date(2026, 10, 7))
    assert day1 == interests.explore_terms(cfg, 3, today=date(2026, 10, 7))     # stable within a day
    assert {"climate", "statistics"}.isdisjoint(day1)
    days = {tuple(interests.explore_terms(cfg, 3, today=date(2026, 10, d))) for d in range(1, 8)}
    assert len(days) > 1                                                       # rotates


def test_mix_keeps_best_first_and_reserves_room_to_explore():
    cfg = _cfg(explore_share=0.2)
    ranked = [{"n": i} for i in range(20)]
    mixed = interests.mix(ranked, 10, cfg, seed=1)
    assert [m["n"] for m in mixed[:8]] == list(range(8)) and not any(m["explore"] for m in mixed[:8])
    assert all(m["explore"] and m["n"] >= 8 for m in mixed[8:]) and len(mixed) == 10
    assert all(not m["explore"] for m in interests.mix(ranked, 10, _cfg(explore_share=0)))


def test_match_needs_real_terms():
    weights = {"gwas": 1.0, "r": 0.4, "fine mapping": 0.8}
    score, hits = interests.match("New fine-mapping method for GWAS", weights)
    assert score > 0.5 and set(hits) == {"gwas", "fine mapping"}
    assert interests.match("Running r for the river race", {"r": 0.4}) == (0.0, [])   # one-letter terms ignored


# --------------------------------------------------------------------------- learning from GitHub
class FakeClient:
    def __init__(self, events):
        self.events, self.repo_calls = events, []

    def get_user(self, login):
        return {"bio": "Single-cell genomics and spatial transcriptomics"}

    def list_user_events(self, username, per_page=30):
        return self.events

    def get_repo(self, name):
        self.repo_calls.append(name)
        return {"description": "Spatial transcriptomics toolkit", "topics": ["spatial-transcriptomics"]}


def test_learn_from_github_follows_stars_and_forks_once():
    cfg = _cfg()
    first = FakeClient([{"id": "1", "type": "WatchEvent", "repo": {"name": "lab/old"}}])
    assert interests.learn_from_github(first, cfg, ["newfriend"]) == 1     # the follow; old stars only noted
    assert first.repo_calls == []
    second = FakeClient([{"id": "2", "type": "ForkEvent", "repo": {"name": "lab/spatial"}},
                         {"id": "1", "type": "WatchEvent", "repo": {"name": "lab/old"}},
                         {"id": "3", "type": "PushEvent", "repo": {"name": "me/x"}}])
    assert interests.learn_from_github(second, cfg) == 1                   # only the new fork
    assert second.repo_calls == ["lab/spatial"]
    kinds = [e["kind"] for e in interests.load_events()]
    assert kinds == ["follow", "fork"]
    assert "spatial transcriptomics" in interests.load_events()[1]["terms"]


def test_panel_clicks_become_interest_events():
    from mygeeky.gui import app as logic
    cfg = _cfg()
    logic.record_click(cfg, "repo", {"full_name": "lab/scvi", "description": "Deep generative single-cell models",
                                     "topics": ["single-cell"]})
    logic.record_click(cfg, "person", {"username": "ana", "bio": "Protein design", "sources": ["stargazer:a/b"]})
    logic.record_click(cfg, "news", {"id": "arxiv:1", "title": "Graph neural networks for molecules"})
    assert [e["kind"] for e in interests.load_events()] == ["repo", "person", "news"]
    assert "ana" == interests.load_events()[1]["source"]
    assert "Deep" not in json.dumps(interests.load_events())   # terms only, never the raw text


# --------------------------------------------------------------------------- news
class Resp:
    def __init__(self, body=None, content=b"", status=200):
        self._body, self.content, self.status_code = body, content, status

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://arxiv.org/abs/2610.01234v1</id><title>Fine-mapping GWAS loci at scale</title>
<summary>We fine-map gwas loci.</summary><published>2026-10-06T10:00:00Z</published></entry>
<entry><id>http://evil.example/abs/x</id><title>Bad id</title><summary>x</summary><published>2026-10-06T10:00:00Z</published></entry>
</feed>"""


class Session:
    def __init__(self, fail=()):
        self.fail = set(fail)

    def get(self, url, params=None, headers=None, timeout=None):
        if any(f in url for f in self.fail):
            raise ConnectionError("down")
        if "arxiv" in url:
            return Resp(content=ATOM)
        if "biorxiv" in url:
            return Resp({"collection": [
                {"doi": "10.1101/2026.10.05.000001", "version": "1", "title": "GWAS of drought tolerance",
                 "abstract": "Fine mapping of gwas hits", "date": "2026-10-05"},
                {"doi": "not a doi", "title": "x"}]})
        if "front_page" in str(params):
            return Resp({"hits": [{"objectID": "99", "title": "A front-page story", "points": 300}]})
        return Resp({"hits": [{"objectID": "42", "title": "Show HN: a GWAS browser", "points": 50,
                               "created_at": "2026-10-06T08:00:00Z"}, {"objectID": "x", "title": "bad id"}]})


def test_news_refresh_ranks_validates_and_explores():
    cfg = _cfg(topics=["gwas", "fine mapping"], news_size=5, explore_share=0.2)
    state = news.refresh(cfg, force=True, session=Session())
    items = state["items"]
    urls = {i["url"] for i in items}
    assert "https://arxiv.org/abs/2610.01234v1" in urls
    assert "https://www.biorxiv.org/content/10.1101/2026.10.05.000001v1" in urls
    assert "https://news.ycombinator.com/item?id=42" in urls
    assert not any("evil" in u or "bad" in i["title"] for i, u in ((i, i["url"]) for i in items))
    assert items[-1]["explore"] and items[-1]["title"] == "A front-page story"
    assert state["errors"] == []


def test_one_source_down_does_not_empty_the_news():
    cfg = _cfg(topics=["gwas", "fine mapping"])
    state = news.refresh(cfg, force=True, session=Session(fail=["arxiv"]))
    assert any(i["source"] == "biorxiv" for i in state["items"])
    assert state["errors"] and "arXiv" in state["errors"][0]


def test_a_single_generic_word_is_not_evidence():
    ranked = news.rank([{"id": "a", "title": "Stress tensor in fluids", "published": NOW.isoformat()},
                        {"id": "b", "title": "Drought stress tolerance genes", "published": NOW.isoformat()}],
                       {"stress": 0.6, "tolerance": 0.5, "genes": 0.8})
    assert ranked[0]["id"] == "b" and ranked[1]["score"] < ranked[0]["score"] / 3


def test_news_tab_renders_and_clicks_teach(monkeypatch):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from mygeeky.gui import app as logic
    from mygeeky.gui.qt_panel import MyGeekyPanel, NewsCard

    for name, value in (("get_contributions", lambda cfg: []),
                        ("get_suggestions", lambda cfg: {"followback": [], "domain_highlights": []}),
                        ("get_activity", lambda cfg, force=False: {"events": []}),
                        ("get_model_history", lambda: []),
                        ("get_friend_stats", lambda cfg: {"total_friends": 0, "new_this_week": 0,
                                                          "follow_back_rate": None, "total_labeled": 0}),
                        ("get_news", lambda cfg: {"items": [
                            {"id": "arxiv:1", "source": "arxiv", "title": "<b>Fine-mapping</b> at scale",
                             "url": "https://arxiv.org/abs/2610.01234v1", "match": ["gwas"], "explore": False,
                             "published": NOW.isoformat()},
                            {"id": "hn:9", "source": "hackernews", "title": "Something new",
                             "url": "https://news.ycombinator.com/item?id=9", "match": [], "explore": True,
                             "published": NOW.isoformat()}]}),
                        ("open_link", lambda url: True)):
        monkeypatch.setattr(logic, name, value)
    panel = MyGeekyPanel(_cfg())
    try:
        assert panel.tab_buttons["news"].text() == "News" and panel.tab_buttons["suggestions"].text() == "People"
        cards = panel.news_area.parentWidget().findChildren(NewsCard)
        assert len(cards) == 2
        cards[0].mousePressEvent(None)
        assert interests.load_events()[-1]["kind"] == "news"
    finally:
        panel.ticker.stop()
        for t in (panel._activity_timer, panel._signals_timer, panel._update_timer, panel._news_timer):
            t.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.close()
        panel.deleteLater()


def test_brain_summarizes_every_model(monkeypatch):
    from mygeeky.gui import app as logic
    from mygeeky import papers
    monkeypatch.setattr(papers, "load_trends", lambda: {"topics": [{"id": "T1", "name": "Plant genomics"}]})
    cfg = _cfg(explore_share=0.2)
    for _ in range(3):
        interests.record("fork", "single cell atlas", topics=["single-cell"], cfg=cfg)
    interests.record("follow", "protein design", cfg=cfg)
    interests.record("repo", "gwas toolkit", topics=["gwas"], cfg=cfg)
    brain = logic.get_brain(cfg)
    assert brain["field"] == ["Plant genomics"]
    assert brain["learned"][0][0] == "single cell"
    assert brain["taught"] == {"clicks": 1, "follows": 1, "stars": 0, "forks": 3}
    assert len(brain["explore"]) == 3 and brain["explore_share"] == 0.2


def test_model_tab_shows_the_interest_map(monkeypatch):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from mygeeky.gui import app as logic
    from mygeeky.gui.qt_panel import MyGeekyPanel

    brain = {"user": "me", "field": ["Genetic Mapping and Diversity in Plants"], "learned": [("gwas", 3.0)],
             "explore": ["climate"], "explore_share": 0.2, "taught": {"clicks": 5, "follows": 1, "stars": 0,
                                                                     "forks": 2}, "learning": True, "half_life": 30}
    for name, value in (("get_contributions", lambda cfg: []),
                        ("get_suggestions", lambda cfg: {"followback": [], "domain_highlights": []}),
                        ("get_activity", lambda cfg, force=False: {"events": []}),
                        ("get_model_history", lambda: []),
                        ("get_friend_stats", lambda cfg: {"total_friends": 0, "new_this_week": 0,
                                                          "follow_back_rate": None, "total_labeled": 0}),
                        ("get_brain", lambda cfg: brain)):
        monkeypatch.setattr(logic, name, value)
    panel = MyGeekyPanel(_cfg())
    try:
        panel._switch_tab("model")
        labels = [n["label"] for n in panel.interest_map._nodes]
        assert labels == ["Genetic Mapping", "gwas", "climate"]          # field shortened; full name in the tooltip
        assert [n["ring"] for n in panel.interest_map._nodes] == [0, 1, 2]
        assert panel.teach_tiles["forks"]._target == 2 and panel.explore_donut._share == 0.2
        assert "20%" in panel.explore_label.text() and "climate" in panel.explore_label.text()
        panel.interest_map.grab()                                          # paints without error
    finally:
        panel.ticker.stop()
        for t in (panel._activity_timer, panel._signals_timer, panel._update_timer, panel._news_timer):
            t.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.close()
        panel.deleteLater()
