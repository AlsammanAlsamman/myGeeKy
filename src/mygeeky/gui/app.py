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


def get_update_info(cfg: MyGeekyConfig) -> dict[str, Any]:
    """Whether to show the update banner: a newer release on PyPI that the
    user hasn't said "Later" to. Checks PyPI at most once a day."""
    from .. import updates
    if not cfg.check_for_updates:
        return {"show": False}
    info = updates.check()
    show = info["newer"] and info["latest"] != cfg.update_dismissed
    return {**info, "show": show, "editable": updates.is_editable(), "releases_url": updates.RELEASES_URL}


def dismiss_update(cfg: MyGeekyConfig, version: str) -> None:
    cfg.update_dismissed = version
    save_config(cfg)


def install_update() -> dict[str, Any]:
    """Only ever called from a click on the banner's Update button."""
    from .. import updates
    ok, message = updates.run_upgrade()
    return {"ok": ok, "message": message}


def get_token_warnings(cfg: MyGeekyConfig) -> list[dict[str, Any]]:
    """Tokens that expire within a week (or already have); checked at most daily."""
    from .. import tokens
    if not cfg.github_username:
        return []
    return tokens.warnings(cfg)


def replace_token(cfg: MyGeekyConfig, name: str, value: str) -> dict[str, Any]:
    """Store a renewed token, but only after it has proven it works: the read
    token must belong to you, and the Signals token must be able to publish."""
    import keyring
    from .. import beacon, tokens
    value = (value or "").strip()
    user = cfg.github_username
    if not value:
        return {"ok": False, "message": "No token pasted."}
    try:
        if name == "read":
            login = GitHubClient(value, rate_limit_sleep=0).get_authenticated_user().get("login", "")
            if login.lower() != user.lower():
                return {"ok": False, "message": f"That token belongs to {login}, not {user}."}
            keyring.set_password(auth.SERVICE_NAME, user, value)
        else:
            beacon.go_live(cfg, beacon.BeaconWriter(value, user))
            keyring.set_password(auth.BEACON_SERVICE_NAME, user, value)
    except Exception as exc:
        from ..errors import describe
        return {"ok": False, "message": f"That token didn't work: {describe(exc)}"}
    tokens.forget()
    renewed = next((t for t in tokens.status(cfg, force=True) if t["name"] == name), None)
    return {"ok": True, "message": "Saved. " + (renewed["message"] if renewed else "")}


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


def record_click(cfg: MyGeekyConfig, kind: str, item: dict[str, Any]) -> None:
    """A click on a person, repo, Market row or news item is an interest
    signal (terms only; see interests.py). Never raises."""
    try:
        from .. import interests
        if kind == "person":
            sources = " ".join(s.split(":", 1)[-1].replace("/", " ") for s in item.get("sources") or [])
            interests.record("person", f"{item.get('bio') or ''} {sources}", source=item.get("username", ""), cfg=cfg)
        elif kind == "repo":
            name = item.get("full_name") or item.get("repo") or ""
            interests.record("repo", f"{name.replace('/', ' ')} {item.get('description') or ''} "
                                     f"{item.get('language') or ''}", topics=item.get("topics") or [],
                             source=name, cfg=cfg)
        elif kind in ("news", "paper", "headline"):
            interests.record("news", item.get("title", ""), topics=item.get("match") or [],
                             source=item.get("id", ""), cfg=cfg)
    except Exception:
        pass


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
    from .. import papers
    rows = last_contributions(cfg.contribute_max_returned)
    return [{**r, "paper": r.get("paper") or papers.cached_paper(r.get("full_name", ""))} for r in rows]


def get_trends(cfg: MyGeekyConfig) -> dict[str, Any]:
    """The saved research trends -- local only, no network."""
    from .. import papers
    return papers.load_trends()


def trends_due(cfg: MyGeekyConfig) -> bool:
    from .. import papers
    return bool(cfg.github_username) and papers.trends_due(cfg, papers.load_trends())


def refresh_trends(cfg: MyGeekyConfig, force: bool = False) -> dict[str, Any]:
    from .. import papers
    try:
        return papers.refresh_trends(cfg, force=force)
    except Exception as exc:   # surfaced in the view, not a crash
        from ..errors import describe
        return {**papers.load_trends(), "error": f"Couldn't update the research trends: {describe(exc)}"}


