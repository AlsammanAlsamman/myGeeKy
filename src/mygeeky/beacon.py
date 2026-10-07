"""Beacons: non-verbal signals between myGeeKy users, carried by GitHub itself.

There is no myGeeKy server. Every user who opts in (`mygeeky beacon init`)
gets a small PUBLIC repo, `<you>/mygeeky-beacon`, tagged with the topic
`mygeeky-beacon`, holding one file, `beacon.json`:

    {"mygeeky_beacon": 1, "status": "open-to-collab",
     "interests": ["gwas", "snakemake"],
     "gestures": [{"to": "bob", "type": "wave", "at": "2026-10-06T09:00:00+00:00"}]}

Other users find beacons with plain repository searches for that topic and
for the repo name (read-only; the topic is easy to forget), read the ones that name them, and show the gestures as
incoming signals. Two people who have each signalled the other get a
"handshake".

Deliberate constraints:

- Non-verbal only. Gestures and statuses come from fixed vocabularies
  below; there is no free-text field anyone can write into your panel, so
  there is nothing to spam or harass with and nothing to moderate.
- Everything is public. Anyone can read anyone's beacon -- the CLI and the
  panel say so plainly.
- Other people's beacons are untrusted input: size-capped, schema-checked,
  logins/repos validated against GitHub's own name rules, unknown gesture
  types dropped, and the owner is taken from the repo, never from the file.
- The ONE write myGeeKy ever makes lives in `BeaconWriter` below: a PUT of
  `beacon.json` (or its README) in YOUR OWN `mygeeky-beacon` repo, with a
  separate fine-grained token scoped to that single repo. The main API
  client (github_client.py) stays read-only, and nothing anywhere can
  follow anyone.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

import requests

from .config import BEACON_CACHE_FILE, MY_BEACON_FILE, MyGeekyConfig, ensure_dirs
from .github_client import API_ROOT, GitHubClient

BEACON_REPO = "mygeeky-beacon"
BEACON_TOPIC = "mygeeky-beacon"
BEACON_PATH = "beacon.json"
README_PATH = "README.md"
SCHEMA_VERSION = 1
MAX_BEACON_BYTES = 64 * 1024
MAX_GESTURES_READ = 300       # per beacon -- anything beyond is ignored
MAX_PER_SENDER = 5            # incoming gestures shown per person
MAX_INTERESTS = 12

# type -> (emoji, how it reads when someone sends it to you)
GESTURES: dict[str, tuple[str, str]] = {
    "wave": ("👋", "waved at you"),
    "learn": ("📚", "learns from your work"),
    "collab": ("🤝", "would like to collaborate"),
    "watching": ("👀", "is following your progress"),
    "kudos": ("🔥", "gave kudos"),             # carries a repo: "gave kudos to <repo>"
}
REPO_GESTURES = {"kudos"}

# status -> label; "" means no status
STATUSES: dict[str, str] = {
    "": "",
    "open-to-collab": "🤝 open to collaborate",
    "learning": "🌱 learning something new",
    "heads-down": "🎧 heads-down",
    "seeking-reviewers": "🔍 looking for reviewers",
    "mentoring": "🧭 happy to mentor",
}

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


# --------------------------------------------------------------------------- parsing untrusted beacons
def parse_beacon(raw: Any, owner: str, ttl_days: int, now: datetime | None = None) -> dict[str, Any] | None:
    """A validated copy of someone's beacon, or None if it isn't one.
    `owner` comes from the repo the file was read from -- a beacon can't
    claim to be someone else's."""
    if not isinstance(raw, dict) or raw.get("mygeeky_beacon") != SCHEMA_VERSION or not valid_login(owner):
        return None
    now = now or _now()
    oldest = now - timedelta(days=ttl_days)
    status = raw.get("status") if raw.get("status") in STATUSES else ""
    interests = clean_interests(raw["interests"] if isinstance(raw.get("interests"), list) else [])
    gestures = []
    raw_gestures = raw.get("gestures") if isinstance(raw.get("gestures"), list) else []
    for g in raw_gestures[:MAX_GESTURES_READ]:
        if not isinstance(g, dict) or g.get("type") not in GESTURES or not valid_login(g.get("to")):
            continue
        at = _parse_time(g.get("at"))
        if at is None or at < oldest or at > now + timedelta(days=1):
            continue
        clean = {"to": g["to"], "type": g["type"], "at": at.isoformat()}
        if g["type"] in REPO_GESTURES:
            if not valid_repo(g.get("repo")):
                continue
            clean["repo"] = g["repo"]
        gestures.append(clean)
    return {"owner": owner, "status": status, "interests": interests, "gestures": gestures}


# --------------------------------------------------------------------------- your own beacon (local source of truth)
def empty_beacon() -> dict[str, Any]:
    return {"mygeeky_beacon": SCHEMA_VERSION, "status": "", "interests": [], "gestures": []}


