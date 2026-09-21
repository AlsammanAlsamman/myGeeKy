<p align="center">
  <img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/src/mygeeky/gui/assets/icon_256.png" width="120" alt="myGeeKy icon: two geeks hugging inside a heart">
</p>

<h1 align="center">myGeeKy</h1>
<p align="center">Find fellow GitHub geeks who match your CV and repos — and are likely to follow you back.</p>

<p align="center">
  <a href="https://pypi.org/project/mygeeky/"><img alt="PyPI" src="https://img.shields.io/pypi/v/mygeeky.svg"></a>
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg">
  <img alt="Python 3.9+" src="https://img.shields.io/badge/python-3.9%2B-blue.svg">
  <img alt="Platform: Windows | Linux" src="https://img.shields.io/badge/platform-windows%20%7C%20linux-lightgrey.svg">
  <img alt="No auto-follow, ever" src="https://img.shields.io/badge/auto--follow-never-critical.svg">
</p>

**myGeeKy never follows anyone for you.** There's no follow/unfollow code
in this project at all (see [Safety](#safety)) — every suggestion is ranked,
explained, and only ever a suggestion. You look, you click, you follow
people yourself, by hand, on github.com.

> **Why this exists:** I don't have Facebook. I only want to follow people
> I can genuinely learn from — and who might learn something from me too.
> myGeeKy is a GitHub-friendly alternative for people like me: we want real
> friends, and we're wary of fake ones.

<p align="center">
  <img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshot.png" width="380" alt="myGeeKy's live panel, docked and translucent, showing the Live tab's scrolling activity feed">
</p>
<p align="center"><em>The actual panel — translucent, docked to the screen edge, showing real activity from people you follow.</em></p>

## How it works

GitHub's Markdown renderer strips `<script>` tags (security), so it can't
run a live JS diagram inline — the image below is a preview of a real,
animated, click-to-expand HTML/JS page that ships in this repo at
[`docs/flowchart.html`](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/flowchart.html):

<p align="center">
  <a href="https://raw.githack.com/AlsammanAlsamman/myGeeKy/main/docs/flowchart.html">
    <img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/flowchart_preview.png" width="480" alt="How myGeeKy works — click for the live interactive version">
  </a>
</p>

**[▶ Open the live interactive version](https://raw.githack.com/AlsammanAlsamman/myGeeKy/main/docs/flowchart.html)**
— real vanilla JS (click any step to expand it), served straight off this
repo via [githack](https://raw.githack.com), no build step, no server.
(If that link is ever slow/unavailable: clone the repo and open
`docs/flowchart.html` directly in a browser — it's fully self-contained,
zero dependencies.)

*The pink "You follow — by hand" step is the only place a follow ever
happens — myGeeKy has no follow/unfollow code anywhere in the project; see
[Safety](#safety).*

## What it does

1. **Understands you** — reads your CV (txt/md/pdf) plus your own GitHub
   repos (languages, topics, descriptions) to build a profile of what
   you're into, and auto-derives a weighted "domain vocabulary" from that
   corpus (not a hardcoded field-specific wordlist).
2. **Collects candidates from multiple sources**, not just a plain search:
   GitHub user search (language/location/follower filters), followers of
   well-known accounts in your field (`seed_accounts`), stargazers of
   relevant repos (`seed_repos`), stargazers of your own repos, and
   optionally second-degree contacts (people followed by people you
   already follow). Candidates corroborated by more than one source get a
   small ranking boost.
3. **Filters out noise before scoring**: accounts following more than
   `max_following` people (a growth-hacking/mass-follow pattern, not
   genuine engagement), dormant/throwaway-looking accounts, organizations,
   and — for the top-ranked candidates — a **real per-repo activity check**
   (a maintained repo pushed to recently, or a freshly-created one; a
   profile's `updated_at` alone can just reflect a bio edit).
4. **Scores each surviving candidate** on:
   - content similarity to your CV/repos (TF-IDF + cosine similarity)
   - how likely they are to follow back (their own following/follower ratio)
   - how active their account is
   - once you've used it a while: a learned model (see below)
5. **Suggests two ranked lists**, not one — printed, or returned as JSON.
   Nothing is followed automatically:
   - **Likely to follow back** — the blended score above.
   - **Domain-fit highlights** — ranked purely by match to your CV/repos,
     *independent* of follow-back likelihood. A senior domain expert who
     follows almost no one on GitHub is exactly who the follow-back score
     would otherwise bury, and is often the best actual match.
6. **Learns from real outcomes**, not just from waiting:
   - `mygeeky bootstrap` seeds the model immediately from accounts you
     *already* follow (checks, read-only, who already follows you back) —
     so you get real training data on day one instead of waiting weeks.
   - `mygeeky learn` (meant to run weekly) looks at who *you* actually
     followed since the last check, checks whether they followed back, and
     retrains a logistic-regression model on the growing set of outcomes —
     reporting cross-validated AUC so you can see how trustworthy it is,
     and excluding mass-follow outliers from training.

## Install

```bash
pip install mygeeky
```

(For PDF CVs: `pip install "mygeeky[pdf]"`.)

## Quick start

```bash
mygeeky init      # asks for your GitHub username, CV, and the kind of people you're looking for
mygeeky run       # get your first batch of suggestions
```

`mygeeky init` asks a short set of questions — all optional, all editable
later:

- Your GitHub username
- Your CV (a file path, pasted text, or skip)
- Languages / topics / keywords / locations you're looking for
- Optional extra candidate sources: well-known accounts in your field, relevant repos
- Follower-count range, `max_following`, minimum repo count, how many suggestions per run

Then it offers to store a GitHub token (see [Safety](#safety) — this is
handled very deliberately), and — if a token is set up — offers to run
`mygeeky bootstrap` immediately so you're not starting the learning model
from zero.

## Everyday use

```bash
mygeeky run                 # search + rank + suggest (two lists: followback + domain-fit)
mygeeky run --json          # same, as JSON (for scripts / AI agents)
mygeeky suggestions         # re-print the last run's results without re-querying GitHub
mygeeky bootstrap           # seed the model from accounts you already follow (run once, early)
mygeeky learn               # check who you followed since last time, learn from who followed back
mygeeky pipeline            # learn, then run — this is what the weekly schedule calls
mygeeky gui                 # launch the live glass panel (needs `pip install "mygeeky[gui]"`)
```

## Running it weekly

myGeeKy doesn't run in the background by itself — you decide when it's
allowed to touch your OS's task scheduler:

```bash
mygeeky schedule show          # print the exact command/cron line for your OS (does nothing)
mygeeky schedule install --yes # actually register it (Windows Task Scheduler / cron)
mygeeky schedule remove        # undo it
```

The scheduled job runs `mygeeky pipeline` — i.e. it *checks and learns*
from what you did last week, then produces new suggestions. It still never
follows anyone.

## Live glass panel (optional GUI)

```bash
pip install "mygeeky[gui]"
mygeeky gui          # (or the standalone `mygeeky-gui` command)
```

A small, translucent, always-on-top panel docked to the edge of your
screen (Windows and Linux), built with [PySide6/Qt](https://doc.qt.io/qtforpython-6/)
— native widgets, not a webview. (An earlier version used pywebview; its
WebView2-on-Windows transparency turned out to be a confirmed, currently
inconsistent upstream bug that even its maintainer can't reproduce reliably
across machines — see [pywebview#1611](https://github.com/r0x0r/pywebview/issues/1611).
Qt's `WA_TranslucentBackground` is the mature, well-supported way apps
actually get real per-pixel window transparency on Windows.) Click the
folded tab to expand it; click the arrow to fold it back to a slim strip.

- **Suggestions tab** — both lists from `mygeeky run` (avatar, bio, score),
  each with an **Open →** button that opens their GitHub profile in your
  browser. That's the *only* thing a click ever does — myGeeKy still never
  follows anyone; a "Refresh" button re-runs a real search on demand (it
  never does this on a timer, to avoid hammering GitHub's rate limits).
- **Activity tab** — a live feed of what people you follow are actually
  doing (pushes, merged PRs, new repos, releases, stars...), from GitHub's
  own events API. Refreshes automatically, but no more often than
  `gui_activity_refresh_minutes` (default 5) — and that refresh is a single
  cheap API call, not a full search.
- **Model tab** — a chart of your learned model's cross-validated AUC and
  training-set size over time, so you can watch it actually improve as you
  run `mygeeky bootstrap`/`learn`.

**⚙ Settings** — click the small gear icon in the header to open a compact
panel with:
- **Theme**, switchable live (no restart needed): **Midnight Glass** (dark,
  cool-toned, the default), **Frosted White** (light, warm,
  iOS-control-center-like), and **Vibrant Aurora** (saturated, colorful,
  leans into the geeky/hearts branding).
- **Transparency**, a slider from 0% (fully opaque) to 100% (fully
  transparent), applied live as you drag.

Both choices are saved (`gui_theme`, `gui_opacity`) and remembered next time
you open the panel.

Config: `gui_dock_side` (`"right"`/`"left"`), `gui_expanded_width`,
`gui_folded_width`, `gui_panel_height_fraction`, `gui_activity_refresh_minutes`,
`gui_activity_limit`, `gui_theme` (`"midnight"`/`"frosted"`/`"aurora"`),
`gui_opacity` (`0.0`-`1.0`, note the settings panel's slider shows this
inverted, as "Transparency") — same `mygeeky config set` mechanism as
everything else.

No LLM/AI is used anywhere in the GUI (or the rest of myGeeKy) — the
suggestions, activity feed, and model chart are all built from the same
TF-IDF/logistic-regression pipeline the CLI uses, so there's no API cost
and nothing to configure to make it work. (There's deliberately no way to
plug in a Claude subscription either — that kind of auth is scoped to
Claude Code itself and isn't something a third-party tool can piggyback
on; if you ever want AI-written explanations, that'd be a separate opt-in
using your own API key or a local model, not something myGeeKy needs.)

*Rendering note: the panel is genuinely transparent (real per-pixel alpha,
confirmed on Windows 11), but it's a flat translucency, not a blurred
"frosted glass" effect — Windows' native DWM Acrylic/Mica backdrop was
tried and turned out to conflict with Qt's own transparency on tested
hardware, reliably making the window opaque instead, so it isn't wired up.
On Linux, real transparency depends on your compositor/window manager the
same way it does for any Qt app.*

## All parameters (adjustable, or leave at the defaults)

```bash
mygeeky config show
mygeeky config set max_followers 3000
mygeeky config set languages "Python, Rust, Go"
mygeeky config reset
```

<details>
<summary><strong>Full parameter table</strong> — every key, what it does, and its default</summary>

| Key | Meaning | Default |
|---|---|---|
| `languages` | languages you're looking for | `[]` (any) |
| `topics` | topics/interests you're looking for | `[]` (any) |
| `keywords` | extra free-text interests fed into matching | `[]` |
| `locations` | optional location filter | `[]` (any) |
| `min_followers` / `max_followers` | candidate follower-count range | `0` / `20000` |
| `max_following` | reject candidates following more than this (growth-hacking signal) | `500` |
| `min_public_repos` | minimum public repos a candidate must have | `2` |
| `require_followers_or_following` / `min_followers_gate` / `min_following_gate` | drop dormant/throwaway accounts with neither | `true` / `5` / `5` |
| `exclude_organizations` | skip org accounts | `true` |
| `exclude_already_following` | skip people you already follow | `true` |
| `exclude_users` | usernames to never suggest | `[]` |
| `seed_accounts` | candidates = followers of these well-known accounts | `[]` |
| `seed_repos` | candidates = stargazers of these `owner/repo` repos | `[]` |
| `include_own_stargazers` | candidates = people who starred your own repos | `true` |
| `include_second_degree` / `second_degree_sample` | candidates = who a sample of your followees follow (expensive) | `false` / `15` |
| `source_max_pages` | pages fetched per candidate source | `3` |
| `activity_check_top_n` | how many top-ranked candidates get the real per-repo activity check | `150` |
| `max_repo_push_age_days` / `recent_upload_days` / `min_maintain_span_days` | real activity QC thresholds | `365` / `120` / `60` |
| `domain_vocab_size` / `domain_highlight_count` | size of the auto-derived domain vocabulary / highlight list | `25` / `15` |
| `search_pages` | GitHub search pages scanned per query | `3` |
| `max_candidates_per_run` | cap on candidates evaluated per run | `60` |
| `max_suggestions_returned` | cap on follow-back suggestions shown per run | `15` |
| `similarity_threshold` | minimum blended score to be suggested | `0.08` |
| `content_similarity_weight` / `follow_back_ratio_weight` / `activity_weight` | heuristic scoring weights | `0.5` / `0.3` / `0.2` |
| `rate_limit_sleep_seconds` / `search_pause_seconds` | pacing for normal vs. GitHub's tighter search-API rate limit | `1.5` / `2.1` |
| `min_training_samples` | labeled examples needed before the ML model kicks in | `8` |
| `ml_blend_weight` | how much the learned model influences the final score once trained | `0.5` |
| `training_mass_follow_outlier` | exclude training examples from accounts following more than this | `3000` |
| `gui_dock_side` | which screen edge the live panel docks to (`"right"`/`"left"`) | `"right"` |
| `gui_expanded_width` / `gui_folded_width` | panel width in pixels, expanded vs. folded | `380` / `48` |
| `gui_panel_height_fraction` | panel height as a fraction of the screen height | `0.25` |
| `gui_activity_refresh_minutes` | minimum minutes between automatic activity-feed refreshes | `5` |
| `gui_activity_limit` | how many recent activity events to show | `30` |
| `gui_theme` | glass style (`"midnight"`/`"frosted"`/`"aurora"`) | `"midnight"` |
| `gui_opacity` | whole-window transparency, adjustable via the ⚙ settings panel | `1.0` |

</details>

## Safety

- **No follow/unfollow code exists in this project.** `github_client.py`
  only implements read endpoints (`GET`). There is no method that calls
  `PUT /user/following/*`, so myGeeKy cannot follow anyone even by
  accident, regardless of what token scope you provide.
- **Your GitHub token is never written to a file.** It's requested with
  hidden input (`getpass`) and stored only in your OS's encrypted secret
  store via the [`keyring`](https://pypi.org/project/keyring/) package
  (Windows Credential Locker / macOS Keychain / Linux Secret Service).
  `mygeeky auth status` shows *where* it's coming from — never the value.
  An environment variable (`MYGEEKY_GITHUB_TOKEN`) is supported as an
  explicit, opt-in fallback for CI/agent contexts.
- **Minimal token scope.** myGeeKy only reads public profile/repo/follower
  data — create your token with **no scopes at all**, or a fine-grained
  token limited to read-only public repositories/followers. Never grant it
  write or admin scopes.
- All local state (config, CV text, suggestion history, the learned model)
  lives under your OS's standard config/data directories, not inside this
  project folder, so nothing personal ever ends up in a repo or a published
  package by accident.
- **The GUI follows the same rule.** `open_profile()` (the only thing a
  click in the panel can trigger) refuses to open anything that isn't a
  `https://github.com/...` URL, and there's no other code path from the
  panel to the network beyond the read-only suggestion/activity fetches
  described above.

## Using myGeeKy from an AI agent / script

Every result-producing command supports `--json`:

```bash
mygeeky run --json
```

<details>
<summary><strong>Example output shape</strong></summary>

```json
{
  "followback": [
    {
      "username": "example-geek",
      "profile_url": "https://github.com/example-geek",
      "score": 0.4123,
      "score_breakdown": {"heuristic": 0.41, "ml_proba": null, "blended": 0.41},
      "features": {
        "content_similarity": 0.31,
        "follow_back_ratio": 0.9,
        "activity_recency": 1.0,
        "shared_languages": 0.5,
        "shared_topics": 0.33
      },
      "domain_fit": 0.62,
      "followers": 120,
      "following": 140,
      "public_repos": 34,
      "bio": "...",
      "sources": ["search:language:Python followers:0..20000 ...", "starred_your_repo:you/tool"],
      "n_sources": 2,
      "timestamp": "2026-09-17T12:00:00+00:00",
      "list": "followback"
    }
  ],
  "domain_highlights": [
    { "...": "same shape, ranked by domain_fit instead of score", "list": "domain" }
  ]
}
```

</details>

An agent can read this list and *present* it to you — it should never be
wired up to auto-follow anyone; that defeats the entire point of this tool.

## How the "learning" works

<details>
<summary><strong>Bootstrapping, retraining, and how to read the AUC</strong></summary>

**Bootstrapping (day one):** `mygeeky bootstrap` looks at accounts you
*already* follow, checks (read-only) whether each one follows you back,
and logs `(features, followed_back)` as a training example immediately —
so the model has real data from the start instead of an empty cold start
that only grows by however many people you manually follow each week.

**Ongoing (weekly):** `mygeeky learn` compares your current GitHub
following list against a snapshot taken at the last check. Anyone new is a
person *you* chose to follow. It checks whether they followed back and
logs the same kind of training example.

In both cases: once there are at least `min_training_samples` examples
with both outcomes represented (excluding accounts following more than
`training_mass_follow_outlier`, a growth-hacking outlier that would
distort the model), a `scikit-learn` `LogisticRegression` model is trained
and its prediction is blended into future scores (`ml_blend_weight`
controls how much). myGeeKy reports the model's cross-validated AUC each
time it retrains, so you can judge how trustworthy it is rather than take
it on faith — with a small training set, treat it as directional, not
precise. This is intentionally simple and transparent rather than a black
box — you can inspect `score_breakdown` on every suggestion to see the
heuristic and learned components separately.

</details>

## Two lists, on purpose

`mygeeky run` produces a **followback** list (ranked by the blended
score above) and a **domain_highlights** list (ranked purely by
`domain_fit`, an auto-derived match to your CV/repo vocabulary,
independent of follow-back likelihood). These optimize for different
things: some of the best domain-specific matches — senior researchers,
niche maintainers — follow almost no one on GitHub, so the reciprocation
model correctly scores them low even though they may be the best actual
fit. Both lists go through the same activity-QC and bot/dormant filters.

## License

MIT — see [LICENSE](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/LICENSE).
