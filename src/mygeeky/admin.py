"""The maker's admin tab: who might want myGeeKy, what people ask for, and how
it's being adopted. Shown only to ADMINS.

Honest note on "only": myGeeKy is open source, so hiding a tab is a
convenience, not security. Nothing here is secret: prospects come from public
GitHub data, the ideas live in a public repo, and the adoption numbers are
public counters. Anything that ever needs to be private must be protected by
GitHub permissions, not by this check.

Invitations are never sent automatically. GitHub has no private messages,
and mass-messaging strangers is spam. myGeeKy ranks people, drafts an
email (when they list a public one) or an invite to copy, and you send each
one yourself -- at most INVITE_DAILY_LIMIT a day. People you invite who later
show up (a myGeeKy Signals beacon, or a star or fork of myGeeKy) are
counted as "joined", so you can see what works.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import quote

import requests

from .config import ADMIN_FILE, MyGeekyConfig, ensure_dirs

ADMINS = {"alsammanalsamman"}
PROJECT_REPO = "AlsammanAlsamman/myGeeKy"
INVITE_DAILY_LIMIT = 10
_RESEARCH_BIO = re.compile(r"ph\.?d|postdoc|professor|lab\b|universit|institut|scientist|research|"
                           r"bioinformatic|genom|genetic|biolog|computational", re.I)
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")


def is_admin(cfg: MyGeekyConfig) -> bool:
    return cfg.github_username.lower() in ADMINS


# --------------------------------------------------------------------------- state
def load() -> dict[str, Any]:
    try:
        return json.loads(ADMIN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"people": {}}


def save(state: dict[str, Any]) -> None:
    ensure_dirs()
    ADMIN_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- the prospects model
WEIGHTS = {
    "starred_mygeeky": 3.0,     # already interested in the project itself
    "forked_mygeeky": 3.0,
    "builds_published_tool": 2.0,   # writes research software with a paper: the core audience
    "field_match": 1.5,         # x domain fit, from your People suggestions
    "public_email": 1.0,        # reachable at all
    "research_bio": 1.0,
    "recently_active": 0.5,
    "reachable_size": 0.5,      # not a celebrity, not empty
}


def score(features: dict[str, float]) -> float:
    return round(sum(WEIGHTS[k] * float(v) for k, v in features.items() if k in WEIGHTS), 3)


def _gather(client, cfg: MyGeekyConfig) -> dict[str, dict[str, Any]]:
    """login -> {features, why} from the strongest signals first."""
    from . import beacon, papers
    from .storage import last_suggestions
    pool: dict[str, dict[str, Any]] = {}

    def add(login: str, feature: str, value: float, why: str) -> None:
        if not login or login.lower() == cfg.github_username.lower() or login.endswith("[bot]"):
            return
        p = pool.setdefault(login.lower(), {"login": login, "features": {}, "why": []})
        p["features"][feature] = max(p["features"].get(feature, 0), value)
        if why not in p["why"]:
            p["why"].append(why)

    for login in client.list_stargazers(PROJECT_REPO, max_pages=3):
        add(login, "starred_mygeeky", 1, "starred myGeeKy")
    resp = client._get(f"/repos/{PROJECT_REPO}/forks", params={"per_page": 100})
    if resp.status_code == 200:
        for f in resp.json():
            add((f.get("owner") or {}).get("login", ""), "forked_mygeeky", 1, "forked myGeeKy")
    for tool in (papers.load_trends().get("tools") or [])[:12]:
        for repo in tool.get("repos", [])[:1]:
            owner = repo.split("/")[0]
            add(owner, "builds_published_tool", 1, f"builds {repo} (published)")
    for s in last_suggestions(60, list_type="domain") + last_suggestions(60, list_type="followback"):
        fit = min(1.0, float(s.get("domain_fit") or 0) * 2)
        if fit > 0:
            add(s.get("username", ""), "field_match", fit, "works in your field")
    # people already on myGeeKy aren't prospects any more
    on_mygeeky = {u.lower() for u in (beacon.load_cache().get("users") or {})}
    return {k: v for k, v in pool.items() if k not in on_mygeeky}


def refresh_prospects(client, cfg: MyGeekyConfig, max_lookups: int = 40,
                      log: Callable[[str], None] = lambda m: None) -> dict[str, Any]:
    from . import beacon
    state = load()
    people = state.setdefault("people", {})
    pool = _gather(client, cfg)
    # outcomes first: invited people who now show up count as joined
    joined_now = {u.lower() for u in (beacon.load_cache().get("users") or {})}
    joined_now |= {k for k, v in pool.items() if {"starred_mygeeky", "forked_mygeeky"} & set(v["features"])}
    for key, p in people.items():
        if p.get("status") == "invited" and key in joined_now:
            p["status"], p["joined_at"] = "joined", _now().isoformat()
    # cheap first ranking, then look up the most promising few (one API call each, cached a week)
    ranked = sorted(pool.values(), key=lambda p: score(p["features"]), reverse=True)
    lookups = 0
    for p in ranked:
        key = p["login"].lower()
        entry = people.setdefault(key, {"login": p["login"], "status": "new"})
        entry["why"], base = p["why"], dict(p["features"])
        fresh = entry.get("looked_up_at") and _now() - datetime.fromisoformat(entry["looked_up_at"]) < timedelta(days=7)
        if not fresh and lookups < max_lookups:
            lookups += 1
            user = client.get_user(p["login"]) or {}
            email = str(user.get("email") or "")
            if user.get("type") == "Organization":     # you invite people, not organizations
                entry.update({"status": "org", "looked_up_at": _now().isoformat()})
                continue
            entry.update({
                "name": str(user.get("name") or "")[:80], "bio": str(user.get("bio") or "")[:200],
                "email": email if _EMAIL.match(email) else "", "followers": int(user.get("followers") or 0),
                "updated_at": user.get("updated_at") or "", "avatar": user.get("avatar_url") or "",
                "looked_up_at": _now().isoformat()})
        if entry.get("status") == "org":
            continue
        if entry.get("looked_up_at"):
            base["public_email"] = 1 if entry.get("email") else 0
            base["research_bio"] = 1 if _RESEARCH_BIO.search(entry.get("bio", "")) else 0
            try:
                active = _now() - datetime.fromisoformat(entry["updated_at"].replace("Z", "+00:00")) < timedelta(days=90)
            except (KeyError, ValueError):
                active = False
            base["recently_active"] = 1 if active else 0
            base["reachable_size"] = 1 if 5 <= entry.get("followers", 0) <= 5000 else 0
        entry["features"], entry["score"] = base, score(base)
    state["updated_at"] = _now().isoformat()
    save(state)
    log(f"prospects: {len(pool)} found, {lookups} looked up")
    return state


def prospects(state: dict[str, Any] | None = None, n: int = 30) -> list[dict[str, Any]]:
    people = (state or load()).get("people", {}).values()
    return sorted((p for p in people if p.get("status") == "new" and p.get("looked_up_at")),
                  key=lambda p: p.get("score", 0), reverse=True)[:n]


def invited_today(state: dict[str, Any] | None = None) -> int:
    today = _now().date().isoformat()
    return sum(1 for p in (state or load()).get("people", {}).values() if (p.get("invited_at") or "")[:10] == today)


def mark(login: str, status: str) -> dict[str, Any]:
    """status: invited | declined | new. Inviting respects the daily limit."""
    state = load()
    entry = state.setdefault("people", {}).setdefault(login.lower(), {"login": login})
    if status == "invited":
        if invited_today(state) >= INVITE_DAILY_LIMIT:
            return {"ok": False, "message": f"That's {INVITE_DAILY_LIMIT} invites today. Pace it: try tomorrow."}
        entry["invited_at"] = _now().isoformat()
    entry["status"] = status
    save(state)
    return {"ok": True}


def funnel(state: dict[str, Any] | None = None) -> dict[str, int]:
    people = (state or load()).get("people", {}).values()
    count = {"new": 0, "invited": 0, "joined": 0, "declined": 0}
    for p in people:
        if p.get("status") in count:
            count[p["status"]] += 1
    return count


def invite(person: dict[str, Any], cfg: MyGeekyConfig) -> dict[str, str]:
    """A short, personal invite (and a mailto link when they list an email)."""
    first = (person.get("name") or person.get("login") or "").split()[0] if (person.get("name") or person.get("login")) else ""
    why = "; ".join(person.get("why", [])[:2])
    subject = "myGeeKy: your corner of GitHub, for research"
    body = (f"Hi {first},\n\n"
            f"I came across your work on GitHub ({why}). I've built myGeeKy, a free, open-source tool for "
            "researchers who code: from your CV and papers it finds people in your field worth following, "
            "repos you could contribute to, rising papers and tools, and what's new in your area, all in a "
            "small panel on your screen. It never acts for you.\n\n"
            "If it sounds useful: https://mygeeky.org (or pip install mygeeky). I'd love your feedback, "
            "and there's a 💡 button in the app for ideas.\n\n"
            f"Best,\n{cfg.github_username}")
    out = {"subject": subject, "body": body}
    if person.get("email"):
        out["mailto"] = f"mailto:{person['email']}?subject={quote(subject)}&body={quote(body)}"
    return out


# --------------------------------------------------------------------------- adoption
def adoption(client) -> dict[str, Any]:
    from . import beacon
    out: dict[str, Any] = {}
    repo = client.get_repo(PROJECT_REPO) or {}
    out["stars"], out["forks"] = repo.get("stargazers_count", 0), repo.get("forks_count", 0)
    resp = client._get(f"/repos/{PROJECT_REPO}/releases", params={"per_page": 50})
    out["installer_downloads"] = sum(a.get("download_count", 0) for r in (resp.json() if resp.status_code == 200 else [])
                                     for a in r.get("assets", []) if a.get("name", "").endswith(".exe"))
    try:
        recent = requests.get("https://pypistats.org/api/packages/mygeeky/recent", timeout=20).json().get("data") or {}
        out["pypi_week"], out["pypi_month"] = recent.get("last_week"), recent.get("last_month")
    except (requests.RequestException, ValueError):
        out["pypi_week"] = out["pypi_month"] = None
    out["signals_users"] = len(beacon.load_cache().get("users") or {})
    return out
