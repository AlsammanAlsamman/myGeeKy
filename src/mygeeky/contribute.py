"""Suggest repositories you could fork, improve, and get merged.

Pipeline:
  1. Turn your profile (your repos' topics, configured topics, the domain
     vocabulary derived from your CV/repos/publications) into a handful of
     GitHub repository searches, restricted to active, non-archived repos
     that have open `good first issue` / `help wanted` issues.
  2. Rank every hit cheaply by how well it matches you (TF-IDF over
     name/description/topics, language overlap, recency).
  3. For the top few, do the check that actually predicts a merge: of the
     repo's recently closed PRs from *outside* contributors, how many did
     the maintainers merge? Plus: are there unassigned beginner/help-wanted
     issues to start from right now?

Like everything in myGeeKy this only suggests. There is no fork, PR, or
comment code here -- you open the repo, fork it, and send the PR yourself.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .config import MyGeekyConfig
from .github_client import GitHubClient
from .matcher import _recency_score
from .profile_builder import Profile

INSIDER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
ISSUE_LABELS = ["good first issue", "help wanted"]
SEARCH_QUALIFIERS = ["good-first-issues:>0", "help-wanted-issues:>0"]

# Terms too broad to find a project with: words that are everywhere on
# GitHub, and whole-discipline names (OpenAlex tags most papers with these).
GENERIC_TERMS = {
    "data", "analysis", "using", "based", "tool", "tools", "code", "project", "projects",
    "university", "research", "new", "use", "work", "study", "studies", "results", "method",
    "methods", "development", "high", "model", "models", "application", "applications",
    "library", "scientific", "python3", "python", "r", "gene", "genes", "population",
    "biology", "medicine", "computer science", "chemistry", "physics", "mathematics",
    "engineering", "agronomy", "botany", "ecology", "genetics", "biotechnology", "animal science",
    "psychology", "economics", "geography", "geology", "materials science", "environmental science",
}


def _norm(term: str) -> str:
    key = term.strip().lower().replace("-", " ")
    return key[:-1] if key.endswith("s") and len(key) > 4 and not key.endswith("ss") else key


def _corpus_count(corpus_lower: str, term: str) -> int:
    return len(re.findall(r"\b" + re.escape(term).replace(r"\ ", r"[\s-]") + r"s?\b", corpus_lower))


def search_terms(cfg: MyGeekyConfig, self_profile: Profile, vocabulary: dict[str, float],
                 keyword_counts: dict[str, int] | None = None) -> list[str]:
    """Pick the profile terms to search GitHub for.

    Explicit choices come first (`contribute_extra_terms`, `topics`). The
    rest are ranked by evidence: how many of your publications carry the
    term as a keyword, plus how often it appears across your CV/repos/
    publications. Your repos' GitHub topics only count if used on 2+ repos
    -- a one-off topic says little about what you work on.
    """
    explicit = list(cfg.contribute_extra_terms) + list(cfg.topics)
    # what you've been engaging with lately (clicks, follows, stars, forks), then
    # one "new territory" term so the searches also reach outside your bubble
    from . import interests
    learned = [t for t, _ in interests.learned_terms(cfg, max(2, cfg.contribute_queries // 4))]
    explore = interests.explore_terms(cfg, 1) if cfg.explore_share > 0 else []
    explicit = explicit + learned
    corpus_lower = self_profile.corpus.lower()
    weighted: dict[str, float] = {}
    for kw, n in (keyword_counts or {}).items():
        weighted[kw] = weighted.get(kw, 0) + 3 * n
    for topic, n in self_profile.topics.items():
        if n >= 2:
            weighted[topic] = weighted.get(topic, 0) + 5 * n
    for term in vocabulary:
        weighted.setdefault(term, 0.0)
    for term in list(weighted):
        # log-damped so frequent abstract words can't drown out curated keywords
        weighted[term] += 2 * math.log1p(_corpus_count(corpus_lower, term.lower().replace("-", " ")))
    ranked = sorted(weighted, key=lambda t: weighted[t], reverse=True)

    seen: set[str] = set()
    terms: list[str] = []
    for t in explicit + ranked:
        term = t.strip().lower().replace("-", " ")
        key = _norm(term)
        if (not key or key in seen or term in GENERIC_TERMS or key in GENERIC_TERMS
                or len(key) < 3 or key.replace(" ", "").isdigit()):
            continue
        seen.add(key)
        terms.append(term)
        if len(terms) >= cfg.contribute_queries - len(explore):
            break
    return terms + [t for t in explore if _norm(t) not in seen]


def build_repo_queries(cfg: MyGeekyConfig, terms: list[str], now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=cfg.contribute_pushed_within_days)).strftime("%Y-%m-%d")
    shared = (f"archived:false fork:false stars:{cfg.contribute_min_stars}..{cfg.contribute_max_stars} "
              f"pushed:>{since}")
    queries = []
    for term in terms:
        quoted = f'"{term}"' if " " in term else term
        for qual in SEARCH_QUALIFIERS:
            queries.append(f"{quoted} in:name,description,topics {shared} {qual}")
    return queries


def _repo_text(repo: dict[str, Any]) -> str:
    name = (repo.get("name") or "").replace("-", " ").replace("_", " ")
    topics = " ".join(t.replace("-", " ") for t in repo.get("topics") or [])
    return " \n ".join(p for p in [name, repo.get("description") or "", topics, repo.get("language") or ""] if p)


def fit_scores(self_corpus: str, repos: list[dict[str, Any]], languages: set[str]) -> list[dict[str, float]]:
    """Cheap per-repo match to you: one TF-IDF fit over your corpus + all repo texts."""
    if not repos:
        return []
    texts = [_repo_text(r) for r in repos]
    sims = [0.0] * len(repos)
    if self_corpus.strip():
        try:
            matrix = TfidfVectorizer(stop_words="english", max_features=5000).fit_transform([self_corpus, *texts])
            sims = list(cosine_similarity(matrix[0:1], matrix[1:])[0])
        except ValueError:
            pass
    top = max(sims) or 1.0
    langs = {lang.lower() for lang in languages}
    out = []
    for repo, sim in zip(repos, sims):
        lang_match = 1.0 if (repo.get("language") or "").lower() in langs else 0.0
        recency = _recency_score(repo.get("pushed_at") or "")
        content = float(sim) / top
        out.append({
            "content_similarity": round(content, 4),
            "language_match": lang_match,
            "recency": round(recency, 4),
            "fit": round(0.65 * content + 0.2 * lang_match + 0.15 * recency, 4),
        })
    return out


def maintainer_stats(pulls: list[dict[str, Any]]) -> dict[str, Any]:
    """How often do maintainers merge PRs from people outside the project?"""
    external = [p for p in pulls
                if (p.get("author_association") or "").upper() not in INSIDER_ASSOCIATIONS
                and ((p.get("user") or {}).get("type") != "Bot")]
    merged = [p for p in external if p.get("merged_at")]
    n_closed, n_merged = len(external), len(merged)
    if n_closed == 0:
        friendliness = 0.2  # no evidence either way -- don't bury it, don't promote it
    else:
        rate = n_merged / n_closed
        friendliness = rate * (0.5 + 0.5 * min(1.0, n_merged / 5))  # trust the rate more with more merges
    return {"external_prs_closed": n_closed, "external_prs_merged": n_merged,
            "merge_friendliness": round(friendliness, 4)}


def open_starter_issues(client: GitHubClient, full_name: str, limit: int = 3,
                        max_age_days: int = 730) -> list[dict[str, Any]]:
    """Unassigned, not-ancient beginner/help-wanted issues -- an issue nobody
    has touched in years is more likely abandoned than waiting for you."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen: set[int] = set()
    issues: list[dict[str, Any]] = []
    for label in ISSUE_LABELS:
        for issue in client.list_open_issues(full_name, label, per_page=10):
            if issue.get("number") in seen or issue.get("assignee") or issue.get("assignees"):
                continue
            if (issue.get("updated_at") or cutoff) < cutoff:
                continue
            seen.add(issue.get("number"))
            issues.append({
                "title": issue.get("title") or "",
                "url": issue.get("html_url") or "",
                "labels": [lb.get("name") for lb in issue.get("labels") or [] if isinstance(lb, dict)],
                "comments": issue.get("comments", 0),
            })
    issues.sort(key=lambda i: i["comments"])  # quieter issues are less likely to already be in progress
    return issues[:limit]


