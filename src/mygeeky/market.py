"""A "stock race" of the popular, active repos in your field.

Not repos for you to contribute to (that's `contribute`) -- the projects
your field runs on, ranked by momentum like a market board: stars gained,
commits, PyPI downloads and how those are trending.

Data sources, all read-only:
  - GitHub repo search, seeded by the same CV/ORCID/repo terms as the rest
    of myGeeKy, picks the watchlist (re-picked weekly; `market_pinned` repos
    always stay on it).
  - GitHub repo info (stars, forks, last push) is snapshotted once a day.
    GitHub has no star history for normal tokens, so star momentum builds
    up from these snapshots -- "collecting" until there are a few days.
  - GitHub `stats/commit_activity` gives 52 weeks of commits at once.
  - pypistats.org gives ~180 days of real (mirrors excluded) PyPI
    downloads at once, for repos that publish a matching PyPI package.

Ranking is a weighted average of each repo's percentile on the signals it
actually has, so a tool that isn't on PyPI (PLINK, GCTA, ...) isn't pushed
down for lacking downloads.
"""

from __future__ import annotations

import json
import math
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable

import requests

from .config import MARKET_FILE, MyGeekyConfig
from .github_client import GitHubClient

PYPISTATS = "https://pypistats.org/api/packages/{}/overall"
PYPI_JSON = "https://pypi.org/pypi/{}/json"

# share of the momentum score; renormalized over the signals a repo has
WEIGHTS = {
    "stars_week": 0.25,
    "commits_4w": 0.25,
    "downloads_week": 0.2,
    "downloads_change": 0.15,
    "stars": 0.15,
}


