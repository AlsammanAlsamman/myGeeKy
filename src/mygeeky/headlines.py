"""Headlines: what's happening across your work, as titles only.

The News tab's papers and discussions go deep; headlines go wide. Every few
hours myGeeKy reads the public RSS/Atom feeds of AI labs, science journals and
the tech press, and keeps just the titles, ranked by YOUR model
(interests.profile_terms: your topics and keywords with their meanings, your
CV and papers, and what you've been clicking lately):

  * "for you": headlines that match your interests, newest and closest first;
  * the big picture: the newest headlines that don't match (🌍), so you still
    hear about the big things -- `explore_share` of the list, and always a few
    from AI (`headlines_ai_min`), since AI is touching every field.

No keys, no accounts; nothing about you is sent anywhere (these are plain feed
downloads). Every feed is someone else's text: titles are size-capped and shown
as plain text, and a link is only kept if it points at that feed's own site.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from . import interests
from .config import HEADLINES_FILE, MyGeekyConfig, ensure_dirs
from .files import write_json

UA = {"User-Agent": "mygeeky-headlines (https://github.com/mygeeky/myGeeKy)"}
MAX_FEED_BYTES = 3 * 1024 * 1024
PER_FEED = 40
CATEGORIES = {"ai": "AI", "science": "Science", "tech": "Tech"}

# (id, label, category, url, hosts its links may point to)
FEEDS: list[tuple[str, str, str, str, tuple[str, ...]]] = [
    ("mittr-ai", "MIT Tech Review", "ai", "https://www.technologyreview.com/topic/artificial-intelligence/feed",
     ("www.technologyreview.com",)),
    ("huggingface", "Hugging Face", "ai", "https://huggingface.co/blog/feed.xml", ("huggingface.co",)),
    ("google-ai", "Google AI", "ai", "https://blog.google/technology/ai/rss/", ("blog.google",)),
    ("deepmind", "Google DeepMind", "ai", "https://deepmind.google/blog/rss.xml", ("deepmind.google",)),
    ("openai", "OpenAI", "ai", "https://openai.com/news/rss.xml", ("openai.com",)),
    ("verge-ai", "The Verge", "ai", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
     ("www.theverge.com",)),
    ("techcrunch-ai", "TechCrunch", "ai", "https://techcrunch.com/category/artificial-intelligence/feed/",
     ("techcrunch.com",)),
    ("nature", "Nature", "science", "https://www.nature.com/nature.rss", ("www.nature.com",)),
    ("nature-genetics", "Nature Genetics", "science", "https://www.nature.com/ng.rss", ("www.nature.com",)),
    ("nature-biotech", "Nature Biotechnology", "science", "https://www.nature.com/nbt.rss", ("www.nature.com",)),
    ("science", "Science", "science", "https://www.science.org/rss/news_current.xml", ("www.science.org",)),
    ("quanta", "Quanta", "science", "https://www.quantamagazine.org/feed/", ("www.quantamagazine.org",)),
    ("ars-science", "Ars Technica", "science", "https://feeds.arstechnica.com/arstechnica/science",
     ("arstechnica.com",)),
    ("sciencedaily", "ScienceDaily", "science", "https://www.sciencedaily.com/rss/top/science.xml",
     ("www.sciencedaily.com",)),
    ("ars-tech", "Ars Technica", "tech", "https://feeds.arstechnica.com/arstechnica/technology-lab",
     ("arstechnica.com",)),
    ("github-blog", "GitHub", "tech", "https://github.blog/feed/", ("github.blog",)),
    ("register", "The Register", "tech", "https://www.theregister.com/headlines.atom", ("www.theregister.com",)),
]
ALLOWED_HOSTS = {h for *_, hosts in FEEDS for h in hosts}

_ATOM = "{http://www.w3.org/2005/Atom}"
_RSS1 = "{http://purl.org/rss/1.0/}"
_DC = "{http://purl.org/dc/elements/1.1/}"


_TAG = re.compile(r"<[^>]{0,200}>")


def _clip(text: Any, n: int) -> str:
    """Plain text: tags dropped, entities decoded (some feeds escape twice)."""
    t = str(text or "")
    for _ in range(2):
        t = html.unescape(_TAG.sub(" ", t))
    return " ".join(t.split())[:n]


def allowed_link(url: Any, hosts: tuple[str, ...] | set[str] = ALLOWED_HOSTS) -> bool:
    if not isinstance(url, str):
        return False
    parts = urlparse(url)
    return parts.scheme == "https" and parts.hostname in hosts and not parts.username


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        ts = parsedate_to_datetime(value)                  # RSS: "Wed, 07 Oct 2026 14:00:00 GMT"
    except (TypeError, ValueError, IndexError):
        try:
            ts = datetime.fromisoformat(value.replace("Z", "+00:00"))   # Atom / dc:date
        except ValueError:
            return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _text(el, *names: str) -> str:
    for name in names:
        found = el.find(name)
        if found is not None and (found.text or "").strip():
            return found.text
    return ""


def parse_feed(xml: bytes, feed: tuple[str, str, str, str, tuple[str, ...]]) -> list[dict[str, Any]]:
    """Headlines from one RSS 2.0 / RSS 1.0 / Atom feed (untrusted input)."""
    fid, label, category, _, hosts = feed
    root = ET.fromstring(xml)
    entries = root.findall(".//item") or root.findall(f".//{_ATOM}entry") or root.findall(f".//{_RSS1}item")
    out = []
    for e in entries:
        title = _clip(_text(e, "title", f"{_ATOM}title", f"{_RSS1}title"), 180)
        link = _text(e, "link", f"{_RSS1}link").strip()
        if not link:
            atom_link = next((l for l in e.findall(f"{_ATOM}link") if l.get("rel") in (None, "alternate")), None)
            link = (atom_link.get("href") if atom_link is not None else "") or ""
        when = _date(_text(e, "pubDate", f"{_ATOM}published", f"{_ATOM}updated", f"{_DC}date"))
        if not title or not allowed_link(link, hosts) or when is None:
            continue
        summary = _clip(_text(e, "description", f"{_ATOM}summary", f"{_RSS1}description"), 400)
        out.append({"id": hashlib.sha1(link.encode()).hexdigest()[:16], "title": title, "link": link,
                    "source": label, "feed": fid, "category": category, "published": when.isoformat(),
                    "summary": summary})
    out.sort(key=lambda x: x["published"], reverse=True)
    return out[:PER_FEED]


def fetch(feed, session: requests.Session) -> list[dict[str, Any]]:
    r = session.get(feed[3], headers=UA, timeout=20)
    r.raise_for_status()
    if len(r.content) > MAX_FEED_BYTES:
        raise ValueError("feed too large")
    return parse_feed(r.content, feed)


# --------------------------------------------------------------------------- ranking with your model
def _age_days(item: dict[str, Any], now: datetime) -> float:
    try:
        return max((now - datetime.fromisoformat(item["published"])).total_seconds() / 86400, 0)
    except (KeyError, ValueError):
        return 7.0


def rank(items: list[dict[str, Any]], weights: dict[str, float], now: datetime) -> list[dict[str, Any]]:
    out = []
    for it in items:
        relevance, matched = interests.match(f"{it['title']} {it.get('summary', '')[:300]}", weights)
        if len(matched) < 2 and not any(" " in m for m in matched):   # one generic word isn't evidence
            relevance *= 0.3
        out.append({**it, "score": round(relevance * math.exp(-_age_days(it, now) / 3), 4), "match": matched})
    return sorted(out, key=lambda x: x["score"], reverse=True)


def strong_match(item: dict[str, Any], weights: dict[str, float]) -> bool:
    """Real evidence it's about your work: two of your terms, a multi-word one,
    or one you chose yourself (a topic or keyword). One stray word from your
    CV -- "link", "response" -- isn't."""
    matched = item.get("match") or []
    return len(matched) >= 2 or any(" " in m for m in matched) or any(weights.get(m, 0) >= 0.9 for m in matched)


