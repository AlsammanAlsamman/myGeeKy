"""Badges: small rewards for using myGeeKy, and your GitHub achievements.

myGeeKy's own badges come in bronze, silver and gold, earned from what you
actually do -- opening things, following people, coming back day after day.
They're computed from local files only:

  * USAGE_FILE (usage.jsonl): one line per click or day of use, recording only
    the KIND of thing (a headline, a model, a paper...) and its area (AI,
    science, tech) -- never titles or links. It syncs with your data, and as a
    .jsonl it merges cleanly between computers.
  * the interest events (follows, stars, forks), your sent signals, keywords.

GitHub's own achievements (Pull Shark, Quickdraw...) have no API, so they're
read from your public profile page at most once a week, best-effort: if GitHub
changes that page, they simply don't show. Only the names and GitHub's own
badge images are kept.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

from .config import GH_ACHIEVEMENTS_FILE, MyGeekyConfig, USAGE_FILE, ensure_dirs
from .files import append_jsonl, write_json

TIERS = ("bronze", "silver", "gold")
TIER_COLORS = {"bronze": "#cd7f32", "silver": "#c0c7d4", "gold": "#ffd24a"}

# id: (emoji, name, what it counts, thresholds for bronze / silver / gold)
BADGES: dict[str, tuple[str, str, str, tuple[int, ...]]] = {
    "active": ("🔥", "Regular", "days you've opened myGeeKy", (3, 14, 60)),
    "clicker": ("🖱️", "Clicker", "things you've opened from myGeeKy", (10, 50, 200)),
    "reader": ("📰", "News Reader", "headlines and news you've read", (10, 50, 200)),
    "analyst": ("📊", "Analyst", "papers you've opened", (5, 25, 100)),
    "ai": ("🤖", "AI Fan", "AI headlines and models you've opened", (5, 25, 100)),
    "models": ("🤗", "Model Hunter", "Hugging Face models you've opened", (3, 15, 50)),
    "explorer": ("🔭", "Explorer", "things you opened from outside your usual interests", (3, 15, 50)),
    "networker": ("🤝", "Networker", "people you've followed", (1, 10, 30)),
    "stargazer": ("⭐", "Stargazer", "repos you've starred", (1, 10, 50)),
    "builder": ("🛠️", "Builder", "repos you've forked to contribute", (1, 5, 20)),
    "grateful": ("🙏", "Grateful", "signals you've sent", (1, 5, 20)),
    "wordsmith": ("🔤", "Wordsmith", "keywords you've set", (3, 8, 15)),
    "ideas": ("💡", "Idea Giver", "ideas and problems you've sent", (1, 3, 10)),
    "everywhere": ("☁️", "Everywhere", "computers in sync (sync set up)", (1,)),
    "early": ("🌱", "Early Adopter", "joined myGeeKy before 2027", (1,)),
}


# --------------------------------------------------------------------------- the usage log
def log(what: str, kind: str = "", category: str = "", explore: bool = False) -> None:
    """One line: a click (what="click") or a day of use (what="open"). Never raises."""
    try:
        ensure_dirs()
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "what": what}
        if kind:
            entry["kind"] = kind[:20]
        if category:
            entry["cat"] = category[:20]
        if explore:
            entry["explore"] = True
        append_jsonl(USAGE_FILE, entry)
    except Exception:
        pass


def log_open_today() -> None:
    """Count today as a day of use (once per day)."""
    today = date.today().isoformat()
    if not any(e.get("what") == "open" and e.get("at", "").startswith(today) for e in _usage()):
        log("open")


def _usage() -> list[dict[str, Any]]:
    try:
        lines = USAGE_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            e = json.loads(line)
            if isinstance(e, dict):
                out.append(e)
        except ValueError:
            continue
    return out


# --------------------------------------------------------------------------- counting
def counts(cfg: MyGeekyConfig) -> dict[str, int]:
    usage = _usage()
    clicks = [e for e in usage if e.get("what") == "click"]
    kinds = Counter(e.get("kind", "") for e in clicks)
    days = {e.get("at", "")[:10] for e in usage if e.get("what") == "open"}
    try:
        from . import interests
        history = interests.load_events()
    except Exception:
        history = []
    events = Counter(e.get("kind") for e in history)
    # before the usage log existed, clicks were only kept as interest events: count those too
    past = [e for e in history if e.get("kind") in ("person", "repo", "news")
            and e.get("at", "") < (min((u.get("at", "") for u in usage), default="9999"))]
    days |= {e.get("at", "")[:10] for e in history if e.get("at")}
    try:
        from . import beacon
        sent = len(beacon.load_my_beacon().get("sent", []))
    except Exception:
        sent = 0
    first = min([e.get("at", "") for e in usage] + [e.get("at", "") for e in history if e.get("at")], default="")
    return {
        "active": len(days),
        "clicker": len(clicks) + len(past),
        "reader": kinds["headline"] + kinds["news"] + sum(1 for e in past if e.get("kind") == "news"),
        "analyst": kinds["paper"],
        "ai": sum(1 for e in clicks if e.get("cat") == "ai" or e.get("kind") == "model"),
        "models": kinds["model"],
        "explorer": sum(1 for e in clicks if e.get("explore")),
        "networker": events["follow"],
        "stargazer": events["star"],
        "builder": events["fork"],
        "grateful": sent,
        "wordsmith": len(cfg.keywords),
        "ideas": sum(1 for e in usage if e.get("what") == "idea"),
        "everywhere": 1 if cfg.sync_repo else 0,
        "early": 1 if first and first < "2027-01-01" else 0,
    }


def earned(cfg: MyGeekyConfig) -> list[dict[str, Any]]:
    """Every badge with its tier ("" = not yet), progress and the next goal."""
    c = counts(cfg)
    out = []
    for bid, (emoji, name, what, levels) in BADGES.items():
        n = c.get(bid, 0)
        reached = [t for t, need in zip(TIERS, levels) if n >= need]
        tier = reached[-1] if reached else ""
        nxt = next((need for need in levels if n < need), None)
        out.append({"id": bid, "emoji": emoji, "name": name, "what": what, "count": n, "tier": tier,
                    "next": nxt, "single": len(levels) == 1,
                    "level": len(reached), "levels": len(levels)})
    return out


def earned_only(cfg: MyGeekyConfig) -> list[dict[str, Any]]:
    """Earned badges, best first (gold, then silver, then bronze)."""
    return sorted((b for b in earned(cfg) if b["tier"]), key=lambda b: (-b["level"], b["name"]))


# --------------------------------------------------------------------------- GitHub's own achievements
_ACH = re.compile(r'<img[^>]*alt="Achievement: ([^"]{1,60})"[^>]*src="(https://github\.githubassets\.com/assets/'
                  r'[a-z0-9-]{1,80}\.png)"', re.I)
_ACH_REV = re.compile(r'<img[^>]*src="(https://github\.githubassets\.com/assets/[a-z0-9-]{1,80}\.png)"[^>]*'
                      r'alt="Achievement: ([^"]{1,60})"', re.I)


def parse_achievements(html: str) -> list[dict[str, str]]:
    found: dict[str, str] = {}
    for name, img in _ACH.findall(html):
        found.setdefault(name.strip(), img)
    for img, name in _ACH_REV.findall(html):
        found.setdefault(name.strip(), img)
    return [{"name": n, "image": i} for n, i in found.items()]


def github_achievements(username: str, force: bool = False) -> list[dict[str, str]]:
    """Cached; re-read from your public profile at most once a week."""
    try:
        cache = json.loads(GH_ACHIEVEMENTS_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        cache = {}
    try:
        fresh = (cache.get("user") == username and datetime.now(timezone.utc)
                 - datetime.fromisoformat(cache["checked_at"]) < timedelta(days=7))
    except (KeyError, ValueError, TypeError):
        fresh = False
    if fresh and not force:
        return cache.get("items", [])
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}", username or ""):
        return []
    try:
        r = requests.get(f"https://github.com/{username}?tab=achievements", timeout=15,
                         headers={"User-Agent": "Mozilla/5.0 (mygeeky)"})
        items = parse_achievements(r.text) if r.status_code == 200 else cache.get("items", [])
    except requests.RequestException:
        items = cache.get("items", [])
    try:
        ensure_dirs()
        write_json(GH_ACHIEVEMENTS_FILE, {"user": username, "items": items,
                                          "checked_at": datetime.now(timezone.utc).isoformat()})
    except OSError:
        pass
    return items
