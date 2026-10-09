"""Beacons: private, non-verbal signals between myGeeKy users, carried by GitHub.

There is no myGeeKy server. Every user who opts in (`mygeeky beacon init`)
gets a small PUBLIC repo, `<you>/mygeeky-beacon`, tagged with the topic
`mygeeky-beacon`, holding one file, `beacon.json`:

    {"mygeeky_beacon": 2,
     "keys": ["<X25519 public key per computer>"],
     "status": "open-to-collab", "quiet": false,
     "interests": ["gwas", "snakemake"],
     "sealed": [{"at": "2026-10-07", "box": "<a signal only its recipient can open>"}]}

The beacon itself (status, interests, keys) is public. The signals are not:
each is sealed to the recipient's key (signal_crypto.py), so nobody else can
tell who it's for or what it says -- not even that someone didn't answer.
Others find beacons with plain repository searches for that topic and the
repo name, and try to open every sealed box with their own key.

Signals are designed to be gifts, never requests:

- 🙏 thanks, 📚 learned from your work, ⭐ used your work (with a repo),
  👀 following your work -- appreciation that needs no reply, and every
  received signal says so.
- 🤝 collaborate is mutual opt-in: the other person only ever sees it if
  they choose it for you too. Then you both get "you both want to collaborate".
- Nothing on the sender's side tracks replies: you see "sent", never "unanswered".
- Courtesy limits: one signal of a kind per person a month, a few new people
  a week, a daily cap; anyone can go quiet ("not taking signals right now"),
  mute someone (they're not told) or block them.

Other people's beacons are untrusted input: size-capped, schema-checked,
logins/repos validated against GitHub's own name rules, unknown gesture types
dropped, and the sender is taken from the repo -- a sealed signal must also
name that same sender inside, so nobody can replay someone else's signal.

The ONE write myGeeKy ever makes lives in `BeaconWriter`: a PUT of
`beacon.json` (or its README) in YOUR OWN `mygeeky-beacon` repo, with a
separate fine-grained token scoped to that single repo. Nothing anywhere can
follow anyone. Beacons from older myGeeKy versions (schema 1, plain-text
gestures) are still read, until their owners update.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

import requests

from . import signal_crypto as sc
from .config import BEACON_CACHE_FILE, MY_BEACON_FILE, MyGeekyConfig, ensure_dirs
from .github_client import API_ROOT, GitHubClient
from .files import write_json

BEACON_REPO = "mygeeky-beacon"
BEACON_TOPIC = "mygeeky-beacon"
BEACON_PATH = "beacon.json"
README_PATH = "README.md"
SCHEMA_VERSION = 2
READ_VERSIONS = (1, 2)
MAX_BEACON_BYTES = 256 * 1024
MAX_GESTURES_READ = 300       # per beacon -- anything beyond is ignored
MAX_SEALED_READ = 600
MAX_KEYS = 4                  # one per computer you use myGeeKy on
MAX_PER_SENDER = 5            # incoming signals shown per person
MAX_INTERESTS = 12
KEY_SERVICE = "mygeeky-signals-key"

# type -> (emoji, how it reads when someone sends it to you)
GESTURES: dict[str, tuple[str, str]] = {
    "thanks": ("🙏", "thanked you for your work"),
    "learn": ("📚", "learned from your work"),
    "used": ("⭐", "used your work"),                 # carries a repo: "used <repo> in their work"
    "watching": ("👀", "is following your work"),
    "collab": ("🤝", "would like to collaborate"),    # only ever shown when it's mutual
}
REPO_GESTURES = {"used"}
MUTUAL_ONLY = {"collab"}
MUTUAL_TEXT = "🤝 you both want to collaborate"
NO_REPLY = "no reply needed"
# how signals from older myGeeKy versions (schema 1) read
LEGACY_GESTURES: dict[str, tuple[str, str]] = {
    "wave": ("👋", "said hello"),
    "learn": ("📚", "learned from your work"),
    "collab": ("🤝", "would like to collaborate"),
    "watching": ("👀", "is following your work"),
    "kudos": ("⭐", "gave kudos"),
}
LEGACY_REPO_GESTURES = {"kudos"}

# status -> label; "" means no status
STATUSES: dict[str, str] = {
    "": "",
    "open-to-collab": "🤝 open to collaborate",
    "learning": "🌱 learning something new",
    "heads-down": "🎧 heads-down",
    "seeking-reviewers": "🔍 looking for reviewers",
    "mentoring": "🧭 happy to mentor",
}
QUIET_LABEL = "🔕 not taking signals right now"

_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}/[A-Za-z0-9._-]{1,100}$")
_INTEREST_RE = re.compile(r"^[\w .+#-]{1,40}$")


class BeaconError(RuntimeError):
    pass


def valid_login(login: Any) -> bool:
    return isinstance(login, str) and bool(_LOGIN_RE.match(login))


def valid_repo(repo: Any) -> bool:
    return isinstance(repo, str) and bool(_REPO_RE.match(repo)) and ".." not in repo


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def clean_interests(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for v in values:
        if not isinstance(v, str):
            continue
        v = " ".join(v.strip().lower().split())
        if _INTEREST_RE.match(v) and v not in out:
            out.append(v)
        if len(out) >= MAX_INTERESTS:
            break
    return out


# --------------------------------------------------------------------------- this computer's key
def my_keypair(user: str) -> tuple[str, str]:
    """(private, public) for this computer, created on first use. The private
    key lives only in this computer's OS keyring."""
    import keyring
    try:
        priv = keyring.get_password(KEY_SERVICE, user)
        if not priv:
            priv, _ = sc.new_keypair()
            keyring.set_password(KEY_SERVICE, user, priv)
        return priv, sc.public_of(priv)
    except Exception as exc:
        raise BeaconError(f"Couldn't use this computer's keyring for your Signals key: {exc}") from exc


