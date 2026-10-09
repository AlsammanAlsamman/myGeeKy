"""News for your field: new preprints and discussions matching your interests.

Free, open, constantly updated sources -- no keys, no accounts:
  - arXiv's API: new preprints (CS, AI, statistics, quantitative biology, ...),
    searched for your top interest terms;
  - bioRxiv's API: the last days' biology preprints, filtered by your terms;
  - Hacker News (Algolia's search API): stories developers are discussing.

Ranked by how well each matches your interests (interests.profile_terms:
your CV, papers, topics and what you've been clicking lately) and by how new
it is. `explore_share` of the list is "new territory": today's exploration
terms plus the Hacker News front page, so you also see what's outside your
bubble. Only your search terms are sent to these services.

Everything that comes back is someone else's text: titles and summaries are
size-capped and shown as plain text; links are rebuilt from validated ids.
"""

from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import requests

from . import interests
from .config import NEWS_FILE, MyGeekyConfig, ensure_dirs
from .files import write_json

ARXIV_API = "https://export.arxiv.org/api/query"
BIORXIV_API = "https://api.biorxiv.org/details/biorxiv/{start}/{end}/{cursor}/json"
HN_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
HN_FRONT = "https://hn.algolia.com/api/v1/search"
UA = {"User-Agent": "mygeeky-news (https://github.com/mygeeky/myGeeKy)"}
SOURCE_LABELS = {"arxiv": "arXiv", "biorxiv": "bioRxiv", "hackernews": "Hacker News"}

