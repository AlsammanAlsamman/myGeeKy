<p align="center">
  <img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/src/mygeeky/gui/assets/icon_256.png" width="128" alt="myGeeKy icon: two geeks hugging inside a heart">
</p>

<h1 align="center">myGeeKy</h1>

<p align="center">
  <b>Your corner of GitHub: the people, projects and pulse of your field.</b><br>
  <sub>From your CV, repos, ORCID and Google Scholar papers: who to follow, what to contribute to,
  what's rising, and a friendly 👋 from fellow geeks. All in one small panel.</sub>
</p>

<p align="center">
  <a href="https://pypi.org/project/mygeeky/"><img alt="PyPI version" src="https://img.shields.io/pypi/v/mygeeky?color=7fd8ff&label=pypi"></a>
  <a href="https://pypi.org/project/mygeeky/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/mygeeky?color=7a5cff"></a>
  <a href="https://pepy.tech/projects/mygeeky"><img alt="Downloads" src="https://img.shields.io/pepy/dt/mygeeky?color=ff6fd8&label=downloads"></a>
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-35e0c1.svg">
  <img alt="Platform: Windows | Linux" src="https://img.shields.io/badge/platform-windows%20%7C%20linux-lightgrey.svg">
  <img alt="Auto-follow: never" src="https://img.shields.io/badge/auto--follow-never-critical.svg">
</p>

<p align="center">
  <a href="#-whats-inside">What's inside</a> ·
  <a href="#-quick-start">Quick start</a> ·
  <a href="#-the-live-panel">Live panel</a> ·
  <a href="#signal-other-mygeeky-users-without-words-mygeeky-beacon">Signals</a> ·
  <a href="#safety">Safety</a> ·
  <a href="#all-parameters-adjustable-or-leave-at-the-defaults">All settings</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/hero.png" width="900" alt="The myGeeKy panel's Live, Suggestions and Repos tabs, side by side">
</p>
<p align="center"><sub><em>Real screenshots, real data: the Live feed, people worth following, and repos you could contribute to.</em></sub></p>

> **Why this exists:** I don't have Facebook. I wanted a real circle in my
> field: people I can genuinely learn from (and who might learn something
> from me too), projects where my work would actually be welcome, and a
> feel for where the field is moving. GitHub has all of that, but scattered
> and buried under famous accounts. myGeeKy gathers it in one place.

## 🧭 What's inside

One profile (your CV, your repos, and optionally your ORCID/OpenAlex and
Google Scholar papers) powers everything:

| | What you get | Command | Panel tab |
|---|---|---|---|
| 👥 **People** | Who shares your research and is likely to follow back, plus domain experts who rarely follow anyone | `mygeeky run` | Suggestions |
| 🛠️ **Projects** | Repos in your field you could improve: open starter issues, maintainers who merge outside PRs | `mygeeky contribute` | Repos |
| 📈 **Pulse** | Your field's popular repos ranked by momentum (stars gained, commits, PyPI downloads), plus new Product Hunt launches in your field | `mygeeky market` | Market |
| 📰 **Activity** | What the people you follow, and your best matches, are doing right now | (in the panel) | Activity · Live |
| 👋 **Signals** | Emoji-only signals between myGeeKy users, and a 🤝 handshake when it's mutual | `mygeeky beacon` | Signals |
| 🧠 **Learning** | A model trained on who actually follows *you* back, getting sharper every week | `mygeeky learn` | Model |
| ☁️ **Sync** | Your data in a private GitHub repo you own, on every computer | `mygeeky sync` | |

## ✨ Highlights

<table>
<tr>
<td width="50%" valign="top">

**🧬 Knows your field, not just your language**<br>
Builds your profile from your CV, your GitHub repos, and, if you give
them, your ORCID/OpenAlex and Google Scholar publications. Everything it
suggests is matched against *your* research, not a generic popularity list.

</td>
<td width="50%" valign="top">

