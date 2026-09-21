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
LOG_DIR = DATA_DIR / "logs"
AVATAR_CACHE_DIR = DATA_DIR / "avatar_cache"


@dataclass
class MyGeekyConfig:
    # Identity
    github_username: str = ""

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
    max_suggestions_returned: int = 15
    similarity_threshold: float = 0.08
    content_similarity_weight: float = 0.5
    follow_back_ratio_weight: float = 0.3
    activity_weight: float = 0.2
    rate_limit_sleep_seconds: float = 1.5
    search_pause_seconds: float = 2.1     # GitHub's search endpoints have their own, tighter rate limit (~30/min)

    # Learning
    min_training_samples: int = 8         # need at least this many labeled examples before ML kicks in
    ml_blend_weight: float = 0.5          # how much the learned model influences the final score once trained
    training_mass_follow_outlier: int = 3000  # exclude accounts following more than this from training data

    # Optional live GUI (`mygeeky gui`, requires `pip install mygeeky[gui]`) -- a
    # small always-on-top glass panel docked to a screen edge. Purely a local
    # viewer over the same data the CLI produces; it never runs a full
    # candidate search on its own (see gui/app.py) and never follows anyone --
    # every profile link is opened in your browser only when you click it.
    gui_dock_side: str = "right"          # "right" or "left"
    gui_expanded_width: int = 380
    gui_folded_width: int = 48
    gui_panel_height_fraction: float = 0.25   # fraction of screen height the panel occupies -- a short
                                               # docked strip rather than a full sidebar; the Live tab's
                                               # rotating spotlight is designed to fit this compact height
    gui_activity_refresh_minutes: int = 5     # min minutes between automatic activity-feed refreshes
    gui_activity_limit: int = 30              # how many recent activity events to show
    gui_theme: str = "midnight"               # "frosted" | "midnight" | "aurora" -- switchable live via the panel's swatch buttons
    gui_live_rotate_seconds: float = 4.5      # how often the Live tab's spotlight card auto-advances
    gui_opacity: float = 1.0                  # whole-window opacity (0.0-1.0); the settings panel exposes this
                                               # as "Transparency" (0% = opaque, 100% = fully transparent), i.e.
                                               # the inverse of this value

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
    base.update(raw)
    return MyGeekyConfig(**base)


def save_config(cfg: MyGeekyConfig) -> None:
    ensure_dirs()
    CONFIG_FILE.write_text(json.dumps(cfg.to_dict(), indent=2), encoding="utf-8")


def config_summary(cfg: MyGeekyConfig) -> str:
    lines = [f"Config file: {CONFIG_FILE}", ""]
    for k, v in cfg.to_dict().items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)
