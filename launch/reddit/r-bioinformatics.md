# r/bioinformatics launch post

## Before posting
- Read the subreddit rules (sidebar / "About") for self-promotion. Tool posts
  are usually tolerated when the tool is free, open source, and you engage
  with comments; check whether a specific flair or weekly thread is required.
- Post from your own account, and say it's your project.
- Best time: a weekday, ~8–10 am US Eastern (Tue–Thu).
- Use the Markdown editor ("Switch to Markdown") so the formatting below works.
- Plan to reply to comments for the first 2–3 hours.

## Flair
Software / Tool (whichever the subreddit offers for tools)

## Title (pick one)
- I built an open-source tool that turns your CV, ORCID and Google Scholar papers into your GitHub circle: people, repos to contribute to, and what's rising in your field
- Open-source tool: find GitHub people and projects that match your publications (ORCID/Scholar), not just your languages

## Body

GitHub discovery mostly shows famous accounts and generic trending repos. As
a bioinformatician I wanted the opposite: the people and projects *in my
field*, matched against what I actually work on. So I built **myGeeKy** (free,
MIT, open source).

It builds a profile from your CV (pdf/txt), your GitHub repos, and optionally
your **ORCID/OpenAlex** and **Google Scholar** publications, then gives you:

- **People**: GitHub users working on the same things as you (found through
  the owners and contributors of active repos matching your research terms),
  plus a separate list of domain experts who rarely follow anyone.
- **Projects**: active repos in your field with open starter issues, ranked by
  how often maintainers actually merge outside PRs. Good if you want to
  contribute to the tools you use.
- **Pulse**: your field's popular repos ranked by momentum (stars gained,
  commits, PyPI downloads), e.g. where single-cell or GWAS tooling is moving.
- A small desktop panel with all of it, plus an activity feed of the people
  you follow.

What it doesn't do: it never follows, stars or forks anything for you. It's
suggest-only, with a read-only token kept in your OS keyring, no server and
no telemetry.

Install: `pip install mygeeky`, then `mygeeky init` and `mygeeky gui`, or on Windows the
one-click installer on the releases page.

GitHub: https://github.com/AlsammanAlsamman/myGeeKy

Video (2.5 min, install + tour): https://youtu.be/VeaHkWyzLK4

It's early, and I'd really value feedback from people here: are the matches
from your publications any good for your subfield, and what would make the
"repos to contribute to" list more useful?

## Image (optional)
Attach docs/screenshots/hero.png or launch/producthunt/gallery-2-overview.png.

## Replies to have ready
- **"Isn't follow-back ranking spammy?"** It never follows anyone. It only
  ranks who's worth a look; you decide. A second list ignores follow-back
  completely and shows pure domain experts.
- **"Why a token?"** Only for GitHub's rate limits. It's read-only, scoped
  to public data, and stored in your OS keyring.
- **"macOS?"** The CLI works anywhere Python runs; the panel is tested on
  Windows and Linux.
- **"Privacy of my CV?"** It stays on your machine (or in your own private
  repo if you turn sync on).
