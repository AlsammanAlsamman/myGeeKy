# myGeeKy — Product Hunt launch kit

Submit at https://www.producthunt.com/posts/new (logged in as the maker).

## Name (≤ 40)
myGeeKy

## Tagline (≤ 60)
The people, projects & pulse of your field on GitHub

## Links
- Website (main link, for now): https://github.com/AlsammanAlsamman/myGeeKy
- Later, once https://mygeeky.org has its HTTPS certificate and is a few weeks old
  (some networks block brand-new domains), switch the main link to it.
- PyPI: https://pypi.org/project/mygeeky/
- Windows installer: https://github.com/AlsammanAlsamman/myGeeKy/releases/latest

## Video (the "YouTube video" field on the media step)
https://youtu.be/NTYDY7IGufw

## Description (≤ 260)
myGeeKy reads your CV, repos and ORCID/Scholar papers, then shows who in your field to follow, repos you could contribute to, what's rising, and emoji signals from fellow users, in one small desktop panel. It only suggests; it never acts for you.

## Topics (pick 3)
Developer Tools · Open Source · GitHub

## Pricing
Free (open source, MIT)

## Thumbnail
thumbnail-240.png

## Gallery (in order; rebuild with `python launch/producthunt/make_gallery.py`)
1. gallery-1-hero.png
2. gallery-2-overview.png
3. gallery-3-suggestions.png
4. gallery-4-signals.png
5. gallery-5-installer.png
6. gallery-6-live.png
7. gallery-7-repos.png
8. gallery-8-market.png
9. gallery-9-model.png

## Maker's first comment
Hi Product Hunt 👋

I don't have Facebook. What I wanted was a real circle in my field:
people I can genuinely learn from (and who might learn something from
me), projects where my work would actually be welcome, and a sense of
where the field is moving. GitHub has all of that, but it's scattered and
buried under famous accounts that will never notice you. So I built
myGeeKy: your corner of GitHub, in one small panel on the edge of your screen.

**One profile, built from your CV, your repos, and your ORCID/OpenAlex and Google Scholar papers, powers all of it:**
- 👥 **People.** Who shares your research and is likely to follow you back. It skips celebrities, mass-followers and dormant accounts, and a second list surfaces the domain experts who rarely follow anyone.
- 🛠️ **Projects.** Repos in your field you could improve, with open starter issues and maintainers who actually merge outside PRs.
- 📈 **Pulse.** Your field's popular repos as a daily "stock race": stars gained, commits, PyPI downloads, and who moved up.
- 📰 **Activity.** What the people you follow, and your best matches, are building right now.
- 👋 **Signals (new).** Wave at, learn from, or offer to collaborate with other myGeeKy users, emoji only and with no server: it runs through GitHub itself. A 🤝 handshake shows when it's mutual. You'd be one of the first, so come say hi.
- 🧠 **Learning.** A small model retrains on who actually followed *you* back, so suggestions get sharper every week.

It also syncs through a private GitHub repo you own, works from scripts
and AI agents (`--json` everywhere), and when the panel is folded, a few
floating hearts 💕 drift up now and then.

**What it never does:** follow, star or fork anything for you. There's no
code path for it. Your main token only needs read access and stays in your
OS keyring. Signals uses a separate, opt-in token that can write to one
repo only.

**Windows:** grab `MyGeeKySetup.exe` from the GitHub releases page. It's Next → Next → Finish (new).
**Anywhere:** `pip install mygeeky` → `mygeeky init` → `mygeeky gui`

It started with researchers in genomics and bioinformatics, but it works
for any field. What would you want it to find for you?
