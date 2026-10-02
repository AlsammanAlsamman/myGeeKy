"""The live glass panel: a small, docked, always-on-top Qt window.

Built on PySide6/Qt, not a webview. pywebview's WebView2-on-Windows
transparency turned out to be a confirmed, currently-unreliable upstream bug
(see https://github.com/r0x0r/pywebview/issues/1611 -- even the maintainer
can't get it consistent across versions/machines, and CSS `backdrop-filter`
never worked through it at all). Qt's `WA_TranslucentBackground` on a
frameless window is the mature, well-supported way apps actually get real
per-pixel window transparency on Windows, confirmed working here. A native
DWM Acrylic backdrop (real blur-behind) was also tried and removed again --
it reliably turned the otherwise-working Qt transparency fully opaque on
this setup (see the comment above `main()`). So this panel is genuinely
see-through (real per-pixel alpha), just without a blurred backdrop.

Design constraints, deliberately unchanged from the previous version:

- Read-only over local state by default. Opening the panel never hits the
  network; `get_suggestions()`/`get_model_history()` replay what `mygeeky
  run`/`learn` already produced and logged to disk.
- The only automatic network call is a cheap, cached activity-feed refresh
  (one GitHub Events API call), rate-limited by `gui_activity_refresh_minutes`
  so the panel can't hammer the API just by being left open.
- A full candidate search (`refresh_suggestions`) runs when the user clicks
  "Refresh", or by itself only once the follow-back list has run empty AND
  the last search is older than `gui_suggestions_auto_refresh_hours`
  (default 6; 0 disables). A repo search (`refresh_contributions`) only ever
  runs on a click.
- Opening a profile is the ONLY thing a click ever reaches out to do, and
  all it does is open the URL in the system browser. There is no
  follow/unfollow call anywhere in this file, same as the rest of myGeeKy.
  Likewise the Repos tab only opens repo/issue/fork pages -- nothing here
  forks a repo or opens a PR.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import auth
from ..activity import get_recent_activity
from ..cli import _run_contribute, _run_suggestions
from ..config import MyGeekyConfig, load_config, save_config
from ..github_client import GitHubClient
from ..storage import (
    add_excluded,
    load_activity_cache,
    load_excluded,
    load_following_snapshot,
    load_model_history,
    load_training_examples,
    last_contributions,
    last_suggestion_time,
    last_suggestions,
    save_activity_cache,
)

THEME_NAMES = ("midnight", "frosted", "aurora")

THEMES: dict[str, dict[str, Any]] = {
    "midnight": {
        "bg": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(28,28,42,158), stop:1 rgba(12,12,20,107))",
        "border": "rgba(255,255,255,31)",
        "text": "#f0f0f5",
        "muted": "rgba(240,240,245,150)",
        "card_bg": "rgba(255,255,255,15)",
        "btn_bg": "rgba(255,255,255,26)",
        "btn_hover": "rgba(255,255,255,51)",
        "tab_active": "rgba(120,180,255,71)",
        "section_btn": "rgba(120,180,255,56)",
        "accent": "#7fd8ff",
        "swatch_border": "rgba(255,255,255,80)",
    },
    "frosted": {
        "bg": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(255,255,255,140), stop:1 rgba(255,255,255,71))",
        "border": "rgba(255,255,255,153)",
        "text": "#241f1a",
        "muted": "rgba(36,31,26,150)",
        "card_bg": "rgba(255,255,255,89)",
        "btn_bg": "rgba(0,0,0,31)",
        "btn_hover": "rgba(0,0,0,51)",
        "tab_active": "rgba(0,0,0,31)",
        "section_btn": "rgba(224,138,79,71)",
        "accent": "#b5591f",
        "swatch_border": "rgba(0,0,0,60)",
    },
    "aurora": {
        "bg": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(255,255,255,41), stop:1 rgba(255,255,255,15))",
        "border": "rgba(255,255,255,89)",
        "text": "#ffffff",
        "muted": "rgba(255,255,255,170)",
        "card_bg": "rgba(255,255,255,26)",
        "btn_bg": "rgba(255,255,255,46)",
        "btn_hover": "rgba(255,255,255,71)",
        "tab_active": "qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #ff6fd8, stop:1 #7a5cff)",
        "section_btn": "rgba(255,111,216,77)",
        "accent": "#ff6fd8",
        "swatch_border": "rgba(255,255,255,120)",
    },
}


# --------------------------------------------------------------------------- business logic (no Qt dependency -- testable without a live app)

def _build_client(cfg: MyGeekyConfig) -> GitHubClient:
    token = auth.get_token(cfg.github_username)
    return GitHubClient(token, rate_limit_sleep=cfg.rate_limit_sleep_seconds, search_pause=cfg.search_pause_seconds)


def get_status(cfg: MyGeekyConfig) -> dict[str, Any]:
    return {
        "github_username": cfg.github_username,
        "token_present": auth.get_token(cfg.github_username) is not None,
        "dock_side": cfg.gui_dock_side,
        "theme": cfg.gui_theme if cfg.gui_theme in THEME_NAMES else "midnight",
        "configured": bool(cfg.github_username),
    }


def set_theme(cfg: MyGeekyConfig, theme: str) -> bool:
    if theme not in THEME_NAMES:
        return False
    cfg.gui_theme = theme
    save_config(cfg)
    return True


MIN_OPACITY = 0.0
MAX_OPACITY = 1.0


def set_opacity(cfg: MyGeekyConfig, opacity: float) -> bool:
    if not (MIN_OPACITY <= opacity <= MAX_OPACITY):
        return False
    cfg.gui_opacity = opacity
    save_config(cfg)
    return True


def _hidden_usernames() -> set[str]:
    """People not to show any more: anyone you clicked (added to the
    excluded list, which future runs skip too) plus anyone you now follow,
    per the following list cached by the last activity refresh. That list is
    deliberately NOT the `learn` snapshot -- `learn` detects new follows by
    diffing against that snapshot, so the panel must never update it."""
    hidden = {u.lower() for u in load_excluded()}
    hidden |= {u.lower() for u in (load_activity_cache() or {}).get("following") or []}
    return hidden


def get_suggestions(cfg: MyGeekyConfig) -> dict[str, Any]:
    hidden = _hidden_usernames()
    return {
        "followback": last_suggestions(cfg.max_suggestions_returned, list_type="followback", exclude=hidden),
        "domain_highlights": last_suggestions(cfg.domain_highlight_count, list_type="domain", exclude=hidden),
    }


def suggestions_auto_refresh_due(cfg: MyGeekyConfig, now: datetime | None = None) -> bool:
    """True when the panel should start a suggestion search by itself: the
    follow-back list is empty and the last search is older than
    `gui_suggestions_auto_refresh_hours` (0 turns this off)."""
    hours = cfg.gui_suggestions_auto_refresh_hours
    if not cfg.github_username or hours <= 0:
        return False
    if get_suggestions(cfg)["followback"]:
        return False
    last = last_suggestion_time()
    if last is None:
        return True
    now = now or datetime.now(timezone.utc)
    return (now - last).total_seconds() >= hours * 3600


def mark_suggestion_seen(username: str) -> None:
    """Clicking a suggestion means you've looked at them: never suggest them again."""
    if username:
        add_excluded([username.lower()])


