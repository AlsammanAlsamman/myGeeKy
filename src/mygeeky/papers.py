"""Research trends, and the papers behind GitHub repos.

Source: OpenAlex (https://openalex.org) -- a free, open index of the world's
scholarly papers, updated daily, no key needed.

Research trends (the Market tab's "Research" view, `mygeeky trends`):
  - Rising papers: recent papers in your field (matched on title and abstract
    to your interest terms), ranked by citations per month -- a hot
    three-month-old paper beats an old classic.
  - Tools with papers: recent papers in your field whose abstract links code
    on GitHub ("available at github.com/...").
  - People behind the trends: the authors who keep showing up.

Published repos (the green [P] badge): a repo whose CITATION.cff or README
names a DOI is matched to that paper on OpenAlex, with its citation count.

Everything that comes back is someone else's text: capped, validated (DOIs,
ORCIDs, GitHub names) and shown as plain text. Only your search terms and
DOIs are sent to OpenAlex.
"""

from __future__ import annotations

import base64
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import requests

from . import interests
from .config import PAPERS_CACHE_FILE, TRENDS_FILE, MyGeekyConfig, ensure_dirs

OPENALEX = "https://api.openalex.org/works"
UA = {"User-Agent": "mygeeky (https://github.com/AlsammanAlsamman/myGeeKy)"}
SELECT = "id,doi,title,publication_date,cited_by_count,authorships,primary_location,abstract_inverted_index,type"
PAPER_TTL_DAYS = 14

_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>()\]]+)", re.I)
_ORCID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
_OPENALEX_ID = re.compile(r"^[AW]\d+$")
_GH_REPO = re.compile(r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})", re.I)


def _clip(text: Any, n: int) -> str:
    return " ".join(str(text or "").split())[:n]


def abstract_text(work: dict[str, Any]) -> str:
    inv = work.get("abstract_inverted_index") or {}
    if not isinstance(inv, dict):
        return ""
    return " ".join(w for _, w in sorted((p, w) for w, ps in inv.items() for p in (ps or []) if isinstance(p, int)))


def github_repos_in(text: str) -> list[str]:
    out = []
    for owner, name in _GH_REPO.findall(text or ""):
        name = name.rstrip(".,;:")
        if name.lower().endswith(".git"):
            name = name[:-4]
        full = f"{owner}/{name}"
        if name and full.lower() not in {r.lower() for r in out}:
            out.append(full)
    return out


def clean_doi(doi: Any) -> str | None:
    m = _DOI.search(str(doi or ""))
    return m.group(1).rstrip(".,;") if m else None


def to_paper(work: dict[str, Any]) -> dict[str, Any] | None:
    """A validated, size-capped copy of an OpenAlex work."""
    if not isinstance(work, dict) or not work.get("title"):
        return None
    oa_id = str(work.get("id") or "").rsplit("/", 1)[-1]
    if not _OPENALEX_ID.match(oa_id):
        return None
    doi = clean_doi(work.get("doi"))
    authors = []
    ships = work.get("authorships") or []
    for a in (ships[:5] + ships[-1:] if len(ships) > 5 else ships):   # first five and the real last (senior) author
        au = (a or {}).get("author") or {}
        orcid = str(au.get("orcid") or "").rsplit("/", 1)[-1]
        au_id = str(au.get("id") or "").rsplit("/", 1)[-1]
        if not au.get("display_name"):
            continue
        authors.append({"name": _clip(au["display_name"], 60),
                        "orcid": orcid if _ORCID.match(orcid) else "",
                        "openalex": au_id if _OPENALEX_ID.match(au_id) else ""})
    abstract = abstract_text(work)
    source = ((work.get("primary_location") or {}).get("source") or {}) if isinstance(work.get("primary_location"), dict) else {}
    try:
        cited = int(work.get("cited_by_count") or 0)
    except (TypeError, ValueError):
        cited = 0
    return {
        "id": oa_id,
        "doi": doi or "",
        "url": f"https://doi.org/{doi}" if doi else f"https://openalex.org/{oa_id}",
        "title": _clip(work.get("title"), 240),
        "date": _clip(work.get("publication_date"), 10),
        "venue": _clip(source.get("display_name"), 80),
        "type": _clip(work.get("type"), 20),
        "cited": cited,
        "authors": authors,
        "abstract": _clip(abstract, 600),
        "repos": github_repos_in(abstract)[:3],
    }


