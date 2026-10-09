# myGeeKy stability protocol

How to check that myGeeKy is stable before a release, and how crashes from
users come back to be fixed. It is built from what goes wrong in apps made the
same way:
- a Python + PySide6 (Qt) desktop panel that is always on top and docked;
- JSON/JSONL files and a git-synced private repo;
- the OS keyring;
- the GitHub API and RSS feeds;
- a PyInstaller Windows setup and a curl | sh Linux installer;
- an Expo / React Native phone app.

The full list of 78 known failure modes, with sources, is in [CATALOGUE.md](CATALOGUE.md).

## The four layers

| Layer | What | How | When |
|---|---|---|---|
| 1. Unit tests | Each feature does what it should | `python -m pytest -q` (must be all green) | Every change |
| 2. Stability probes | Deliberately break things the way real users' machines do, and record what myGeeKy does | `python stability/probes.py` writes [REPORT.md](REPORT.md) | Before every release |
| 3. Platform matrix | What can't be faked on one PC: Wayland, other distros, antivirus, work networks | The manual checklist below | Before a minor release (0.x.0), or after touching install, windowing or sync |
| 4. Crash reports | What breaks for real users | The in-app reporter files GitHub issues labelled `crash` | Triage weekly (below) |

### Release gate
- **No ❌ FAIL** in layer 2 for anything in an area the release touched.
- **No new ❌ anywhere.** Known FAILs are listed in REPORT.md and need a deliberate decision to ship with.
- Layer 1 all green.
- Open `crash` issues: none newer than the last release without at least a reply.

## Layer 2: what the probes cover

Every probe runs in its own process, with a throwaway data folder and a
null keyring. Your real settings, tokens and synced repo are never touched
(the probe refuses to start if that isolation fails).

| Area | Probes |
|---|---|
| Data files | D1 half-written config · D1b killed mid-save ×40 · D4 BOM from an editor · D2 half-written history line · D3 every other state file half-written |
| Sync (git) | G1 server stops answering · G1b hidden password prompt in a background sync |
| Network | N1 "wait an hour" rate limit · N2 secondary rate limit (403/429) · N7 HTTPS-inspecting work network · N9 Wi-Fi login page instead of GitHub |
| Panel (Qt) | Q9 quit while work runs ×10 · Q9b quit while a download is stuck · Q10 pictures made off the UI thread · P3 an error in a button or timer · P3b a hard crash · D6 starting it twice |
| Weekly run | S1 Python in a folder with spaces (cron) · S2 PC asleep at the weekly time (Windows) |
| Phone app | M1 sign-in on a stalled network · M3 token unreadable after reinstall/restore · M7 coming back after hours |
| Your running panel | R1 idle CPU and memory |

**Adding a probe:** write a function with `@probe(id, area, title)` in
`probes.py` that returns `result("PASS"|"WARN"|"FAIL", what happened, fix)`.
A probe must reproduce the failure *for real* (corrupt the file, kill the
process, stall the socket), not read the code and guess. Code-reading is
only allowed for the phone app, which can't run here; those probes say so.

**Check the probe before trusting a FAIL.** Two of the first run's FAILs
were bugs in the probes themselves: a setting name that doesn't exist, and
output lost when the process died. Rerun one probe with `python stability/probes.py D1b`.

## Layer 3: the manual platform checklist

Each line is a failure that real users of similar apps report, and that a
single Windows PC can't reproduce. The ID points into CATALOGUE.md.

**Windows (a clean VM, or a friend's PC):**
- [ ] W1/W2: download the release .exe, then check SmartScreen and Defender, and upload it to VirusTotal.
- [ ] D7: Windows user name with an accent or non-Latin letters (`José`, `محمد`). Install, start, sync.
- [ ] W4/W6: Microsoft Store "python" alias on and no Python, then let the installer install Python and Git.
- [ ] N7: work network or mitmproxy with its own certificate. Install, then refresh.
- [ ] Q6: laptop at 100% plus an external screen at 150%. Dock on each, unplug the external.
- [ ] Q5/T1: sleep 10 minutes, then wake. Check the panel is still on top and refreshes.
- [ ] W12: click **Update** with the panel open.

**Linux (Ubuntu 24.04 is done by CI in `.github/workflows/linux-install.yml`):**
- [ ] Q1/Q2: GNOME on **Wayland**. Does it dock at the edge, and does it stay on top?
- [ ] L3/L4: Fedora latest and Debian 12. Run the one-line install, then start.
- [ ] Q15/L11: minimal install without emoji fonts. Are there boxes instead of icons?
- [ ] K2/K3: a locked keyring, and the weekly cron run (`env -i` with the cron line).

**Phone:**
- [ ] M3: uninstall and reinstall (or restore a backup). The app starts and asks to sign in.
- [ ] M5/M6: Android 15 with gesture navigation. Back from every screen; nothing under the bars.
- [ ] M8: deny camera twice, then open Scan. There should be a way to reach settings.

## Layer 4: crash reports from users

**What happens on a user's computer:**
1. Every error is saved as a report in the logs folder. That covers:
   - an error in the panel;
   - an error in a background thread;
   - Qt's own fatal errors;
   - a **hard crash** that kills the program, recorded by `faulthandler` and turned into a report on the next start;
   - a panel that can't start, or a failed command.
2. The same error repeating counts once, with at most 20 reports per run.
3. A window, *myGeeKy: something went wrong*, shows **exactly** what would be sent, with these removed:
   - tokens;
   - email addresses;
   - the user's name and GitHub login;
   - their home folder.

   It never locks the panel and is offered once per report.
4. **Report on GitHub** opens a prefilled issue in the browser: title `💥 <Error> in <function>`, label `crash`, the user's note, and the cleaned report. **The user submits it.** Nothing is ever sent automatically.

The code is in `src/mygeeky/crashreport.py` and `src/mygeeky/gui/crash_dialog.py`; the tests are in `tests/test_crashreport.py`.

**Weekly triage:**
1. Open the [crash issues](https://github.com/mygeeky/myGeeKy/issues?q=label%3Acrash).
2. Group them by title: the same `<Error> in <function>` is the same bug.
3. For each new one, **first write a failing test or probe** that reproduces it, then fix it.
4. Reply on the issue with the version that fixes it, and close it on release.
5. If a crash came from a situation the probes didn't cover, add the situation to `probes.py` and CATALOGUE.md.

The `crash` label must exist in the repo for the prefilled issues to carry it: Issues → Labels → New label → `crash`.