**👥 People worth following**<br>
Skips famous accounts that follow almost nobody, mass-followers and dormant
profiles, and learns from who actually followed you back. A second list
surfaces the domain experts a follow-back score would bury.

</td>
</tr>
<tr>
<td valign="top">

**🛠️ Repos you could improve**<br>
Active projects matching your work, with open starter issues, ranked by
how often their maintainers merge outside contributors' PRs.

</td>
<td valign="top">

**📈 The pulse of your field**<br>
A daily "stock race" of your field's repos: who gained stars, who's
shipping commits, whose PyPI downloads are climbing, and who moved up.

</td>
</tr>
<tr>
<td valign="top">

**👋 Signals, without words** <sup>new</sup><br>
Wave at, learn from, or offer to collaborate with other myGeeKy users,
using emoji only and no server. 🤝 Handshake when it's mutual.

</td>
<td valign="top">

**🪟 A glass panel on your screen edge**<br>
All of it live, always on top, in three themes. It folds down to a small
icon that now and then lets out a few floating hearts.

</td>
</tr>
<tr>
<td valign="top">

**🛡️ Suggest-only, by design**<br>
There is **no follow, star or fork code in this project at all**. You look,
you click, and you act yourself, by hand, on github.com.

</td>
<td valign="top">

**☁️ Yours, on every computer**<br>
Optional sync through a **private** GitHub repo you own. No server, no
account, no telemetry.

</td>
</tr>
<tr>
<td valign="top">

**🪄 One-click Windows installer** <sup>new</sup><br>
Next → Next → Finish. It sets up Python, your token, private sync and
shortcuts for you, and you can uninstall it from *Settings → Apps*.

</td>
<td valign="top">

**🤖 Scriptable**<br>
Every command has `--json`, so scripts and AI agents can use myGeeKy
as easily as you can.

</td>
</tr>
</table>

## 🚀 Quick start

**Windows, the easy way:** download `MyGeeKySetup-<version>.exe` from
[Releases](https://github.com/AlsammanAlsamman/myGeeKy/releases) and click
Next → Next → Finish. It installs Python for you if it's missing, installs or
updates myGeeKy, and stores your token in the Windows Credential Locker. It
also connects your private data repo, can turn on Signals, and adds Start
menu and startup shortcuts. It appears in *Settings → Apps* so you can
uninstall it later. Run it again (or `mygeeky setup`) any time to update or
reconfigure.

<p align="center">
<img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/setup-welcome.png" width="400" alt="Setup wizard: welcome page">
<img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/setup-signals.png" width="400" alt="Setup wizard: step-by-step Signals token instructions">
</p>

**Any OS, with pip:**

```bash
pip install mygeeky
mygeeky init          # GitHub username (required); CV, ORCID, Google Scholar (optional)
mygeeky run           # who to follow
mygeeky contribute    # which repos to improve
mygeeky market        # the "stock race" of your field's repos
mygeeky gui           # the live panel (sets up its GUI library by itself the first time)
```

If `mygeeky` isn't recognized, use `python -m mygeeky` instead (for example
`python -m mygeeky init`). It offers to fix your PATH so plain `mygeeky`
works next time.

