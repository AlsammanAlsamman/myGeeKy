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
- The one exception, opt-in via `mygeeky beacon init`: clicking a gesture
  button on the Signals tab publishes that emoji signal to your own public
  beacon repo (see beacon.py). Nothing else in the panel writes anything.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import auth
from ..activity import get_matched_activity, get_recent_activity
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


def set_hearts(cfg: MyGeekyConfig, enabled: bool) -> None:
    cfg.gui_hearts_enabled = bool(enabled)
    save_config(cfg)


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


def _followed_only(cache: dict[str, Any]) -> list[dict[str, Any]]:
    """Caches written before 0.2.3 hold strangers' events too; drop them on
    read. Profile-match events were vetted when fetched, so they stay."""
    following = cache.get("following")
    if following is None:
        return cache["events"]
    allowed = {u.lower() for u in following}
    return [e for e in cache["events"]
            if e.get("source") == "match" or (e.get("actor") or "").lower() in allowed]


def _profile_matches(cfg: MyGeekyConfig, following: list[str]) -> list[str]:
    """Your best-scoring recent suggestions (both lists), i.e. people already
    matched against your CV, ORCID and repos and past the quality gates.
    People you follow are skipped -- their activity comes in anyway."""
    if cfg.gui_activity_match_people <= 0:
        return []
    skip = {u.lower() for u in following} | {cfg.github_username.lower()}
    pool = last_suggestions(cfg.gui_activity_match_people, list_type="domain", exclude=skip)         + last_suggestions(cfg.gui_activity_match_people, list_type="followback", exclude=skip)
    seen: set[str] = set()
    picked = []
    for r in sorted(pool, key=lambda r: r.get("score", 0), reverse=True):
        name = r.get("username") or ""
        if name and name.lower() not in seen:
            seen.add(name.lower())
            picked.append(name)
    return picked[: cfg.gui_activity_match_people]


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
            return {"events": _followed_only(cache), "fetched_at": cache["fetched_at"], "cached": True}

    try:
        client = _build_client(cfg)
        # piggybacks on the same rate-limited refresh, so people you follow
        # from the browser drop out of the suggestions within a few minutes;
        # also restricts the feed to people you actually follow
        following = client.list_following(cfg.github_username)
        events = get_recent_activity(client, cfg.github_username, limit=cfg.gui_activity_limit,
                                     following=following)
        for e in events:
            e["source"] = "following"
        events += get_matched_activity(client, _profile_matches(cfg, following))
        events.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    except Exception as exc:
        if cache:
            return {"events": _followed_only(cache), "fetched_at": cache["fetched_at"], "cached": True, "error": str(exc)}
        return {"events": [], "error": str(exc)}

    fetched_at_iso = now.isoformat()
    save_activity_cache(events, fetched_at_iso, following)
    return {"events": events, "fetched_at": fetched_at_iso, "cached": False}


