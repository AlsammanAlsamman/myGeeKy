from datetime import date, timedelta

from mygeeky import market
from mygeeky.config import MyGeekyConfig
from mygeeky.market import compute_board, discover_watchlist, relevance

TERMS = ["computational biology", "genotype", "snp", "genome", "gwas", "bioinformatics"]


def test_relevance_keeps_field_tools():
    assert relevance({"full_name": "rgcgithub/regenie", "description": "whole genome regression modelling"}, TERMS) > 0
    assert relevance({"full_name": "odelaneau/GLIMPSE", "description": "Low Coverage Calling of Genotypes"}, TERMS) > 0
    assert relevance({"full_name": "privefl/bigsnpr", "description": "Analysis of massive SNP arrays",
                      "topics": ["gwas", "snp", "r"]}, TERMS) > 0


def test_relevance_drops_lookalikes_and_collections():
    # "SNP" in AMD's SEV-SNP is not genetics
    assert relevance({"full_name": "virtee/sev", "description": "Rust library for AMD SEV and SEV-SNP"}, TERMS) == 0
    # one field tag among many unrelated ones
    assert relevance({"full_name": "plotly/dash", "description": "Data Apps & Dashboards for Python.",
                      "topics": ["bioinformatics"] + [f"t{i}" for i in range(15)]}, TERMS) == 0
    assert relevance({"full_name": "x/Awesome-Bioinformatics", "description": "A curated list"}, TERMS) == 0
    # an AI tool using the word loosely
    assert relevance({"full_name": "x/harness", "description": "coding agent + Genome config layer"}, TERMS) == 0
    assert relevance({"full_name": "x/empryo", "description": "the AI coding genome",
                      "topics": ["ai", "cli"]}, TERMS) == 0


class SearchClient:
    def __init__(self, by_term):
        self.by_term = by_term

    def search_repositories(self, query, max_pages=1, per_page=20, sort="stars"):
        for term, repos in self.by_term.items():
            if query.startswith((term, f'"{term}"')):
                return repos
        return []


def test_watchlist_takes_turns_across_terms():
    big = [{"full_name": f"big/{i}", "description": "genome toolkit", "stargazers_count": 5000 - i} for i in range(5)]
    gwas = [{"full_name": "small/gwas-tool", "description": "fast GWAS", "stargazers_count": 60}]
    cfg = MyGeekyConfig(market_size=3, market_terms=2, market_pinned=["me/pinned"])
    picked = discover_watchlist(SearchClient({"genome": big, "gwas": gwas}), cfg, ["genome", "gwas"])
    assert picked == ["me/pinned", "big/0", "small/gwas-tool"]


def _days(n):
    return [(date(2026, 10, 1) + timedelta(days=i)).isoformat() for i in range(n)]


def test_compute_board_scores_ranks_and_movement():
    state = {
        "watchlist": ["a/hot", "b/quiet", "c/cli"],
        "pypi": {"a/hot": "hot", "b/quiet": "quiet", "c/cli": None},
        "snapshot_date": "2026-10-09",
        "rank_history": {"2026-10-08": ["b/quiet", "a/hot"]},
        "repos": {
            "a/hot": {"stars": [[d, 100 + 10 * i] for i, d in enumerate(_days(9))],
                      "commit_weeks": [5] * 52,
                      "downloads": [[d, 100 if i < 7 else 300] for i, d in enumerate(_days(14))]},
            "b/quiet": {"stars": [[d, 500] for d in _days(9)], "commit_weeks": [0] * 52,
                        "downloads": [[d, 50] for d in _days(14)]},
            "c/cli": {"stars": [["2026-10-09", 80]], "commit_weeks": [1] * 52},
        },
    }
    rows = compute_board(state)
    by = {r["repo"]: r for r in rows}
    assert rows[0]["repo"] == "a/hot"
    assert by["a/hot"]["stars_week"] == 70 and by["a/hot"]["movement"] == 1
    assert by["b/quiet"]["movement"] == -2  # was #1, now below the two active ones
    assert by["c/cli"]["movement"] == "new" and by["c/cli"]["stars_week"] is None  # still collecting
    assert by["c/cli"]["downloads_week"] is None and by["c/cli"]["spark_kind"] == "commits"
    assert by["a/hot"]["trend"] == "up" and by["c/cli"]["trend"] is None  # flat commits
    assert round(by["a/hot"]["downloads_change"], 2) == 2.0


def test_pypi_name_requires_link_back(monkeypatch):
    class Resp:
        def __init__(self, code, info=None):
            self.status_code, self._info = code, info

        def json(self):
            return {"info": self._info}

    pages = {"tool": Resp(200, {"name": "tool", "project_urls": {"Source": "https://github.com/someone-else/tool"}}),
             "owner": Resp(404)}

    class Http:
        def get(self, url, timeout=20):
            return pages.get(url.split("/pypi/")[1].split("/")[0], Resp(404))

    assert market.pypi_name_for("owner/tool", Http()) is None
    pages["tool"] = Resp(200, {"name": "tool", "project_urls": {"Source": "https://github.com/Owner/Tool/"}})
    assert market.pypi_name_for("owner/tool", Http()) == "tool"
