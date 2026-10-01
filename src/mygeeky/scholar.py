"""Scholarly profile enrichment: ORCID + OpenAlex.

Both are free, open, read-only APIs that need no key:

- ORCID public API (pub.orcid.org) -- your self-declared keywords and the
  titles of works on your ORCID record.
- OpenAlex (api.openalex.org) -- looked up by the same ORCID iD; adds
  research topics and publication titles/abstracts.

Google Scholar is deliberately NOT used: it has no public API and actively
blocks automated access, so scraping it would be both fragile and against
its terms. OpenAlex indexes the same publications and is built for this.

The result is cached as JSON under the data dir (it's part of what
`mygeeky sync` carries between your machines), so normal runs don't
re-query either service -- `mygeeky profile refresh` does.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import requests

from .config import SCHOLAR_PROFILE_FILE, ensure_dirs

ORCID_API = "https://pub.orcid.org/v3.0"
OPENALEX_API = "https://api.openalex.org"
ORCID_RE = re.compile(r"\b(\d{4}-\d{4}-\d{4}-\d{3}[\dX])\b")
USER_AGENT = "mygeeky (https://github.com/AlsammanAlsamman/myGeeKy)"


def normalize_orcid(value: str) -> str:
    """Accept a bare iD or an orcid.org URL; return the bare iD, or "" if invalid."""
    m = ORCID_RE.search(value or "")
    return m.group(1) if m else ""


def find_orcid_in_text(text: str) -> str:
    """The first ORCID-shaped iD in a CV. CVs often list co-authors' iDs
    too, so this is only a suggestion for `init` to confirm, never trusted silently."""
    return normalize_orcid(text)


def _get_json(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None,
              timeout: int = 30) -> Any | None:
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    h.update(headers or {})
    try:
        resp = requests.get(url, params=params, headers=h, timeout=timeout)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def fetch_orcid(orcid: str) -> dict[str, Any]:
    keywords: list[str] = []
    titles: list[str] = []
    kw = _get_json(f"{ORCID_API}/{orcid}/keywords") or {}
    for k in kw.get("keyword") or []:
        if k.get("content"):
            keywords.append(k["content"])
    works = _get_json(f"{ORCID_API}/{orcid}/works") or {}
    for group in works.get("group") or []:
        for summary in (group.get("work-summary") or [])[:1]:
            title = ((summary.get("title") or {}).get("title") or {}).get("value")
            if title:
                titles.append(title)
    return {"keywords": keywords, "titles": titles}


def _abstract_from_inverted_index(inv: dict[str, list[int]] | None) -> str:
    if not inv:
        return ""
    positions: list[tuple[int, str]] = [(p, word) for word, ps in inv.items() for p in ps]
    return " ".join(word for _, word in sorted(positions))


def fetch_openalex(orcid: str, max_works: int = 100) -> dict[str, Any]:
    author = _get_json(f"{OPENALEX_API}/authors/orcid:{orcid}")
    if not author:
        return {"author_id": "", "topics": [], "works": []}
    author_id = (author.get("id") or "").rsplit("/", 1)[-1]
    topics = [t["display_name"] for t in author.get("topics") or [] if t.get("display_name")]
    data = _get_json(f"{OPENALEX_API}/works", params={
        "filter": f"author.id:{author_id}",
        "per-page": min(max_works, 200),
        "sort": "publication_year:desc",
        "select": "title,publication_year,abstract_inverted_index,keywords",
    }) or {}
    works = []
    for w in data.get("results") or []:
        works.append({
            "title": w.get("title") or "",
            "year": w.get("publication_year"),
            "abstract": _abstract_from_inverted_index(w.get("abstract_inverted_index")),
            "keywords": [k.get("display_name") for k in w.get("keywords") or [] if k.get("display_name")],
        })
    return {"author_id": author_id, "display_name": author.get("display_name", ""),
            "works_count": author.get("works_count", 0), "topics": topics, "works": works}


def refresh_scholar_profile(orcid: str) -> dict[str, Any]:
    """Fetch ORCID + OpenAlex for `orcid` and cache the combined result."""
    orcid = normalize_orcid(orcid)
    if not orcid:
        raise ValueError("Not a valid ORCID iD (expected e.g. 0000-0002-1825-0097).")
    profile = {
        "orcid": orcid,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "orcid_record": fetch_orcid(orcid),
        "openalex": fetch_openalex(orcid),
    }
    ensure_dirs()
    SCHOLAR_PROFILE_FILE.write_text(json.dumps(profile, indent=1), encoding="utf-8")
    return profile


def load_scholar_profile() -> dict[str, Any] | None:
    if not SCHOLAR_PROFILE_FILE.exists():
        return None
    try:
        return json.loads(SCHOLAR_PROFILE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def scholar_corpus(profile: dict[str, Any] | None) -> str:
    """Flatten the cached scholarly profile into free text for TF-IDF matching.
    Topics and keywords are repeated so they weigh more than incidental words."""
    if not profile:
        return ""
    orcid_rec = profile.get("orcid_record") or {}
    oa = profile.get("openalex") or {}
    parts: list[str] = []
    parts += (orcid_rec.get("keywords") or []) * 3
    parts += (oa.get("topics") or []) * 3
    oa_titles = set()
    for w in oa.get("works") or []:
        oa_titles.add((w.get("title") or "").lower())
        parts.append(w.get("title") or "")
        parts += w.get("keywords") or []
        if w.get("abstract"):
            parts.append(w["abstract"])
    # ORCID titles that OpenAlex didn't already cover
    parts += [t for t in orcid_rec.get("titles") or [] if t.lower() not in oa_titles]
    return "\n".join(p for p in parts if p)


def scholar_topics(profile: dict[str, Any] | None) -> list[str]:
    if not profile:
        return []
    return list((profile.get("orcid_record") or {}).get("keywords") or []) + \
        list((profile.get("openalex") or {}).get("topics") or [])


def scholar_keyword_counts(profile: dict[str, Any] | None) -> dict[str, int]:
    """How many of your publications carry each OpenAlex keyword (plus your
    ORCID keywords) -- concise, specific concepts that make good search terms."""
    if not profile:
        return {}
    counts: dict[str, int] = {}
    for w in (profile.get("openalex") or {}).get("works") or []:
        for k in w.get("keywords") or []:
            counts[k.lower()] = counts.get(k.lower(), 0) + 1
    for k in (profile.get("orcid_record") or {}).get("keywords") or []:
        counts[k.lower()] = counts.get(k.lower(), 0) + 3
    return counts
