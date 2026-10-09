from datetime import datetime, timedelta, timezone

from mygeeky import profile_card as pc

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def test_links_are_sorted_out_by_kind_and_only_https():
    user = {"blog": "http://example.org", "twitter_username": "heng", "bio": "ORCID 0000-0002-1825-0097"}
    socials = [{"provider": "linkedin", "url": "https://www.linkedin.com/in/someone"},
               {"provider": "generic", "url": "https://scholar.google.com/citations?user=abc"},
               {"provider": "facebook", "url": "https://facebook.com/someone"}]
    kinds = {l["kind"]: l["url"] for l in pc.links(user, socials)}
    assert kinds["linkedin"].startswith("https://www.linkedin.com/") and kinds["scholar"].startswith("https://scholar.google")
    assert kinds["orcid"] == "https://orcid.org/0000-0002-1825-0097" and kinds["x"] == "https://x.com/heng"
    assert kinds["web"] == "https://example.org" and kinds["facebook"].startswith("https://")
    assert [l["kind"] for l in pc.links({}, [])] == []                    # nothing they haven't put there


def test_daily_counts_the_last_30_days():
    ev = [{"created_at": (NOW - timedelta(days=d)).isoformat()} for d in (0, 0, 1, 29, 30, 45)]
    counts = pc.daily(ev, now=NOW)
    assert len(counts) == 30 and counts[-1] == 2 and counts[-2] == 1 and counts[0] == 1 and sum(counts) == 4


def test_the_card_picks_active_and_top_repos_and_interests():
    repos = [
        {"name": "old", "pushed_at": "2020-01-01", "stargazers_count": 900, "topics": ["gwas"], "language": "R"},
        {"name": "new", "pushed_at": "2026-10-07", "stargazers_count": 3, "topics": ["gwas", "fine-mapping"], "language": "Python"},
        {"name": "mid", "pushed_at": "2026-09-01", "stargazers_count": 10, "language": "Python"},
        {"name": "fork", "pushed_at": "2026-10-08", "stargazers_count": 5000, "fork": True},
    ]
    card = pc.build({"login": "me", "followers": 3}, repos, [], [])
    assert [r["name"] for r in card["active"]] == ["new", "mid"] and card["top"]["name"] == "old"
    assert card["interests"][:2] == ["gwas", "fine mapping"] and "Python" in card["interests"]


def test_a_bad_login_is_refused_before_any_call():
    import pytest
    with pytest.raises(pc.CardError):
        pc.fetch("not a/login")
