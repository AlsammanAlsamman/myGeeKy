"""Sync your myGeeKy data between computers through a PRIVATE GitHub repo.

The data directory itself becomes a git clone of that repo. What travels:
config, CV text, scholarly profile, suggestion/contribution history,
training data, follow snapshot, exclusions, model history. What never
does (see GITIGNORE): any token (they aren't in the data dir at all), the
pickled model (unpickling a file that came over the network would let a
compromised repo run code on your machine -- it's retrained locally from
the synced training data instead), caches, and logs.

All git operations use your own git/`gh` credentials, never myGeeKy's
read-only API token, so the rest of myGeeKy stays read-only.

Append-only `.jsonl` logs use git's built-in `union` merge driver, so two
machines adding records in the same week merge cleanly instead of
conflicting.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import winproc
from .files import write_text_atomic
from .config import CONFIG_FILE, DATA_DIR, MODEL_FILE, SYNCED_CONFIG_FILE, ensure_dirs

GITIGNORE = """\
# myGeeKy sync: never commit these
model.pkl
*.pkl
avatar_cache/
logs/
activity_cache.json
beacons_cache.json
.path_offered
update_check.json
token_check.json
news.json
headlines.json
hf_models.json
github_achievements.json
keywords.json
trends.json
papers_cache.json
interest_seen.json
*.token
*.lock
*.tmp
*.broken-*
config.previous.json
config.backup-*.json
"""

GITATTRIBUTES = """\
# append-only logs: keep both machines' lines on merge
*.jsonl merge=union
"""

README = """\
# myGeeKy data (private)