def refresh_suggestions(cfg: MyGeekyConfig) -> dict[str, Any]:
    """Runs a real `mygeeky run` -- only ever called from an explicit button click."""
    if not cfg.github_username:
        return {"error": "Run `mygeeky init` in a terminal first."}
    try:
        return _run_suggestions(cfg)
    except Exception as exc:  # surfaced to the panel, not a crash
        return {"error": str(exc)}


def get_contributions(cfg: MyGeekyConfig) -> list[dict[str, Any]]:
    return last_contributions(cfg.contribute_max_returned)


def refresh_contributions(cfg: MyGeekyConfig) -> list[dict[str, Any]] | dict[str, Any]:
    """Runs a real `mygeeky contribute` -- only ever called from an explicit button click."""
    if not cfg.github_username:
        return {"error": "Run `mygeeky init` in a terminal first."}
    try:
        return _run_contribute(cfg)
    except Exception as exc:  # surfaced to the panel, not a crash
        return {"error": str(exc)}


def get_activity(cfg: MyGeekyConfig, force: bool = False) -> dict[str, Any]:
    if not cfg.github_username:
        return {"events": [], "error": "not configured"}

    cache = load_activity_cache()
    now = datetime.now(timezone.utc)
    if not force and cache:
        try:
            fetched_at = datetime.fromisoformat(cache["fetched_at"])
            age_minutes = (now - fetched_at).total_seconds() / 60
        except (KeyError, ValueError):
            age_minutes = float("inf")
        if age_minutes < cfg.gui_activity_refresh_minutes:
            return {"events": cache["events"], "fetched_at": cache["fetched_at"], "cached": True}

    try:
        client = _build_client(cfg)
        events = get_recent_activity(client, cfg.github_username, limit=cfg.gui_activity_limit)
        # piggybacks on the same rate-limited refresh, so people you follow
        # from the browser drop out of the suggestions within a few minutes
        following = client.list_following(cfg.github_username)
    except Exception as exc:
        if cache:
            return {"events": cache["events"], "fetched_at": cache["fetched_at"], "cached": True, "error": str(exc)}
        return {"events": [], "error": str(exc)}

    fetched_at_iso = now.isoformat()
    save_activity_cache(events, fetched_at_iso, following)
    return {"events": events, "fetched_at": fetched_at_iso, "cached": False}


