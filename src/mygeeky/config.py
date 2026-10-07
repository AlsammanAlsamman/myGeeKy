"""Configuration storage for myGeeKy.

All state lives under the OS-appropriate user config/data directories
(via `platformdirs`) -- never inside the project/repo itself, so nothing
personal (CV keywords, search parameters, learned model) ever risks being
committed or published by accident.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir, user_data_dir

APP_NAME = "mygeeky"

CONFIG_DIR = Path(user_config_dir(APP_NAME))
DATA_DIR = Path(user_data_dir(APP_NAME))

CONFIG_FILE = CONFIG_DIR / "config.json"
SUGGESTIONS_LOG = DATA_DIR / "suggestions_history.jsonl"
TRAINING_LOG = DATA_DIR / "training_data.jsonl"
FOLLOWING_SNAPSHOT = DATA_DIR / "following_snapshot.json"
EXCLUDED_FILE = DATA_DIR / "excluded.json"
MODEL_FILE = DATA_DIR / "model.pkl"
MODEL_HISTORY_LOG = DATA_DIR / "model_history.jsonl"
ACTIVITY_CACHE_FILE = DATA_DIR / "activity_cache.json"
CV_TEXT_FILE = DATA_DIR / "cv_text.txt"
SCHOLAR_PROFILE_FILE = DATA_DIR / "scholar_profile.json"
CONTRIBUTE_LOG = DATA_DIR / "contribute_history.jsonl"
MARKET_FILE = DATA_DIR / "market.json"
PRODUCTHUNT_FILE = DATA_DIR / "producthunt.json"
UPDATE_CHECK_FILE = DATA_DIR / "update_check.json"   # last PyPI version check; never synced
TOKEN_CHECK_FILE = DATA_DIR / "token_check.json"     # tokens' expiry dates (never the tokens); never synced
SYNCED_CONFIG_FILE = DATA_DIR / "config.synced.json"
LOG_DIR = DATA_DIR / "logs"
AVATAR_CACHE_DIR = DATA_DIR / "avatar_cache"
MY_BEACON_FILE = DATA_DIR / "beacon.json"          # what you publish to <you>/mygeeky-beacon
BEACON_CACHE_FILE = DATA_DIR / "beacons_cache.json"  # everyone else's beacons, last read


@dataclass
class MyGeekyConfig:
    # Identity
    github_username: str = ""

    # Where your profile comes from beyond your GitHub repos -- all optional.
    # `mygeeky profile refresh` re-reads these (CV pdf -> text, ORCID + OpenAlex, Google Scholar).
    cv_path: str = ""                     # remembered so the CV can be re-extracted when it changes
    orcid_id: str = ""                    # e.g. "0000-0002-1825-0097"; enables ORCID + OpenAlex enrichment
    scholar_id: str = ""                  # Google Scholar user id, the `user=` part of your profile URL

    # What "geeks like him/her" means -- all optional, all adjustable.
    languages: list[str] = field(default_factory=list)      # e.g. ["Python", "Rust"]
    topics: list[str] = field(default_factory=list)         # e.g. ["bioinformatics", "llm"]
    keywords: list[str] = field(default_factory=list)       # extra free-text interests
    locations: list[str] = field(default_factory=list)      # optional, e.g. ["Cairo", "Remote"]

    # Candidate filters
    min_followers: int = 0
    max_followers: int = 20000
    max_following: int = 500              # past this, following-to-followers ratio looks like growth-hacking,
                                           # not genuine engagement, even for non-bot accounts
    min_public_repos: int = 2
    require_followers_or_following: bool = True  # drop accounts with neither -- looks dormant/throwaway
    min_followers_gate: int = 5
    min_following_gate: int = 5
    exclude_organizations: bool = True
    exclude_already_following: bool = True
    exclude_users: list[str] = field(default_factory=list)

    # Candidate sources, beyond plain GitHub user search -- all optional
    seed_accounts: list[str] = field(default_factory=list)   # candidates = followers of these well-known accounts
    seed_repos: list[str] = field(default_factory=list)      # "owner/repo" -- candidates = stargazers of these
    include_own_stargazers: bool = True                       # candidates = people who starred your own repos
    include_second_degree: bool = False                        # candidates = who your followees follow (expensive)
    # candidates = owners/contributors of active repos matching your CV/publication terms;
    # these are ranked ahead of the plain language search, which mostly returns famous accounts
    include_domain_repo_people: bool = True
    domain_repo_terms: int = 6                 # how many profile terms to search repos for
    domain_repo_count: int = 20                # how many matching repos to take people from
    second_degree_sample: int = 15            # cap on how many of your followees to expand for second_degree
    source_max_pages: int = 3                  # pages fetched per source (stargazers/followers/etc.)

    # Real per-repo activity QC (hard gate; costs one extra API call per
    # candidate checked, so it only runs on the top-ranked candidates)
    activity_check_top_n: int = 150
    max_repo_push_age_days: int = 365          # a maintained repo must have been pushed to within this window
    recent_upload_days: int = 120              # OR: counts as active if a new (non-fork) repo was created this recently
    min_maintain_span_days: int = 60           # a "maintained" repo must be older than a one-day dump-and-abandon

    # Domain-fit scoring: a vocabulary auto-derived from YOUR OWN CV/repo
    # corpus (not a hardcoded wordlist), scored independently of follow-back
    # likelihood. Domain experts who follow almost no one on GitHub are
    # exactly the people the follow-back heuristic unfairly demotes.
    domain_vocab_size: int = 25
    domain_highlight_count: int = 15

    # Search / scoring knobs
    search_pages: int = 3                 # GitHub search pages to scan per run (30 users/page)
    max_candidates_per_run: int = 60
    # "Likely to follow back" list only: skip accounts that follow almost nobody
    # relative to their audience (following/followers below this), or that are
    # simply too famous to notice a follow. The domain-highlights list ignores these.
    followback_min_ratio: float = 0.05
    followback_max_followers: int = 3000
    max_suggestions_returned: int = 15
    similarity_threshold: float = 0.08
    content_similarity_weight: float = 0.5
    follow_back_ratio_weight: float = 0.3
    activity_weight: float = 0.2
    rate_limit_sleep_seconds: float = 1.5
    search_pause_seconds: float = 2.1     # GitHub's search endpoints have their own, tighter rate limit (~30/min)

    # Repos to contribute to (`mygeeky contribute`): active, non-archived repos
    # matching your profile, with open beginner/help-wanted issues and
    # maintainers who actually merge outside contributors' PRs. Suggest-only:
    # you fork and open PRs yourself.
    contribute_min_stars: int = 10
    contribute_max_stars: int = 20000      # huge projects rarely merge drive-by PRs quickly
    contribute_pushed_within_days: int = 90
    contribute_queries: int = 10           # how many profile terms to turn into repo searches
    contribute_check_top_n: int = 25       # how many top repos get the (costlier) maintainer check
    contribute_max_returned: int = 10
    contribute_extra_terms: list[str] = field(default_factory=list)  # always searched, e.g. ["gwas", "snakemake"]

    # Market: a momentum board of the popular, active repos in your field
    market_size: int = 25                  # repos on the board
    market_terms: int = 8                  # profile terms searched to pick them (weekly)
    market_min_stars: int = 50
    market_pushed_within_days: int = 180
    market_pinned: list[str] = field(default_factory=list)  # "owner/repo" always on the board
    market_refresh_hours: float = 12.0     # panel refreshes the board by itself once it's this old
    # Product Hunt launches in your field, under the board (needs `mygeeky auth producthunt`)
    market_ph_topics: list[str] = field(default_factory=lambda: [
        "developer-tools", "open-source", "github", "artificial-intelligence", "science", "health"])
    market_ph_days: int = 30               # launches from the last N days
    market_ph_size: int = 10               # launches shown

    # Cross-machine sync: your data dir is a clone of a PRIVATE GitHub repo
    # (`mygeeky sync init`). Uses your normal git/gh credentials, never
    # myGeeKy's read-only token, and never syncs any secret.
    sync_repo: str = ""                    # "owner/name", set by `mygeeky sync init`
    sync_auto: bool = True                 # `pipeline` pulls first and pushes last when sync is set up

    # Beacons (`mygeeky beacon init`): non-verbal signals between myGeeKy users
    # (wave, learn-from, collab, watching, kudos) through a PUBLIC repo,
    # <you>/mygeeky-beacon. Off until you opt in; everything in it is public.
    beacon_enabled: bool = False
    beacon_status: str = ""                 # one of beacon.STATUSES, e.g. "open-to-collab"
    beacon_share_interests: bool = True     # publish your topics/keywords/languages as interest tags
    beacon_blocked: list[str] = field(default_factory=list)  # never show signals from these
    beacon_daily_limit: int = 20            # signals you can send per day
    beacon_gesture_ttl_days: int = 90       # signals expire (yours are pruned, others' ignored) after this
    beacon_refresh_minutes: int = 30        # min minutes between re-reading everyone's beacons
    beacon_max_users: int = 60              # beacons read per refresh (one API call each when changed)

    # Updates: check PyPI for a newer myGeeKy once a day (one read-only request)
    check_for_updates: bool = True
    update_dismissed: str = ""             # "Later" on this version hides the banner until a newer one

    # Learning
    min_training_samples: int = 8         # need at least this many labeled examples before ML kicks in
    ml_blend_weight: float = 0.5          # how much the learned model influences the final score once trained
    training_mass_follow_outlier: int = 3000  # exclude accounts following more than this from training data

    # Optional live GUI (`mygeeky gui`, Qt is set up on first run) -- a
    # small always-on-top glass panel docked to a screen edge. Purely a local
    # viewer over the same data the CLI produces; it never runs a full
    # candidate search on its own (see gui/app.py) and never follows anyone --
    # every profile link is opened in your browser only when you click it.
    gui_dock_side: str = "right"          # "right" or "left"
    gui_expanded_width: int = 380
    gui_folded_width: int = 76                # folded, the panel is just the app icon on the screen edge
    gui_folded_height: int = 76
    gui_hearts_enabled: bool = True           # folded icon lets a few small hearts drift up now and then
    gui_hearts_interval_minutes: float = 3.0  # how often; they fade out in ~3 s, never while the panel is open
    gui_folded_opacity: float = 0.5           # folded icon's opacity; it turns fully opaque while hovered
    gui_panel_height_fraction: float = 0.25   # fraction of screen height the panel occupies -- a short
                                               # docked strip rather than a full sidebar; the Live tab's
                                               # rotating spotlight is designed to fit this compact height
    gui_activity_refresh_minutes: int = 5     # min minutes between automatic activity-feed refreshes
    gui_activity_limit: int = 30              # how many recent activity events to show
    gui_activity_match_people: int = 12       # also show activity of this many top suggestions (matched to your
                                               # CV/ORCID/repos); one API call each per refresh, 0 = followed only
    gui_suggestions_auto_refresh_hours: float = 6.0  # panel searches again by itself once the follow-back list is
                                               # empty and the last search is this old; 0 = only on Refresh click
    gui_theme: str = "midnight"               # "frosted" | "midnight" | "aurora" -- switchable live via the panel's swatch buttons
    gui_live_rotate_seconds: float = 4.5      # how often the Live tab's spotlight card auto-advances
    gui_opacity: float = 1.0                  # whole-window opacity (0.0-1.0); the settings panel exposes this
                                               # as "Transparency" (0% = opaque, 100% = fully transparent), i.e.
                                               # the inverse of this value

    # Bumped when a default changes in a way existing configs should pick up
    # (see _migrate). Every saved config carries every key, so a new default
    # alone never reaches people who already ran myGeeKy.
    config_version: int = 2

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULTS = MyGeekyConfig()


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    AVATAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> MyGeekyConfig:
    ensure_dirs()
    if not CONFIG_FILE.exists():
        return MyGeekyConfig()
    raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    base = asdict(MyGeekyConfig())
    # ignore keys this version doesn't know -- a config synced from another
    # machine may have been written by a newer myGeeKy
    base.update({k: v for k, v in raw.items() if k in base})
    return MyGeekyConfig(**_migrate(base, raw.get("config_version", 1)))


def _migrate(values: dict[str, Any], version: int) -> dict[str, Any]:
    if version < 2:
        # 0.4: the folded icon grew from 58px; keep any size someone chose themselves
        if values.get("gui_folded_width") == 58 and values.get("gui_folded_height") == 58:
            values["gui_folded_width"] = values["gui_folded_height"] = 76
    values["config_version"] = MyGeekyConfig.config_version
    return values


def save_config(cfg: MyGeekyConfig) -> None:
    ensure_dirs()
    CONFIG_FILE.write_text(json.dumps(cfg.to_dict(), indent=2), encoding="utf-8")


def config_summary(cfg: MyGeekyConfig) -> str:
    lines = [f"Config file: {CONFIG_FILE}", ""]
    for k, v in cfg.to_dict().items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)