# --------------------------------------------------------------------------- state
def load_state() -> dict[str, Any]:
    if not MARKET_FILE.exists():
        return {}
    try:
        return json.loads(MARKET_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    MARKET_FILE.parent.mkdir(parents=True, exist_ok=True)
    MARKET_FILE.write_text(json.dumps(state), encoding="utf-8")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# --------------------------------------------------------------------------- watchlist
# collections and learning material rank high on stars but aren't software the field runs on
_NOT_SOFTWARE = re.compile(r"\bawesome\b|curated|\blist of\b|\bcourses?\b|tutorials?\b|lecture|portfolio|"
                           r"job[- ]search|cheat ?sheet|interview|roadmap|datasets? for|introduction to", re.I)


# assistants/agents borrow field words loosely ("genome config", "bioinformatics skills")
_AI_TOOLING = re.compile(r"\b(agents?|agentic|claude|llm|coding assistant|prompts?|skills)\b", re.I)


def _term_pattern(term: str) -> re.Pattern:
    words = [re.escape(w) for w in term.lower().replace("-", " ").split()]
    return re.compile(r"\b" + r"[\s_-]+".join(words), re.I)  # prefix match: "genotype" hits "genotypes"


def relevance(repo: dict[str, Any], terms: list[str]) -> float:
    """How clearly a repo belongs to your field: your terms in its own name
    or description count fully; its topics count by the share of them that
    are yours, so a repo listing "bioinformatics" among 20 unrelated tags
    stays out. A lone short term ("snp") needs backing -- "SEV-SNP" is not genetics."""
    if _NOT_SOFTWARE.search(f"{repo.get('full_name', '')} {repo.get('description') or ''}"):
        return 0.0
    own_text = f"{repo.get('full_name', '').replace('/', ' ')} {repo.get('description') or ''}"
    topics = [t.replace("-", " ") for t in repo.get("topics") or []]
    if {"awesome", "awesome list"} & set(topics):
        return 0.0
    patterns = [(t, _term_pattern(t)) for t in terms]
    own_hits = {t for t, pat in patterns if pat.search(own_text)}
    topic_hits = [x for x in topics if any(pat.search(x) for _, pat in patterns)]
    topic_share = len(topic_hits) / len(topics) if topics else 0.0
    if own_hits and all(len(t) <= 3 for t in own_hits) and len(own_hits) < 2 and topic_share < 0.25:
        return 0.0
    if not own_hits and topic_share < 0.25:
        return 0.0
    if len(own_hits) == 1 and topics and not topic_hits:
        return 0.0  # one word in passing, and none of its own tags agree
    score = len(own_hits) + 2 * topic_share
    if _AI_TOOLING.search(f"{own_text} {' '.join(topics)}") and score < 2:
        return 0.0
    return score


def discover_watchlist(client: GitHubClient, cfg: MyGeekyConfig, terms: list[str]) -> list[str]:
    """`owner/name` of the most-starred, recently-pushed repos that clearly
    belong to your field, found by searching your profile terms (as text
    and as GitHub topics)."""
    since = (datetime.now(timezone.utc) - timedelta(days=cfg.market_pushed_within_days)).strftime("%Y-%m-%d")
    filters = f"fork:false archived:false stars:>={cfg.market_min_stars} pushed:>{since}"
    match_terms = terms[: max(cfg.market_terms * 3, 20)]
    per_term: list[list[str]] = []
    for term in terms[: cfg.market_terms]:
        quoted = f'"{term}"' if " " in term else term
        slug = term.lower().replace(" ", "-")
        hits: dict[str, dict[str, Any]] = {}
        for query in (f"{quoted} in:name,description,topics {filters}", f"topic:{slug} {filters}"):
            for repo in client.search_repositories(query, max_pages=1, per_page=20, sort="stars"):
                if repo.get("full_name") and relevance(repo, match_terms) > 0:
                    hits[repo["full_name"]] = repo
        per_term.append([n for n in sorted(hits, key=lambda n: hits[n].get("stargazers_count", 0), reverse=True)])

    # take turns across your terms (most-evidenced first), so broad terms
    # like "genome" can't fill the board before "gwas" or "snp" get a seat
    pinned = [p for p in cfg.market_pinned if p]
    picked = list(pinned)
    seen = {p.lower() for p in pinned}
    size = max(cfg.market_size, len(pinned))
    depth = 0
    while len(picked) < size and any(depth < len(lst) for lst in per_term):
        for lst in per_term:
            if depth < len(lst) and lst[depth].lower() not in seen and len(picked) < size:
                seen.add(lst[depth].lower())
                picked.append(lst[depth])
        depth += 1
    return picked


def pypi_name_for(full_name: str, session: requests.Session | None = None) -> str | None:
    """The PyPI project published from this repo, if any. A candidate name
    only counts when its PyPI page links back to this exact repo, so a
    same-named stranger's package is never mixed in."""
    http = session or requests
    owner, repo = full_name.split("/", 1)
    repo_url = f"github.com/{full_name}".lower()
    for candidate in dict.fromkeys([repo, repo.lower(), repo.replace("_", "-"), owner]):
        try:
            resp = http.get(PYPI_JSON.format(candidate), timeout=20)
        except requests.RequestException:
            continue
        if resp.status_code != 200:
            continue
        info = resp.json().get("info") or {}
        links = [info.get("home_page") or "", info.get("download_url") or "",
                 *((info.get("project_urls") or {}).values())]
        if any(repo_url in (link or "").lower().rstrip("/").removesuffix(".git") for link in links):
            return info.get("name") or candidate
    return None


# --------------------------------------------------------------------------- daily snapshot
def _commit_weeks(client: GitHubClient, full_name: str) -> list[int] | None:
    # GitHub answers 202 while it computes the stats the first time
    for attempt in range(3):
        resp = client._get(f"/repos/{full_name}/stats/commit_activity")
        if resp.status_code == 200:
            return [w.get("total", 0) for w in resp.json()]
        if resp.status_code != 202:
            return None
        time.sleep(3 + 3 * attempt)
    return None


def _daily_downloads(package: str, session: requests.Session | None = None) -> list[list[Any]] | None:
    http = session or requests
    try:
        resp = http.get(PYPISTATS.format(package.lower()), params={"mirrors": "false"}, timeout=30)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    rows = [r for r in resp.json().get("data", []) if r.get("category") == "without_mirrors"]
    return [[r["date"], r["downloads"]] for r in sorted(rows, key=lambda r: r["date"])]


def refresh_market(client: GitHubClient, cfg: MyGeekyConfig, terms_fn: Callable[[], list[str]],
                   force: bool = False, log: Callable[[str], None] = lambda m: None) -> dict[str, Any]:
    """Re-pick the watchlist when it's a week old, then snapshot every repo
    at most once a day (or now, with `force`). Returns the saved state."""
    state = load_state()
    today = _today()
    picked_at = state.get("watchlist_at", "")
    stale = not state.get("watchlist") or picked_at < (date.today() - timedelta(days=7)).isoformat()
    if stale:
        log("picking the watchlist from your profile terms")
        state["watchlist"] = discover_watchlist(client, cfg, terms_fn())
        state["watchlist_at"] = today
    if not force and state.get("snapshot_date") == today:
        return state

    pypi = state.setdefault("pypi", {})
    repos = state.setdefault("repos", {})
    session = requests.Session()
    session.headers["User-Agent"] = "mygeeky-market"
    for full_name in state["watchlist"]:
        log(f"snapshot {full_name}")
        info = client._get(f"/repos/{full_name}")
        if info.status_code != 200:
            continue
        data = info.json()
        entry = repos.setdefault(full_name, {"stars": []})
        entry.update({
            "url": data.get("html_url", f"https://github.com/{full_name}"),
            "description": data.get("description") or "",
            "language": data.get("language") or "",
            "forks": data.get("forks_count", 0),
            "open_issues": data.get("open_issues_count", 0),
            "pushed_at": data.get("pushed_at", ""),
            "avatar": (data.get("owner") or {}).get("avatar_url", ""),
        })
        stars = [s for s in entry["stars"] if s[0] != today]
        stars.append([today, data.get("stargazers_count", 0)])
        entry["stars"] = stars[-120:]

        weeks = _commit_weeks(client, full_name)
        if weeks is not None:
            entry["commit_weeks"] = weeks

        if full_name not in pypi:  # looked up once, then remembered (None = not on PyPI)
            pypi[full_name] = pypi_name_for(full_name, session)
        if pypi[full_name]:
            downloads = _daily_downloads(pypi[full_name], session)
            if downloads is not None:
                entry["downloads"] = downloads[-90:]

    board = compute_board(state)
    history = state.setdefault("rank_history", {})
    history[today] = [row["repo"] for row in board]
    for old in sorted(history)[:-14]:
        del history[old]
    state["snapshot_date"] = today
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    return state


# --------------------------------------------------------------------------- board
def _stars_week(stars: list[list[Any]]) -> int | None:
    """Stars gained over the last ~7 days of snapshots; None while there is
    less than a day of history to compare against."""
    if len(stars) < 2:
        return None
    latest_day = date.fromisoformat(stars[-1][0])
    base = stars[0]
    for day, count in stars:
        if date.fromisoformat(day) >= latest_day - timedelta(days=7):
            base = [day, count]
            break
    if base[0] == stars[-1][0]:
        base = stars[-2]
    return stars[-1][1] - base[1]


def _percentiles(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values.values())
    n = len(ordered)
    if n == 1:
        return {k: 1.0 for k in values}
    return {k: sum(1 for x in ordered if x < v) / (n - 1) for k, v in values.items()}


def compute_board(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The ranked rows, best momentum first, with movement since the last day ranked."""
    rows: list[dict[str, Any]] = []
    pypi = state.get("pypi", {})
    for full_name in state.get("watchlist", []):
        entry = (state.get("repos") or {}).get(full_name)
        if not entry or not entry.get("stars"):
            continue
        weeks = entry.get("commit_weeks") or []
        downloads = [d[1] for d in entry.get("downloads") or []]
        week = sum(downloads[-7:]) if len(downloads) >= 7 else None
        prev_week = sum(downloads[-14:-7]) if len(downloads) >= 14 else None
        change = (week - prev_week) / prev_week if week is not None and prev_week else None
        commits_prev = sum(weeks[-8:-4]) if len(weeks) >= 8 else None
        if downloads:
            weekly = [sum(downloads[max(0, i - 7):i]) for i in range(len(downloads), 0, -7)][:12][::-1]
            spark, spark_kind = weekly, "downloads"
            trend = None if change is None else ("up" if change >= 0 else "down")
        else:
            spark, spark_kind = weeks[-12:], "commits"
            recent = sum(weeks[-4:]) if weeks else None
            trend = None if recent is None or commits_prev is None or recent == commits_prev                 else ("up" if recent > commits_prev else "down")
        rows.append({
            "repo": full_name,
            "url": entry.get("url", f"https://github.com/{full_name}"),
            "avatar": entry.get("avatar", ""),
            "description": entry.get("description", ""),
            "language": entry.get("language", ""),
            "stars": entry["stars"][-1][1],
            "stars_week": _stars_week(entry["stars"]),
            "commits_4w": sum(weeks[-4:]) if weeks else None,
            "pypi": pypi.get(full_name),
            "downloads_week": week,
            "downloads_change": change,
            "spark": spark,
            "spark_kind": spark_kind,
            "trend": trend,  # same comparison as the headline number, so line colour and % agree
            "pushed_at": entry.get("pushed_at", ""),
        })

    metric_pct = {m: _percentiles({r["repo"]: _signal(r, m) for r in rows if _signal(r, m) is not None})
                  for m in WEIGHTS}
    for r in rows:
        have = {m: metric_pct[m][r["repo"]] for m in WEIGHTS if r["repo"] in metric_pct[m]}
        total = sum(WEIGHTS[m] for m in have) or 1.0
        r["score"] = round(sum(WEIGHTS[m] * p for m, p in have.items()) / total, 4)
    rows.sort(key=lambda r: r["score"], reverse=True)

    history = state.get("rank_history") or {}
    today = state.get("snapshot_date") or _today()
    earlier = [d for d in sorted(history) if d < today]
    previous = history[earlier[-1]] if earlier else None
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
        if previous is None:
            r["movement"] = None
        elif r["repo"] in previous:
            r["movement"] = previous.index(r["repo"]) + 1 - i
        else:
            r["movement"] = "new"
    return rows


def _signal(row: dict[str, Any], metric: str) -> float | None:
    value = row.get(metric)
    if value is None:
        return None
    if metric in ("stars", "downloads_week", "commits_4w", "stars_week"):
        return math.log1p(max(value, 0))
    return float(value)


def top_movers(rows: Iterable[dict[str, Any]], n: int = 3) -> list[dict[str, Any]]:
    """Biggest climbers by rank movement, for a compact "movers" strip."""
    moved = [r for r in rows if isinstance(r.get("movement"), int) and r["movement"] > 0]
    return sorted(moved, key=lambda r: r["movement"], reverse=True)[:n]
