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

import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

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
*.token
*.lock
"""

GITATTRIBUTES = """\
# append-only logs: keep both machines' lines on merge
*.jsonl merge=union
"""

README = """\
# myGeeKy data (private)

Synced automatically by [myGeeKy](https://github.com/AlsammanAlsamman/myGeeKy)
(`mygeeky sync push` / `mygeeky sync pull`). Keep this repository **private**:
it contains your CV text and your suggestion history.

On a new computer: `pip install mygeeky && mygeeky sync init --repo <owner>/<this-repo>`.
"""


class SyncError(RuntimeError):
    pass


def _has_gh() -> bool:
    return shutil.which("gh") is not None


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["git"]
    if _has_gh():
        # let git borrow gh's login for github.com without touching the user's git config
        cmd += ["-c", "credential.https://github.com.helper=", "-c",
                "credential.https://github.com.helper=!gh auth git-credential"]
    cmd += list(args)
    result = subprocess.run(cmd, cwd=str(cwd or DATA_DIR), capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SyncError(f"`git {' '.join(args)}` failed:\n{result.stderr.strip() or result.stdout.strip()}")
    return result


def is_initialized() -> bool:
    return (DATA_DIR / ".git").exists()


def remote_url(repo: str) -> str:
    return f"https://github.com/{repo}.git"


def _repo_exists(repo: str) -> bool:
    if not _has_gh():
        return _git("ls-remote", remote_url(repo), check=False).returncode == 0
    return subprocess.run(["gh", "repo", "view", repo, "--json", "visibility"],
                          capture_output=True, text=True).returncode == 0


def _repo_is_private(repo: str) -> bool | None:
    if not _has_gh():
        return None
    r = subprocess.run(["gh", "repo", "view", repo, "--json", "visibility", "-q", ".visibility"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return r.stdout.strip().upper() == "PRIVATE"


def _create_private_repo(repo: str) -> None:
    if not _has_gh():
        raise SyncError(
            f"Repo {repo} doesn't exist and the GitHub CLI (`gh`) isn't installed to create it.\n"
            f"Create it yourself as a PRIVATE repo at https://github.com/new, then re-run this command."
        )
    r = subprocess.run(["gh", "repo", "create", repo, "--private",
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
    if CONFIG_FILE.exists():
        shutil.copyfile(CONFIG_FILE, SYNCED_CONFIG_FILE)


def import_config() -> bool:
    if not SYNCED_CONFIG_FILE.exists():
        return False
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SYNCED_CONFIG_FILE, CONFIG_FILE)
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


def init(repo: str) -> str:
    """Turn the data dir into a clone of private GitHub repo `repo` ("owner/name"),
    creating the repo (private) if it doesn't exist yet."""
    if "/" not in repo:
        raise SyncError("Give the repo as owner/name, e.g. octocat/mygeeky-data.")
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
