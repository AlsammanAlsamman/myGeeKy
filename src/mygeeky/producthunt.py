"""Product Hunt launches in your field, for the Market board.

Read-only. Without any setup, from Product Hunt's public feed (today's
featured launches). With a free developer token, through the official GraphQL
API (v2) instead, which adds upvotes and topics and reaches back further:
create an app at https://www.producthunt.com/v2/oauth/applications and copy
its "Developer Token" (`mygeeky auth producthunt` stores it in the OS keyring).

Product Hunt has no full-text search, so recent launches are pulled from a
few topics (`market_ph_topics`), then scored against the same profile terms
as the rest of the Market: launches that mention your field (name, tagline,
description or topics) come first, the rest follow by upvotes.

Everything that comes back is someone else's text: lengths are capped,
links are rebuilt from a validated slug, and the panel shows it as plain text.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import requests

from .config import PRODUCTHUNT_FILE, MyGeekyConfig, ensure_dirs
from .market import _term_pattern
from .files import write_json

API = "https://api.producthunt.com/v2/api/graphql"
FEED = "https://www.producthunt.com/feed"
_FEED_LINK = re.compile(r"^https://www\.producthunt\.com/(?:products|posts)/([a-z0-9][a-z0-9-]{0,120})(?:[/?#]|$)")
TOKEN_URL = "https://www.producthunt.com/v2/oauth/applications"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,120}$")

QUERY = """
query($topic: String, $after: DateTime, $cursor: String) {
  posts(order: VOTES, topic: $topic, postedAfter: $after, first: 20, after: $cursor) {
    edges { node {
      name tagline description slug votesCount commentsCount createdAt
      thumbnail { url }
      topics(first: 6) { edges { node { name slug } } }
    } }
    pageInfo { hasNextPage endCursor }
  }
}
"""


class ProductHuntError(RuntimeError):
    pass


def _clip(value: Any, n: int) -> str:
    return " ".join(str(value or "").split())[:n]


def clean_post(node: Any) -> dict[str, Any] | None:
    """A validated, size-capped copy of one API post, or None."""
    if not isinstance(node, dict):
        return None
    slug = node.get("slug")
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        return None
    thumb = ((node.get("thumbnail") or {}).get("url") or "") if isinstance(node.get("thumbnail"), dict) else ""
    topics = []
    for edge in ((node.get("topics") or {}).get("edges") or [])[:6]:
        name = _clip(((edge or {}).get("node") or {}).get("name"), 40)
        if name:
            topics.append(name)
    try:
        votes, comments = int(node.get("votesCount") or 0), int(node.get("commentsCount") or 0)
    except (TypeError, ValueError):
        return None
    return {
        "slug": slug,
        "name": _clip(node.get("name"), 80),
        "tagline": _clip(node.get("tagline"), 140),
        "description": _clip(node.get("description"), 400),
        "votes": votes,
        "comments": comments,
        "created_at": _clip(node.get("createdAt"), 40),
        "thumbnail": thumb if isinstance(thumb, str) and thumb.startswith("https://") else "",
        "topics": topics,
        "url": f"https://www.producthunt.com/posts/{slug}",
    }


def field_hits(post: dict[str, Any], terms: list[str]) -> list[str]:
    """Which of your profile terms the launch mentions."""
    text = " ".join([post["name"], post["tagline"], post["description"], " ".join(post["topics"])])
    return [t for t in terms if len(t) >= 3 and _term_pattern(t).search(text)]   # "r" would match anything


def rank(posts: list[dict[str, Any]], terms: list[str], size: int) -> list[dict[str, Any]]:
    """Launches in your field first (most matching terms, then upvotes), then the rest by upvotes."""
    for p in posts:
        p["match"] = field_hits(p, terms)
    ordered = sorted(posts, key=lambda p: (bool(p["match"]), len(p["match"]), p["votes"]), reverse=True)
    return ordered[:size]


def fetch_feed(session: requests.Session | None = None) -> list[dict[str, Any]]:
    """Today's featured launches from Product Hunt's public Atom feed (no token)."""
    import html as html_mod
    import xml.etree.ElementTree as ET
    session = session or requests.Session()
    r = session.get(FEED, timeout=25, headers={"User-Agent": "mygeeky (https://github.com/mygeeky/myGeeKy)"})
    r.raise_for_status()
    atom = "{http://www.w3.org/2005/Atom}"
    posts = []
    for e in ET.fromstring(r.content).findall(f"{atom}entry")[:60]:
        link_el = next((l for l in e.findall(f"{atom}link") if l.get("rel") in (None, "alternate")), None)
        m = _FEED_LINK.match((link_el.get("href") if link_el is not None else "") or "")
        name = _clip((e.findtext(f"{atom}title") or ""), 80)
        if not m or not name:
            continue
        content = e.findtext(f"{atom}content") or ""
        first_p = re.search(r"<p>(.*?)</p>", content, re.S)
        tagline = _clip(html_mod.unescape(re.sub(r"<[^>]+>", " ", first_p.group(1) if first_p else "")), 140)
        posts.append({"slug": m.group(1), "name": name, "tagline": tagline, "description": "", "votes": 0,
                      "comments": 0, "created_at": _clip(e.findtext(f"{atom}published"), 40), "thumbnail": "",
                      "topics": [], "url": f"https://www.producthunt.com/products/{m.group(1)}", "from_feed": True})
    return posts


def fetch_posts(token: str, topics: list[str], days: int, pages: int = 2,
                session: requests.Session | None = None,
                log: Callable[[str], None] = lambda m: None) -> list[dict[str, Any]]:
    session = session or requests.Session()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
               "Accept": "application/json", "User-Agent": "mygeeky-market"}
    after = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    seen: dict[str, dict[str, Any]] = {}
    for topic in topics:
        cursor = None
        for _ in range(pages):
            resp = session.post(API, headers=headers, timeout=30, json={
                "query": QUERY, "variables": {"topic": topic, "after": after, "cursor": cursor}})
            if resp.status_code == 401:
                raise ProductHuntError("Product Hunt refused the token. Run `mygeeky auth producthunt` again.")
            if resp.status_code != 200:
                log(f"Product Hunt topic '{topic}': HTTP {resp.status_code}, skipped")
                break
            body = resp.json()
            if body.get("errors"):
                log(f"Product Hunt topic '{topic}': {body['errors'][0].get('message', 'error')}, skipped")
                break
            posts = ((body.get("data") or {}).get("posts") or {})
            for edge in posts.get("edges") or []:
                post = clean_post((edge or {}).get("node"))
                if post:
                    seen.setdefault(post["slug"], post)
            info = posts.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                break
            cursor = info.get("endCursor")
    return list(seen.values())


# --------------------------------------------------------------------------- state
def load_state() -> dict[str, Any]:
    if not PRODUCTHUNT_FILE.exists():
        return {}
    try:
        return json.loads(PRODUCTHUNT_FILE.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    ensure_dirs()
    write_json(PRODUCTHUNT_FILE, state)


def refresh_due(cfg: MyGeekyConfig, state: dict[str, Any], now: datetime | None = None) -> bool:
    try:
        updated = datetime.fromisoformat(state["updated_at"])
    except (KeyError, TypeError, ValueError):
        return True
    return ((now or datetime.now(timezone.utc)) - updated).total_seconds() >= cfg.market_refresh_hours * 3600


def refresh(cfg: MyGeekyConfig, token: str | None, terms_fn: Callable[[], list[str]], force: bool = False,
            log: Callable[[str], None] = lambda m: None,
            session: requests.Session | None = None) -> dict[str, Any]:
    state = load_state()
    if not force and not refresh_due(cfg, state):
        return state
    log("reading Product Hunt launches")
    if token:
        posts = fetch_posts(token, cfg.market_ph_topics, cfg.market_ph_days, session=session, log=log)
    else:   # no token: today's featured launches, from the public feed
        posts = fetch_feed(session)
    state = {"updated_at": datetime.now(timezone.utc).isoformat(),
             "posts": rank(posts, terms_fn(), cfg.market_ph_size)}
    save_state(state)
    return state
