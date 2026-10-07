"""When do your GitHub tokens expire?

GitHub sends a token's expiry date with every API response (the
`github-authentication-token-expiration` header), so a single call to
/rate_limit -- which doesn't count against the rate limit -- is enough. The
check runs at most once a day; only the dates are cached (TOKEN_CHECK_FILE),
never the tokens. From WARN_DAYS before expiry, the panel and the command line
remind you to renew.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from .config import TOKEN_CHECK_FILE, MyGeekyConfig, ensure_dirs

EXPIRY_HEADER = "github-authentication-token-expiration"
SETTINGS_URL = "https://github.com/settings/personal-access-tokens"
WARN_DAYS = 7

TOKENS = {
    "read": ("Token 1 (read-only)", "mygeeky auth login"),
    "beacon": ("Token 2 (Signals)", "mygeeky beacon init"),
}


def parse_expiry(value: str | None) -> datetime | None:
    """GitHub sends '2026-10-18 04:23:30 UTC' (or with a +hhmm offset)."""
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S %z"):
        try:
            ts = datetime.strptime(value, fmt)
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def probe(token: str, timeout: float = 10.0) -> dict[str, Any]:
    """{"state": "ok" | "expired" | "unreachable", "expires_at": iso or None}.
    expires_at None with state ok means the token never expires."""
    try:
        r = requests.get("https://api.github.com/rate_limit", timeout=timeout,
                         headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    except requests.RequestException:
        return {"state": "unreachable", "expires_at": None}
    if r.status_code == 401:
        return {"state": "expired", "expires_at": None}   # expired, revoked or mistyped: GitHub won't say which
    expiry = parse_expiry(r.headers.get(EXPIRY_HEADER))
    return {"state": "ok", "expires_at": expiry.isoformat() if expiry else None}


def _stored_tokens(username: str) -> dict[str, str]:
    from . import auth
    found = {}
    read = auth.get_token(username)
    if read:
        found["read"] = read
    beacon = auth.get_beacon_token(username)
    if beacon:
        found["beacon"] = beacon
    return found


def describe(entry: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Adds days_left, warn and a one-line message to a probe result."""
    now = now or datetime.now(timezone.utc)
    label, renew = TOKENS[entry["name"]]
    out = {**entry, "label": label, "renew": renew, "days_left": None, "warn": False}
    if entry["state"] == "expired":
        out.update(warn=True, message=f"{label} has expired or was revoked. Make a new one and run `{renew}`.")
    elif entry["state"] == "unreachable":
        out["message"] = f"{label}: couldn't reach GitHub to check it."
    elif not entry.get("expires_at"):
        out["message"] = f"{label} never expires."
    else:
        exp = datetime.fromisoformat(entry["expires_at"])
        days = (exp - now).total_seconds() / 86400
        out["days_left"] = int(days)
        when = exp.strftime("%d %B %Y").lstrip("0")
        if days < 0:
            out.update(warn=True, message=f"{label} expired on {when}. Make a new one and run `{renew}`.")
        elif days <= WARN_DAYS:
            left = "today" if days < 1 else f"in {int(days)} day{'s' if int(days) != 1 else ''}"
            out.update(warn=True, message=f"{label} expires {left} ({when}). Renew it, then run `{renew}`.")
        else:
            out["message"] = f"{label} expires on {when} ({int(days)} days left)."
    return out


def status(cfg: MyGeekyConfig, force: bool = False, max_age_hours: float = 24.0) -> list[dict[str, Any]]:
    """Every stored token's expiry, from a cache of dates at most a day old."""
    try:
        cache = json.loads(TOKEN_CHECK_FILE.read_text(encoding="utf-8"))
        fresh = datetime.now(timezone.utc) - datetime.fromisoformat(cache["checked_at"]) < timedelta(hours=max_age_hours)
    except (OSError, ValueError, KeyError, TypeError):
        cache, fresh = {}, False
    stored = _stored_tokens(cfg.github_username) if cfg.github_username else {}
    if force or not fresh or set(cache.get("tokens", {})) != set(stored):
        cache = {"checked_at": datetime.now(timezone.utc).isoformat(),
                 "tokens": {name: probe(tok) for name, tok in stored.items()}}
        if any(t["state"] != "unreachable" for t in cache["tokens"].values()):
            try:
                ensure_dirs()
                TOKEN_CHECK_FILE.write_text(json.dumps(cache), encoding="utf-8")
            except OSError:
                pass
    return [describe({"name": name, **cache["tokens"][name]}) for name in TOKENS if name in cache["tokens"]]


def warnings(cfg: MyGeekyConfig) -> list[dict[str, Any]]:
    return [t for t in status(cfg) if t["warn"]]


def forget() -> None:
    """Drop the cached dates (after a token was replaced)."""
    try:
        TOKEN_CHECK_FILE.unlink()
    except OSError:
        pass