def load_my_beacon() -> dict[str, Any]:
    if not MY_BEACON_FILE.exists():
        return empty_beacon()
    try:
        data = json.loads(MY_BEACON_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return empty_beacon()
    base = empty_beacon()
    base.update({k: v for k, v in data.items() if k in base})
    return base


def save_my_beacon(beacon: dict[str, Any]) -> None:
    ensure_dirs()
    MY_BEACON_FILE.write_text(json.dumps(beacon, indent=2), encoding="utf-8")


def prune(beacon: dict[str, Any], ttl_days: int, now: datetime | None = None) -> dict[str, Any]:
    """Drop expired gestures, so the public file doesn't grow forever."""
    oldest = (now or _now()) - timedelta(days=ttl_days)
    kept = [g for g in beacon.get("gestures", []) if (_parse_time(g.get("at")) or oldest) > oldest]
    return {**beacon, "gestures": kept}


def gestures_sent_today(beacon: dict[str, Any], now: datetime | None = None) -> int:
    today = (now or _now()).date()
    return sum(1 for g in beacon.get("gestures", []) if (ts := _parse_time(g.get("at"))) and ts.date() == today)


def add_gesture(beacon: dict[str, Any], me: str, to: str, gesture: str, repo: str | None,
                cfg: MyGeekyConfig, now: datetime | None = None) -> dict[str, Any]:
    """A new beacon with the gesture added. Re-sending the same gesture to
    the same person (and repo) just refreshes its date instead of stacking."""
    now = now or _now()
    if gesture not in GESTURES:
        raise BeaconError(f"Unknown gesture '{gesture}'. Choose one of: {', '.join(GESTURES)}.")
    if not valid_login(to):
        raise BeaconError(f"'{to}' isn't a valid GitHub username.")
    if to.lower() == me.lower():
        raise BeaconError("You can't signal yourself.")
    if to.lower() in {u.lower() for u in cfg.beacon_blocked}:
        raise BeaconError(f"You've blocked {to}; unblock them first.")
    if gesture in REPO_GESTURES:
        if not valid_repo(repo):
            raise BeaconError(f"'{gesture}' needs a repo, as owner/name.")
    else:
        repo = None
    if gestures_sent_today(beacon, now) >= cfg.beacon_daily_limit:
        raise BeaconError(f"Daily limit reached ({cfg.beacon_daily_limit} signals). Try again tomorrow.")
    beacon = prune(beacon, cfg.beacon_gesture_ttl_days, now)
    same = lambda g: (g.get("to", "").lower() == to.lower() and g.get("type") == gesture  # noqa: E731
                      and g.get("repo") == repo)
    gestures = [g for g in beacon["gestures"] if not same(g)]
    new = {"to": to, "type": gesture, "at": now.isoformat(timespec="seconds")}
    if repo:
        new["repo"] = repo
    gestures.append(new)
    return {**beacon, "gestures": gestures}


def remove_gestures(beacon: dict[str, Any], to: str, gesture: str | None = None) -> dict[str, Any]:
    kept = [g for g in beacon.get("gestures", [])
            if not (g.get("to", "").lower() == to.lower() and (gesture is None or g.get("type") == gesture))]
    return {**beacon, "gestures": kept}


def public_beacon(beacon: dict[str, Any], cfg: MyGeekyConfig) -> dict[str, Any]:
    """Exactly what gets published -- nothing but these four fields."""
    return {
        "mygeeky_beacon": SCHEMA_VERSION,
        "status": cfg.beacon_status if cfg.beacon_status in STATUSES else "",
        "interests": clean_interests(cfg.topics + cfg.keywords + cfg.languages) if cfg.beacon_share_interests else [],
        "gestures": prune(beacon, cfg.beacon_gesture_ttl_days)["gestures"],
    }


BEACON_README = """\
# mygeeky-beacon

This is a public [myGeeKy](https://github.com/AlsammanAlsamman/myGeeKy) beacon.

`beacon.json` holds non-verbal signals (👋 wave, 📚 learn-from, 🤝 collab,
👀 watching, 🔥 kudos) that this account sent to other GitHub users, plus an
optional status and a few interest tags. myGeeKy users who are named here
see the signals in their panel. There's no free text, and everything is public.

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
        return json.loads(BEACON_CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"fetched_at": None, "users": {}}


def save_cache(cache: dict[str, Any]) -> None:
    ensure_dirs()
    BEACON_CACHE_FILE.write_text(json.dumps(cache), encoding="utf-8")


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


def _sent_to(my_beacon: dict[str, Any]) -> set[str]:
    return {g.get("to", "").lower() for g in my_beacon.get("gestures", [])}


def gesture_text(g: dict[str, Any]) -> str:
    emoji, verb = GESTURES[g["type"]]
    return f"{emoji} {verb}" + (f" to {g['repo']}" if g.get("repo") else "")


def inbox(cache: dict[str, Any], cfg: MyGeekyConfig, my_beacon: dict[str, Any]) -> list[dict[str, Any]]:
    """Signals other people sent you, newest first, at most MAX_PER_SENDER
    per person; `mutual` marks a handshake (you've signalled them too)."""
    me = cfg.github_username.lower()
    sent = _sent_to(my_beacon)
    out = []
    for user in _parsed_users(cache, cfg):
        mine = sorted((g for g in user["gestures"] if g["to"].lower() == me), key=lambda g: g["at"], reverse=True)
        for g in mine[:MAX_PER_SENDER]:
            out.append({
                "from": user["owner"],
                "avatar_url": user["avatar_url"],
                "profile_url": f"https://github.com/{user['owner']}",
                "type": g["type"],
                "emoji": GESTURES[g["type"]][0],
                "text": gesture_text(g),
                "repo": g.get("repo", ""),
                "at": g["at"],
                "mutual": user["owner"].lower() in sent,
            })
    return sorted(out, key=lambda r: r["at"], reverse=True)


def people(cache: dict[str, Any], cfg: MyGeekyConfig, my_beacon: dict[str, Any],
           my_terms: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Fellow myGeeKy users, those sharing the most interests with you first."""
    me = cfg.github_username.lower()
    mine = set(clean_interests(my_terms if my_terms is not None else cfg.topics + cfg.keywords + cfg.languages))
    sent = _sent_to(my_beacon)
    out = []
    for user in _parsed_users(cache, cfg):
        shared = [i for i in user["interests"] if i in mine]
        received = any(g["to"].lower() == me for g in user["gestures"])
        out.append({
            "login": user["owner"],
            "avatar_url": user["avatar_url"],
            "profile_url": f"https://github.com/{user['owner']}",
            "status": STATUSES.get(user["status"], ""),
            "interests": user["interests"],
            "shared": shared,
            "signalled_you": received,
            "you_signalled": user["owner"].lower() in sent,
        })
    return sorted(out, key=lambda p: (p["signalled_you"], len(p["shared"])), reverse=True)


def suggestion_signals(cache: dict[str, Any], cfg: MyGeekyConfig) -> dict[str, str]:
    """{login_lower: source} for the suggestion search: people who signalled
    you, and fellow users sharing at least one interest with you."""
    out: dict[str, str] = {}
    for p in people(cache, cfg, empty_beacon()):
        if p["signalled_you"]:
            out[p["login"].lower()] = "signalled_you"
        elif p["shared"]:
            out[p["login"].lower()] = "mygeeky_user"
    return out


# --------------------------------------------------------------------------- send / publish (shared by CLI and panel)
def writer_for(cfg: MyGeekyConfig) -> BeaconWriter:
    from . import auth
    token = auth.get_beacon_token(cfg.github_username)
    if not cfg.beacon_enabled or not token:
        raise BeaconError("Beacons aren't set up on this machine yet -- run `mygeeky beacon init`.")
    return BeaconWriter(token, cfg.github_username)


def publish(cfg: MyGeekyConfig, beacon: dict[str, Any], writer: BeaconWriter | None = None) -> None:
    """Publish first, then save locally -- a failed write leaves no gesture
    that looks sent but isn't."""
    (writer or writer_for(cfg)).publish(public_beacon(beacon, cfg))
    save_my_beacon(prune(beacon, cfg.beacon_gesture_ttl_days))


def send(cfg: MyGeekyConfig, to: str, gesture: str, repo: str | None = None,
         writer: BeaconWriter | None = None) -> dict[str, Any]:
    writer = writer or writer_for(cfg)  # fail before changing anything
    beacon = add_gesture(load_my_beacon(), cfg.github_username, to, gesture, repo, cfg)
    publish(cfg, beacon, writer)
    return beacon


def unsend(cfg: MyGeekyConfig, to: str, gesture: str | None = None,
           writer: BeaconWriter | None = None) -> int:
    before = load_my_beacon()
    after = remove_gestures(before, to, gesture)
    removed = len(before["gestures"]) - len(after["gestures"])
    if removed:
        publish(cfg, after, writer)
    return removed


# --------------------------------------------------------------------------- one-time setup (CLI `beacon init` and the installer)
def _gh(*args: str):
    import subprocess
    return subprocess.run(["gh", *args], capture_output=True, text=True)


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
        r = _gh("repo", "create", repo, "--public", "--description", "My myGeeKy beacon (non-verbal signals)")
        if r.returncode != 0:
            raise BeaconError(f"`gh repo create` failed: {r.stderr.strip()}")
        notes.append(f"Created the public repo https://github.com/{repo}")
        info = {"topics": []}
    elif info.get("private"):
        raise BeaconError(f"{repo} is private, so nobody could see your beacon. Make it public first.")
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


# --------------------------------------------------------------------------- the setup guide (one text for CLI, installer and README)
NEW_REPO_URL = ("https://github.com/new?name=mygeeky-beacon&visibility=public"
                "&description=My+myGeeKy+beacon+(non-verbal+signals)")
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
    else:
        results.append((True, f"beacon.json is published ({len(parsed['gestures'])} signal(s) sent)."))
    if not cfg.beacon_enabled:
        results.append((False, "Signals are turned off in this computer's settings. `mygeeky beacon init` "
                               "turns them on."))
    return results