def _big_picture(items: list[dict[str, Any]], exclude: set[str]) -> list[dict[str, Any]]:
    """The newest headlines you weren't matched with, taking turns across AI,
    science and tech so no one area crowds out the others."""
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for it in sorted(items, key=lambda x: x["published"], reverse=True):
        if it["id"] not in exclude:
            by_cat.setdefault(it["category"], []).append(it)
    out, i = [], 0
    while any(i < len(v) for v in by_cat.values()):
        out += [v[i] for v in by_cat.values() if i < len(v)]
        i += 1
    return out


def select(items: list[dict[str, Any]], cfg: MyGeekyConfig, weights: dict[str, float],
           now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    fresh = [x for x in items if _age_days(x, now) <= cfg.headlines_days]
    seen_titles: set[str] = set()
    unique = []
    for x in sorted(fresh, key=lambda x: x["published"], reverse=True):   # the same story from two feeds
        key = x["title"].lower()
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(x)
    ranked = [x for x in rank(unique, weights, now) if x["score"] > 0 and strong_match(x, weights)]
    n = cfg.headlines_size
    picks = interests.mix(ranked, n, cfg, explore_pool=_big_picture(unique, {x["id"] for x in ranked[:n]})[:n])
    taken = {x["id"] for x in picks}
    big = [x for x in _big_picture(unique, taken)]
    ai_have = sum(1 for x in picks if x["category"] == "ai")
    for x in [b for b in big if b["category"] == "ai"][:max(0, cfg.headlines_ai_min - ai_have)]:
        picks.append(dict(x, explore=True))
        taken.add(x["id"])
    for x in big:                             # a narrow model still gets a full list
        if len(picks) >= n:
            break
        if x["id"] not in taken:
            picks.append(dict(x, explore=True))
            taken.add(x["id"])
    for x in picks:
        x.pop("summary", None)                # titles only, as promised
        x.setdefault("match", [])
    return picks[: max(n, len(picks))]


# --------------------------------------------------------------------------- state
def load_state() -> dict[str, Any]:
    try:
        return json.loads(HEADLINES_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    ensure_dirs()
    write_json(HEADLINES_FILE, state)


def refresh_due(cfg: MyGeekyConfig, state: dict[str, Any], now: datetime | None = None) -> bool:
    try:
        age = (now or datetime.now(timezone.utc)) - datetime.fromisoformat(state["updated_at"])
    except (KeyError, ValueError, TypeError):
        return True
    return age >= timedelta(hours=cfg.headlines_refresh_hours)


def refresh(cfg: MyGeekyConfig, force: bool = False, log: Callable[[str], None] = lambda m: None,
            session: requests.Session | None = None) -> dict[str, Any]:
    state = load_state()
    if not cfg.headlines_enabled or (not force and not refresh_due(cfg, state)):
        return state
    session = session or requests.Session()
    found, errors = [], []
    for feed in FEEDS:
        if feed[2] not in cfg.headlines_categories:
            continue
        try:
            found += fetch(feed, session)
        except Exception as exc:          # one feed down mustn't empty the list
            errors.append(feed[1])
            log(f"headlines: {feed[1]} failed ({exc})")
    items = select(found, cfg, interests.profile_terms(cfg))
    new = {"updated_at": datetime.now(timezone.utc).isoformat(), "items": items, "errors": sorted(set(errors))}
    if items or not state.get("items"):
        save_state(new)
    log(f"headlines: {len(items)} ({sum(1 for i in items if not i.get('explore'))} for you)")
    return new if items or not state.get("items") else {**state, "errors": new["errors"]}
