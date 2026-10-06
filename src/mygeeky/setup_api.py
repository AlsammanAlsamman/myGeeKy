"""Non-interactive setup steps for the graphical installer.

The installer (gui/setup_wizard.py, also shipped as MyGeeKySetup.exe) may
run on a machine where myGeeKy isn't importable in its own process -- it
installs myGeeKy into the user's Python first. So every step after the
install runs here, inside that Python:

    python -m mygeeky.setup_api <action>      (JSON request on stdin)

and answers with one JSON object on stdout: {"ok": true, ...} or
{"ok": false, "error": "..."}. Secrets (tokens) only ever travel on stdin,
never on the command line, where other processes could read them.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

from . import __version__

GH_DIRS = (
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "GitHub CLI",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "GitHub CLI",
)


def _ensure_gh_on_path() -> None:
    """A GitHub CLI installed a moment ago by the installer isn't on this
    process's PATH yet; sync.py and beacon.py look it up with shutil.which."""
    if shutil.which("gh"):
        return
    for d in GH_DIRS:
        if (d / "gh.exe").exists():
            os.environ["PATH"] = f"{d}{os.pathsep}{os.environ.get('PATH', '')}"
            return


def _split(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [s.strip() for s in str(value or "").split(",") if s.strip()]


def status(req: dict[str, Any]) -> dict[str, Any]:
    from . import auth, sync
    from .config import CONFIG_FILE, load_config
    cfg = load_config()
    user = cfg.github_username
    return {
        "version": __version__,
        "configured": CONFIG_FILE.exists() and bool(user),
        "github_username": user,
        "cv_path": cfg.cv_path,
        "orcid_id": cfg.orcid_id,
        "scholar_id": cfg.scholar_id,
        "languages": cfg.languages,
        "topics": cfg.topics,
        "keywords": cfg.keywords,
        "token_source": auth.token_source(user) if user else "none",
        "gh": shutil.which("gh") is not None,
        "sync_repo": cfg.sync_repo,
        "sync_initialized": sync.is_initialized(),
        "beacon_enabled": cfg.beacon_enabled,
        "beacon_token": bool(user and auth.get_beacon_token(user)),
    }


def save_profile(req: dict[str, Any]) -> dict[str, Any]:
    from . import scholar
    from .config import CV_TEXT_FILE, load_config, save_config
    from .text_utils import load_cv_text
    cfg = load_config()
    username = str(req.get("github_username") or "").strip()
    if not username:
        return {"ok": False, "error": "Your GitHub username is required."}
    cfg.github_username = username
    notes = []
    cv_path = str(req.get("cv_path") or "").strip()
    if cv_path and cv_path != cfg.cv_path:
        try:
            text = load_cv_text(cv_path)
        except Exception as exc:
            return {"ok": False, "error": f"Couldn't read the CV: {exc}"}
        CV_TEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
        CV_TEXT_FILE.write_text(text, encoding="utf-8")
        cfg.cv_path = cv_path
        notes.append(f"Read your CV ({len(text)} characters).")
    orcid = str(req.get("orcid_id") or "").strip()
    cfg.orcid_id = scholar.normalize_orcid(orcid) if orcid else ""
    if orcid and not cfg.orcid_id:
        return {"ok": False, "error": "That doesn't look like an ORCID iD (e.g. 0000-0002-1825-0097)."}
    gs = str(req.get("scholar_id") or "").strip()
    cfg.scholar_id = scholar.normalize_scholar_id(gs) if gs else ""
    if gs and not cfg.scholar_id:
        return {"ok": False, "error": "That doesn't look like a Google Scholar profile URL."}
    for key in ("languages", "topics", "keywords"):
        if key in req:
            setattr(cfg, key, _split(req[key]))
    save_config(cfg)
    if cfg.orcid_id or cfg.scholar_id:
        try:
            scholar.refresh_scholar_profile(cfg.orcid_id, cfg.scholar_id)
            notes.append("Fetched your publications.")
        except Exception as exc:  # never block setup on a publication lookup
            notes.append(f"Couldn't fetch publications right now ({exc}); `mygeeky profile refresh` retries.")
    return {"ok": True, "notes": notes}


def check_token(req: dict[str, Any]) -> dict[str, Any]:
    """Who a token belongs to -- read-only, nothing stored."""
    from .github_client import GitHubClient
    token = str(req.get("token") or "").strip()
    if not token:
        return {"ok": False, "error": "Empty token."}
    try:
        login = GitHubClient(token, rate_limit_sleep=0).get_authenticated_user().get("login")
    except Exception:
        return {"ok": False, "error": "GitHub didn't accept that token."}
    return {"ok": True, "login": login}


def store_token(req: dict[str, Any]) -> dict[str, Any]:
    import keyring
    from . import auth
    from .config import load_config
    user = load_config().github_username
    checked = check_token(req)
    if not checked["ok"]:
        return checked
    if user and checked["login"].lower() != user.lower():
        return {"ok": False, "error": f"That token belongs to {checked['login']}, not {user}."}
    keyring.set_password(auth.SERVICE_NAME, user, str(req["token"]).strip())
    return {"ok": True, "login": checked["login"]}


def sync_init(req: dict[str, Any]) -> dict[str, Any]:
    from . import sync
    from .config import load_config, save_config
    _ensure_gh_on_path()
    cfg = load_config()
    repo = str(req.get("repo") or f"{cfg.github_username}/mygeeky-data").strip()
    message = sync.init(repo)
    cfg = load_config()  # init may have pulled a synced config
    cfg.sync_repo = repo
    save_config(cfg)
    try:
        sync.push()
    except sync.SyncError as exc:
        message += f"\n(First push will retry later: {exc})"
    return {"ok": True, "message": message}


def beacon_init(req: dict[str, Any]) -> dict[str, Any]:
    import keyring
    from . import auth, beacon
    from .config import load_config
    from .github_client import GitHubClient
    _ensure_gh_on_path()
    cfg = load_config()
    user = cfg.github_username
    token = str(req.get("token") or "").strip()
    if token:
        keyring.set_password(auth.BEACON_SERVICE_NAME, user, token)
    elif not auth.get_beacon_token(user):
        return {"ok": False, "error": "Paste the beacon token first."}
    notes = beacon.ensure_repo(cfg, GitHubClient(auth.get_token(user), rate_limit_sleep=0), create=True)
    beacon.go_live(cfg)
    return {"ok": True, "notes": notes, "url": f"https://github.com/{user}/{beacon.BEACON_REPO}"}


def schedule(req: dict[str, Any]) -> dict[str, Any]:
    from . import scheduler
    message = scheduler.install(confirmed=True)
    return {"ok": not message.startswith("Failed"), "message": message}


ACTIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "status": status,
    "save_profile": save_profile,
    "check_token": check_token,
    "store_token": store_token,
    "sync_init": sync_init,
    "beacon_init": beacon_init,
    "schedule": schedule,
}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    action = ACTIONS.get(argv[0] if argv else "")
    if action is None:
        print(json.dumps({"ok": False, "error": f"Unknown action. Choose one of: {', '.join(ACTIONS)}"}))
        return 2
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        req = json.loads(raw) if raw.strip() else {}
        result = action(req)
    except Exception as exc:  # reported to the installer, never a traceback dump
        result = {"ok": False, "error": str(exc) or exc.__class__.__name__}
    result.setdefault("ok", True)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
