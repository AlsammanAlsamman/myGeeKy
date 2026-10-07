import json

import pytest

from mygeeky import keywords as kw
from mygeeky.config import MyGeekyConfig

DICT = {"version": "2026.10.07.0000", "terms": {
    "ai": {"label": "ai", "repos": 100, "related": [["llm", 1.0], ["deep-learning", 0.8], ["r", 0.7]]},
    "gwas": {"label": "gwas", "repos": 100, "related": [["genomics", 1.0], ["statistical-genetics", 0.6]]},
    "single-cell": {"label": "single cell", "repos": 100, "related": [["rna-seq", 1.0]]},
    "transformer": {"label": "transformer", "repos": 50, "related": []},
}}


@pytest.fixture(autouse=True)
def dictionary(monkeypatch, tmp_path):
    path = tmp_path / "keywords.json"
    path.write_text(json.dumps(DICT))
    monkeypatch.setattr(kw, "BUNDLED", path)
    monkeypatch.setattr(kw, "CACHE_FILE", tmp_path / "cache.json")
    kw.load(force=True)
    yield
    kw._loaded = None


def test_lookup_handles_spelling_aliases_and_plurals():
    assert kw.lookup("AI")["topic"] == "ai"
    assert kw.lookup("Single Cell")["topic"] == "single-cell"
    assert kw.lookup("scRNA-seq")["topic"] == "single-cell"          # an alias
    assert kw.lookup("transformers")["topic"] == "transformer"        # a plural
    assert kw.lookup("basket weaving") is None
    assert kw.split_known(["AI", "basket weaving", "gwas"]) == (["AI", "gwas"], ["basket weaving"])


def test_a_known_keyword_brings_its_meaning_an_unknown_one_only_itself():
    out = kw.expand(["AI", "basket weaving"])
    assert out["ai"] == 1.0 and out["basket weaving"] == 1.0
    assert out["llm"] == pytest.approx(kw.RELATED_WEIGHT) and out["deep learning"] == pytest.approx(0.48)
    assert "r" not in out                                              # too short to match safely
    assert not any(k.startswith("basket") and k != "basket weaving" for k in out)


def test_enrich_vocabulary_keeps_your_own_weights_and_skips_tiny_terms():
    cfg = MyGeekyConfig(keywords=["AI", "gwas"])
    out = kw.enrich_vocabulary({"genomics": 0.9, "llm": 0.1}, cfg)
    assert out["genomics"] == 0.9                     # yours was higher: kept
    assert out["llm"] == pytest.approx(0.6)            # the dictionary's was higher: raised
    assert "ai" not in out                             # 2 letters would match inside "said"
    assert out["statistical genetics"] == pytest.approx(0.36)


def test_interest_matching_uses_the_meaning(monkeypatch):
    from mygeeky import interests
    cfg = MyGeekyConfig(keywords=["gwas"], topics=[], languages=[])
    weights = interests.profile_terms(cfg)
    score, matched = interests.match("New statistical genetics method for genomics cohorts", weights)
    assert score > 0 and "genomics" in matched


def test_red_keywords_arrive_from_both_routes():
    from mygeeky import beacon
    cache = {"users": {"alice": {"raw": {"mygeeky_beacon": 2, "keys": [], "interests": ["basket weaving", "gwas"],
                                         "sealed": []}}}}
    assert kw.requests_from_beacons(cache) == {"basket weaving": 1}
    issues = [{"kind": "keyword", "title": "🔤 Keyword: Basket Weaving"}, {"kind": "keyword", "title": "🔤 Keyword: AI"},
              {"kind": "idea", "title": "💡 something"}]
    assert kw.requests_from_issues(issues) == {"basket weaving": 1}
    # your beacon carries red keywords first, so they survive the interest cap
    cfg = MyGeekyConfig(keywords=["gwas", "basket weaving"], topics=["t%d" % i for i in range(20)])
    assert beacon._interests(cfg)[0] == "basket weaving"


def test_suggest_link_is_a_prefilled_keyword_issue():
    from urllib.parse import parse_qs, urlparse
    from mygeeky import ideas
    q = parse_qs(urlparse(ideas.keyword_url("basket weaving")).query)
    assert q["labels"] == ["keyword"] and q["title"] == ["🔤 Keyword: basket weaving"]


class FakeClient:
    """Repos per topic: 'gwas' repos always carry genomics, often statistical-genetics,
    and everything carries python (generic) and hacktoberfest (noise)."""

    def __init__(self):
        self.calls = []

    def _get(self, path, params=None, is_search=False):
        topic = params["q"].split()[0].split(":")[1]
        self.calls.append(topic)
        data = {
            "gwas": [["gwas", "genomics", "python", "hacktoberfest"]] * 10
            + [["gwas", "genomics", "statistical-genetics", "python"]] * 10,
            "genomics": [["genomics", "gwas", "python"]] * 8 + [["genomics", "rna-seq", "python"]] * 12,
            "statistical-genetics": [["statistical-genetics", "gwas"]] * 3,      # too few to learn
        }.get(topic, [])

        class R:
            status_code = 200

            def json(self_inner):
                return {"items": [{"topics": t} for t in data]}
        return R()


def test_the_model_learns_what_goes_together_and_ignores_noise():
    client = FakeClient()
    d = kw.build(client, seeds=["gwas"], max_terms=10, min_repos=5)
    assert set(d["terms"]) == {"gwas", "genomics"}            # statistical-genetics had too few repos
    rel = dict(d["terms"]["gwas"]["related"])
    assert rel["genomics"] == 1.0 and 0 < rel["statistical-genetics"] < 1
    assert "python" not in rel and "hacktoberfest" not in rel  # generic topics say nothing
    assert client.calls[0] == "gwas" and "genomics" in client.calls   # it snowballed


def test_refresh_takes_a_newer_published_dictionary_once_a_week(monkeypatch):
    newer = {**DICT, "version": "2026.11.01.0000", "terms": {**DICT["terms"], "basket-weaving": {
        "label": "basket weaving", "repos": 20, "related": []}}}

    class R:
        status_code = 200

        def json(self):
            return newer
    calls = []
    monkeypatch.setattr(kw.requests, "get", lambda url, timeout: calls.append(url) or R())
    assert kw.refresh_if_due() is True and kw.known("basket weaving")
    assert kw.refresh_if_due() is False and len(calls) == 1      # checked: not again this week


def test_model_tab_shows_green_and_red_keywords(monkeypatch):
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
    opened = []
    monkeypatch.setattr(logic, "open_link", lambda url: opened.append(url) or True)
    panel = MyGeekyPanel(MyGeekyConfig(github_username="me", keywords=["AI", "basket weaving"]))
    try:
        panel._render_keywords()
        html = panel.kw_chips.text()
        assert "#34d399; text-decoration:none'>● AI" in html
        assert "#f87171; text-decoration:none'>● basket&nbsp;weaving" in html   # never breaks mid-keyword
        panel._on_keyword_hover("kw:0")
        assert "llm" in panel.kw_detail.text()
        panel._on_keyword_link("kw:1")                         # red: suggest it
        assert opened and "Keyword" in opened[0]
        assert panel.kw_completer.model().rowCount() == len(DICT["terms"])
    finally:
        panel.ticker.stop()
        for t in (panel._activity_timer, panel._signals_timer, panel._update_timer, panel._news_timer,
                  panel._dock_guard):
            t.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.close()
        panel.deleteLater()
