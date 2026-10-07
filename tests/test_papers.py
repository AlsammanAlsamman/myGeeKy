import base64
from datetime import date, datetime, timezone

import pytest

from mygeeky import papers
from mygeeky.config import MyGeekyConfig


def _work(i="W1", title="IQ-TREE 3: phylogenomic inference", cited=417, day="2026-01-01", **kw):
    abstract = kw.get("abstract", "We present IQ-TREE 3. Code: https://github.com/iqtree/iqtree3.")
    inv = {}
    for pos, word in enumerate(abstract.split()):
        inv.setdefault(word, []).append(pos)
    return {"id": f"https://openalex.org/{i}", "doi": kw.get("doi", "https://doi.org/10.1093/molbev/msag117"),
            "title": title, "publication_date": day, "cited_by_count": cited, "type": "article",
            "primary_location": {"source": {"display_name": "Molecular Biology and Evolution"}},
            "abstract_inverted_index": inv,
            "authorships": kw.get("authorships", [
                {"author": {"display_name": "Thomas Wong", "orcid": "https://orcid.org/0000-0002-1825-0097",
                            "id": "https://openalex.org/A1"}},
                {"author": {"display_name": "Middle Person", "id": "https://openalex.org/A2"}},
                {"author": {"display_name": "Bui Quang Minh", "id": "https://openalex.org/A3"}}])}


def test_to_paper_validates_and_rebuilds_the_abstract():
    p = papers.to_paper(_work())
    assert p["url"] == "https://doi.org/10.1093/molbev/msag117" and p["repos"] == ["iqtree/iqtree3"]
    assert p["abstract"].startswith("We present IQ-TREE 3.") and p["venue"] == "Molecular Biology and Evolution"
    assert p["authors"][0]["orcid"] == "0000-0002-1825-0097"
    assert papers.to_paper(dict(_work(), id="https://evil/xyz")) is None
    assert papers.to_paper(dict(_work(), doi="javascript:alert(1)"))["url"].startswith("https://openalex.org/")


def test_github_links_in_abstracts():
    text = "Available at github.com/lab/tool.git and https://github.com/lab/tool, plus github.com/x/y."
    assert papers.github_repos_in(text) == ["lab/tool", "x/y"]


def test_velocity_is_citations_per_month():
    assert papers.velocity({"cited": 120, "date": "2026-01-01"}, today=date(2026, 4, 1)) == pytest.approx(40.5, 0.1)
    assert papers.velocity({"cited": 5, "date": "2026-09-30"}, today=date(2026, 10, 1)) == 5.0   # at least a month


def test_people_behind_counts_lead_and_senior_authors():
    a = papers.to_paper(_work("W1"))
    b = papers.to_paper(_work("W2", title="Another", cited=10))
    people = papers.people_behind([a, b])
    names = [p["name"] for p in people]
    assert "Middle Person" not in names                      # not first or last
    assert people[0]["papers"] == 2 and people[0]["url"].startswith("https://orcid.org/")


class FakeGitHub:
    def __init__(self, files):
        self.files = files

    def get_repo_file(self, repo, path):
        text = self.files.get((repo, path))
        if text is None:
            return None
        return {"encoding": "base64", "size": len(text), "content": base64.b64encode(text.encode()).decode()}


def test_doi_from_citation_cff_prefers_the_paper_then_readme():
    cff = "cff-version: 1.2.0\ndoi: 10.5281/zenodo.123\npreferred-citation:\n  type: article\n  doi: 10.1002/imt2.70078\n"
    gh = FakeGitHub({("a/b", "CITATION.cff"): cff,
                     ("c/d", "README.md"): "[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.9.svg)] Please cite "
                                           "https://doi.org/10.1186/s13059-017-1382-0."})
    assert papers.doi_for_repo(gh, "a/b") == "10.1002/imt2.70078"
    assert papers.doi_for_repo(gh, "c/d") == "10.1186/s13059-017-1382-0"     # the paper, not the zenodo badge
    assert papers.doi_for_repo(gh, "e/f") is None


class Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_annotate_repos_caches_and_limits_lookups(monkeypatch):
    gh = FakeGitHub({("a/b", "CITATION.cff"): "doi: 10.1093/molbev/msag117\n"})

    class S:
        calls = 0

        def get(self, url, params=None, headers=None, timeout=None):
            S.calls += 1
            return Resp(_work())
    found = papers.annotate_repos(gh, ["a/b", "no/paper"], session=S())
    assert found["a/b"]["cited"] == 417 and "no/paper" not in found
    assert papers.cached_paper("A/B")["doi"] == "10.1093/molbev/msag117"
    papers.annotate_repos(gh, ["a/b", "no/paper"], session=S())
    assert S.calls == 1                                       # both cached (with or without a paper)
    assert papers.annotate_repos(gh, ["x/1", "x/2", "x/3"], max_lookups=1, session=S()) == {}


def test_trends_use_your_openalex_topics(monkeypatch):
    from mygeeky import scholar
    monkeypatch.setattr(scholar, "load_scholar_profile", lambda: {"openalex": {"author_id": "A99"}})
    asked = []

    class S:
        def get(self, url, params=None, headers=None, timeout=None):
            asked.append((url, (params or {}).get("filter", "")))
            if "/authors/" in url:
                return Resp({"topics": [{"id": "https://openalex.org/T10001", "display_name": "Plant genomics"}]})
            if "/topics" in url:
                return Resp({"results": []})
            if "github" in (params or {}).get("filter", ""):
                return Resp({"results": [_work("W5", title="ToolX for plant genomics", cited=3,
                                               abstract="ToolX code at github.com/lab/toolx")]})
            if "primary_topic" in (params or {}).get("filter", ""):
                return Resp({"results": [_work("W1"), _work("W2", title="Old", cited=10, day="2025-06-01",
                                                            abstract="no code here")]})
            return Resp({"results": []})
    cfg = MyGeekyConfig(github_username="me", explore_share=0, trends_size=5)
    state = papers.refresh_trends(cfg, force=True, session=S())
    assert [t["name"] for t in state["topics"]] == ["Plant genomics"]
    assert any("primary_topic.id:T10001" in f for _, f in asked)
    assert state["rising"][0]["id"] == "W1"                    # fastest-cited first
    assert state["tools"][0]["repos"] == ["lab/toolx"]
    assert papers.cached_paper("lab/toolx")["title"].startswith("ToolX")   # tool papers feed the [P] badge


def test_research_view_renders_and_expands_to_people(monkeypatch):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel
    QApplication.instance() or QApplication([])
    from mygeeky.gui import app as logic
    from mygeeky.gui.qt_panel import MyGeekyPanel, ResearchCard, ResearcherRow

    paper = {**papers.to_paper(_work()), "velocity": 79.7, "match": [], "explore": False}
    for name, value in (("get_contributions", lambda cfg: []),
                        ("get_suggestions", lambda cfg: {"followback": [], "domain_highlights": []}),
                        ("get_activity", lambda cfg, force=False: {"events": []}),
                        ("get_model_history", lambda: []),
                        ("get_friend_stats", lambda cfg: {"total_friends": 0, "new_this_week": 0,
                                                          "follow_back_rate": None, "total_labeled": 0}),
                        ("get_trends", lambda cfg: {"rising": [paper], "tools": [], "people": [
                            {"name": "Bui Quang Minh", "papers": 2, "citations": 900,
                             "url": "https://orcid.org/0000-0002-1825-0097"}], "topics": []}),
                        ("trends_due", lambda cfg: False),
                        ("repo_people", lambda cfg, repo: [{"login": "bqminh", "avatar": "", "role": "owner"}])):
        monkeypatch.setattr(logic, name, value)
    panel = MyGeekyPanel(MyGeekyConfig(github_username="me"))
    try:
        panel._switch_tab("market")
        panel._set_market_mode("research")
        assert panel.market_stack.currentIndex() == 1
        card = panel.research_area.parentWidget().findChildren(ResearchCard)[0]
        assert len(panel.research_area.parentWidget().findChildren(ResearcherRow)) == 1
        card.toggle()
        import time
        for _ in range(40):   # the people arrive from a background thread
            QApplication.processEvents()
            if any(lbl.text() == "bqminh" for lbl in card.findChildren(QLabel)):
                break
            time.sleep(0.05)
        assert any(lbl.text() == "bqminh" for lbl in card.findChildren(QLabel))
    finally:
        panel.ticker.stop()
        for t in (panel._activity_timer, panel._signals_timer, panel._update_timer, panel._news_timer):
            t.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.close()
        panel.deleteLater()