_ARXIV_ID = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$|^[a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?$")
_DOI = re.compile(r"^10\.\d{4,9}/[\w.\-]+$")


def _clip(text: Any, n: int) -> str:
    return " ".join(str(text or "").split())[:n]


def _when(value: str) -> str:
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        try:
            ts = datetime.strptime(value[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            return ""
    return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).isoformat()


# --------------------------------------------------------------------------- sources
def fetch_arxiv(terms: list[str], session: requests.Session, max_results: int = 40) -> list[dict[str, Any]]:
    if not terms:
        return []
    query = " OR ".join(f'all:"{t}"' if " " in t else f"all:{t}" for t in terms[:6])
    r = session.get(ARXIV_API, params={"search_query": query, "sortBy": "submittedDate",
                                       "sortOrder": "descending", "max_results": max_results},
                    headers=UA, timeout=30)
    r.raise_for_status()
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in ET.fromstring(r.content).findall("a:entry", ns):
        raw_id = (e.findtext("a:id", "", ns) or "").rsplit("/abs/", 1)[-1]
        if not _ARXIV_ID.match(raw_id):
            continue
        out.append({"source": "arxiv", "id": f"arxiv:{raw_id}", "title": _clip(e.findtext("a:title", "", ns), 220),
                    "summary": _clip(e.findtext("a:summary", "", ns), 400),
                    "published": _when(e.findtext("a:published", "", ns)),
                    "url": f"https://arxiv.org/abs/{raw_id}"})
    return out


def fetch_biorxiv(days: int, session: requests.Session, pages: int = 3) -> list[dict[str, Any]]:
    end = date.today()
    start = end - timedelta(days=min(days, 3))     # bioRxiv publishes hundreds a day: the last few are plenty
    out = []
    for cursor in range(0, pages * 100, 100):
        r = session.get(BIORXIV_API.format(start=start, end=end, cursor=cursor), headers=UA, timeout=30)
        r.raise_for_status()
        items = r.json().get("collection") or []
        for it in items:
            doi = str(it.get("doi") or "")
            if not _DOI.match(doi):
                continue
            version = str(it.get("version") or "1")
            out.append({"source": "biorxiv", "id": f"biorxiv:{doi}", "title": _clip(it.get("title"), 220),
                        "summary": _clip(it.get("abstract"), 400), "published": _when(str(it.get("date"))),
                        "url": f"https://www.biorxiv.org/content/{doi}v{version if version.isdigit() else '1'}",
                        "category": _clip(it.get("category"), 60)})
        if len(items) < 100:
            break
    return out


def _hn_items(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for h in hits:
        oid = str(h.get("objectID") or "")
        if not oid.isdigit() or not h.get("title"):
            continue
        out.append({"source": "hackernews", "id": f"hn:{oid}", "title": _clip(h.get("title"), 220),
                    "summary": f"{int(h.get('points') or 0)} points · {int(h.get('num_comments') or 0)} comments",
                    "published": _when(str(h.get("created_at") or "")),
                    "url": f"https://news.ycombinator.com/item?id={oid}",
                    "story_url": _clip(h.get("url"), 300) if str(h.get("url") or "").startswith("https://") else ""})
    return out


def fetch_hackernews(terms: list[str], days: int, session: requests.Session) -> list[dict[str, Any]]:
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    out = []
    for term in terms[:3]:
        r = session.get(HN_SEARCH, params={"query": term, "tags": "story",
                                           "numericFilters": f"points>10,created_at_i>{since}"},
                        headers=UA, timeout=30)
        r.raise_for_status()
        out += _hn_items(r.json().get("hits") or [])
    return out


def fetch_hn_front(session: requests.Session) -> list[dict[str, Any]]:
    r = session.get(HN_FRONT, params={"tags": "front_page"}, headers=UA, timeout=30)
    r.raise_for_status()
    return _hn_items(r.json().get("hits") or [])


# --------------------------------------------------------------------------- ranking
def _age_days(item: dict[str, Any], now: datetime) -> float:
    try:
        return max((now - datetime.fromisoformat(item["published"])).total_seconds() / 86400, 0)
    except (KeyError, ValueError, TypeError):
        return 7.0


def rank(items: list[dict[str, Any]], weights: dict[str, float], now: datetime | None = None) -> list[dict[str, Any]]:
    """Relevance to your interests, faded by age (half a point every ~4 days)."""
    now = now or datetime.now(timezone.utc)
    seen, out = set(), []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        relevance, matched = interests.match(f"{it['title']} {it.get('summary', '')}", weights)
        # one generic word ("stress", "markers") isn't evidence: physics and finance use them too
        if len(matched) < 2 and not any(" " in m for m in matched):
            relevance *= 0.2
        score = relevance * math.exp(-_age_days(it, now) / 6)
        out.append({**it, "score": round(score, 4), "match": matched})
    return sorted(out, key=lambda x: x["score"], reverse=True)


# --------------------------------------------------------------------------- refresh
def load_state() -> dict[str, Any]:
    try:
        return json.loads(NEWS_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    ensure_dirs()
    write_json(NEWS_FILE, state)


def refresh_due(cfg: MyGeekyConfig, state: dict[str, Any], now: datetime | None = None) -> bool:
    try:
        age = (now or datetime.now(timezone.utc)) - datetime.fromisoformat(state["updated_at"])
    except (KeyError, ValueError, TypeError):
        return True
    return age.total_seconds() >= cfg.news_refresh_hours * 3600


def search_terms(cfg: MyGeekyConfig, weights: dict[str, float], n: int = 6) -> list[str]:
    """Your strongest, most specific interests: multi-word and rarer terms first."""
    ok = [t for t in weights if len(t) >= 4 and t not in interests.STOPWORDS]
    phrases = sorted((t for t in ok if " " in t), key=lambda t: weights[t], reverse=True)
    words = sorted((t for t in ok if " " not in t), key=lambda t: weights[t], reverse=True)
    return (phrases[: n - 2] + words)[:n]       # specific phrases first, then a couple of strong words


def refresh(cfg: MyGeekyConfig, force: bool = False, log: Callable[[str], None] = lambda m: None,
            session: requests.Session | None = None) -> dict[str, Any]:
    state = load_state()
    if not force and not refresh_due(cfg, state):
        return state
    session = session or requests.Session()
    weights = interests.profile_terms(cfg)
    terms = search_terms(cfg, weights)
    explore = interests.explore_terms(cfg, 2)
    found, explore_pool, errors = [], [], []

    def attempt(name: str, fn) -> list[dict[str, Any]]:
        try:
            return fn()
        except Exception as exc:          # one source down mustn't empty the whole feed
            errors.append(f"{SOURCE_LABELS.get(name, name)}: {type(exc).__name__}")
            log(f"news: {name} failed ({exc})")
            return []

    if "arxiv" in cfg.news_sources:
        found += attempt("arxiv", lambda: fetch_arxiv(terms, session))
        explore_pool += attempt("arxiv", lambda: fetch_arxiv(explore, session, max_results=10))
    if "biorxiv" in cfg.news_sources:
        found += attempt("biorxiv", lambda: fetch_biorxiv(cfg.news_days, session))
    if "hackernews" in cfg.news_sources:
        found += attempt("hackernews", lambda: fetch_hackernews(terms, cfg.news_days, session))
        explore_pool += attempt("hackernews", lambda: fetch_hn_front(session))

    ranked = [x for x in rank(found, weights) if x["score"] > 0]
    pool = [x for x in rank(explore_pool, {t: 1.0 for t in explore}) if x["id"] not in {r["id"] for r in ranked}]
    items = interests.mix(ranked, cfg.news_size, cfg, explore_pool=pool)
    state = {"updated_at": datetime.now(timezone.utc).isoformat(), "terms": terms, "explore_terms": explore,
             "items": items, "errors": errors}
    if items or not state.get("items"):
        save_state(state)
    log(f"news: {len(items)} items ({sum(1 for i in items if i.get('explore'))} to explore)")
    return state
