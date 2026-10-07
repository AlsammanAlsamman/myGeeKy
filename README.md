<p align="center">
  <img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/src/mygeeky/gui/assets/icon_256.png" width="132" alt="myGeeKy icon: two geeks hugging inside a heart">
</p>

<h1 align="center">myGeeKy</h1>

<h3 align="center">Your corner of GitHub, for research.</h3>

<p align="center">
  The <b>people</b>, <b>projects</b>, <b>papers</b> and <b>pulse</b> of your field,<br>
  found from your CV, repos, ORCID and Google Scholar, in one small glass panel on your screen.
</p>

<p align="center">
  <a href="https://github.com/AlsammanAlsamman/myGeeKy/releases/latest"><img alt="Download for Windows" src="https://img.shields.io/badge/%E2%AC%87%20Download%20for%20Windows-MyGeeKySetup.exe-ff6fd8?style=for-the-badge&logo=windows&logoColor=white" height="44"></a>
  &nbsp;
  <a href="https://pypi.org/project/mygeeky/"><img alt="pip install mygeeky" src="https://img.shields.io/badge/macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-pip%20install%20mygeeky-7a5cff?style=for-the-badge&logo=python&logoColor=white" height="44"></a>
</p>

<p align="center">
  <a href="https://pypi.org/project/mygeeky/"><img alt="PyPI version" src="https://img.shields.io/pypi/v/mygeeky?color=7fd8ff&label=pypi&style=flat-square"></a>
  <a href="https://pypi.org/project/mygeeky/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/mygeeky?color=7a5cff&style=flat-square"></a>
  <a href="https://pepy.tech/projects/mygeeky"><img alt="Downloads" src="https://img.shields.io/pepy/dt/mygeeky?color=ff6fd8&label=downloads&style=flat-square"></a>
  <a href="https://github.com/AlsammanAlsamman/myGeeKy/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-35e0c1?style=flat-square"></a>
  <img alt="Auto-follow: never" src="https://img.shields.io/badge/auto--follow-never-e5484d?style=flat-square">
  <img alt="Telemetry: none" src="https://img.shields.io/badge/telemetry-none-35e0c1?style=flat-square">
</p>

<p align="center">
  <a href="https://youtu.be/VeaHkWyzLK4"><b>▶ Watch the video</b></a> ·
  <a href="https://mygeeky.org">Website</a> ·
  <a href="#-get-started-in-3-steps">Get started</a> ·
  <a href="#-every-tab">Every tab</a> ·
  <a href="#-two-tokens-two-jobs">Tokens</a> ·
  <a href="#-what-it-will-never-do">Safety</a> ·
  <a href="https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md">Full guide</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/hero.png" width="920" alt="Three myGeeKy panel tabs: People likely to follow you back, what myGeeKy knows about you, and research rising in your field">
</p>
<p align="center"><sub><em>Real screenshots, real data: people likely to follow you back · what myGeeKy knows about you · research rising in your field.</em></sub></p>

> **Why this exists:** I don't have Facebook. I wanted a real circle in my field: people I can genuinely learn
> from (and who might learn something from me), projects where my work would be welcome, and a feel for where
> the field is moving. GitHub has all of that, but scattered and buried under famous accounts. myGeeKy gathers
> it in one place, and **never acts for you**.

<br>

<table>
<tr>
<td width="44%" align="center" valign="top">
  <img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/tour.gif" width="330" alt="Animated tour of every myGeeKy tab"><br>
  <sub><em>Every tab, in 20 seconds</em></sub>
</td>
<td width="56%" valign="top">

### ✨ What it does for you

👥 **Finds your people.** Researchers who share your work and are likely to follow you back. It skips celebrities, mass-followers and dormant accounts.

🛠️ **Finds projects that want you.** Active repos in your field with starter issues, ranked by how often their maintainers merge outside pull requests.

📈 **Feels the pulse.** Your field's repos as a daily stock race: stars, commits, PyPI downloads, who moved up.

🔬 **Reads the literature.** Papers gaining citations fastest, new tools with their code, and the people behind them. A green **P** marks repos with a published paper.

🗞️ **Brings the news.** New arXiv, bioRxiv and Hacker News items about *your* topics.

🙏 **Says thanks, privately.** Small signals between myGeeKy users (thanks, "I learned from your work",
"I used your tool"), sealed so **only the recipient can read them**. No reply is ever expected, and 🤝
"let's collaborate" only shows up if you *both* choose it.

🧠 **Learns what you're into.** Every click, follow, star and fork tunes it, and 🔭 20% of every list stays open for new territory.

</td>
</tr>
</table>

## 🚀 Get started in 3 steps

