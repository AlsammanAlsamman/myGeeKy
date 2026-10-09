"""Connect your phone: a QR code that sets up the myGeeKy phone app in one scan.

The code carries your profile -- GitHub username, ORCID, keywords, topics, and
what this computer has learned about you (weighted interests, research field,
badges) --
and, only when it is strictly read-only (can't follow anyone, can't write to
any repo), your GitHub token. The Signals token and key never go into a QR code.
It's shown only when you ask for it, and only for a couple of minutes.

Format: `mygeeky:1:` + base64url(JSON {u, o, k, t, w, f, b, tok?}), ASCII only, which
the phone app checks field by field (mobile/src/lib/pairing.ts).
"""

from __future__ import annotations

import base64
import json
from typing import Any

from .config import MyGeekyConfig

PREFIX = "mygeeky:1:"
SHOW_SECONDS = 120


def _learned(cfg: MyGeekyConfig) -> tuple[dict[str, float], list[str], list[str]]:
    """What this computer has learned about you, so the phone knows you too:
    your weighted interest terms, your research field, and your badges."""
    terms: dict[str, float] = {}
    field: list[str] = []
    badges: list[str] = []
    try:
        from . import interests
        langs = {x.lower() for x in cfg.languages}
        ranked = sorted(interests.profile_terms(cfg).items(), key=lambda kv: -kv[1])
        for term, w in ranked:
            if 2 <= len(term) <= 40 and term.isascii() and any(c.isalpha() for c in term) and term not in langs:
                terms[term] = round(min(max(w, 0.0), 1.0), 2)
            if len(terms) >= 30:
                break
    except Exception:
        pass
    try:
        from .gui import app as logic
        field = [f[:80] for f in logic.get_brain(cfg).get("field", []) if f.isascii()][:6]
    except Exception:
        pass
    try:
        from . import achievements
        badges = [f"{b['id']}:{b['tier']}" for b in achievements.earned_only(cfg)][:20]
    except Exception:
        pass
    return terms, field, badges


def payload(cfg: MyGeekyConfig, token: str | None = None) -> str:
    terms, field, badges = _learned(cfg)
    data: dict[str, Any] = {"u": cfg.github_username, "o": cfg.orcid_id or "",
                            "k": list(cfg.keywords)[:40], "t": list(cfg.topics)[:40],
                            "w": terms, "f": field, "b": badges}
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
