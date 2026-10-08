"""Sign in with GitHub: no token to create or copy.

GitHub's device flow, made for apps that can't keep a secret (myGeeKy is open
source, so it can't): myGeeKy asks GitHub for a short code, you open
github.com/login/device, type the code and click Authorize, and myGeeKy
receives a token by itself.

The sign-in asks for NO scopes, so the token can only read public data -- the
same thing token 1 does -- and can never follow, star or write anything. It's
stored in your OS keyring like any token 1. You can revoke it any time in
GitHub -> Settings -> Applications -> Authorized OAuth Apps -> myGeeKy.
Signals still uses its own single-repo token.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import requests

CLIENT_ID = "Ov23liNyUzK9THj5uAyH"          # the myGeeKy OAuth app (public; there is no secret)
DEVICE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
HEADERS = {"Accept": "application/json", "User-Agent": "mygeeky"}


class LoginError(RuntimeError):
    pass


def start() -> dict[str, Any]:
    """{"user_code", "verification_uri", "device_code", "interval", "expires_in"}."""
    try:
        r = requests.post(DEVICE_URL, data={"client_id": CLIENT_ID, "scope": ""}, headers=HEADERS, timeout=20)
        data = r.json()
    except (requests.RequestException, ValueError) as exc:
        raise LoginError(f"Couldn't reach GitHub to sign in ({exc}).") from exc
    if not data.get("device_code") or not data.get("user_code"):
        raise LoginError(f"GitHub didn't start the sign-in: {data.get('error_description') or data}")
    return {"device_code": data["device_code"], "user_code": data["user_code"],
            "verification_uri": data.get("verification_uri") or "https://github.com/login/device",
            "interval": int(data.get("interval") or 5), "expires_in": int(data.get("expires_in") or 900)}


def poll(device_code: str, interval: int = 5, expires_in: int = 900,
         sleep: Callable[[float], None] = time.sleep, cancelled: Callable[[], bool] = lambda: False) -> str:
    """Wait for you to authorize on github.com; returns the token."""
    deadline = time.monotonic() + expires_in
    wait = max(interval, 1)
    while time.monotonic() < deadline:
        if cancelled():
            raise LoginError("Sign-in cancelled.")
        sleep(wait)
        try:
            data = requests.post(TOKEN_URL, headers=HEADERS, timeout=20, data={
                "client_id": CLIENT_ID, "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}).json()
        except (requests.RequestException, ValueError):
            continue                                   # a network hiccup: just try again
        if data.get("access_token"):
            return data["access_token"]
        error = data.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            wait = int(data.get("interval") or wait + 5)
            continue
        if error == "expired_token":
            raise LoginError("The code expired before it was used. Start the sign-in again.")
        if error == "access_denied":
            raise LoginError("You cancelled the sign-in on GitHub.")
        raise LoginError(f"GitHub sign-in failed: {data.get('error_description') or error}")
    raise LoginError("The code expired before it was used. Start the sign-in again.")


def who(token: str) -> str:
    """The username the token belongs to."""
    r = requests.get("https://api.github.com/user", timeout=20,
                     headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    if r.status_code != 200:
        raise LoginError("GitHub didn't accept the new sign-in. Please try again.")
    return r.json().get("login", "")


def store(token: str, username: str) -> None:
    """Keep it as this computer's token 1 (OS keyring only)."""
    import keyring
    from . import auth, tokens
    keyring.set_password(auth.SERVICE_NAME, username, token)
    tokens.forget()