<p align="center">
  <a href="https://youtu.be/VeaHkWyzLK4"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/video-thumbnail.png" width="640" alt="Watch: install and set up myGeeKy"></a><br>
  <sub>▶ <b>Watch the video:</b> install, set up, and a tour of the panel</sub>
</p>

<table>
<tr>
<td width="50%" valign="top">

### 🪟 Windows: one installer

1. Download **[MyGeeKySetup.exe](https://github.com/AlsammanAlsamman/myGeeKy/releases/latest)** (under *Assets*).
2. Click **Next → Next → Finish**.

**You don't need anything installed first.** It sets up Python and Git if they're missing (just for you, no admin rights),
asks who you are, checks your tokens, connects private sync, and adds a Start-menu shortcut.

<sub>Windows may say <i>"Windows protected your PC"</i> (the installer isn't code-signed yet): click <b>More info → Run anyway</b>.</sub>

</td>
<td width="50%" valign="top">

### 🐍 macOS · Linux · Windows

```bash
pip install mygeeky
mygeeky init      # who you are + token 1
mygeeky gui       # open the panel
```

Only your **GitHub username** is required. Your **CV**, **ORCID** and **Google Scholar** profile are optional,
and they make every match much better.

<sub><code>'mygeeky' is not recognized</code>? Use <code>python -m mygeeky</code>: it offers to fix your PATH.</sub>

</td>
</tr>
</table>

Then, any time, from the panel or the terminal:

```bash
mygeeky run           # 👥 people in your field worth following
mygeeky contribute    # 🛠️ repos you could improve
mygeeky market        # 📈 what's rising in your field
mygeeky trends        # 🔬 papers and tools gaining traction
mygeeky news          # 🗞️ news about your interests
mygeeky beacon init   # 🙏 join Signals (optional)
```

## 🔑 Two tokens, two jobs

myGeeKy uses **two separate GitHub tokens** with very different powers. **Setup checks what each token can
actually do** (with tests that change nothing on GitHub), and refuses a token that doesn't fit its job.

| | 🔍 Token 1: read-only | ✍️ Token 2: Signals *(optional)* |
|---|---|---|
| **What it's for** | Reading public profiles, repos and followers | Writing your `mygeeky-beacon` repo, and nothing else |
| **Repository access** | *Public repositories* | *Only select repositories* → `mygeeky-beacon` |
| **Permissions** | Account → **Followers: Read-only** | Repository → **Contents: Read and write** |
| **Refused if…** | it can write to any repo, can follow people, or is your Signals token | it can't write to `mygeeky-beacon`, or is token 1 again |
| **Made with** | [new fine-grained token ↗](https://github.com/settings/personal-access-tokens/new) | the same page, *after* the repo exists |

Both live only in your OS keyring (Windows Credential Locker / macOS Keychain / Secret Service), never in a file.
myGeeKy reminds you a week before either one expires, and `mygeeky auth status` shows what each can do.

## 🪟 Every tab

<table>
<tr>
<td align="center" width="33%"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/live.png" width="260" alt="Live tab"><br><b>Live</b><br><sub>Your circle's activity and top suggestions, scrolling live</sub></td>
<td align="center" width="33%"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/suggestions.png" width="260" alt="People tab"><br><b>People</b><br><sub>Likely to follow you back, plus domain experts. Click to open; you follow by hand</sub></td>
<td align="center" width="33%"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/repos.png" width="260" alt="Repos tab"><br><b>Repos</b><br><sub>Projects in your field with starter issues and maintainers who merge</sub></td>
</tr>
<tr>
<td align="center"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/market.png" width="260" alt="Market tab"><br><b>Market</b><br><sub>Your field's repos as a stock race: stars, commits, downloads</sub></td>
<td align="center"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/research.png" width="260" alt="Research view"><br><b>Market → Research</b><br><sub>Rising papers, their code, and the people behind them (OpenAlex)</sub></td>
<td align="center"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/news.png" width="260" alt="News tab"><br><b>News</b><br><sub>arXiv, bioRxiv and Hacker News about your interests</sub></td>
</tr>
<tr>
<td align="center"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/activity.png" width="260" alt="Activity tab"><br><b>Activity</b><br><sub>One card per person: what they're building right now</sub></td>
<td align="center"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/signals.png" width="260" alt="Signals tab"><br><b>Signals</b><br><sub>Private 🙏 📚 👀 from fellow users; 🤝 only when you both choose it <i>(example people)</i></sub></td>
<td align="center"><img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/model.png" width="260" alt="Model tab"><br><b>Model</b><br><sub>What myGeeKy knows about you: your interest map, what teaches it, room to explore</sub></td>
</tr>
</table>

<p align="center">
  <img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/hearts.png" width="120" alt="The folded icon letting out small hearts"><br>
  <sub><b>Folded</b>, it's just a small icon on your screen edge that now and then lets out a few floating hearts (turn them off in ⚙).</sub>
</p>

## 🔤 Keywords that mean something

Add **AI** and myGeeKy also looks for LLMs, deep learning and AI agents; add **GWAS** and it brings in
genomics and statistical genetics. A small model reads which GitHub topics go together across the most-starred
repos, and builds a **keyword dictionary** that every myGeeKy uses.

- 🟢 **Green** keywords are in the dictionary: they bring their whole meaning to People, Repos, Research and News.
- 🔴 **Red** ones aren't yet: they still work as plain words, and they're **passed on** (through your
  Signals beacon, or with one click as a suggestion) so the next dictionary learns them.

```bash
mygeeky keywords add AI "single cell"   # or in the panel: Model → 🔤 Your keywords
mygeeky keywords explain gwas           # what it brings in, and how strongly
```

## 🧠 It learns, and keeps room to explore

<table>
<tr>
<td width="55%" valign="top">

Everything starts from **your research field**: topics from your papers (OpenAlex), your Google Scholar
interests, and your repos. Then it watches what you **actually do**:

| You… | It learns… |
|---|---|
| click a person, repo, paper or news item | a little |
| ⭐ star or 🍴 fork a repo | more |
| follow someone | the most |

Interests fade with a 30-day half-life, so it follows you as you change. And **🔭 20% of every list** is
deliberately kept for fields you've never touched, so you don't end up in a bubble.

A separate model learns **who follows you back**, from your own history, and gets sharper every week.

</td>
<td width="45%" align="center" valign="top">
<img src="https://raw.githubusercontent.com/AlsammanAlsamman/myGeeKy/main/docs/screenshots/model.png" width="300" alt="Your interest map"><br>
<sub>The Model tab: you in the middle, your field, what you're into lately, and new territory</sub>
</td>
</tr>
</table>

## 🔒 What it will never do

- **Never follows, stars, forks or comments for you.** There is no code for it anywhere in the project. You look,
  you click, you act yourself on github.com.
- **No server, no account, no telemetry.** It talks only to GitHub and public research APIs (OpenAlex, arXiv,
  bioRxiv, Hacker News, PyPI).
- **Your data stays yours:** on your computer, plus (if you choose) a **private** GitHub repo you own for sync.
- **Tokens only in your OS keyring**, checked for least privilege, never logged or printed.

Details: [Safety](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md#safety).

## 💡 Ideas, problems and questions

Click **💡** at the top of the panel (or run `mygeeky idea "your idea"`). Pick *Idea*, *Problem* or *Question*,
and your browser opens a ready-to-send issue in
[myGeeKy-ideas](https://github.com/AlsammanAlsamman/myGeeKy-ideas). Click **Submit** to send it. Nothing is sent
until you do, and no token passes through myGeeKy. Issues there are public, so leave out tokens and private data.

## 📚 The full guide

Everything else is in **[docs/GUIDE.md](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md)**:

| | | |
|---|---|---|
| [How it works](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md#how-it-works) | [Finding people](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md#finding-people-mygeeky-run) | [Repos to improve](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md#repos-you-could-improve-mygeeky-contribute) |
| [Market board](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md#your-fields-repos-as-a-market-board-mygeeky-market) | [Research trends](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md#research-trends-and-the-papers-behind-repos-mygeeky-trends) | [News](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md#news-for-your-field-mygeeky-news) |
| [Your profile](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md#your-profile-cv--github--orcidopenalex--google-scholar) | [Signals, step by step](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md#join-signals-step-by-step) | [Sync across computers](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md#use-it-from-any-computer-mygeeky-sync) |
| [Updating](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md#updating) | [Token expiry](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md#token-expiry) | [Troubleshooting](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md#if-something-goes-wrong-on-windows) |
| [The panel](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md#live-glass-panel-optional-gui) | [All settings](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md#all-parameters-adjustable-or-leave-at-the-defaults) | [Scripts & AI agents](https://github.com/AlsammanAlsamman/myGeeKy/blob/main/docs/GUIDE.md#using-mygeeky-from-an-ai-agent--script) |

## License

MIT. Made with ❤️ for researchers who code.

<p align="center">
  <a href="https://github.com/AlsammanAlsamman/myGeeKy"><img alt="Star myGeeKy on GitHub" src="https://img.shields.io/github/stars/AlsammanAlsamman/myGeeKy?style=social"></a>
</p>