# --------------------------------------------------------------------------- parsing untrusted beacons
def parse_beacon(raw: Any, owner: str, ttl_days: int, now: datetime | None = None) -> dict[str, Any] | None:
    """A validated copy of someone's beacon, or None if it isn't one.
    `owner` comes from the repo the file was read from -- a beacon can't
    claim to be someone else's."""
    if not isinstance(raw, dict) or raw.get("mygeeky_beacon") not in READ_VERSIONS or not valid_login(owner):
        return None
    now = now or _now()
    oldest = now - timedelta(days=ttl_days)
    out: dict[str, Any] = {
        "owner": owner, "version": raw["mygeeky_beacon"],
        "status": raw.get("status") if raw.get("status") in STATUSES else "",
        "quiet": raw.get("quiet") is True,
        "interests": clean_interests(raw["interests"] if isinstance(raw.get("interests"), list) else []),
        "keys": [], "sealed": [], "gestures": [],
    }
    if out["version"] == 1:   # older myGeeKy: plain-text gestures
        raw_gestures = raw.get("gestures") if isinstance(raw.get("gestures"), list) else []
        for g in raw_gestures[:MAX_GESTURES_READ]:
            if not isinstance(g, dict) or g.get("type") not in LEGACY_GESTURES or not valid_login(g.get("to")):
                continue
            at = _parse_time(g.get("at"))
            if at is None or at < oldest or at > now + timedelta(days=1):
                continue
            clean = {"to": g["to"], "type": g["type"], "at": at.isoformat(), "legacy": True}
            if g["type"] in LEGACY_REPO_GESTURES:
                if not valid_repo(g.get("repo")):
                    continue
                clean["repo"] = g["repo"]
            out["gestures"].append(clean)
        return out
    keys = raw.get("keys") if isinstance(raw.get("keys"), list) else []
    out["keys"] = [k for k in keys[:MAX_KEYS] if sc.valid_public_key(k)]
    sealed = raw.get("sealed") if isinstance(raw.get("sealed"), list) else []
    for s in sealed[:MAX_SEALED_READ]:
        if not isinstance(s, dict) or not isinstance(s.get("box"), str) or len(s["box"]) != sc.BOX_LEN:
            continue
        at = _parse_time(s.get("at"))
        if at is None or at < oldest - timedelta(days=1) or at > now + timedelta(days=1):
            continue
        out["sealed"].append(s["box"])
    return out