def _reasons(fit: dict[str, float], stats: dict[str, Any], issues: list[dict[str, Any]],
             repo: dict[str, Any]) -> list[str]:
    reasons = []
    if fit["content_similarity"] >= 0.5:
        reasons.append("strong match to your CV/repos/publications")
    elif fit["content_similarity"] >= 0.2:
        reasons.append("related to your field")
    if fit["language_match"]:
        reasons.append(f"written in {repo.get('language')}, which you use")
    if stats["external_prs_merged"]:
        reasons.append(f"maintainers merged {stats['external_prs_merged']}/{stats['external_prs_closed']} "
                       "recent outside PRs")
    elif stats["external_prs_closed"]:
        reasons.append(f"0/{stats['external_prs_closed']} recent outside PRs merged -- check first")
    if issues:
        reasons.append(f"{len(issues)} unassigned starter issue(s) open")
    return reasons


def suggest_repositories(client: GitHubClient, cfg: MyGeekyConfig, self_profile: Profile,
                         vocabulary: dict[str, float], keyword_counts: dict[str, int] | None = None,
                         log: Callable[[str], None] = lambda _msg: None) -> list[dict[str, Any]]:
    terms = search_terms(cfg, self_profile, vocabulary, keyword_counts)
    if not terms:
        return []
    log(f"Searching repos for: {', '.join(terms)}")

    own = cfg.github_username.lower()
    pool: dict[str, dict[str, Any]] = {}
    matched_terms: dict[str, set[str]] = {}
    for query in build_repo_queries(cfg, terms):
        term = query.split(" in:", 1)[0].strip('"')
        for repo in client.search_repositories(query, per_page=30):
            full = repo.get("full_name")
            if not full or repo.get("archived") or repo.get("fork"):
                continue
            if ((repo.get("owner") or {}).get("login") or "").lower() == own:
                continue
            pool.setdefault(full, repo)
            matched_terms.setdefault(full, set()).add(term)
    if not pool:
        return []

    repos = list(pool.values())
    # a language from a single old repo isn't one you "use"
    languages = set(cfg.languages) | {lang for lang, n in self_profile.languages.items() if n >= 2}
    fits = fit_scores(self_profile.corpus, repos, languages)
    ranked = sorted(zip(repos, fits), key=lambda rf: rf[1]["fit"], reverse=True)
    log(f"{len(repos)} candidate repos; checking maintainers of the top {cfg.contribute_check_top_n}...")

    ts = datetime.now(timezone.utc).isoformat()
    results = []
    for repo, fit in ranked[: cfg.contribute_check_top_n]:
        full = repo["full_name"]
        stats = maintainer_stats(client.list_closed_pulls(full))
        issues = open_starter_issues(client, full)
        issue_score = min(1.0, len(issues) / 2)
        score = 0.45 * fit["fit"] + 0.35 * stats["merge_friendliness"] + 0.2 * issue_score
        results.append({
            "full_name": full,
            "repo_url": repo.get("html_url") or f"https://github.com/{full}",
            "fork_url": f"https://github.com/{full}/fork",
            "owner": (repo.get("owner") or {}).get("login", ""),
            "owner_avatar_url": (repo.get("owner") or {}).get("avatar_url", ""),
            "description": repo.get("description") or "",
            "language": repo.get("language") or "",
            "topics": repo.get("topics") or [],
            "stars": repo.get("stargazers_count", 0),
            "pushed_at": repo.get("pushed_at") or "",
            "score": round(score, 4),
            "fit": fit,
            "maintainers": stats,
            "starter_issues": issues,
            "matched_terms": sorted(matched_terms.get(full, ())),
            "reasons": _reasons(fit, stats, issues, repo),
            "timestamp": ts,
            "list": "contribute",
        })
    # what you've been engaging with lately nudges the order...
    from . import interests
    weights = interests.profile_terms(cfg)
    for r in results:
        boost, _ = interests.match(" ".join([r["full_name"], r["description"], " ".join(r["topics"])]), weights)
        r["score"] = round(r["score"] + 0.15 * boost, 4)
    results.sort(key=lambda r: r["score"], reverse=True)
    # ...and some places stay open for repos found through today's exploration terms
    explore = set(interests.explore_terms(cfg, 1))
    pool = [r for r in results if explore & set(r["matched_terms"])]
    mixed = interests.mix([r for r in results if r not in pool], cfg.contribute_max_returned, cfg,
                          explore_pool=pool or None)
    return mixed
