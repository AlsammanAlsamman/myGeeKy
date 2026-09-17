"""Integration tests for the run/suggestions pipeline against a fake GitHubClient."""
from datetime import datetime, timedelta, timezone

from click.testing import CliRunner

from mygeeky import cli as mg_cli
from mygeeky.config import MyGeekyConfig, save_config

NOW = datetime.now(timezone.utc)


def iso(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


USERS = {
    "me": {"login": "me", "bio": "I build GWAS and population genetics tools", "company": "",
           "followers": 100, "following": 120, "public_repos": 20, "type": "User"},
    "matchy": {"login": "matchy", "bio": "population genetics and GWAS researcher", "company": "",
               "followers": 50, "following": 60, "public_repos": 10, "type": "User"},
    "bot_massfollow": {"login": "bot_massfollow", "bio": "genomics enjoyer", "company": "",
                        "followers": 10, "following": 9000, "public_repos": 5, "type": "User"},
    "dormant": {"login": "dormant", "bio": "population genetics", "company": "",
                "followers": 1, "following": 1, "public_repos": 3, "type": "User"},
    "stale_repo": {"login": "stale_repo", "bio": "population genetics GWAS", "company": "",
                   "followers": 40, "following": 30, "public_repos": 4, "type": "User"},
    "org_account": {"login": "org_account", "bio": "population genetics org", "company": "",
                     "followers": 500, "following": 1, "public_repos": 40, "type": "Organization"},
}

REPOS = {
    "matchy": [{"name": "gwastool", "description": "GWAS pipeline", "language": "Python",
                "topics": ["gwas"], "fork": False, "pushed_at": iso(10), "created_at": iso(400),
                "full_name": "matchy/gwastool", "stargazers_count": 5}],
    "me": [{"name": "poptools", "description": "population genetics", "language": "Python",
            "topics": ["popgen"], "fork": False, "pushed_at": iso(5), "created_at": iso(300),
            "full_name": "me/poptools", "stargazers_count": 20}],
    "bot_massfollow": [{"name": "x", "description": "", "language": "Python", "topics": [],
                         "fork": False, "pushed_at": iso(5), "created_at": iso(100),
                         "full_name": "bot_massfollow/x", "stargazers_count": 0}],
    "dormant": [{"name": "y", "description": "", "language": "Python", "topics": [],
                 "fork": False, "pushed_at": iso(5), "created_at": iso(100),
                 "full_name": "dormant/y", "stargazers_count": 0}],
    "stale_repo": [{"name": "z", "description": "old stuff", "language": "Python", "topics": [],
                     "fork": False, "pushed_at": iso(900), "created_at": iso(1200),
                     "full_name": "stale_repo/z", "stargazers_count": 0}],
    "org_account": [{"name": "w", "description": "", "language": "Python", "topics": [],
                      "fork": False, "pushed_at": iso(5), "created_at": iso(100),
                      "full_name": "org_account/w", "stargazers_count": 0}],
}


class FakeClient:
    def get_user(self, username):
        return USERS.get(username.lower())

    def list_repos(self, username, max_pages=3, per_page=100, sort="updated"):
        return REPOS.get(username.lower(), [])

    def list_following(self, username, max_pages=10):
        return []

    def list_followers(self, username, max_pages=10):
        return []

    def list_stargazers(self, owner_repo, max_pages=3):
        return []

    def search_users(self, query, max_pages=3, per_page=30):
        for login in ["matchy", "bot_massfollow", "dormant", "stale_repo", "org_account"]:
            yield {"login": login}

    def is_following(self, source, target):
        return False


def _cfg() -> MyGeekyConfig:
    return MyGeekyConfig(
        github_username="me", max_following=500, min_public_repos=1,
        similarity_threshold=0.0, max_candidates_per_run=20,
        max_suggestions_returned=10, domain_highlight_count=10,
        require_followers_or_following=True, min_followers_gate=5, min_following_gate=5,
    )


def test_hard_filters_reject_bad_candidates(monkeypatch):
    monkeypatch.setattr(mg_cli, "_client_for", lambda cfg: FakeClient())
    results = mg_cli._run_suggestions(_cfg())

    followback_users = [r["username"] for r in results["followback"]]
    assert "bot_massfollow" not in followback_users  # over max_following
    assert "dormant" not in followback_users          # fails followers-or-following gate
    assert "stale_repo" not in followback_users        # fails real per-repo activity QC
    assert "org_account" not in followback_users        # organizations excluded
    assert "matchy" in followback_users


def test_suggestions_log_tags_survive_dual_list_membership(monkeypatch, tmp_path):
    """Regression test: a candidate qualifying for both the followback and
    domain-fit lists must be logged as two distinct records with correct,
    independent `list` tags -- not one record whose tag gets clobbered by
    whichever list was tagged second (see cli.py _run_suggestions)."""
    import mygeeky.storage as storage_module

    # storage.py resolves SUGGESTIONS_LOG as a module-global at call time, so
    # patching it there (not on mygeeky.config, which owns a separate binding)
    # is what actually redirects log_suggestions()/last_suggestions().
    monkeypatch.setattr(storage_module, "SUGGESTIONS_LOG", tmp_path / "suggestions_history.jsonl")
    monkeypatch.setattr(mg_cli, "_client_for", lambda cfg: FakeClient())

    cfg = _cfg()
    cfg.similarity_threshold = 0.0  # ensure matchy (positive domain_fit) also clears followback threshold
    results = mg_cli._run_suggestions(cfg)

    assert any(r["username"] == "matchy" for r in results["followback"])
    assert any(r["username"] == "matchy" for r in results["domain_highlights"])

    from mygeeky.storage import last_suggestions
    followback_logged = last_suggestions(50, list_type="followback")
    domain_logged = last_suggestions(50, list_type="domain")
    assert any(r["username"] == "matchy" for r in followback_logged)
    assert any(r["username"] == "matchy" for r in domain_logged)


def test_bootstrap_labels_and_excludes_mass_follow_outlier(monkeypatch, tmp_path):
    import mygeeky.config as config_module
    import mygeeky.matcher as matcher_module
    import mygeeky.storage as storage_module

    # Every one of these constants is bound into its *own* module's
    # namespace by `from .config import X`, and (for MODEL_FILE) only ever
    # resolved at call time -- so each importing module needs patching
    # separately; patching mygeeky.config alone would not affect any of them.
    monkeypatch.setattr(config_module, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(storage_module, "TRAINING_LOG", tmp_path / "training_data.jsonl")
    monkeypatch.setattr(storage_module, "FOLLOWING_SNAPSHOT", tmp_path / "following_snapshot.json")
    monkeypatch.setattr(storage_module, "EXCLUDED_FILE", tmp_path / "excluded.json")
    monkeypatch.setattr(matcher_module, "MODEL_FILE", tmp_path / "model.pkl")

    followees = [f"user{i}" for i in range(10)]
    follows_back = {"user0", "user1", "user2", "user3"}
    following_counts = {f"user{i}": (5000 if i == 9 else 20 + i) for i in range(10)}
    users = {"me": USERS["me"]}
    for u in followees:
        users[u] = {"login": u, "bio": "bioinformatics geek", "company": "", "followers": 30,
                     "following": following_counts[u], "public_repos": 5, "type": "User"}

    class BootstrapFakeClient(FakeClient):
        def get_user(self, username):
            return users.get(username.lower())

        def list_following(self, username, max_pages=10):
            return followees if username == "me" else []

        def is_following(self, source, target):
            return source in follows_back

    monkeypatch.setattr(mg_cli, "_client_for", lambda cfg: BootstrapFakeClient())
    save_config(MyGeekyConfig(github_username="me", min_training_samples=5, training_mass_follow_outlier=3000))

    runner = CliRunner()
    result = runner.invoke(mg_cli.bootstrap, ["--limit", "300"])
    assert result.exit_code == 0, result.output
    assert "4 follow you back" in result.output
    assert "excluded 1 mass-follow outlier" in result.output