def repo_people(cfg: MyGeekyConfig, repo: str) -> list[dict[str, Any]]:
    from .. import papers
    try:
        return papers.repo_people(_build_client(cfg), repo)
    except Exception:
        return []


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
        # new follows, and repos you starred or forked, teach myGeeKy what you're into
        before = {u.lower() for u in (cache or {}).get("following") or []}
        if before:
            try:
                from .. import interests
                interests.learn_from_github(client, cfg, [u for u in following if u.lower() not in before])
            except Exception:
                pass   # learning is a bonus; the activity feed matters more
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


def get_news(cfg: MyGeekyConfig) -> dict[str, Any]:
    """The saved news -- local only, no network."""
    from .. import news
    return news.load_state()


def get_headlines(cfg: MyGeekyConfig) -> dict[str, Any]:
    """The saved headlines -- local only, no network."""
    from .. import headlines
    return headlines.load_state()


def refresh_headlines(cfg: MyGeekyConfig, force: bool = False) -> dict[str, Any]:
    from .. import headlines
    try:
        return headlines.refresh(cfg, force=force)
    except Exception as exc:   # surfaced in the tab, not a crash
        from ..errors import describe
        return {**headlines.load_state(), "error": f"Couldn't update the headlines: {describe(exc)}"}


def refresh_news_and_headlines(cfg: MyGeekyConfig, force: bool = False) -> dict[str, Any]:
    return {"news": refresh_news(cfg, force=force), "headlines": refresh_headlines(cfg, force=force)}


def news_mentions(repos: list[str]) -> dict[str, dict[str, Any]]:
    """{owner/name: the story} for repos in this week's news or discussions (local files only)."""
    from .. import badges, headlines, news
    try:
        items = (news.load_state().get("items") or []) + (headlines.load_state().get("items") or [])
        return badges.in_the_news(repos, items)
    except Exception:
        return {}


def news_refresh_due(cfg: MyGeekyConfig) -> bool:
    from .. import news
    from .. import headlines
    return (bool(cfg.news_sources) and news.refresh_due(cfg, news.load_state())) or \
        (cfg.headlines_enabled and headlines.refresh_due(cfg, headlines.load_state()))


def refresh_news(cfg: MyGeekyConfig, force: bool = False) -> dict[str, Any]:
    from .. import keywords, news
    try:
        keywords.refresh_if_due()   # a newer keyword dictionary, at most once a week
    except Exception:
        pass
    try:
        return news.refresh(cfg, force=force)
    except Exception as exc:   # surfaced in the tab, not a crash
        from ..errors import describe
        return {**news.load_state(), "error": f"Couldn't update the news: {describe(exc)}"}


def sync_enabled(cfg: MyGeekyConfig) -> bool:
    if not cfg.sync_repo or not cfg.sync_auto:
        return False
    try:
        from .. import sync
        return sync.is_initialized() and sync.git_exe() is not None
    except Exception:
        return False


def sync_now(cfg: MyGeekyConfig) -> dict[str, Any]:
    """Two-way sync with your private data repo: this computer's changes go up,
    the other computers' come down. Returns whether anything came down."""
    from .. import sync
    if not sync_enabled(cfg):
        return {"ok": False, "skipped": True}
    try:
        before = sync._git("rev-parse", "HEAD", check=False).stdout.strip()
        message = sync.push()
        after = sync._git("rev-parse", "HEAD", check=False).stdout.strip()
    except Exception as exc:
        from ..errors import describe
        return {"ok": False, "error": describe(exc)}
    return {"ok": True, "changed": before != after, "message": message}


def get_keywords(cfg: MyGeekyConfig) -> dict[str, Any]:
    """Your keywords, each green (the dictionary knows what it means) or red
    (used as a plain word until the dictionary learns it)."""
    from .. import keywords
    rows = []
    for word in cfg.keywords:
        entry = keywords.lookup(word)
        rows.append({"word": word, "known": entry is not None,
                     "related": [keywords.label_of(r) for r, _ in (entry or {}).get("related", [])
                                 if len(r) >= 3][:6]})
    terms = keywords.load()["terms"]
    return {"rows": rows, "version": keywords.load().get("version", ""),
            "vocabulary": sorted({keywords.label_of(t) for t in terms})}