Synced automatically by [myGeeKy](https://github.com/mygeeky/myGeeKy)
(`mygeeky sync push` / `mygeeky sync pull`). Keep this repository **private**:
it contains your CV text and your suggestion history.

On a new computer: `pip install mygeeky && mygeeky sync init --repo <owner>/<this-repo>`.
"""


class SyncError(RuntimeError):
    pass


GIT_MISSING = ("Sync needs Git, which isn't installed on this computer. Install Git for Windows from "
               "https://git-scm.com/download/win (the default options are fine), open a new terminal, and "
               "try again. Everything else in myGeeKy works without it.")


def git_exe() -> str | None:
    """git on PATH, or a Git for Windows installed a moment ago (per-user or
    machine-wide) that this process's PATH doesn't know about yet."""
    found = shutil.which("git")
    if found:
        return found
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", r"C:\Program Files")):
        candidate = Path(base) / ("Programs/Git/cmd/git.exe" if "Local" in base else "Git/cmd/git.exe")
        if base and candidate.exists():
            return str(candidate)
    return None


def _require_git() -> None:
    if git_exe() is None:
        raise SyncError(GIT_MISSING)


def _has_gh() -> bool:
    return shutil.which("gh") is not None


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    cmd = [git_exe() or "git"]
    if _has_gh():
        # let git borrow gh's login for github.com without touching the user's git config
        cmd += ["-c", "credential.https://github.com.helper=", "-c",
                "credential.https://github.com.helper=!gh auth git-credential"]
    # a stalled connection (proxy, captive portal) gives up instead of hanging the sync forever
    cmd += ["-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=60"]
    cmd += list(args)
    env = dict(os.environ)
    if not _interactive:
        # background syncs never wait on a password prompt nobody can see; only the
        # `sync init` the user runs themselves may open Git's sign-in window
        env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    timeout = 900 if _interactive else 180
    try:
        result = winproc.run(cmd, cwd=str(cwd or DATA_DIR), capture_output=True, text=True, env=env,
                             timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SyncError(f"`git {args[0] if args else ''}` didn't finish in {timeout // 60} minutes: the network is "
                        "slow or blocking GitHub. Sync will try again later.") from None
    if check and result.returncode != 0:
        raise SyncError(f"`git {' '.join(args)}` failed:\n{result.stderr.strip() or result.stdout.strip()}")
    return result


def is_initialized() -> bool:
    return (DATA_DIR / ".git").exists()


def remote_url(repo: str) -> str:
    return f"https://github.com/{repo}.git"


def new_repo_url(repo: str) -> str:
    """GitHub's 'new repository' page with the name filled in and Private chosen."""
    name = repo.split("/", 1)[-1]
    return (f"https://github.com/new?name={name}&visibility=private"
            "&description=Private+myGeeKy+data+(synced+by+mygeeky)")


def create_steps(repo: str) -> list[str]:
    """How to make the sync repo yourself (one text for the installer and the terminal)."""
    return [f"Open {new_repo_url(repo)} (the name {repo.split('/', 1)[-1]} is filled in).",
            "Choose Private. Don't add a README, .gitignore or license: it must start empty.",
            "Click Create repository, then come back."]


def public_on_github(repo: str) -> bool | None:
    """True if anyone can see the repo (asked without logging in: a private repo
    looks like it doesn't exist), False if not, None if GitHub didn't say."""
    try:
        import requests
        r = requests.get(f"https://api.github.com/repos/{repo}", timeout=15,
                         headers={"Accept": "application/vnd.github+json"})
    except Exception:
        return None
    if r.status_code == 200:
        return not r.json().get("private", False)
    return False if r.status_code == 404 else None


def _repo_exists(repo: str) -> bool:
    if not _has_gh():
        return _git("ls-remote", remote_url(repo), check=False).returncode == 0
    return winproc.run(["gh", "repo", "view", repo, "--json", "visibility"],
                          capture_output=True, text=True).returncode == 0


def _repo_is_private(repo: str) -> bool | None:
    if not _has_gh():
        return False if public_on_github(repo) else None
    r = winproc.run(["gh", "repo", "view", repo, "--json", "visibility", "-q", ".visibility"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return r.stdout.strip().upper() == "PRIVATE"


def _create_private_repo(repo: str) -> None:
    if not _has_gh():
        raise SyncError(f"The private repo {repo} doesn't exist yet. Create it on GitHub:\n"
                        + "\n".join(f"  {i}. {step}" for i, step in enumerate(create_steps(repo), 1))
                        + "\nThen try again.")
    r = winproc.run(["gh", "repo", "create", repo, "--private",
                        "--description", "Private myGeeKy data (synced by mygeeky)"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SyncError(f"`gh repo create` failed:\n{r.stderr.strip()}")


def _write_meta_files() -> None:
    for name, content in ((".gitignore", GITIGNORE), (".gitattributes", GITATTRIBUTES), ("README.md", README)):
        path = DATA_DIR / name
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")


def export_config() -> None:
    from .config import _readable
    if _readable(CONFIG_FILE):            # never spread a damaged config to the other computers
        write_text_atomic(SYNCED_CONFIG_FILE, CONFIG_FILE.read_text(encoding="utf-8-sig"))


def import_config() -> bool:
    from .config import _readable
    if not SYNCED_CONFIG_FILE.exists() or not _readable(SYNCED_CONFIG_FILE):
        return False                      # a damaged synced copy never replaces a good local one
    write_text_atomic(CONFIG_FILE, SYNCED_CONFIG_FILE.read_text(encoding="utf-8-sig"))
    return True


def _commit_local(message: str) -> bool:
    export_config()
    _write_meta_files()
    if not _git("config", "user.email", check=False).stdout.strip():
        _git("config", "user.name", "myGeeKy sync")
        _git("config", "user.email", "mygeeky-sync@users.noreply.github.com")
    _git("add", "-A")
    if not _git("status", "--porcelain").stdout.strip():
        return False
    _git("commit", "-q", "-m", message)
    return True


def _remote_has_main() -> bool:
    return bool(_git("ls-remote", "--heads", "origin", "main", check=False).stdout.strip())


def _stamp() -> str:
    return f"{platform.node() or 'unknown-host'} {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"


_interactive = False     # True only inside init(): the user is there to sign in to Git


def init(repo: str) -> str:
    """Turn the data dir into a clone of private GitHub repo `repo` ("owner/name"),
    creating the repo (private) if it doesn't exist yet."""
    global _interactive
    _interactive = True
    try:
        return _init(repo)
    finally:
        _interactive = False


def _init(repo: str) -> str:
    if "/" not in repo:
        raise SyncError("Give the repo as owner/name, e.g. octocat/mygeeky-data.")
    if public_on_github(repo):   # checked first, with or without the GitHub CLI: your CV must never go public
        raise SyncError(f"https://github.com/{repo} is PUBLIC. myGeeKy only syncs to a private repo: make it "
                        "private (its Settings -> Danger Zone -> Change visibility) or pick another name.")
    _require_git()
    ensure_dirs()
    messages = []

    if not _repo_exists(repo):
        _create_private_repo(repo)
        messages.append(f"Created private repo https://github.com/{repo}")
    elif _repo_is_private(repo) is False:
        raise SyncError(f"https://github.com/{repo} is PUBLIC. myGeeKy only syncs to a private repo -- "
                        "make it private (Settings -> Danger Zone) or pick another name.")

    if is_initialized():
        if "origin" in _git("remote").stdout.split():
            _git("remote", "set-url", "origin", remote_url(repo))
        else:
            _git("remote", "add", "origin", remote_url(repo))
    else:
        _git("init", "-q", "-b", "main")
        _git("remote", "add", "origin", remote_url(repo))

    _git("fetch", "-q", "origin")
    if _remote_has_main() and not _git("rev-parse", "--verify", "-q", "HEAD", check=False).stdout.strip():
        # A fresh machine joining existing synced data: keep anything local
        # in a backup, then take the repo's version.
        local_files = [p for p in DATA_DIR.iterdir() if p.name != ".git"]
        if local_files:
            backup = DATA_DIR.parent / f"{DATA_DIR.name}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            shutil.copytree(DATA_DIR, backup, ignore=shutil.ignore_patterns(".git"))
            messages.append(f"Backed up this machine's existing data to {backup}")
        _git("checkout", "-q", "-f", "-B", "main", "origin/main")
        # The model is never synced, so a leftover local one was trained on
        # this machine's old data, not the synced data just checked out.
        # Drop it (it's in the backup) so the caller retrains from the synced data.
        MODEL_FILE.unlink(missing_ok=True)
        import_config()
        messages.append("Pulled your synced data from GitHub.")
    else:
        _commit_local(f"myGeeKy sync from {_stamp()}")
        if _remote_has_main():
            _git("merge", "-q", "--no-edit", "--allow-unrelated-histories", "-X", "theirs", "origin/main")
            import_config()
        _git("push", "-q", "-u", "origin", "main")
        messages.append("Pushed this machine's data to GitHub.")
    return "\n".join(messages)


def pull() -> str:
    _require_git()
    if not is_initialized():
        raise SyncError("Sync isn't set up on this machine -- run `mygeeky sync init --repo owner/name`.")
    _commit_local(f"myGeeKy sync from {_stamp()}")
    _git("fetch", "-q", "origin")
    if not _remote_has_main():
        return "Remote is empty -- nothing to pull."
    before = _git("rev-parse", "HEAD").stdout.strip()
    # union-merged .jsonl never conflicts; for the small JSON state files the
    # other machine's newer copy wins
    _git("merge", "-q", "--no-edit", "-X", "theirs", "origin/main")
    after = _git("rev-parse", "HEAD").stdout.strip()
    import_config()
    return "Already up to date." if before == after else "Pulled updates from GitHub."


def push() -> str:
    _require_git()
    if not is_initialized():
        raise SyncError("Sync isn't set up on this machine -- run `mygeeky sync init --repo owner/name`.")
    committed = _commit_local(f"myGeeKy sync from {_stamp()}")
    _git("fetch", "-q", "origin")
    if _remote_has_main():
        _git("merge", "-q", "--no-edit", "-X", "theirs", "origin/main")
        import_config()
    _git("push", "-q", "-u", "origin", "main")
    return "Pushed to GitHub." if committed else "Nothing new to push (remote is up to date)."


def status() -> str:
    if not is_initialized():
        return "Sync not set up on this machine."
    url = _git("remote", "get-url", "origin", check=False).stdout.strip()
    last = _git("log", "-1", "--format=%cr: %s", check=False).stdout.strip()
    dirty = bool(_git("status", "--porcelain", check=False).stdout.strip())
    return f"Remote: {url}\nLast commit: {last or '(none)'}\nUncommitted local changes: {'yes' if dirty else 'no'}"
