# myGeeKy — Product Hunt launch kit

Submit at https://www.producthunt.com/posts/new (logged in as the maker).

## Name (≤ 40)
myGeeKy

## Tagline (≤ 60)
Find GitHub people in your field who'll follow you back

## Links
- Website: https://github.com/AlsammanAlsamman/myGeeKy
- PyPI: https://pypi.org/project/mygeeky/
- Windows installer: https://github.com/AlsammanAlsamman/myGeeKy/releases/latest

## Description (≤ 260)
myGeeKy reads your CV, GitHub repos and ORCID/Google Scholar papers and suggests people in your field who are likely to follow you back, plus repos to contribute to. It learns who actually follows back. It only suggests; it never follows anyone for you.

## Topics (pick 3)
Developer Tools · Open Source · GitHub

## Pricing
Free (open source, MIT)

## Thumbnail
thumbnail-240.png

## Gallery (in order; rebuild with `python launch/producthunt/make_gallery.py`)
1. gallery-1-hero.png
2. gallery-2-suggestions.png
3. gallery-3-signals.png
4. gallery-4-installer.png
5. gallery-5-live.png
6. gallery-6-repos.png
7. gallery-7-market.png
8. gallery-8-model.png

## Maker's first comment
Hi Product Hunt 👋

I don't have Facebook, and I only want to follow people I can genuinely
learn from, and who might learn something from me too. GitHub's own
discovery mostly shows famous accounts that will never notice you. So I
built myGeeKy.

**What it does**
- 🧬 **Knows your field, not just your language.** It builds your profile from your CV, your repos, and your ORCID/OpenAlex and Google Scholar papers. Then it finds people through the repos in your field that they own and contribute to.
- 🔁 **Ranks people by real follow-back odds.** It skips celebrities, mass-followers and dormant accounts, and a small model retrains on who actually followed you back.
- 🛠️ **Suggests repos you could improve.** These are active projects with starter issues whose maintainers merge outside PRs.
- 📈 **Shows a market board of your field.** Repos are ranked by momentum: stars gained, commits and PyPI downloads.
- 🪟 **Runs in a live glass panel** docked to the edge of your screen. Folded, it's a small icon that now and then lets out a few floating hearts 💕.
- 👋 **New: Signals.** Wave at, learn from, or offer to collaborate with other myGeeKy users, emoji only and with no server: it runs through GitHub itself. A 🤝 handshake shows when it's mutual. You'd be one of the first, so come say hi.
- 🪄 **New: a one-click Windows installer.** Next → Next → Finish, and it sets up Python, your token and shortcuts for you.

**What it never does:** follow, star or fork anything for you. There's no
code path for it. Your token stays in your OS keyring and only needs read
access.

**Windows:** grab `MyGeeKySetup.exe` from the releases page.
**Anywhere:** `pip install "mygeeky[gui]"` → `mygeeky init` → `mygeeky gui`

It started with researchers in genomics and bioinformatics, but it works
for any field. I'd love to hear what you'd want it to find for you.