def get_model_history() -> list[dict[str, Any]]:
    return load_model_history()


def get_friend_stats(cfg: MyGeekyConfig) -> dict[str, Any]:
    """Friend-count and follow-back stats for the Live tab -- built entirely
    from local data already on disk (the last following snapshot and the
    labeled training examples logged by `learn`/`bootstrap`), so viewing it
    never triggers a network call of its own."""
    total_friends = len(load_following_snapshot())

    examples = load_training_examples()
    now = datetime.now(timezone.utc)
    new_this_week = 0
    for e in examples:
        try:
            ts = datetime.fromisoformat(e.get("timestamp", ""))
        except ValueError:
            continue
        if (now - ts).days < 7:
            new_this_week += 1

    total_labeled = len(examples)
    positives = sum(1 for e in examples if e.get("label") == 1)
    follow_back_rate = (positives / total_labeled) if total_labeled else None

    return {
        "total_friends": total_friends,
        "new_this_week": new_this_week,
        "follow_back_rate": follow_back_rate,
        "total_labeled": total_labeled,
    }


def open_profile(url: str) -> bool:
    if not isinstance(url, str) or not url.startswith("https://github.com/"):
        return False
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl(url))
    return True


def _panel_geometry(cfg: MyGeekyConfig, folded: bool, screen_rect,
                    min_width: int = 0, min_height: int = 0) -> tuple[int, int, int, int]:
    """Returns (x, y, width, height) docked to the configured edge of
    `screen_rect` (the screen's available area, i.e. minus the taskbar).

    `min_width`/`min_height` are what the content actually needs: Qt won't
    shrink a window below that, so the position is computed from the real
    size -- otherwise a right-docked panel wider than configured hangs off
    the right edge onto the neighbouring monitor. The result always stays
    inside `screen_rect`, whatever its (possibly negative) origin."""
    if folded:
        width, height = cfg.gui_folded_width, cfg.gui_folded_height
    else:
        width, height = cfg.gui_expanded_width, int(screen_rect.height() * cfg.gui_panel_height_fraction)
    width = min(max(width, min_width), screen_rect.width())
    height = min(max(height, min_height), screen_rect.height())
    y = screen_rect.y() + (screen_rect.height() - height) // 2
    x = screen_rect.x() if cfg.gui_dock_side == "left" else screen_rect.x() + screen_rect.width() - width
    return x, y, width, height


# A native Windows DWM Acrylic backdrop (DwmExtendFrameIntoClientArea +
# DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE=3)) was tried here and
# deliberately removed: isolated side-by-side testing (two otherwise-
# identical minimal Qt windows, one with the DWM calls and one without)
# showed it reliably turns an already-working, genuinely transparent Qt
# window (WA_TranslucentBackground) fully opaque instead -- reproduced with
# and without window focus, so it isn't a focus-dependent Windows rendering
# quirk. Qt's own translucency is what actually ships; layering DWM's
# system backdrop on top of it made things strictly worse on this setup.


def main() -> None:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        raise SystemExit(
            "The live GUI needs the optional 'gui' extra.\n"
            "Install it with: pip install \"mygeeky[gui]\""
        )

    from .qt_panel import ICON_WINDOW, MyGeekyPanel

    app = QApplication.instance() or QApplication([])
    if ICON_WINDOW.exists():
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(ICON_WINDOW)))
    cfg = load_config()
    panel = MyGeekyPanel(cfg)
    panel.show()
    app.exec()


if __name__ == "__main__":
    main()
