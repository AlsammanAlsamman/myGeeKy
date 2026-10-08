"""Connect your phone: a QR code that sets up the myGeeKy phone app in one scan.

The code carries your profile -- GitHub username, ORCID, keywords, topics --
and, only when it is strictly read-only (can't follow anyone, can't write to
any repo), your GitHub token. The Signals token and key never go into a QR code.
It's shown only when you ask for it, and only for a couple of minutes.

Format: `mygeeky:1:` + base64url(JSON {u, o, k, t, tok?}), ASCII only, which
the phone app checks field by field (mobile/src/lib/pairing.ts).
"""

from __future__ import annotations

import base64
import json
from typing import Any

from .config import MyGeekyConfig

PREFIX = "mygeeky:1:"
SHOW_SECONDS = 120


def payload(cfg: MyGeekyConfig, token: str | None = None) -> str:
    data: dict[str, Any] = {"u": cfg.github_username, "o": cfg.orcid_id or "",
                            "k": list(cfg.keywords)[:40], "t": list(cfg.topics)[:40]}
    if token:
        data["tok"] = token
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode(text: str) -> dict[str, Any]:
    """The other direction (for tests and troubleshooting)."""
    body = text[len(PREFIX):]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def shareable_token(cfg: MyGeekyConfig) -> tuple[str | None, str]:
    """(token, why): this computer's token if it's safe to hand to the phone --
    strictly read-only -- else None and the reason."""
    from . import auth, token_check
    token = auth.get_token(cfg.github_username)
    if not token:
        return None, "No GitHub token on this computer: the phone will ask you to sign in."
    verdict = token_check.check("read", token, cfg.github_username)
    if not verdict["ok"]:
        return None, ("Your token here can do more than read, so it stays on this computer; "
                      "the phone will ask you to sign in with GitHub instead.")
    return token, "Your read-only GitHub token goes along, so the phone needs nothing else."


def matrix(text: str) -> list[list[bool]]:
    """The QR code's modules (True = dark), with a quiet border."""
    import qrcode
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=3)
    q.add_data(text)
    q.make(fit=True)
    return q.get_matrix()