def set_keywords(cfg: MyGeekyConfig, words: list[str]) -> dict[str, Any]:
    """Save your keywords; on Signals, republish your beacon so red ones reach the maker."""
    seen, clean = set(), []
    for w in words:
        w = " ".join(str(w).split())[:40]
        if w and w.lower() not in seen:
            seen.add(w.lower())
            clean.append(w)
    cfg.keywords = clean
    save_config(cfg)
    note = ""
    if cfg.beacon_enabled and auth.get_beacon_token(cfg.github_username):
        try:
            from .. import beacon as bc
            bc.publish(cfg, bc.load_my_beacon())
        except Exception as exc:
            note = f"Saved. (Couldn't update your beacon: {exc})"
    return {"ok": True, "note": note}


def suggest_keyword(word: str) -> bool:
    from .. import ideas
    return open_link(ideas.keyword_url(word))


def is_admin(cfg: MyGeekyConfig) -> bool:
    from .. import admin
    return admin.is_admin(cfg)


def admin_data(cfg: MyGeekyConfig) -> dict[str, Any]:
    """The admin tab from local state (no network)."""
    from .. import admin
    state = admin.load()
    return {"prospects": admin.prospects(state), "funnel": admin.funnel(state),
            "invited_today": admin.invited_today(state), "inbox": state.get("inbox") or [],
            "adoption": state.get("adoption") or {}, "fetched_at": state.get("updated_at"),
            "keyword_requests": state.get("keyword_requests") or []}


def admin_refresh(cfg: MyGeekyConfig) -> dict[str, Any]:
    from .. import admin, ideas
    if not admin.is_admin(cfg):
        return {"error": "Admin only."}
    try:
        client = _build_client(cfg)
        admin.refresh_prospects(client, cfg)
        state = admin.load()
        state["inbox"] = ideas.inbox(client)
        state["adoption"] = admin.adoption(client)
        from .. import keywords
        state["keyword_requests"] = keywords.keyword_requests(client, cfg)
        admin.save(state)
    except Exception as exc:
        from ..errors import describe
        return {"error": f"Couldn't refresh: {describe(exc)}"}
    return {"ok": True}


def admin_mark(login: str, status: str) -> dict[str, Any]:
    from .. import admin
    return admin.mark(login, status)


def admin_invite(cfg: MyGeekyConfig, person: dict[str, Any]) -> dict[str, str]:
    from .. import admin
    return admin.invite(person, cfg)


def get_brain(cfg: MyGeekyConfig) -> dict[str, Any]:
    """Everything myGeeKy has learned about you, for the Model tab -- local only."""
    from datetime import timedelta
    from .. import interests, papers, scholar
    field = [t["name"] for t in (papers.load_trends().get("topics") or [])]
    if not field:
        field = list(cfg.topics) + scholar.scholar_topics(scholar.load_scholar_profile())
    since = datetime.now(timezone.utc) - timedelta(days=30)
    taught = {"clicks": 0, "follows": 0, "stars": 0, "forks": 0}
    for ev in interests.load_events():
        try:
            if datetime.fromisoformat(ev["at"]) < since:
                continue
        except (KeyError, ValueError, TypeError):
            continue
        kind = ev.get("kind")
        key = {"follow": "follows", "star": "stars", "fork": "forks"}.get(kind, "clicks")
        taught[key] += 1
    return {
        "user": cfg.github_username,
        "field": field[:6],
        "learned": interests.learned_terms(cfg, 10) if cfg.interest_learning else [],
        "explore": interests.explore_terms(cfg, 3) if cfg.explore_share > 0 else [],
        "explore_share": cfg.explore_share,
        "taught": taught,
        "learning": cfg.interest_learning,
        "half_life": cfg.interest_half_life_days,
    }


def get_learned_interests(cfg: MyGeekyConfig) -> list[tuple[str, float]]:
    from .. import interests
    return interests.learned_terms(cfg, 10)


