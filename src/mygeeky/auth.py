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
"""

from __future__ import annotations

import getpass
import os

import keyring
from keyring.errors import PasswordDeleteError

SERVICE_NAME = "mygeeky-github-token"
ENV_VAR = "MYGEEKY_GITHUB_TOKEN"


class TokenNotFoundError(RuntimeError):
    pass


def get_token(username: str) -> str | None:
    """Resolve the GitHub token: env var first, then OS keyring."""
    env_token = os.environ.get(ENV_VAR)
    if env_token:
        return env_token.strip()
    try:
        return keyring.get_password(SERVICE_NAME, username)
    except Exception:
        # Some headless/CI environments have no keyring backend at all.
        return None


def token_source(username: str) -> str:
    if os.environ.get(ENV_VAR):
        return f"environment variable {ENV_VAR}"
    try:
        if keyring.get_password(SERVICE_NAME, username):
            return "OS keyring (encrypted secret store)"
    except Exception:
        pass
    return "none"


def prompt_and_store_token(username: str) -> None:
    """Interactively prompt for a token (hidden input) and store it in the OS keyring."""
    print(
        "myGeeKy needs a GitHub Personal Access Token to read public profile/repo/\n"
        "follower data on your behalf (and to raise your API rate limit).\n\n"
        "Create one at: https://github.com/settings/tokens?type=beta\n"
        "  -> grant it READ-ONLY access to public repositories and followers.\n"
        "  -> do NOT grant any write, follow, or admin scopes -- myGeeKy never needs them\n"
        "     and has no code path that could use them.\n\n"
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


def require_token(username: str) -> str:
    token = get_token(username)
    if not token:
        raise TokenNotFoundError(
            "No GitHub token found. Run `mygeeky auth login` first, or set the "
            f"{ENV_VAR} environment variable."
        )
    return token