`init` asks a few questions — only your GitHub username is required, every
other answer can be skipped and changed later. Details in
[Quick start](#quick-start) below.

## 🪟 The live panel

<table>
<tr>
<td align="center"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/live.png" width="240" alt="Live tab"><br><sub><b>Live</b> — friends' activity + top suggestions, scrolling</sub></td>
<td align="center"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/suggestions.png" width="240" alt="Suggestions tab"><br><sub><b>Suggestions</b> — click someone to open them; they leave the list</sub></td>
<td align="center"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/repos.png" width="240" alt="Repos tab"><br><sub><b>Repos</b> — projects in your field with starter issues</sub></td>
</tr>
<tr>
<td align="center"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/activity.png" width="240" alt="Activity tab"><br><sub><b>Activity</b> — one card per person; click to expand</sub></td>
<td align="center"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/model.png" width="240" alt="Model tab"><br><sub><b>Model</b> — how good it is, what it learned, and the trend</sub></td>
<td align="center"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/market.png" width="240" alt="Market tab"><br><sub><b>Market</b> — your field's repos as a stock race</sub></td>
</tr>
<tr>
<td align="center"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/signals.png" width="240" alt="Signals tab"><br><sub><b>Signals</b> — emoji signals from other myGeeKy users (example data)</sub></td>
<td align="center" valign="bottom"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/hearts.png" width="150" alt="Folded icon with floating hearts"><br><sub><b>Folded</b> — just the icon on the screen edge; every few minutes a few small hearts drift up and fade (turn off in ⚙)</sub></td>
</tr>
</table>

More in [Live glass panel](#live-glass-panel-optional-gui) below.

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

## Finding people (`mygeeky run`)

How the people suggestions are made:

1. **Understands you** — reads your CV (txt/md/pdf), your own GitHub
   repos (languages, topics, descriptions) and, if you give them, your
   ORCID/OpenAlex and Google Scholar publications to build a profile of what
   you're into, and auto-derives a weighted "domain vocabulary" from that
   corpus (not a hardcoded field-specific wordlist).
2. **Collects candidates from multiple sources**, not just a plain search:
   the owners and contributors of active repos matching your research terms
   (ranked first — a plain language search mostly returns famous accounts),
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
   - how likely they are to follow back (their own following/follower ratio);
     for the follow-back list, accounts that follow almost nobody relative to
     their audience, or have more than `followback_max_followers`, are skipped
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

## Repos you could improve (`mygeeky contribute`)

Beyond people, myGeeKy suggests **repositories you could fork, improve,
and realistically get merged**, matched to your CV, repos, and
publications:

```bash
mygeeky contribute          # search + rank (a few minutes; GitHub's search API is rate-limited)
mygeeky contribute --last   # re-print the last results
mygeeky contribute --json   # for scripts / AI agents
```

1. Your profile is turned into a handful of search terms: your
   publications' OpenAlex keywords, topics used across your repos, and the
   CV vocabulary. Explicit `topics` / `contribute_extra_terms` always come first.
2. GitHub is searched for **active, non-archived, non-fork** repos matching
   those terms that have open `good first issue` / `help wanted` issues.
3. Each repo is ranked on fit (content similarity, a language you use,
   recency), then the top few get the check that actually predicts a merge:
   **of its recently closed PRs from outside contributors, how many did the
   maintainers merge?** Bot PRs and insiders' own PRs don't count.
4. Each suggestion lists its unassigned, recent starter issues and a
   plain-language "why".

As with people, this only ever *suggests*: there is no fork, PR, or comment
code anywhere. You open the repo, fork it, and send the PR yourself.

## Your field's repos as a market board (`mygeeky market`)

<img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/market.png" width="300" align="right" alt="Market tab">

Not repos to contribute to — the projects your field actually runs on,
ranked like a stock board by **momentum**:

```bash
mygeeky market              # snapshot (once a day) + print the board
mygeeky market --refresh    # snapshot again now
mygeeky market --last       # print the saved board, no network
mygeeky market --json       # for scripts / AI agents
```

```
#1    +2  bioconda/bioconda-recipes   *1.9k (+31)  752 commits/4wk
#2   NEW  biotite-dev/biotite         * 976 (+9)   pypi 391.1k/wk +117%  6 commits/4wk
#3    -1  rgcgithub/regenie           * 270 (+3)   1 commits/4wk
```

1. **The watchlist** (`market_size`, default 25) is picked weekly by
   searching GitHub for your profile terms, as text and as topics, among
   repos with `market_min_stars`+ stars pushed in the last
   `market_pushed_within_days`. Your terms take turns filling it, so broad
   ones like "genome" can't crowd out "gwas". Repos only get in when they
   clearly belong to the field: your terms in their own name/description,
   or a real share of their topics — not "bioinformatics" as one tag among
   twenty, not AMD's "SEV-SNP", not awesome-lists, courses or AI-agent
   tooling borrowing the words. `market_pinned` repos always stay on.
2. **Signals:** stars (GitHub has no star history for normal tokens, so
   star momentum builds from myGeeKy's own daily snapshots — "collecting"
   for the first days), commits over the last 4 weeks (52 weeks of history
   come at once), and — when the repo publishes a PyPI package whose page
   links back to it — real PyPI downloads per week and their change, from
   pypistats.org with mirrors excluded.
3. **Ranking:** a weighted average of each repo's percentile on the signals
   it actually has, so tools that aren't on PyPI (PLINK, GATK, …) aren't
   pushed down for lacking downloads. ▲▼ shows places moved since the last
   day ranked.

About 3 GitHub API calls per repo, once a day. In the panel it's the
**Market** tab, refreshed in the background when it's older than
`market_refresh_hours` (default 12).

**Product Hunt launches in your field.** Under the board, the Market also
lists recent [Product Hunt](https://www.producthunt.com) launches. Launches
that mention your profile terms come first (tagged *your field*), then the
rest by upvotes. Product Hunt has no search, so launches are pulled from a few
topics (`market_ph_topics`), from the last `market_ph_days` (30). It's
read-only and needs a free Product Hunt developer token:

```bash
mygeeky auth producthunt          # walks you through creating the token; stored in the OS keyring
mygeeky market --refresh          # board + launches
```

<br clear="right">

## Your profile: CV + GitHub + ORCID/OpenAlex + Google Scholar

```bash
mygeeky profile refresh --cv ~/cv.pdf --orcid 0000-0002-1825-0097 \
    --scholar "https://scholar.google.com/citations?user=XXXXXXXXXXXX"   # all remembered
mygeeky profile refresh     # after updating your CV: re-extract the PDF, re-fetch publications
mygeeky profile show        # what myGeeKy knows about you (no network)
```

- **CV**: PDF/txt/md, converted to text.
- **ORCID** (public API) and **OpenAlex** (looked up by your ORCID): your
  publication titles, abstracts, keywords and research topics. They're free and
  need no key. They feed both people matching and repo suggestions.
- **Google Scholar** (optional): your research interests and up to 100 paper
  titles, read from your own public profile page. Scholar has no API and limits
  automated access, so this is one request per `profile refresh`, never part of
  a normal run; if Google refuses it, the last fetched copy is kept and
  ORCID/OpenAlex still cover your publications.

## Use it from any computer (`mygeeky sync`)

Your myGeeKy data can live in a **private** GitHub repo, so the model keeps
learning no matter which machine you run it on:

```bash
mygeeky sync init                      # creates <you>/mygeeky-data (private) and pushes
mygeeky sync init --repo you/other     # or use/choose another private repo
mygeeky sync pull | push | status
```

On a new computer: `pip install mygeeky`, then `gh auth login` and
`mygeeky sync init` again. It pulls your config, CV text, publications,
history and training data. `mygeeky pipeline` (the weekly job) then does
**pull → learn → run → contribute → push** automatically.

- It refuses to sync to a public repo.
- Never synced: any token, caches, logs, and the pickled model. Loading a
  pickle that came over the network could run code, so the model is
  retrained locally from the synced training data instead.
- `.jsonl` logs use git's `union` merge, so two machines in the same week merge cleanly.
- Git uses your own `gh`/git credentials. myGeeKy's API client stays read-only.

## Signal other myGeeKy users, without words (`mygeeky beacon`)

myGeeKy users can send each other **emoji-only signals**, and myGeeKy
never needs a server for it: everything goes through GitHub.

| | Signal | Means |
|---|---|---|
| 👋 | `wave` | "I noticed you" |
| 📚 | `learn` | "I learn from your work" |
| 🤝 | `collab` | "I'd like to work with you" |
| 👀 | `watching` | "I'm following your progress" |
| 🔥 | `kudos --repo owner/name` | "this repo of yours is great" |

```bash
mygeeky beacon init                  # one-time: creates <you>/mygeeky-beacon (PUBLIC) + its token
mygeeky beacon people                # fellow myGeeKy users, those sharing your interests first
mygeeky beacon send alice wave       # or: learn | collab | watching | kudos --repo alice/tool
mygeeky beacon inbox                 # signals sent to you -- 🤝 handshake = you both signalled
mygeeky beacon status open-to-collab # or learning, heads-down, seeking-reviewers, mentoring, none
mygeeky beacon sent | unsend alice | block troll | unblock troll
```

<img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/signals.png" width="260" align="right" alt="Signals tab (example data)">

In the panel, the **Signals** tab shows what people sent you and who else
is around, with one-click 👋 📚 🤝 👀 buttons. Incoming signals also lead
the Live tab's rotation.

How it works: each user's beacon is a public repo tagged with the topic
`mygeeky-beacon`, holding one `beacon.json` file. It lists the signals you
sent, your status, and a few interest tags taken from your `topics`,
`keywords` and `languages` (turn those off with `beacon_share_interests false`).
myGeeKy finds other beacons with a normal repo search and reads the ones that
name you. Someone who signalled you also gets a boost in your
suggestions.

- **It's public.** Anyone can read who you signalled, and when.
- **There's no text, so there's nothing to moderate.** Signals and statuses come from fixed lists.
  Everything read from other people's beacons is validated and shown as plain
  text. `block` hides a person for good.
- **Signals expire** after `beacon_gesture_ttl_days` (90). You can send
  `beacon_daily_limit` (20) per day.
- **A separate, single-repo token.** `init` asks for a fine-grained token
  with access to *only* `<you>/mygeeky-beacon` and only **Contents: Read and
  write**. It's stored in your OS keyring under its own entry. Your main token
  stays read-only.

## Install

```bash
pip install mygeeky
```

That's all: PDF CVs work out of the box, and the panel's GUI library (Qt) is
set up automatically the first time you run `mygeeky gui`. (`pip install
"mygeeky[gui,pdf]"` still works too; the extras just aren't needed any more.)

On Windows you can use `MyGeeKySetup.exe` instead (see the top of this page).
To build it yourself: `pip install pyinstaller build`, then
`python installer/build.py`, which writes `dist/MyGeeKySetup-<version>.exe`.

### If something goes wrong on Windows

- **`'mygeeky' is not recognized`**: pip put the command in a folder that isn't
  on your PATH (common with the Microsoft Store Python). Use `python -m mygeeky`
  instead, e.g. `python -m mygeeky init`. It offers once to add that folder to
  your PATH, so plain `mygeeky` works in new terminals.
- **`OSError: [Errno 2] No such file or directory: ...PySide6\qml\...`** with a
  *Long Path* hint, from installing PySide6 yourself: the Microsoft Store
  Python's package folder is too deep for Qt's files. You don't need to install
  Qt by hand. `mygeeky gui` sets it up in a short folder (`~/.mygeeky/qt`) that
  avoids the limit, no admin rights needed. If you'd rather, `MyGeeKySetup.exe`
  sets up a regular Python instead.

## Quick start

```bash
mygeeky init      # asks for your GitHub username, CV, and the kind of people you're looking for
mygeeky run       # get your first batch of suggestions
```

`mygeeky init` asks a short set of questions — all optional, all editable
later:

- Your GitHub username (the only required answer)
- Your CV (a file path, pasted text, or skip)
- Your ORCID iD and your Google Scholar profile URL (each optional)
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
mygeeky contribute          # repos you could fork, improve, and get merged
mygeeky market              # momentum board of the popular, active repos in your field
mygeeky profile refresh     # re-read your CV + publications (ORCID/OpenAlex)
mygeeky sync push|pull      # keep your data in your private GitHub repo
mygeeky pipeline            # sync pull, learn, run, contribute, sync push — the weekly job
mygeeky gui                 # launch the live glass panel
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
mygeeky gui          # (or the standalone `mygeeky-gui` command)
```

The first run sets up Qt (PySide6, about 80 MB) by itself. It uses this
Python's normal package folder when Windows' path limit allows, and otherwise
a short private folder, `~/.mygeeky/qt` (or `$MYGEEKY_QT_DIR`).

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
  follows anyone; a "Refresh" button re-runs a real search on demand.
  People you open or already follow drop off, and older unseen suggestions
  move up to fill their place. Once the list is empty, the panel searches
  again by itself, but no more often than `gui_suggestions_auto_refresh_hours`
  (default 6; `0` turns it off), to stay well inside GitHub's rate limits.
- **Market tab** — the `mygeeky market` board: rank, ▲▼ places moved,
  stars (+ this week), PyPI downloads/week (± change), commits, and a
  green/red sparkline of weekly downloads (or commits for non-PyPI tools).
  Click a row to open the repo. It refreshes itself in the background.
- **Repos tab** — the results of `mygeeky contribute`: repos you could
  improve, each with why it fits you, its top starter issues, and
  **Fork →** / **Open →** buttons. Those buttons only open the GitHub page;
  forking and the PR stay yours. It shows the last run's results, and
  "Refresh" runs a new repo search only when you click it.
- **Activity tab** — a live feed of what people you follow are actually
  doing (pushes, merged PRs, new repos, releases, stars...), from GitHub's
  own events API, plus the recent activity of your best profile matches
  (your top `gui_activity_match_people` suggestions, scored against your
  CV, ORCID and repos), tagged "profile match". Grouped into one card per
  person with their latest action and a count; click a card to expand
  everything they did, or ↗ to open their profile. Strangers acting on
  repos of orgs you follow are filtered out. Refreshes automatically, but no
  more often than `gui_activity_refresh_minutes` (default 5) — about one API
  call per matched person, not a full search.
- **Model tab** — an animated ring with your model's cross-validated AUC and
  a plain-language grade, tiles for examples / follow-backs / follow-back
  rate / retrains, bars showing what the trained model rewards and
  penalizes, and a trend chart (hover a point for details) so you can watch
  it actually improve as you run `mygeeky bootstrap`/`learn`.

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

Clicking a person in the Suggestions list (or a suggestion in the Live tab)
opens their profile and removes them from the list — they're added to your
excluded list, so later runs skip them too. People you follow from the browser
drop out on the next activity refresh (within `gui_activity_refresh_minutes`).

Folded, the panel shrinks to just the app icon on the screen edge,
half-transparent until you hover it. It always stays inside the screen it's
on, including on multi-monitor setups.

Config: `gui_dock_side` (`"right"`/`"left"`), `gui_expanded_width`,
`gui_folded_width`, `gui_folded_height`, `gui_folded_opacity`, `gui_panel_height_fraction`, `gui_activity_refresh_minutes`, `gui_suggestions_auto_refresh_hours`,
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
| `cv_path` / `orcid_id` / `scholar_id` | CV file, ORCID iD and Google Scholar user id used by `mygeeky profile refresh` | `""` / `""` / `""` |
| `include_domain_repo_people` / `domain_repo_terms` / `domain_repo_count` | candidates = owners/contributors of active repos matching your profile terms | `true` / `6` / `20` |
| `followback_min_ratio` / `followback_max_followers` | follow-back list only: skip accounts with following/followers below this, or more followers than this | `0.05` / `3000` |
| `contribute_extra_terms` | terms always searched by `contribute`, e.g. `gwas, snakemake` | `[]` |
| `contribute_min_stars` / `contribute_max_stars` | star range for repo suggestions | `10` / `20000` |
| `contribute_pushed_within_days` | a suggested repo must have been pushed to this recently | `90` |
| `contribute_queries` / `contribute_check_top_n` / `contribute_max_returned` | search terms used / repos given the maintainer check / results shown | `10` / `25` / `10` |
| `market_size` / `market_terms` | repos on the market board / profile terms searched to pick them | `25` / `8` |
| `market_min_stars` / `market_pushed_within_days` | a board repo needs this many stars and a push this recent | `50` / `180` |
| `market_pinned` | `owner/repo` always on the board, e.g. `snakemake/snakemake, chrchang/plink-ng` | `[]` |
| `market_ph_topics` / `market_ph_days` / `market_ph_size` | Product Hunt topics to read, how far back, and how many launches to show (needs `mygeeky auth producthunt`) | `developer-tools, open-source, github, artificial-intelligence, science, health` / `30` / `10` |
| `market_refresh_hours` | the panel re-snapshots the board once it's this old | `12` |
| `beacon_enabled` | set by `mygeeky beacon init`; signals are off until then | `false` |
| `beacon_status` | your status (`open-to-collab`, `learning`, `heads-down`, `seeking-reviewers`, `mentoring`) | `""` |
| `beacon_share_interests` | publish your topics/keywords/languages as interest tags in your beacon | `true` |
| `beacon_blocked` | people whose signals are never shown | `[]` |
| `beacon_daily_limit` / `beacon_gesture_ttl_days` | signals you can send per day / days before a signal expires | `20` / `90` |
| `beacon_refresh_minutes` / `beacon_max_users` | minimum minutes between re-reading beacons / beacons read per refresh | `30` / `60` |
| `sync_repo` / `sync_auto` | private data repo (set by `sync init`) / whether `pipeline` pulls+pushes | `""` / `true` |
| `min_training_samples` | labeled examples needed before the ML model kicks in | `8` |
| `ml_blend_weight` | how much the learned model influences the final score once trained | `0.5` |
| `training_mass_follow_outlier` | exclude training examples from accounts following more than this | `3000` |
| `gui_dock_side` | which screen edge the live panel docks to (`"right"`/`"left"`) | `"right"` |
| `gui_expanded_width` / `gui_folded_width` / `gui_folded_height` | panel size in pixels, expanded vs. folded (the folded icon) | `380` / `76` / `76` |
| `gui_hearts_enabled` / `gui_hearts_interval_minutes` | a few small hearts drift up from the folded icon, fade and vanish (toggle in the panel's ⚙ settings) | `true` / `3` |
| `gui_folded_opacity` | folded icon's opacity (fully opaque while hovered) | `0.5` |
| `gui_panel_height_fraction` | panel height as a fraction of the screen height | `0.25` |
| `gui_activity_refresh_minutes` | minimum minutes between automatic activity-feed refreshes | `5` |
| `gui_activity_limit` | how many recent activity events to show | `30` |
| `gui_suggestions_auto_refresh_hours` | once the follow-back list is empty, search again by itself if the last search is at least this old (`0` = only on Refresh) | `6` |
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
- **Token fallback to the GitHub CLI.** If no keyring token or env var is
  set, myGeeKy uses `gh auth token` when `gh` is logged in. This is still only
  used for GET requests.
- **Sync writes only to your own private data repo**, through `git`
  with your own credentials, never through myGeeKy's API client.
- **Beacons are the one opt-in write.** After `mygeeky beacon init`,
  myGeeKy writes `beacon.json`/`README.md` in your own public
  `mygeeky-beacon` repo, and nothing else. The writer has no parameter that
  could point it at another repo or file. It uses a second, fine-grained token
  scoped to that single repo, and never falls back to `gh`.
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
  described above, except the Signals tab's emoji buttons. Once you've run
  `mygeeky beacon init`, those publish to your own beacon repo.

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
