"""Tests for repo-contribution suggestions, the scholarly profile, and data sync."""
import json
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from mygeeky import contribute, scholar
from mygeeky.config import MyGeekyConfig
from mygeeky.profile_builder import Profile

NOW = datetime.now(timezone.utc)


def iso(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _repo(full, desc, lang="Python", topics=(), pushed=5, owner_type="User"):
    owner = full.split("/")[0]
    return {"full_name": full, "name": full.split("/")[1], "description": desc, "language": lang,
            "topics": list(topics), "stargazers_count": 100, "pushed_at": iso(pushed),
            "archived": False, "fork": False, "html_url": f"https://github.com/{full}",
            "owner": {"login": owner, "type": owner_type, "avatar_url": ""}}


def _pr(assoc, merged, user_type="User"):
    return {"author_association": assoc, "merged_at": "2026-01-01T00:00:00Z" if merged else None,
            "user": {"type": user_type}}


class FakeRepoClient:
    REPOS = [
        _repo("lab/gwas-kit", "GWAS summary statistics toolkit", topics=["gwas", "genomics"]),
        _repo("corp/webframework", "a JavaScript web framework", lang="JavaScript", topics=["web"]),
        _repo("me/my-own", "my own GWAS repo", topics=["gwas"]),
        _repo("closed/gwas-strict", "GWAS fine-mapping", topics=["gwas"]),
    ]
    PULLS = {
        "lab/gwas-kit": [_pr("CONTRIBUTOR", True)] * 6 + [_pr("NONE", False)],
        "corp/webframework": [_pr("NONE", True)] * 3,
        "closed/gwas-strict": [_pr("NONE", False)] * 6 + [_pr("MEMBER", True)] * 5,
    }

    def __init__(self):
        self.queries = []

    def search_repositories(self, query, max_pages=1, per_page=30, sort="updated"):
        self.queries.append(query)
        return list(self.REPOS)

    def list_closed_pulls(self, full, per_page=30):
        return self.PULLS.get(full, [])

    def list_open_issues(self, full, label, per_page=10):
        if full == "lab/gwas-kit" and label == "good first issue":
            return [{"number": 1, "title": "Add docs", "html_url": "u1", "labels": [{"name": label}],
                     "comments": 0, "assignee": None, "assignees": []},
                    {"number": 2, "title": "Taken", "html_url": "u2", "labels": [], "comments": 0,
                     "assignee": {"login": "x"}, "assignees": [{"login": "x"}]},
                    {"number": 3, "title": "Ancient", "html_url": "u3", "labels": [], "comments": 0,
                     "assignee": None, "assignees": [], "updated_at": iso(2000)}]
        return []


def _self():
    return Profile(username="me", corpus="GWAS genomics fine-mapping summary statistics population genetics",
                   languages=Counter({"Python": 3}), topics=Counter({"gwas": 2}))


def test_maintainer_stats_ignores_insiders_and_bots():
    stats = contribute.maintainer_stats(
        [_pr("MEMBER", True), _pr("OWNER", True), _pr("NONE", True, "Bot"), _pr("NONE", False)])
    assert stats["external_prs_closed"] == 1
    assert stats["external_prs_merged"] == 0
    assert stats["merge_friendliness"] == 0.0


def test_search_terms_skip_generic_and_duplicates():
    cfg = MyGeekyConfig(github_username="me", topics=["GWAS", "gwas"], contribute_queries=3, explore_share=0)
    terms = contribute.search_terms(cfg, _self(), {"data": 1.0, "fine mapping": 0.9, "snakemake": 0.5})
    assert terms == ["gwas", "fine mapping", "snakemake"]


def test_search_terms_keep_one_slot_for_new_territory():
    from mygeeky import interests
    cfg = MyGeekyConfig(github_username="me", topics=["GWAS"], contribute_queries=3, explore_share=0.2)
    terms = contribute.search_terms(cfg, _self(), {"fine mapping": 0.9, "snakemake": 0.5})
    assert terms[:2] == ["gwas", "fine mapping"]
    assert terms[2] in interests.EXPLORE_POOL


def test_suggest_repositories_ranks_merge_friendly_fit_first():
    # explore_share=0: with one query, the day's "new territory" term would otherwise take it on some days
    cfg = MyGeekyConfig(github_username="me", contribute_queries=1, contribute_check_top_n=10, explore_share=0)
    client = FakeRepoClient()
    results = contribute.suggest_repositories(client, cfg, _self(), {"gwas": 1.0})
    names = [r["full_name"] for r in results]
    assert "me/my-own" not in names                      # never suggest your own repos
    assert names[0] == "lab/gwas-kit"                    # fits + merges outside PRs + open issues
    assert names.index("closed/gwas-strict") > 0         # fits, but only insiders get merged
    top = results[0]
    assert [i["title"] for i in top["starter_issues"]] == ["Add docs"]  # assigned + stale issues dropped
    assert top["fork_url"] == "https://github.com/lab/gwas-kit/fork"
    assert all("archived:false" in q and "fork:false" in q for q in client.queries)


def test_scholar_corpus_and_orcid_parsing():
    assert scholar.normalize_orcid("https://orcid.org/0000-0002-7765-5035") == "0000-0002-7765-5035"
    assert scholar.normalize_orcid("nope") == ""
    assert scholar._abstract_from_inverted_index({"world": [1], "hello": [0]}) == "hello world"
    prof = {"orcid_record": {"keywords": ["GWAS"], "titles": ["Paper A", "Paper B"]},
            "openalex": {"topics": ["Genomics"], "works": [{"title": "Paper A", "abstract": "abs",
                                                             "keywords": ["lupus"]}]}}
    text = scholar.scholar_corpus(prof)
    assert text.count("Paper A") == 1 and "Paper B" in text and "lupus" in text
    assert scholar.scholar_topics(prof) == ["GWAS", "Genomics"]


@pytest.fixture
def sync_env(tmp_path, monkeypatch):
    """Two 'machines' (data dirs) sharing one local bare repo instead of GitHub."""
    from mygeeky import sync

    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    monkeypatch.setattr(sync, "_has_gh", lambda: False)
    monkeypatch.setattr(sync, "_repo_exists", lambda repo: True)
    monkeypatch.setattr(sync, "_repo_is_private", lambda repo: True)
    monkeypatch.setattr(sync, "remote_url", lambda repo: str(bare))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t")

    def use_machine(name):
        data, conf = tmp_path / name / "data", tmp_path / name / "conf"
        data.mkdir(parents=True, exist_ok=True)
        conf.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(sync, "DATA_DIR", data)
        monkeypatch.setattr(sync, "CONFIG_FILE", conf / "config.json")
        monkeypatch.setattr(sync, "SYNCED_CONFIG_FILE", data / "config.synced.json")
        monkeypatch.setattr(sync, "MODEL_FILE", data / "model.pkl")
        monkeypatch.setattr(sync, "ensure_dirs", lambda: None)
        return data, conf / "config.json"

    return sync, use_machine


def test_sync_round_trip_merges_logs_and_skips_model(sync_env):
    sync, use_machine = sync_env

    data_a, conf_a = use_machine("a")
    conf_a.write_text(json.dumps({"github_username": "me", "orcid_id": "0000-0002-7765-5035"}))
    (data_a / "training_data.jsonl").write_text('{"u": "a1"}\n')
    (data_a / "model.pkl").write_bytes(b"not synced")
    sync.init("me/mygeeky-data")

    data_b, conf_b = use_machine("b")
    sync.init("me/mygeeky-data")
    assert json.loads(conf_b.read_text())["orcid_id"] == "0000-0002-7765-5035"
    assert not (data_b / "model.pkl").exists()

    with (data_b / "training_data.jsonl").open("a") as fh:
        fh.write('{"u": "b1"}\n')
    sync.push()

    use_machine("a")
    with (data_a / "training_data.jsonl").open("a") as fh:
        fh.write('{"u": "a2"}\n')
    assert sync.pull() == "Pulled updates from GitHub."
    lines = (data_a / "training_data.jsonl").read_text().split()
    assert sorted(lines) == sorted(['{"u":', '"a1"}', '{"u":', '"b1"}', '{"u":', '"a2"}'])


def test_joining_existing_data_drops_stale_local_model(sync_env):
    sync, use_machine = sync_env

    data_a, conf_a = use_machine("a")
    conf_a.write_text(json.dumps({"github_username": "me"}))
    (data_a / "training_data.jsonl").write_text('{"u": "a1"}\n')
    sync.init("me/mygeeky-data")

    # machine b used myGeeKy on its own first, so it has a model trained on other data
    data_b, conf_b = use_machine("b")
    conf_b.write_text(json.dumps({"github_username": "me"}))
    (data_b / "model.pkl").write_bytes(b"trained on b's old data")
    sync.init("me/mygeeky-data")

    assert not (data_b / "model.pkl").exists()  # so the caller retrains from synced data
    backups = list(data_b.parent.glob("data.backup-*"))
    assert len(backups) == 1 and (backups[0] / "model.pkl").exists()