def velocity(paper: dict[str, Any], today: date | None = None) -> float:
    """Citations per month since publication (at least one month)."""
    try:
        published = date.fromisoformat(paper["date"])
    except (KeyError, ValueError):
        return 0.0
    months = max(((today or date.today()) - published).days / 30.4, 1.0)
    return round(paper["cited"] / months, 2)


# --------------------------------------------------------------------------- OpenAlex queries
def search_works(filters: str, session: requests.Session, sort: str = "cited_by_count:desc",
                 per_page: int = 25) -> list[dict[str, Any]]:
    r = session.get(OPENALEX, params={"filter": filters, "sort": sort, "per-page": per_page, "select": SELECT},
                    headers=UA, timeout=30)
    r.raise_for_status()
    return [p for p in (to_paper(w) for w in r.json().get("results") or []) if p]


def _term_filter(term: str) -> str:
    term = term.replace('"', "").replace(",", " ").strip()
    return f'title_and_abstract.search:"{term}"' if " " in term else f"title_and_abstract.search:{term}"


def work_by_doi(doi: str, session: requests.Session) -> dict[str, Any] | None:
    r = session.get(f"{OPENALEX}/doi:{doi}", params={"select": SELECT}, headers=UA, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return to_paper(r.json())


# --------------------------------------------------------------------------- trends
def _relevant(paper: dict[str, Any], weights: dict[str, float]) -> tuple[float, list[str]]:
    score, hits = interests.match(f"{paper['title']} {paper['abstract']}", weights)
    if len(hits) < 2 and not any(" " in h for h in hits):   # one generic word isn't evidence
        score *= 0.2
    return score, hits


def people_behind(papers: list[dict[str, Any]], n: int = 8) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    count: Counter[str] = Counter()
    for p in papers:
        leads = p["authors"][:1] + p["authors"][-1:] if len(p["authors"]) > 1 else p["authors"]
        for a in leads:   # first (lead) and last (senior) authors, not a consortium's whole list
            key = a["orcid"] or a["openalex"] or a["name"].lower()
            count[key] += 1
            s = stats.setdefault(key, {**a, "papers": 0, "citations": 0})
            s["papers"] += 1
            s["citations"] += p["cited"]
    people = sorted(stats.values(), key=lambda s: (s["papers"], s["citations"]), reverse=True)
    for s in people:
        s["role"] = "leads" if s["papers"] > 1 else "lead or senior author"
    for s in people:
        s["url"] = (f"https://orcid.org/{s['orcid']}" if s["orcid"] else
                    f"https://openalex.org/{s['openalex']}" if s["openalex"] else "")
    return people[:n]


def load_trends() -> dict[str, Any]:
    try:
        return json.loads(TRENDS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def trends_due(cfg: MyGeekyConfig, state: dict[str, Any], now: datetime | None = None) -> bool:
    try:
        age = (now or datetime.now(timezone.utc)) - datetime.fromisoformat(state["updated_at"])
    except (KeyError, ValueError, TypeError):
        return True
    return age.total_seconds() >= cfg.trends_refresh_hours * 3600


_TOPIC_ID = re.compile(r"^T\d+$")


def _topic_id(raw: Any) -> str | None:
    tid = str(raw or "").rsplit("/", 1)[-1]
    return tid if _TOPIC_ID.match(tid) else None


def your_topics(cfg: MyGeekyConfig, session: requests.Session, n: int = 6) -> list[dict[str, str]]:
    """Your research topics as OpenAlex topic ids: from your OpenAlex author
    record when you gave an ORCID (most precise), then your stated topics,
    Scholar interests and what you've been engaging with lately, each looked
    up by name."""
    from . import scholar
    profile = scholar.load_scholar_profile() or {}
    topics: list[dict[str, str]] = []
    author = str(((profile.get("openalex") or {}).get("author_id")) or "").rsplit("/", 1)[-1]
    if _OPENALEX_ID.match(author):
        r = session.get(f"https://api.openalex.org/authors/{author}", params={"select": "topics"},
                        headers=UA, timeout=30)
        if r.status_code == 200:
            for t in (r.json().get("topics") or [])[:n]:
                tid = _topic_id(t.get("id"))
                if tid:
                    topics.append({"id": tid, "name": _clip(t.get("display_name"), 80)})
    names = list(cfg.topics) + list(((profile.get("google_scholar") or {}).get("interests")) or [])
    names += [t for t, _ in interests.learned_terms(cfg, 3)]
    for name in names:
        if len(topics) >= n:
            break
        r = session.get("https://api.openalex.org/topics", params={"search": name, "per-page": 1},
                        headers=UA, timeout=30)
        if r.status_code != 200:
            continue
        for t in (r.json().get("results") or [])[:1]:
            tid = _topic_id(t.get("id"))
            if tid and tid not in {x["id"] for x in topics}:
                topics.append({"id": tid, "name": _clip(t.get("display_name"), 80)})
    return topics[:n]


def refresh_trends(cfg: MyGeekyConfig, force: bool = False, log: Callable[[str], None] = lambda m: None,
                   session: requests.Session | None = None) -> dict[str, Any]:
    state = load_trends()
    if not force and not trends_due(cfg, state):
        return state
    session = session or requests.Session()
    weights = interests.profile_terms(cfg)
    since = (date.today() - timedelta(days=int(cfg.trends_months * 30.4))).isoformat()
    base = f",from_publication_date:{since},type:article|preprint"
    topics = your_topics(cfg, session)
    if topics:
        field = "primary_topic.id:" + "|".join(t["id"] for t in topics)
        log(f"trends: {len(topics)} research topics")
        found = search_works(field + base, session, per_page=50)
        tools_raw = search_works(field + ",title_and_abstract.search:github" + base, session,
                                 sort="cited_by_count:desc", per_page=50)
    else:   # no topics known yet: fall back to your strongest interest phrases
        from .news import search_terms
        found, tools_raw = [], []
        for term in search_terms(cfg, weights, n=3):
            found += search_works(_term_filter(term) + base, session)
            tools_raw += search_works(_term_filter(term) + " github" + base, session)
    unique = {p["id"]: p for p in found}
    rising = []
    for p in unique.values():
        relevance, hits = interests.match(f"{p['title']} {p['abstract']}", weights)
        boost = 0.5 + relevance if topics else (relevance if (len(hits) >= 2 or any(" " in h for h in hits)) else 0)
        if boost <= 0:
            continue
        rising.append({**p, "velocity": velocity(p), "match": hits, "score": round(velocity(p) * boost, 3)})
    rising.sort(key=lambda p: p["score"], reverse=True)
    explore_pool = []
    for term in interests.explore_terms(cfg, 1):
        for p in search_works(_term_filter(term) + base, session, per_page=10):
            explore_pool.append({**p, "velocity": velocity(p), "match": [term], "score": velocity(p)})
    rising = interests.mix(rising, cfg.trends_size, cfg,
                           explore_pool=sorted(explore_pool, key=lambda p: p["score"], reverse=True)[:5] or None)
    tools = {p["id"]: {**p, "velocity": velocity(p)} for p in tools_raw if p["repos"]}
    tool_list = sorted(tools.values(), key=lambda p: (p["velocity"], p["cited"]), reverse=True)[: cfg.trends_size]
    state = {"updated_at": datetime.now(timezone.utc).isoformat(), "topics": topics, "rising": rising,
             "tools": tool_list, "people": people_behind([p for p in rising if not p.get("explore")])}
    ensure_dirs()
    TRENDS_FILE.write_text(json.dumps(state), encoding="utf-8")
    # repos named in tool papers are published: remember that for the [P] badge
    cache = _load_cache()
    for p in tool_list:
        for repo in p["repos"]:
            cache[repo.lower()] = {"checked_at": state["updated_at"], "paper": _slim(p)}
    _save_cache(cache)
    return state


# --------------------------------------------------------------------------- the [P] badge
def _slim(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p[k] for k in ("title", "doi", "url", "date", "venue", "cited", "type")}


def _load_cache() -> dict[str, Any]:
    try:
        return json.loads(PAPERS_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict[str, Any]) -> None:
    ensure_dirs()
    PAPERS_CACHE_FILE.write_text(json.dumps(cache), encoding="utf-8")


def cached_paper(full_name: str) -> dict[str, Any] | None:
    return (_load_cache().get(full_name.lower()) or {}).get("paper")


def _repo_text_file(client, full_name: str, path: str) -> str:
    data = client.get_repo_file(full_name, path)
    if not data or data.get("encoding") != "base64" or (data.get("size") or 0) > 400_000:
        return ""
    try:
        return base64.b64decode(data.get("content") or "").decode("utf-8", "replace")
    except ValueError:
        return ""


def doi_for_repo(client, full_name: str) -> str | None:
    """The paper a repo asks you to cite: CITATION.cff's preferred-citation
    DOI (or its own DOI), else the first DOI in the README."""
    cff = _repo_text_file(client, full_name, "CITATION.cff")
    if cff:
        pref = re.search(r"preferred-citation:(.*)", cff, re.S)
        for text in ([pref.group(1)] if pref else []) + [cff]:
            m = re.search(r"^\s*doi:\s*['\"]?(10\.[^\s'\"]+)", text, re.M)
            if m:
                return m.group(1)
    readme = client.get_repo_file(full_name, "README.md")
    text = ""
    if readme and readme.get("encoding") == "base64" and (readme.get("size") or 0) <= 400_000:
        try:
            text = base64.b64decode(readme.get("content") or "").decode("utf-8", "replace")
        except ValueError:
            text = ""
    for m in _DOI.finditer(text):
        doi = m.group(1).rstrip(".,;)")
        if "zenodo" not in doi.lower() or not any("zenodo" not in d.group(1).lower() for d in _DOI.finditer(text)):
            return doi
    return None


def annotate_repos(client, names: list[str], max_lookups: int = 15,
                   session: requests.Session | None = None) -> dict[str, dict[str, Any]]:
    """{repo: paper} for the repos that have one; at most `max_lookups` new
    GitHub/OpenAlex lookups per call, everything else from a 14-day cache."""
    session = session or requests.Session()
    cache = _load_cache()
    now = datetime.now(timezone.utc)
    lookups = 0
    for name in names:
        entry = cache.get(name.lower())
        try:
            fresh = entry and now - datetime.fromisoformat(entry["checked_at"]) < timedelta(days=PAPER_TTL_DAYS)
        except (KeyError, ValueError, TypeError):
            fresh = False
        if fresh or lookups >= max_lookups:
            continue
        lookups += 1
        paper = None
        try:
            doi = doi_for_repo(client, name)
            if doi:
                p = work_by_doi(doi, session)
                paper = _slim(p) if p else {"title": "", "doi": doi, "url": f"https://doi.org/{doi}", "date": "",
                                             "venue": "", "cited": 0, "type": ""}
        except Exception:
            continue      # try again next time
        cache[name.lower()] = {"checked_at": now.isoformat(), "paper": paper}
    _save_cache(cache)
    return {n: cache[n.lower()]["paper"] for n in names if (cache.get(n.lower()) or {}).get("paper")}


def repo_people(client, full_name: str, n: int = 6) -> list[dict[str, Any]]:
    """The repo's owner and top human contributors -- who's working on it."""
    people, seen = [], set()
    repo = client.get_repo(full_name) or {}
    owner = repo.get("owner") or {}
    if owner.get("type") == "User" and owner.get("login"):
        people.append({"login": owner["login"], "avatar": owner.get("avatar_url", ""), "role": "owner"})
        seen.add(owner["login"].lower())
    for c in client.list_contributors(full_name, per_page=15):
        login = c.get("login") or ""
        if c.get("type") != "User" or not login or login.lower() in seen or login.endswith("[bot]"):
            continue
        seen.add(login.lower())
        people.append({"login": login, "avatar": c.get("avatar_url", ""),
                       "role": f"{c.get('contributions', 0)} commits"})
        if len(people) >= n:
            break
    return people