def get_market(cfg: MyGeekyConfig) -> dict[str, Any]:
    """The saved board -- local only, no network."""
    from .. import producthunt
    from ..market import compute_board, load_state
    state = load_state()
    from .. import papers
    rows = [{**r, "paper": papers.cached_paper(r.get("repo", ""))} for r in compute_board(state)]
    return {"rows": rows, "updated_at": state.get("updated_at"),
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
    can_send = auth.get_beacon_token(cfg.github_username) is not None
    if can_send:
        try:   # after an update: publish this computer's key once, so others can send to you
            bc.ensure_published(cfg)
        except Exception as exc:
            error = error or f"Couldn't update your beacon: {exc}"
    key = bc.private_key_or_none(cfg)
    mine = bc.load_my_beacon()
    incoming = bc.inbox(cache, cfg, mine, key)
    return {
        "enabled": True,
        "can_send": can_send,
        "quiet": cfg.beacon_quiet,
        "incoming": [] if cfg.beacon_quiet else incoming,
        "held": len(incoming) if cfg.beacon_quiet else 0,
        "people": bc.people(cache, cfg, mine, private_key=key),
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


def set_signals_quiet(cfg: MyGeekyConfig, quiet: bool) -> dict[str, Any]:
    from .. import beacon as bc
    try:
        bc.set_quiet(cfg, quiet)
    except Exception as exc:
        cfg.beacon_quiet = not quiet
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


def mute_signals(cfg: MyGeekyConfig, login: str, mute: bool = True) -> None:
    """Hide (or show again) someone's signals. They're never told."""
    from .. import beacon as bc
    bc.set_muted(cfg, login, mute)


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


LINK_PREFIXES = ("https://github.com/", "https://www.producthunt.com/posts/", "https://arxiv.org/abs/",
                 "https://www.biorxiv.org/content/", "https://news.ycombinator.com/item?id=",
                 "https://doi.org/", "https://orcid.org/", "https://openalex.org/")


def open_link(url: str) -> bool:
    """Like open_profile, but also lets Product Hunt launch pages through."""
    from .. import headlines
    if not isinstance(url, str) or not (url.startswith(LINK_PREFIXES) or headlines.allowed_link(url)):
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
    """Start the panel. It usually runs without a console (pythonw), so a
    failure must be shown in a message box -- otherwise it just never appears."""
    import sys
    from ..config import LOG_DIR
    from ..errors import ISSUES_URL, describe, save_crash_report, show_message_box

    def log_late_error(kind, exc, tb):   # errors after start-up: report, don't crash silently
        if issubclass(kind, KeyboardInterrupt):
            return sys.__excepthook__(kind, exc, tb)
        save_crash_report(exc.with_traceback(tb), LOG_DIR, "panel")
    sys.excepthook = log_late_error
    try:
        _main()
    except SystemExit:
        raise
    except Exception as exc:
        report = save_crash_report(exc, LOG_DIR, "panel start-up")
        show_message_box("myGeeKy couldn't start",
                         f"{describe(exc)}\n\n"
                         + (f"Full details were saved to:\n{report}\n\n" if report else "")
                         + f"If it keeps happening, please report it at {ISSUES_URL}")
        raise SystemExit(1)


def _main() -> None:
    import os
    import sys
    from .bootstrap import ensure_qt
    ensure_qt()  # installs Qt on first use, wherever this Python can hold it
    # Linux desktops without the xdg-desktop-portal "Settings" interface make Qt's
    # GNOME theme code log a harmless dbus error on every start; it only means Qt
    # can't ask the desktop for its dark/light preference. Keep the terminal quiet.
    rules = os.environ.get("QT_LOGGING_RULES", "")
    if "qt.qpa.theme" not in rules:
        os.environ["QT_LOGGING_RULES"] = ";".join(r for r in (rules, "qt.qpa.theme.gnome=false") if r)

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
    app.setApplicationName("mygeeky")
    if sys.platform.startswith("linux"):
        app.setDesktopFileName("mygeeky")    # the dock/taskbar uses the menu entry's icon
    if ICON_WINDOW.exists():
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(ICON_WINDOW)))
    cfg = load_config()
    panel = MyGeekyPanel(cfg)
    panel.show()
    app.exec()


if __name__ == "__main__":
    main()
