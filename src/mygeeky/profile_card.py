"""A person at a glance: what you see when you click someone, before (maybe)
opening their GitHub profile to follow them.

Four read-only calls: the profile, their repos, their recent public events and
their linked accounts. From those: their two most recently active repos, their
most-starred repo, a 30-day activity chart, their interests (repo topics and
languages), and their links elsewhere (LinkedIn, Facebook, ORCID, Google
Scholar, X, a website), each only if they've put it on GitHub.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

API = "https://api.github.com"
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
ORCID_RE = re.compile(r"\b(\d{4}-\d{4}-\d{4}-\d{3}[\dX])\b")
DAYS = 30
_cache: dict[str, tuple[float, dict[str, Any]]] = {}     # login -> (time, card), for this session
CACHE_SECONDS = 3600

# where a link points -> the icon kind the apps draw
LINK_KINDS = [
    ("orcid", re.compile(r"(^|//|\.)orcid\.org/", re.I)),
    ("scholar", re.compile(r"scholar\.google\.", re.I)),
    ("linkedin", re.compile(r"(^|//|\.)linkedin\.com/", re.I)),
    ("facebook", re.compile(r"(^|//|\.)(facebook|fb)\.com/", re.I)),
    ("x", re.compile(r"(^|//|\.)(twitter|x)\.com/", re.I)),
    ("researchgate", re.compile(r"researchgate\.net/", re.I)),
]


class CardError(RuntimeError):
    pass


def _get(path: str, token: str | None, params: dict | None = None) -> Any:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(f"{API}{path}", headers=headers, params=params, timeout=20)
    if r.status_code == 404:
        raise CardError("GitHub doesn't know this account (renamed or deleted?).")
    if r.status_code in (403, 429):
        raise CardError("GitHub asks us to slow down. Try again in a few minutes.")
    r.raise_for_status()
    return r.json()


def kind_of(url: str) -> str:
    for kind, pat in LINK_KINDS:
        if pat.search(url or ""):
            return kind
    return "web"


def links(user: dict[str, Any], socials: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Their links elsewhere, one per kind, https only."""
    found: dict[str, str] = {}

    def add(url: str) -> None:
        url = (url or "").strip()
        if not url:
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        found.setdefault(kind_of(url), url)
    for s in socials or []:
        add(s.get("url", ""))
    if user.get("twitter_username"):
        found.setdefault("x", f"https://x.com/{user['twitter_username']}")
    add(user.get("blog") or "")
    m = ORCID_RE.search(user.get("bio") or "")
    if m:
        found.setdefault("orcid", f"https://orcid.org/{m.group(1)}")
    order = ["linkedin", "orcid", "scholar", "researchgate", "facebook", "x", "web"]
    return [{"kind": k, "url": found[k]} for k in order if k in found]


def daily(events: list[dict[str, Any]], days: int = DAYS, now: datetime | None = None) -> list[int]:
    """Public events per day, oldest first, the last `days` days."""
    now = now or datetime.now(timezone.utc)
    start = (now - timedelta(days=days - 1)).date()
    counts = [0] * days
    for e in events:
        try:
            d = datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")).date()
        except (KeyError, ValueError, AttributeError):
            continue
        i = (d - start).days
        if 0 <= i < days:
            counts[i] += 1
    return counts


def interests(repos: list[dict[str, Any]], n: int = 8) -> list[str]:
    """What they work on: their repos' topics (most-used first), then languages."""
    topics: Counter = Counter()
    langs: Counter = Counter()
    for r in repos:
        if r.get("fork"):
            continue
        for t in r.get("topics") or []:
            topics[t.replace("-", " ")] += 1
        if r.get("language"):
            langs[r["language"]] += 1
    out = [t for t, _ in topics.most_common(n)]
    out += [lang for lang, _ in langs.most_common(4) if lang not in out]
    return out[:n]


def _repo(r: dict[str, Any]) -> dict[str, Any]:
    return {"name": r.get("name", ""), "full_name": r.get("full_name", ""), "url": r.get("html_url", ""),
            "description": (r.get("description") or "")[:160], "stars": r.get("stargazers_count", 0),
            "language": r.get("language") or "", "pushed_at": r.get("pushed_at") or ""}


def build(user: dict[str, Any], repos: list[dict[str, Any]], events: list[dict[str, Any]],
          socials: list[dict[str, Any]]) -> dict[str, Any]:
    own = [r for r in repos if not r.get("fork")]
    active = sorted(own, key=lambda r: r.get("pushed_at") or "", reverse=True)[:2]
    top = max(own, key=lambda r: r.get("stargazers_count", 0), default=None)
    return {
        "login": user.get("login", ""), "name": user.get("name") or "", "avatar": user.get("avatar_url", ""),
        "bio": (user.get("bio") or "").strip()[:300], "company": (user.get("company") or "").strip(),
        "location": (user.get("location") or "").strip(), "followers": user.get("followers", 0),
        "following": user.get("following", 0), "public_repos": user.get("public_repos", 0),
        "since": (user.get("created_at") or "")[:4], "url": user.get("html_url") or f"https://github.com/{user.get('login', '')}",
        "active": [_repo(r) for r in active],
        "top": _repo(top) if top and top.get("stargazers_count", 0) > 0 else None,
        "daily": daily(events), "interests": interests(own), "links": links(user, socials),
    }


def fetch(login: str, token: str | None = None) -> dict[str, Any]:
    if not LOGIN_RE.match(login or ""):
        raise CardError("That isn't a GitHub username.")
    hit = _cache.get(login.lower())
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    user = _get(f"/users/{login}", token)
    repos = _get(f"/users/{login}/repos", token, {"per_page": 100, "sort": "pushed", "type": "owner"})
    try:
        events = _get(f"/users/{login}/events/public", token, {"per_page": 100})
    except (CardError, requests.RequestException):
        events = []
    try:
        socials = _get(f"/users/{login}/social_accounts", token)
    except (CardError, requests.RequestException):
        socials = []
    card = build(user, repos if isinstance(repos, list) else [], events if isinstance(events, list) else [],
                 socials if isinstance(socials, list) else [])
    _cache[login.lower()] = (time.time(), card)
    return card