def group_activity(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per person, busiest-recent first: their events newest first,
    and `source` "following" if any of their events came from people you
    follow, else "match"."""
    groups: dict[str, dict[str, Any]] = {}
    for e in sorted(events, key=lambda e: e.get("created_at", ""), reverse=True):
        key = (e.get("actor") or "").lower()
        if not key:
            continue
        g = groups.setdefault(key, {
            "actor": e.get("actor", ""),
            "actor_avatar": e.get("actor_avatar", ""),
            "profile_url": e.get("profile_url", ""),
            "source": "match",
            "latest": e.get("created_at", ""),
            "events": [],
        })
        g["events"].append(e)
        if e.get("source") != "match":
            g["source"] = "following"
    return list(groups.values())


def get_market(cfg: MyGeekyConfig) -> dict[str, Any]:
    """The saved board -- local only, no network."""
    from .. import producthunt
    from ..market import compute_board, load_state
    state = load_state()
    return {"rows": compute_board(state), "updated_at": state.get("updated_at"),
            "producthunt": producthunt.load_state().get("posts") or [],
            "producthunt_token": bool(cfg.github_username and auth.get_producthunt_token(cfg.github_username))}


def market_refresh_due(cfg: MyGeekyConfig, now: datetime | None = None) -> bool:
    from ..market import load_state
    updated = load_state().get("updated_at")
    if not updated:
        return True
    try:
        age = (now or datetime.now(timezone.utc)) - datetime.fromisoformat(updated)
    except ValueError:
        return True
    return age.total_seconds() >= cfg.market_refresh_hours * 3600


def refresh_market(cfg: MyGeekyConfig, force: bool = False) -> dict[str, Any]:
    if not cfg.github_username:
        return {"rows": [], "error": "Run `mygeeky init` in a terminal first."}
    try:
        from ..cli import _run_market
        _run_market(cfg, force=force)
    except Exception as exc:  # surfaced to the panel, not a crash
        return {**get_market(cfg), "error": str(exc)}
    return get_market(cfg)


def get_signals(cfg: MyGeekyConfig, force: bool = False) -> dict[str, Any]:
    """Beacon signals for the Signals tab. Re-reads everyone's beacons only
    when `beacon_refresh_minutes` have passed (or on a Refresh click)."""
    from .. import beacon as bc
    if not cfg.github_username or not cfg.beacon_enabled:
        return {"enabled": False, "incoming": [], "people": []}
    cache, error = bc.load_cache(), None
    if force or bc.refresh_due(cfg, cache):
        try:
            cache = bc.refresh(_build_client(cfg), cfg, force=True)
        except Exception as exc:  # surfaced to the panel, not a crash
            error = str(exc)
    mine = bc.load_my_beacon()
    return {
        "enabled": True,
        "can_send": auth.get_beacon_token(cfg.github_username) is not None,
        "incoming": bc.inbox(cache, cfg, mine),
        "people": bc.people(cache, cfg, mine),
        "fetched_at": cache.get("fetched_at"),
        "error": error,
    }


def send_signal(cfg: MyGeekyConfig, to: str, gesture: str) -> dict[str, Any]:
    """Only ever called from a click on a gesture button."""
    from .. import beacon as bc
    try:
        bc.send(cfg, to, gesture)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


def get_model_history() -> list[dict[str, Any]]:
    return load_model_history()


FEATURE_LABELS = {
    "content_similarity": "Content match",
    "follow_back_ratio": "Follows people back",
    "activity_recency": "Recently active",
    "shared_languages": "Shared languages",
    "shared_topics": "Shared topics",
}


def get_model_weights() -> list[dict[str, Any]]:
    """What the trained model rewards (+) and penalizes (-): the logistic
    regression's coefficients on standardized features, so their sizes are
    comparable. Empty when no model has been trained yet."""
    from ..matcher import FEATURE_NAMES, LearnedModel

    model = LearnedModel.load()
    if not model.is_trained:
        return []
    try:
        coef = model.pipeline[1].coef_[0]
    except (AttributeError, IndexError, TypeError):
        return []
    weights = [{"feature": name, "label": FEATURE_LABELS.get(name, name), "weight": float(c)}
               for name, c in zip(FEATURE_NAMES, coef)]
    return sorted(weights, key=lambda w: abs(w["weight"]), reverse=True)


def auc_verdict(auc: float | None) -> tuple[str, str]:
    """(short grade, one-line explanation) for a cross-validated AUC."""
    if auc is None:
        return "Untrained", "Run mygeeky bootstrap to teach it who follows back."
    if auc >= 0.8:
        return "Sharp", "Reliably tells who will follow you back."
    if auc >= 0.7:
        return "Good", "Clearly better than chance at spotting follow-backs."
    if auc >= 0.6:
        return "Learning", "Some signal -- more follow-backs will sharpen it."
    return "Early", "Barely above a coin flip; keep running mygeeky learn."


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


LINK_PREFIXES = ("https://github.com/", "https://www.producthunt.com/posts/")


def open_link(url: str) -> bool:
    """Like open_profile, but also lets Product Hunt launch pages through."""
    if not isinstance(url, str) or not url.startswith(LINK_PREFIXES):
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
    from .bootstrap import ensure_qt
    ensure_qt()  # installs Qt on first use, wherever this Python can hold it

    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication

    from ..config import DATA_DIR, ensure_dirs
    from .qt_panel import ICON_WINDOW, MyGeekyPanel

    # One panel at a time: the Start menu, the sign-in shortcut and the
    # installer can all launch it. A crashed panel's lock is detected as
    # stale (its process is gone) and taken over. `*.lock` is never synced.
    ensure_dirs()
    lock = QLockFile(str(DATA_DIR / "panel.lock"))
    if not lock.tryLock(200):
        return

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
