"""Secure GitHub token handling.

Design goals, in priority order:

1. The token is NEVER written to a plaintext file anywhere in this project
   or in the config directory. It never appears in `config.json`.
2. The primary storage is the OS-native secret store via the `keyring`
   package: Windows Credential Locker, macOS Keychain, or the Linux Secret
   Service (gnome-keyring / kwallet). That store is encrypted-at-rest and
   gated by the OS user session -- the same place browsers and git
   credential managers keep secrets.
3. An environment variable (`MYGEEKY_GITHUB_TOKEN`) is supported as an
   opt-in escape hatch for CI machines, containers, or AI-agent contexts
   where no OS keyring is available. It always takes priority when set
   (explicit > implicit), and every command that reads it prints a one-line
   reminder that it's less safe than the keyring.
4. myGeeKy requests the token interactively via `getpass` (never echoed to
   the terminal, never passed as a CLI argument, so it never lands in shell
   history or `ps`/process-list output).
5. myGeeKy only ever needs READ access. A classic Personal Access Token
   with **no scopes at all** (or a fine-grained token with only
   "Public repositories: read-only" and "Followers: read-only") is enough
   -- myGeeKy reads your public profile/repos/followers and never calls any
   write endpoint. There is no follow/unfollow code path in this project at
   all (see github_client.py) -- it is impossible for myGeeKy to follow
   anyone even if a broader token were supplied by mistake.
6. The one exception is opt-in: beacons (`mygeeky beacon init`) publish
   your non-verbal signals to your own public `mygeeky-beacon` repo. That
   uses a SECOND, separate token, stored the same way under its own
   keyring entry, which you create as fine-grained and limited to that
   single repository with only "Contents: Read and write". The read token
   above is never used to write, and the beacon token is never used for
   anything but that one file.
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess

import keyring
from keyring.errors import PasswordDeleteError

SERVICE_NAME = "mygeeky-github-token"
ENV_VAR = "MYGEEKY_GITHUB_TOKEN"


class TokenNotFoundError(RuntimeError):
    pass


def _gh_cli_token() -> str | None:
    """The token of a logged-in GitHub CLI (`gh auth login`), if any -- so
    myGeeKy works on any of your machines where `gh` is already set up,
    without storing a second token. myGeeKy's API client only ever issues
    GET requests, so a broader gh token still can't follow anyone."""
    if not shutil.which("gh"):
        return None
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    token = r.stdout.strip()
    return token if r.returncode == 0 and token else None


def get_token(username: str) -> str | None:
    """Resolve the GitHub token: env var first, then OS keyring, then the GitHub CLI."""
    env_token = os.environ.get(ENV_VAR)
    if env_token:
        return env_token.strip()
    try:
        token = keyring.get_password(SERVICE_NAME, username)
    except Exception:
        # Some headless/CI environments have no keyring backend at all.
        token = None
    return token or _gh_cli_token()


def token_source(username: str) -> str:
    if os.environ.get(ENV_VAR):
        return f"environment variable {ENV_VAR}"
    try:
        if keyring.get_password(SERVICE_NAME, username):
            return "OS keyring (encrypted secret store)"
    except Exception:
        pass
    if _gh_cli_token():
        return "GitHub CLI login (`gh auth token`)"
    return "none"


def prompt_and_store_token(username: str) -> None:
    """Interactively prompt for a token (hidden input) and store it in the OS keyring."""
    print(
        "myGeeKy needs a GitHub Personal Access Token to read public profile/repo/\n"
        "follower data on your behalf (and to raise your API rate limit).\n\n"
        "Create one at: https://github.com/settings/tokens?type=beta\n"
        "  -> grant it READ-ONLY access to public repositories and followers.\n"
        "  -> do NOT grant any write, follow, or admin scopes -- myGeeKy never needs them\n"
        "     and has no code path that could use them.\n"
        "  -> Expiration: pick a long one (90 days or a year). myGeeKy reminds you a week\n"
        "     before it ends (`mygeeky auth status` shows the date).\n\n"
        "The token will be typed with hidden input and stored ONLY in your OS's\n"
        "encrypted secret store (Windows Credential Locker / macOS Keychain / Linux\n"
        "Secret Service) via the `keyring` package. It is never written to any file\n"
        "in this project, never logged, and never leaves your machine.\n"
    )
    token = getpass.getpass("Paste your GitHub token (input hidden): ").strip()
    if not token:
        raise ValueError("Empty token, nothing stored.")
    try:
        keyring.set_password(SERVICE_NAME, username, token)
    except Exception as exc:
        raise RuntimeError(
            "Could not access an OS keyring backend on this machine.\n"
            f"Underlying error: {exc}\n\n"
            f"As a fallback, you can set the {ENV_VAR} environment variable yourself "
            "in your own shell/session instead (less safe -- avoid on shared machines)."
        ) from exc
    print("Token stored securely in your OS keyring.")


def delete_token(username: str) -> bool:
    try:
        keyring.delete_password(SERVICE_NAME, username)
        return True
    except PasswordDeleteError:
        return False
    except Exception:
        return False


BEACON_SERVICE_NAME = "mygeeky-beacon-token"
BEACON_ENV_VAR = "MYGEEKY_BEACON_TOKEN"


def get_beacon_token(username: str) -> str | None:
    """The beacon write token: env var first, then the OS keyring. Never
    falls back to `gh` -- that token is far broader than one repo."""
    env_token = os.environ.get(BEACON_ENV_VAR)
    if env_token:
        return env_token.strip()
    try:
        return keyring.get_password(BEACON_SERVICE_NAME, username)
    except Exception:
        return None


def delete_beacon_token(username: str) -> bool:
    try:
        keyring.delete_password(BEACON_SERVICE_NAME, username)
        return True
    except Exception:
        return False


PRODUCTHUNT_SERVICE_NAME = "mygeeky-producthunt-token"
PRODUCTHUNT_ENV_VAR = "MYGEEKY_PRODUCTHUNT_TOKEN"


def get_producthunt_token(username: str) -> str | None:
    """Product Hunt developer token (read-only API access), if set up."""
    env_token = os.environ.get(PRODUCTHUNT_ENV_VAR)
    if env_token:
        return env_token.strip()
    try:
        return keyring.get_password(PRODUCTHUNT_SERVICE_NAME, username)
    except Exception:
        return None


def prompt_and_store_producthunt_token(username: str) -> None:
    print(
        "Product Hunt launches in the Market tab need a free Product Hunt developer token.\n\n"
        "  1. Open https://www.producthunt.com/v2/oauth/applications and sign in.\n"
        "  2. Click 'Add an application'. Any name works (e.g. mygeeky), and the\n"
        "     redirect URI can be https://localhost.\n"
        "  3. On the app's page, click 'Create Token' under Developer Token and copy it.\n\n"
        "It's read-only and stored only in your OS keyring.\n"
    )
    token = getpass.getpass("Paste the Product Hunt token (input hidden): ").strip()
    if not token:
        raise ValueError("Empty token, nothing stored.")
    try:
        keyring.set_password(PRODUCTHUNT_SERVICE_NAME, username, token)
    except Exception as exc:
        raise RuntimeError(f"Could not access an OS keyring backend ({exc}). "
                           f"Set {PRODUCTHUNT_ENV_VAR} yourself instead.") from exc
    print("Product Hunt token stored securely in your OS keyring.")


def require_token(username: str) -> str:
    token = get_token(username)
    if not token:
        raise TokenNotFoundError(
            "No GitHub token found. Run `mygeeky auth login` first, or set the "
            f"{ENV_VAR} environment variable."
        )
    return token