def open_signals(parsed: dict[str, Any], me: str, private_key: str, ttl_days: int,
                 now: datetime | None = None) -> list[dict[str, Any]]:
    """The signals in `parsed` (someone's beacon) that are for `me`: plain
    legacy ones, plus every sealed box our key opens and that checks out."""
    now = now or _now()
    oldest = now - timedelta(days=ttl_days)
    found = [g for g in parsed.get("gestures", []) if g["to"].lower() == me.lower()]
    for box in parsed.get("sealed", []):
        plain = sc.open_box(private_key, box)
        if plain is None:
            continue
        try:
            msg = json.loads(plain.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if not isinstance(msg, dict) or msg.get("type") not in GESTURES:
            continue
        # sent by the beacon's owner, to us -- a copied box from someone else's beacon fails here
        if str(msg.get("from", "")).lower() != parsed["owner"].lower() or str(msg.get("to", "")).lower() != me.lower():
            continue
        at = _parse_time(msg.get("at"))
        if at is None or at < oldest or at > now + timedelta(days=1):
            continue
        g = {"to": me, "type": msg["type"], "at": at.isoformat()}
        if msg["type"] in REPO_GESTURES:
            if not valid_repo(msg.get("repo")):
                continue
            g["repo"] = msg["repo"]
        found.append(g)
    return found


# --------------------------------------------------------------------------- your own beacon (local source of truth)
def empty_beacon() -> dict[str, Any]:
    return {"mygeeky_beacon": SCHEMA_VERSION, "sent": [], "withdrawn": [], "published_key": ""}


def load_my_beacon() -> dict[str, Any]:
    """Your local record. `sent` is only ever on this computer (and your
    private sync repo): the public file holds sealed boxes, not this list."""
    base = empty_beacon()
    if not MY_BEACON_FILE.exists():
        return base
    try:
        data = json.loads(MY_BEACON_FILE.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return base
    if not isinstance(data, dict):
        return base
    if data.get("mygeeky_beacon") == 1 or "gestures" in data:   # upgrade: keep the history, privately
        base["sent"] = [{k: v for k, v in g.items() if k in ("to", "type", "repo", "at")}
                        for g in data.get("gestures", []) if isinstance(g, dict)]
        return base
    base.update({k: v for k, v in data.items() if k in base})
    return base


def save_my_beacon(beacon: dict[str, Any]) -> None:
    ensure_dirs()
    write_json(MY_BEACON_FILE, beacon, indent=2)


def prune(beacon: dict[str, Any], ttl_days: int, now: datetime | None = None) -> dict[str, Any]:
    """Drop expired signals, so nothing stays around forever."""
    oldest = (now or _now()) - timedelta(days=ttl_days)
    fresh = lambda g: (_parse_time(g.get("at")) or oldest) > oldest  # noqa: E731
    return {**beacon, "sent": [g for g in beacon.get("sent", []) if fresh(g)],
            "withdrawn": [w for w in beacon.get("withdrawn", []) if fresh(w)]}


def _sent_recently(beacon: dict[str, Any], days: int, now: datetime) -> list[dict[str, Any]]:
    since = now - timedelta(days=days)
    return [g for g in beacon.get("sent", []) if (ts := _parse_time(g.get("at"))) and ts > since]


def gestures_sent_today(beacon: dict[str, Any], now: datetime | None = None) -> int:
    today = (now or _now()).date()
    return sum(1 for g in beacon.get("sent", []) if (ts := _parse_time(g.get("at"))) and ts.date() == today)


def _signal_text(msg: dict[str, Any]) -> bytes:
    return json.dumps(msg, separators=(",", ":"), sort_keys=True).encode("utf-8")


def add_signal(beacon: dict[str, Any], me: str, to: str, gesture: str, repo: str | None,
               cfg: MyGeekyConfig, recipient: dict[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    """A new local beacon with the signal sealed for `recipient` (their parsed
    beacon). Every courtesy rule is checked here, before anything is sent."""
    now = now or _now()
    if gesture not in GESTURES:
        raise BeaconError(f"Unknown signal '{gesture}'. Choose one of: {', '.join(GESTURES)}.")
    if not valid_login(to):
        raise BeaconError(f"'{to}' isn't a valid GitHub username.")
    if to.lower() == me.lower():
        raise BeaconError("You can't signal yourself.")
    if to.lower() in {u.lower() for u in cfg.beacon_blocked}:
        raise BeaconError(f"You've blocked {to}; unblock them first.")
    if gesture in REPO_GESTURES:
        if not valid_repo(repo):
            raise BeaconError(f"'{gesture}' needs the repo you used, as owner/name.")
    else:
        repo = None
    if recipient is None:
        raise BeaconError(f"{to} isn't on myGeeKy Signals (or hasn't been seen yet: try Refresh). "
                          "Nothing was sent.")
    if recipient.get("quiet"):
        raise BeaconError(f"{to} isn't taking signals right now. Nothing was sent; maybe another time.")
    if not recipient.get("keys"):
        raise BeaconError(f"{to} uses an older myGeeKy that can't receive private signals yet. "
                          "Nothing was sent; it will work once they update.")
    beacon = prune(beacon, cfg.beacon_gesture_ttl_days, now)
    for g in _sent_recently(beacon, cfg.beacon_repeat_days, now):
        if g.get("to", "").lower() == to.lower() and g.get("type") == gesture and g.get("repo") == repo:
            raise BeaconError(f"You already sent {to} this on {g['at'][:10]}. Once is enough: "
                              f"it stays with them for {cfg.beacon_gesture_ttl_days} days.")
    if gestures_sent_today(beacon, now) >= cfg.beacon_daily_limit:
        raise BeaconError(f"That's {cfg.beacon_daily_limit} signals today. Try again tomorrow.")
    known = {g.get("to", "").lower() for g in beacon.get("sent", [])
             if (ts := _parse_time(g.get("at"))) and ts <= now - timedelta(days=7)}
    new_this_week = {g.get("to", "").lower() for g in _sent_recently(beacon, 7, now)} - known
    if to.lower() not in known | new_this_week and len(new_this_week) >= cfg.beacon_weekly_new_people:
        raise BeaconError(f"You've signalled {cfg.beacon_weekly_new_people} new people this week. "
                          "Pace it: try again in a few days.")
    msg = {"v": SCHEMA_VERSION, "from": me, "to": to, "type": gesture, "at": now.isoformat(timespec="seconds")}
    if repo:
        msg["repo"] = repo
    boxes = [sc.seal(k, _signal_text(msg)) for k in recipient["keys"][:MAX_KEYS]]
    entry = {"to": to, "type": gesture, "at": msg["at"], "boxes": boxes}
    if repo:
        entry["repo"] = repo
    return {**beacon, "sent": beacon.get("sent", []) + [entry]}


def remove_signals(beacon: dict[str, Any], to: str, gesture: str | None = None,
                   now: datetime | None = None) -> dict[str, Any]:
    """Take signals back: their boxes leave the public file on the next publish
    (and are remembered as withdrawn, so another computer can't re-add them)."""
    now = now or _now()
    match = lambda g: g.get("to", "").lower() == to.lower() and (gesture is None or g.get("type") == gesture)  # noqa: E731
    gone = [b for g in beacon.get("sent", []) if match(g) for b in g.get("boxes", [])]
    return {**beacon, "sent": [g for g in beacon.get("sent", []) if not match(g)],
            "withdrawn": beacon.get("withdrawn", []) + [{"id": _box_id(b), "at": now.isoformat()} for b in gone]}


def _box_id(box: str) -> str:
    return hashlib.sha256(box.encode("ascii")).hexdigest()[:24]


def public_beacon(beacon: dict[str, Any], cfg: MyGeekyConfig, my_public_key: str,
                  remote: dict[str, Any] | None = None) -> dict[str, Any]:
    """Exactly what gets published. `remote` is what's published now: keys
    and sealed boxes added from your other computers are kept."""
    now = _now()
    oldest = now - timedelta(days=cfg.beacon_gesture_ttl_days)
    remote = remote if isinstance(remote, dict) and remote.get("mygeeky_beacon") == SCHEMA_VERSION else {}
    keys = [my_public_key] + [k for k in (remote.get("keys") or []) if sc.valid_public_key(k) and k != my_public_key]
    withdrawn = {w.get("id") for w in beacon.get("withdrawn", [])}
    sealed: dict[str, dict[str, str]] = {}
    for g in beacon.get("sent", []):
        ts = _parse_time(g.get("at"))
        if ts and ts > oldest:
            for b in g.get("boxes", []):
                sealed[b] = {"at": ts.date().isoformat(), "box": b}
    for s in remote.get("sealed") or []:
        ts = _parse_time(s.get("at")) if isinstance(s, dict) else None
        if ts and ts > oldest - timedelta(days=1) and isinstance(s.get("box"), str) \
                and len(s["box"]) == sc.BOX_LEN and _box_id(s["box"]) not in withdrawn:
            sealed.setdefault(s["box"], {"at": s["at"][:10], "box": s["box"]})
    return {
        "mygeeky_beacon": SCHEMA_VERSION,
        "keys": keys[:MAX_KEYS],
        "status": cfg.beacon_status if cfg.beacon_status in STATUSES else "",
        "quiet": bool(cfg.beacon_quiet),
        "interests": _interests(cfg) if cfg.beacon_share_interests else [],
        "sealed": sorted(sealed.values(), key=lambda s: s["at"]),
    }


def _interests(cfg: MyGeekyConfig) -> list[str]:
    """Your interest tags, keywords the dictionary doesn't know yet first: that's
    how they reach the maker, who teaches them to the next dictionary."""
    try:
        from . import keywords
        red = keywords.split_known(cfg.keywords)[1]
    except Exception:
        red = []
    return clean_interests(red + cfg.topics + cfg.keywords + cfg.languages)


BEACON_README = """\
# mygeeky-beacon

This is a [myGeeKy](https://github.com/mygeeky/myGeeKy) beacon.

`beacon.json` holds a public key, an optional status and a few interest tags.
It also holds **sealed signals** (🙏 thanks, 📚 learned from your work, ⭐ used
your work, 👀 following, 🤝 collaborate) this account sent to other myGeeKy
users. Each one is encrypted so that **only its recipient can read it**:
nobody else can tell who it's for or what it says. There's no free text.

It's written only by myGeeKy, with a token scoped to this one repository.
"""


# --------------------------------------------------------------------------- the one write path
class BeaconWriter:
    """Writes `beacon.json`/`README.md` in YOUR `mygeeky-beacon` repo -- and
    nothing else. The URL is built from constants plus your own validated
    login; there is no parameter that could point it anywhere else."""

    ALLOWED_PATHS = (BEACON_PATH, README_PATH)

    def __init__(self, token: str, owner: str, session: requests.Session | None = None):
        if not valid_login(owner):
            raise BeaconError(f"'{owner}' isn't a valid GitHub username.")
        self.owner = owner
        self.session = session or requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "mygeeky-beacon",
            "Authorization": f"Bearer {token}",
        })

    def _url(self, path: str) -> str:
        if path not in self.ALLOWED_PATHS:
            raise BeaconError(f"myGeeKy only ever writes {', '.join(self.ALLOWED_PATHS)}.")
        return f"{API_ROOT}/repos/{self.owner}/{BEACON_REPO}/contents/{path}"

    def read(self) -> dict[str, Any] | None:
        """What's published in your beacon.json right now (None if nothing)."""
        r = self.session.get(self._url(BEACON_PATH), timeout=30)
        if r.status_code != 200:
            return None
        try:
            data = json.loads(base64.b64decode(r.json().get("content") or "").decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def write(self, path: str, text: str, message: str) -> None:
        url = self._url(path)
        current = self.session.get(url, timeout=30)
        body: dict[str, Any] = {"message": message,
                                "content": base64.b64encode(text.encode("utf-8")).decode("ascii")}
        if current.status_code == 200:
            body["sha"] = current.json().get("sha")
            existing = current.json().get("content")
            if existing and base64.b64decode(existing).decode("utf-8", "replace") == text:
                return  # unchanged: no empty commit
        resp = self.session.put(url, json=body, timeout=30)
        if resp.status_code in (401, 403):
            raise BeaconError("GitHub refused the write. Check that your beacon token has "
                              f"'Contents: Read and write' on {self.owner}/{BEACON_REPO} "
                              "(`mygeeky beacon init` sets it up).")
        if resp.status_code == 404:
            raise BeaconError(f"{self.owner}/{BEACON_REPO} doesn't exist, or the token can't see it. "
                              "Run `mygeeky beacon init`.")
        if resp.status_code not in (200, 201):
            raise BeaconError(f"Writing {path} failed: HTTP {resp.status_code} {resp.text[:200]}")

    def publish(self, beacon: dict[str, Any]) -> None:
        self.write(BEACON_PATH, json.dumps(beacon, indent=2) + "\n", "Update myGeeKy beacon")


# --------------------------------------------------------------------------- reading everyone else's
def discover(client: GitHubClient, max_users: int) -> dict[str, dict[str, Any]]:
    """{login: {"pushed_at", "avatar_url"}} for every beacon repo the searches
    find. Two searches: by topic, and by the repo's name -- adding the topic
    takes a manual step (or the GitHub CLI) that people miss, while every
    beacon is named `mygeeky-beacon`. One search call per 100 users each."""
    found: dict[str, dict[str, Any]] = {}
    pages = max(1, -(-max_users // 100))
    for query in (f"topic:{BEACON_TOPIC} fork:false", f"{BEACON_REPO} in:name fork:false"):
        for repo in client.search_repositories(query, max_pages=pages, per_page=100, sort="updated"):
            owner = repo.get("owner") or {}
            login = owner.get("login")
            if ((repo.get("name") or "").lower() != BEACON_REPO or owner.get("type") != "User"
                    or not valid_login(login) or repo.get("private")):
                continue
            found.setdefault(login, {"pushed_at": repo.get("pushed_at") or "",
                                     "avatar_url": owner.get("avatar_url") or ""})
            if len(found) >= max_users:
                return found
    return found


def fetch_beacon(client: GitHubClient, owner: str) -> Any:
    """The raw JSON of `owner`'s beacon, or None. Read-only."""
    data = client.get_repo_file(f"{owner}/{BEACON_REPO}", BEACON_PATH)
    if not data or data.get("encoding") != "base64" or (data.get("size") or 0) > MAX_BEACON_BYTES:
        return None
    try:
        return json.loads(base64.b64decode(data.get("content") or "").decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def load_cache() -> dict[str, Any]:
    if not BEACON_CACHE_FILE.exists():
        return {"fetched_at": None, "users": {}}
    try:
        return json.loads(BEACON_CACHE_FILE.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {"fetched_at": None, "users": {}}


def save_cache(cache: dict[str, Any]) -> None:
    ensure_dirs()
    write_json(BEACON_CACHE_FILE, cache)


def refresh_due(cfg: MyGeekyConfig, cache: dict[str, Any], now: datetime | None = None) -> bool:
    fetched = _parse_time(cache.get("fetched_at"))
    return fetched is None or ((now or _now()) - fetched).total_seconds() >= cfg.beacon_refresh_minutes * 60


def refresh(client: GitHubClient, cfg: MyGeekyConfig, force: bool = False,
            log: Callable[[str], None] = lambda m: None) -> dict[str, Any]:
    """Re-read everyone's beacons; a beacon whose repo hasn't been pushed
    since last time is reused from the cache instead of fetched again."""
    cache = load_cache()
    if not force and not refresh_due(cfg, cache):
        return cache
    me = cfg.github_username.lower()
    old = cache.get("users") or {}
    users: dict[str, Any] = {}
    found = discover(client, cfg.beacon_max_users)
    log(f"found {len(found)} beacon(s)")
    for login, meta in found.items():
        if login.lower() == me:
            continue
        prev = old.get(login)
        if prev and prev.get("pushed_at") == meta["pushed_at"] and prev.get("raw") is not None:
            raw = prev["raw"]
        else:
            raw = fetch_beacon(client, login)
        if raw is None:
            continue
        users[login] = {**meta, "raw": raw}
    cache = {"fetched_at": _now().isoformat(), "users": users}
    save_cache(cache)
    return cache


def _parsed_users(cache: dict[str, Any], cfg: MyGeekyConfig) -> list[dict[str, Any]]:
    blocked = {u.lower() for u in cfg.beacon_blocked}
    out = []
    for login, entry in (cache.get("users") or {}).items():
        if login.lower() in blocked or login.lower() == cfg.github_username.lower():
            continue
        parsed = parse_beacon(entry.get("raw"), login, cfg.beacon_gesture_ttl_days)
        if parsed:
            parsed["avatar_url"] = entry.get("avatar_url", "")
            out.append(parsed)
    return out


def recipient_beacon(cache: dict[str, Any], cfg: MyGeekyConfig, login: str) -> dict[str, Any] | None:
    for user in _parsed_users(cache, cfg):
        if user["owner"].lower() == login.lower():
            return user
    return None


def _sent_to(my_beacon: dict[str, Any], gesture: str | None = None) -> set[str]:
    return {g.get("to", "").lower() for g in my_beacon.get("sent", []) if gesture is None or g.get("type") == gesture}


def gesture_text(g: dict[str, Any]) -> str:
    emoji, verb = (LEGACY_GESTURES if g.get("legacy") else GESTURES)[g["type"]]
    if g.get("repo"):
        return f"{emoji} used {g['repo']} in their work" if g["type"] == "used" else f"{emoji} {verb} to {g['repo']}"
    return f"{emoji} {verb}"


def _received(cache: dict[str, Any], cfg: MyGeekyConfig, my_beacon: dict[str, Any],
              private_key: str | None) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """[(their parsed beacon, the signals they sent you that you may see)].
    🤝 collaborate only counts when you've chosen it for them too."""
    me = cfg.github_username
    my_collab = _sent_to(my_beacon, "collab")
    muted = {u.lower() for u in cfg.beacon_muted}
    out = []
    for user in _parsed_users(cache, cfg):
        if user["owner"].lower() in muted:
            out.append((user, []))
            continue
        got = open_signals(user, me, private_key, cfg.beacon_gesture_ttl_days) if private_key else \
            [g for g in user.get("gestures", []) if g["to"].lower() == me.lower()]
        visible = [g for g in got if g["type"] not in MUTUAL_ONLY or user["owner"].lower() in my_collab]
        out.append((user, visible))
    return out


def inbox(cache: dict[str, Any], cfg: MyGeekyConfig, my_beacon: dict[str, Any],
          private_key: str | None = None) -> list[dict[str, Any]]:
    """Signals other people sent you, newest first, at most MAX_PER_SENDER per
    person. `mutual` marks a collaboration you both chose."""
    out = []
    for user, signals in _received(cache, cfg, my_beacon, private_key):
        for g in sorted(signals, key=lambda g: g["at"], reverse=True)[:MAX_PER_SENDER]:
            mutual = g["type"] in MUTUAL_ONLY
            out.append({
                "from": user["owner"],
                "avatar_url": user["avatar_url"],
                "profile_url": f"https://github.com/{user['owner']}",
                "type": g["type"],
                "emoji": (LEGACY_GESTURES if g.get("legacy") else GESTURES)[g["type"]][0],
                "text": MUTUAL_TEXT if mutual else gesture_text(g),
                "repo": g.get("repo", ""),
                "at": g["at"],
                "mutual": mutual,
            })
    return sorted(out, key=lambda r: r["at"], reverse=True)


def people(cache: dict[str, Any], cfg: MyGeekyConfig, my_beacon: dict[str, Any],
           my_terms: Iterable[str] | None = None, private_key: str | None = None) -> list[dict[str, Any]]:
    """Fellow myGeeKy users, those sharing the most interests with you first."""
    mine = set(clean_interests(my_terms if my_terms is not None else cfg.topics + cfg.keywords + cfg.languages))
    sent = _sent_to(my_beacon)
    muted = {u.lower() for u in cfg.beacon_muted}
    out = []
    for user, signals in _received(cache, cfg, my_beacon, private_key):
        shared = [i for i in user["interests"] if i in mine]
        out.append({
            "login": user["owner"],
            "avatar_url": user["avatar_url"],
            "profile_url": f"https://github.com/{user['owner']}",
            "status": QUIET_LABEL if user.get("quiet") else STATUSES.get(user["status"], ""),
            "interests": user["interests"],
            "shared": shared,
            "signalled_you": bool(signals),
            "you_signalled": user["owner"].lower() in sent,
            "can_receive": bool(user.get("keys")) and not user.get("quiet"),
            "quiet": user.get("quiet", False),
            "muted": user["owner"].lower() in muted,
        })
    return sorted(out, key=lambda p: (p["signalled_you"], len(p["shared"])), reverse=True)


def suggestion_signals(cache: dict[str, Any], cfg: MyGeekyConfig, private_key: str | None = None) -> dict[str, str]:
    """{login_lower: source} for the suggestion search: people who signalled
    you, and fellow users sharing at least one interest with you."""
    out: dict[str, str] = {}
    for p in people(cache, cfg, load_my_beacon(), private_key=private_key):
        if p["signalled_you"]:
            out[p["login"].lower()] = "signalled_you"
        elif p["shared"]:
            out[p["login"].lower()] = "mygeeky_user"
    return out


def private_key_or_none(cfg: MyGeekyConfig) -> str | None:
    """This computer's private key if Signals is set up (never creates one quietly
    when it isn't)."""
    if not cfg.beacon_enabled or not cfg.github_username:
        return None
    try:
        return my_keypair(cfg.github_username)[0]
    except BeaconError:
        return None


# --------------------------------------------------------------------------- send / publish (shared by CLI and panel)
def writer_for(cfg: MyGeekyConfig) -> BeaconWriter:
    from . import auth
    token = auth.get_beacon_token(cfg.github_username)
    if not cfg.beacon_enabled or not token:
        raise BeaconError("Signals aren't set up on this computer yet -- run `mygeeky beacon init`.")
    return BeaconWriter(token, cfg.github_username)


def publish(cfg: MyGeekyConfig, beacon: dict[str, Any], writer: BeaconWriter | None = None) -> None:
    """Publish first, then save locally -- a failed write leaves no signal
    that looks sent but isn't. Keys and boxes from your other computers stay."""
    writer = writer or writer_for(cfg)
    _, my_pub = my_keypair(cfg.github_username)
    beacon = prune(beacon, cfg.beacon_gesture_ttl_days)
    writer.publish(public_beacon(beacon, cfg, my_pub, writer.read()))
    save_my_beacon({**beacon, "published_key": my_pub})


def ensure_published(cfg: MyGeekyConfig, writer: BeaconWriter | None = None) -> bool:
    """After an update: publish this computer's key (and the private-signals
    README) once, so others can send to you. True if it published."""
    if not cfg.beacon_enabled or not cfg.github_username:
        return False
    beacon = load_my_beacon()
    _, my_pub = my_keypair(cfg.github_username)
    if beacon.get("published_key") == my_pub:
        return False
    writer = writer or writer_for(cfg)
    writer.write(README_PATH, BEACON_README, "Signals are private now")
    publish(cfg, beacon, writer)
    return True


def send(cfg: MyGeekyConfig, to: str, gesture: str, repo: str | None = None,
         writer: BeaconWriter | None = None, cache: dict[str, Any] | None = None) -> dict[str, Any]:
    writer = writer or writer_for(cfg)  # fail before changing anything
    recipient = recipient_beacon(cache if cache is not None else load_cache(), cfg, to)
    beacon = add_signal(load_my_beacon(), cfg.github_username, to, gesture, repo, cfg, recipient)
    publish(cfg, beacon, writer)
    return beacon


def unsend(cfg: MyGeekyConfig, to: str, gesture: str | None = None,
           writer: BeaconWriter | None = None) -> int:
    before = load_my_beacon()
    after = remove_signals(before, to, gesture)
    removed = len(before["sent"]) - len(after["sent"])
    if removed:
        publish(cfg, after, writer)
    return removed


def set_quiet(cfg: MyGeekyConfig, quiet: bool, writer: BeaconWriter | None = None) -> None:
    from .config import save_config
    cfg.beacon_quiet = quiet
    publish(cfg, load_my_beacon(), writer)
    save_config(cfg)


def set_muted(cfg: MyGeekyConfig, login: str, mute: bool = True) -> None:
    """Hide (or show again) someone's signals. They're never told."""
    from .config import save_config
    others = [u for u in cfg.beacon_muted if u.lower() != login.lower()]
    cfg.beacon_muted = others + [login] if mute else others
    save_config(cfg)


# --------------------------------------------------------------------------- one-time setup (CLI `beacon init` and the installer)
def _gh(*args: str):
    from . import winproc
    return winproc.run(["gh", *args], capture_output=True, text=True)


def ensure_repo(cfg: MyGeekyConfig, client: GitHubClient, create: bool) -> list[str]:
    """Make sure <you>/mygeeky-beacon exists, is public and carries the
    topic others search for. Creates it with the GitHub CLI only if `create`."""
    import shutil
    repo = f"{cfg.github_username}/{BEACON_REPO}"
    has_gh = shutil.which("gh") is not None
    notes: list[str] = []
    info = client.get_repo(repo)
    if info is None:
        if not has_gh:
            raise BeaconError(f"Create the public repo {repo} first: open {NEW_REPO_URL} "
                              "and click 'Create repository', then try again.")
        if not create:
            raise BeaconError(f"{repo} doesn't exist yet.")
        r = _gh("repo", "create", repo, "--public", "--description", "My myGeeKy beacon (private signals)")
        if r.returncode != 0:
            raise BeaconError(f"`gh repo create` failed: {r.stderr.strip()}")
        notes.append(f"Created the public repo https://github.com/{repo}")
        info = {"topics": []}
    elif info.get("private"):
        raise BeaconError(f"{repo} is private, so nobody could find your beacon. Make it public first.")
    if BEACON_TOPIC not in (info.get("topics") or []):
        if has_gh and _gh("repo", "edit", repo, "--add-topic", BEACON_TOPIC).returncode == 0:
            notes.append(f"Tagged it with the '{BEACON_TOPIC}' topic, so other users can find it.")
        else:
            notes.append(f"Optional: add the topic '{BEACON_TOPIC}' to {repo} (repo page -> About -> "
                         "gear icon). Others find your beacon by its name anyway.")
    return notes


def go_live(cfg: MyGeekyConfig, writer: BeaconWriter | None = None) -> None:
    """Turn beacons on and publish (with `writer`, or the stored beacon token).
    Saves `beacon_enabled` only once the first publish worked."""
    from .config import save_config
    cfg.beacon_enabled = True
    try:
        writer = writer or writer_for(cfg)
        writer.write(README_PATH, BEACON_README, "Explain this myGeeKy beacon")
        publish(cfg, load_my_beacon(), writer)
    except Exception:
        cfg.beacon_enabled = False
        raise
    save_config(cfg)


WITHDRAWN_README = """# mygeeky-beacon

This myGeeKy beacon has been withdrawn: its owner left Signals. It holds no keys
and no signals, so nothing can be sent here. (Earlier versions remain in this
repository's history until the owner deletes the repository.)
"""


def withdraw(cfg: MyGeekyConfig, writer: BeaconWriter | None = None) -> None:
    """Leave Signals: publish an empty beacon (no keys, no signals, no interests),
    so other users stop seeing you and can't send you anything. The repo itself
    stays: deleting a repository needs a permission myGeeKy never asks for."""
    from . import auth
    if writer is None:
        token = auth.get_beacon_token(cfg.github_username)
        if not token:
            raise BeaconError("There's no Signals token on this computer, so the beacon can't be withdrawn from here.")
        writer = BeaconWriter(token, cfg.github_username)
    writer.publish({"mygeeky_beacon": SCHEMA_VERSION, "keys": [], "status": "", "quiet": True,
                    "interests": [], "sealed": [], "withdrawn": True})
    writer.write(README_PATH, WITHDRAWN_README, "myGeeKy beacon withdrawn")


# --------------------------------------------------------------------------- the setup guide (one text for CLI, installer and README)
NEW_REPO_URL = ("https://github.com/new?name=mygeeky-beacon&visibility=public"
                "&description=My+myGeeKy+beacon+(private+signals)")
TOKEN_URL = "https://github.com/settings/personal-access-tokens/new"


def repo_steps(user: str) -> list[str]:
    return [
        f"Open {NEW_REPO_URL}",
        "  (the name 'mygeeky-beacon' and 'Public' are already filled in)",
        f"Check that the owner is {user} and the visibility is Public, then click 'Create repository'.",
        "Leave it empty: no README needed. myGeeKy writes the files itself.",
    ]


def token_steps(user: str) -> list[str]:
    return [
        "This is a SECOND token, separate from your read-only one, and it needs the repo from step 1.",
        f"Open {TOKEN_URL}",
        f"Token name: mygeeky-beacon. Resource owner: {user}.",
        "Expiration: pick a long one (e.g. 90 days or a year). myGeeKy reminds you a week before it ends.",
        "Repository access: choose 'Only select repositories', then pick mygeeky-beacon.",
        "  (the permission list only appears after you pick the repo)",
        "Permissions: under 'Repositories' click 'Add permissions' and choose 'Contents'",
        "  (older page: open 'Repository permissions' and find 'Contents').",
        "Set Contents to 'Read and write'. 'Metadata: Read-only' is added by itself; that's fine.",
        "Don't add anything else. Click 'Generate token' and copy it (starts with github_pat_).",
    ]


def check(cfg: MyGeekyConfig, client: GitHubClient) -> list[tuple[bool, str]]:
    """Diagnose a Signals setup without writing anything: [(ok, message), ...]
    in the order a user has to fix them."""
    from . import auth
    user = cfg.github_username
    if not user:
        return [(False, "No GitHub username set. Run `mygeeky init` first.")]
    repo = f"{user}/{BEACON_REPO}"
    results: list[tuple[bool, str]] = []
    info = client.get_repo(repo)
    if info is None:
        return [(False, f"The repo {repo} doesn't exist yet. Run `mygeeky beacon init` (step 1 creates it).")]
    if info.get("private"):
        return [(False, f"{repo} is private. Make it public (Settings -> Danger Zone -> Change visibility).")]
    results.append((True, f"Repo https://github.com/{repo} exists and is public."))
    token = auth.get_beacon_token(user)
    if not token:
        results.append((False, "No Signals token stored on this computer. Run `mygeeky beacon init` (step 2)."))
    else:
        r = requests.get(f"{API_ROOT}/repos/{repo}", timeout=30,
                         headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        if r.status_code == 401:
            results.append((False, "The stored Signals token is invalid or expired. Run `mygeeky beacon init` "
                                   "again to paste a new one."))
        elif r.status_code == 404:
            results.append((False, f"The stored Signals token can't see {repo}. It must be limited to "
                                   "'Only select repositories' -> mygeeky-beacon."))
        else:
            results.append((True, "A Signals token is stored and can see the repo."))
    raw = fetch_beacon(client, user)
    parsed = parse_beacon(raw, user, cfg.beacon_gesture_ttl_days) if raw is not None else None
    if parsed is None:
        results.append((False, f"beacon.json isn't published in {repo} yet, so nobody can see you. "
                               "Run `mygeeky beacon init` to publish it."))
    elif parsed["version"] < SCHEMA_VERSION or not parsed["keys"]:
        results.append((False, "Your beacon is from an older myGeeKy, so others can't send you private "
                               "signals yet. Open the panel (it updates it by itself) or run "
                               "`mygeeky beacon publish`."))
    else:
        try:
            mine = my_keypair(user)[1] in parsed["keys"]
        except BeaconError:
            mine = False
        results.append((mine, f"beacon.json is published with {len(parsed['keys'])} key(s) and "
                              f"{len(parsed['sealed'])} sealed signal(s)." if mine else
                              "This computer's key isn't in your beacon yet. Run `mygeeky beacon publish`."))
    if not cfg.beacon_enabled:
        results.append((False, "Signals are turned off in this computer's settings. `mygeeky beacon init` "
                               "turns them on."))
    return results
