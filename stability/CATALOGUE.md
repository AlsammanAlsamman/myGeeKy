# Failure-mode catalogue

Known failures of apps built like myGeeKy (PySide6 desktop panel, JSON/JSONL data, git sync, keyring, GitHub API, PyInstaller/curl|sh installers, Expo phone app), gathered from issue trackers, docs and Q&A on 2026-10-09. The IDs are used by PROTOCOL.md and probes.py. Sources were collected by research and not each re-checked; "[seen in code]" lines were checked against the code on that date. For what was actually *measured*, see REPORT.md.

**Status (2026-10-09):** every exposure that `probes.py` checks has since been fixed (REPORT.md: 23 of 23 pass). Items without a probe are still as described below.

**How to read this.** There are 78 items. Each has a failure, the symptom a user sees, a test, and a source. About 30 of them were checked against the code; those are marked **[seen in code]** with file:line. **[handled]** means the code already deals with it. **[not verified]** means it was not confirmed either way. Where a cell says "common, no link found", the issue is well known but no citable report was found.

The code already handles many classic traps. It has a single-instance `QLockFile`, the Microsoft Store Python stub is skipped, the Windows long-path problem is worked around, consoles stay hidden, device-flow `slow_down` is handled, `.jsonl` files use `merge=union`, the Linux installer uses a venv and spots a missing `libxcb-cursor0`, the phone app's `fetchT` has a timeout, and there are a screen-change redock and a topmost watchdog. The exposures that remain are listed first.

---

## A. The 15 things myGeeKy is most exposed to (from reading the code)

| # | Exposure | Evidence | Why it matters |
|---|---|---|---|
| 1 | **A broken config.json stops the panel starting** | `config.py:259` calls `json.loads(CONFIG_FILE.read_text(...))` with no try. `config.py:295` writes non-atomically with `write_text`. | A crash, power loss or full disk during a save leaves a truncated file. On the next start `load_config()` (`gui/app.py:1046`) raises and the panel never opens. A UTF-8 BOM added by an editor causes the same failure. |
| 2 | **One bad JSONL line breaks a whole history** | `storage.py:41`: `out.append(json.loads(line))` has no per-line try. Appends are plain `open("a")` (`storage.py:27-30`, `interests.py:105`, `achievements.py:67`). | A half-written last line (crash, AV lock, sync-union edge case) makes every caller of `read_jsonl` raise. That covers suggestions, training data, contributions and model history. |
| 3 | **Every other state file is also written non-atomically** | `write_text` in `admin.py:52`, `beacon.py:267,517`, `headlines.py:228`, `hfmodels.py:111`, `interests.py:240`, `keywords.py:192`, `storage.py:66,79,153`. | Same truncation risk. Some readers guard against bad JSON (`load_activity_cache`); others don't (`load_excluded`, `load_following_snapshot`, `storage.py:61,72`). |
| 4 | **git sync can hang forever** | `sync.py:101-113`: `_git()` passes no `timeout=` and does not set `GIT_TERMINAL_PROMPT=0` or `GCM_INTERACTIVE=Never`. The gh credential helper is only added when `gh` exists. | With no gh and no cached credential, git waits on a hidden prompt or a Git Credential Manager window. The worker thread never returns and the sync label stays stuck. |
| 5 | **Sync merges throw away this machine's edits** | `sync.py:267,285,298` use `merge -X theirs`. Push (`sync.py:300`) has no retry on non-fast-forward. | Editing `excluded.json` or config on two machines keeps only the remote copy, silently. If two machines push close together, one gets a raw `SyncError`. |
| 6 | **Secondary rate limits are not handled** | `github_client.py:40-52` only checks `X-RateLimit-Remaining <= 1`. Nothing handles 403/429 or `Retry-After`. `time.sleep(wait)` can block a worker for up to an hour. | Search-heavy runs hit GitHub's secondary limit. Callers see `None` or empty results (for example `get_user` returns None on non-200) rather than a "rate limited" message. |
| 7 | **Breaks on networks that inspect TLS** | No `truststore`, `certifi` override or `REQUESTS_CA_BUNDLE` handling anywhere in `src/`. `errors.py:62` reports `SSLError` as "Couldn't reach the internet". | On Zscaler/Netskope-style corporate networks every HTTPS call fails with a misleading message. This matters because the author's own work network is one of them. |
| 8 | **Possible crash on quit while workers are running.** **Fixed after this research (probe Q9: 10 of 10 quits crashed before, 0 of 10 after).** | `_Worker(QThread)` at `qt_panel.py:238` has no parent and nothing calls `quit()`/`wait()` on exit. `QApplication.quit()` is called at `qt_panel.py:4157` and `3787`. `_finish` drops the last reference while `run()` may not have returned yet (`qt_panel.py:300-305`, `4699-4705`). | Classic "QThread: Destroyed while thread is still running" abort, or a random crash at exit or during avatar loads. |
| 9 | **The weekly cron job is fragile** | `scheduler.py:52`: the Python path is unquoted and the log path `~/.local/share/mygeeky/logs/weekly.log` is hard-coded. | A path with spaces breaks the job. If the logs folder is missing, the shell redirect fails and the job never runs. On macOS the data dir is elsewhere. Cron also has no `DBUS_SESSION_BUS_ADDRESS`, so `keyring` (Secret Service) fails and the run falls back to gh or no auth. There is also no PATH for git/gh. |
| 10 | **Scheduled task misses its run if the PC is off** | `scheduler.py:33-36`: `schtasks /SC WEEKLY /ST 09:00` without "run as soon as possible after a missed start" (StartWhenAvailable needs XML or PowerShell). | A laptop asleep or off at Monday 09:00 skips the week silently. |
| 11 | **Wayland: no docking and no always-on-top** | Nothing in `src/` mentions `QT_QPA_PLATFORM` or Wayland. Docking relies on `move()` and `WindowStaysOnTopHint` (`qt_panel.py:2903`, `3082`, `4607`). | On GNOME/KDE Wayland the compositor ignores `move()` and stay-on-top. The panel appears wherever the compositor puts it (often centred) and goes behind other windows. |
| 12 | **The curl \| sh installer is not protected against a truncated download** | `website/install.sh` runs at top level, not inside a function called on the last line. | If the download drops mid-stream, sh runs a partial script. `set -eu` limits but does not prevent the damage. |
| 13 | **The Windows setup .exe is unsigned** | `installer/build.py:37` uses `--onefile --windowed` and no signing step was found in that file. Not verified whether CI signs it. | SmartScreen shows "Windows protected your PC" and Defender or other AV may quarantine it. The onefile `_MEI` temp extraction is also a common heuristic trigger. |
| 14 | **Phone sign-in can hang without a timeout** | `mobile/src/lib/github-login.ts:12,60` call raw `fetch` instead of `fetchT` (`net.ts:4`). | On a captive portal or stalled network the sign-in spinner never ends. |
| 15 | **Token in the QR code** | `pairing.py:1-12` puts the read-only token in the QR, shown for 120 s. | Not a stability bug, but a screen-share or screenshot leaks a token. Worth a check in the protocol. |

---

## B. The full catalogue

### 1. Qt / PySide6 windowing, painting and threads

| ID | Failure | Symptom | Test | Source | myGeeKy |
|---|---|---|---|---|---|
| Q1 | On Wayland, `move()`/`setGeometry()` on top-level windows is ignored | Panel not docked to the edge; appears centred | Run under a GNOME Wayland session, check `windowHandle().position()` against the screen edge | [QTBUG-110119](https://bugreports.qt.io/browse/QTBUG-110119), [Qt interest list](https://lists.qt-project.org/pipermail/interest/2014-August/013271.html) | **Exposed** (no Wayland handling) |
| Q2 | `WindowStaysOnTopHint` is ignored on Wayland | Panel goes under other windows | Wayland session: open another window, see if the panel stays above | Same as Q1 | **Exposed** |
| Q3 | Workaround `QT_QPA_PLATFORM=xcb` fails when XWayland or libxcb-cursor0 is missing | "Could not load the Qt platform plugin xcb" | Fresh Ubuntu 24.04 without libxcb-cursor0: `python -c "from PySide6.QtWidgets import QApplication; QApplication([])"` | [Qt 6.5 heads-up](https://www.riverbankcomputing.com/pipermail/pyqt/2023-April/045248.html), [Qt Linux requirements](https://doc.qt.io/qt-6/linux-requirements.html) | **[handled]** at install time (`install.sh` greps for xcb-cursor). Not verified at app runtime. |
| Q4 | `WA_TranslucentBackground` renders black with no compositor (bare X11 WM, VNC, RDP) | Black box round the rounded panel | Run under Xvfb or a WM with no compositor | Common, no link found | Not verified |
| Q5 | On Windows, the topmost flag is lost after a full-screen app, virtual-desktop switch or sleep | Folded icon hidden behind windows | Fullscreen video then exit; Win+Ctrl+arrow to switch desktop; sleep/resume | [MS SetWindowPos docs](https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-setwindowpos) | **[handled]** `gui/topmost.py` |
| Q6 | Mixed-DPI monitors give wrong positions or a jump between screens | Panel off-screen, wrong size or blurry on the second monitor | 100% laptop + 150% external: dock on each, drag between them, unplug the external | [QTBUG-73014](https://bugreports.qt.io/browse/QTBUG-73014), [QTBUG-77307](https://bugreports.qt.io/browse/QTBUG-77307), [QTBUG-104074](https://bugreports.qt.io/browse/QTBUG-104074) | Partly handled (`qt_panel.py:4625-4648` redocks on screen changes). Mixed DPI not verified. |
| Q7 | Fractional scaling (125/150%) gives cut-off text or 1-px seams in custom painting | Clipped labels, hairlines | Screenshot tests at 100/125/150/175% (`QT_SCALE_FACTOR`) | [QTBUG-80228](https://bugreports.qt.io/browse/QTBUG-80228) | Not verified (lots of custom `paintEvent`) |
| Q8 | The docked monitor is unplugged or the taskbar moves | Panel stranded off-screen | Dock on monitor 2, unplug it, move the taskbar to the left | Common, no link found | **[handled]** `screenRemoved`/`availableGeometryChanged` (`qt_panel.py:4631-4641`) |
| Q9 | QThread destroyed while running at quit | "QThread: Destroyed while thread is still running" then abort, or crash at exit | Start a long refresh, then Quit at once; repeat 20 times | [Qt forum](https://forum.qt.io/post/576640), [PySide list](https://lists.qt-project.org/pipermail/pyside/2013-December/001780.html) | **Fixed after this research (probe Q9: 10 of 10 quits crashed before, 0 of 10 after).** Originally exposed (A8). |
| Q10 | A worker touches widgets or `QPixmap` off the GUI thread | Random crash, "QPixmap: It is not safe to use pixmaps outside the GUI thread" | Run with `QT_FATAL_WARNINGS=1`, hammer avatar loading | [Qt threading docs](https://doc.qt.io/qt-6/threads-qobject.html) | **Check**: `AvatarLoader.fetch` builds and saves a `QPixmap` inside the worker (`qt_panel.py:277-296`). Qt 6 documents `QPixmap` as GUI-thread-only; `QImage` is the safe type. Likely exposed. |
| Q11 | Signal emitted after the receiving widget is deleted | `RuntimeError: Internal C++ object already deleted` | Close a dialog while its fetch is in flight | Common, no link found | Not verified (dialogs at `qt_panel.py:1505`, `1823`) |
| Q12 | Light/dark switch at OS level does not repaint custom-painted parts | Mixed light and dark parts | Toggle the OS theme with the panel open | [Qt 6.5 colorScheme](https://doc.qt.io/qt-6/qstylehints.html#colorScheme-prop) | Not verified |
| Q13 | Frameless window cannot be dragged or resized, or Aero Snap fights the docking | Panel snaps or maximizes oddly | Win+Arrow while the panel is focused | Common, no link found | Not verified |
| Q14 | `Qt.Tool` windows have no taskbar entry, so after hiding the user cannot find the app | "App vanished" | Hide or fold, then switch desktops or log off and on | Common, no link found | Not verified |
| Q15 | Emoji draw as tofu boxes on Linux without a colour emoji font | Squares where emoji should be | Container without `fonts-noto-color-emoji` | Common, no link found | **Likely exposed**: emoji used in UI (`qt_panel.py:1836` `KINDS`) |
| Q16 | High CPU or battery drain from many `QTimer`s and repaint animations | Fan noise, laptop drain | Idle panel for 10 min; check CPU% and wakeups (`powercfg /energy`) | Common, no link found | Not verified (about 10 timers, `qt_panel.py:3093-3165`) |
| Q17 | A remote-desktop/RDP session change makes the screen or DPI change underneath the app | Panel off-screen or tiny after RDP reconnect | RDP in from another machine at a different resolution | Common, no link found | Partly handled (redock) |

### 2. Sleep/resume, clocks, timers

| ID | Failure | Symptom | Test | Source | myGeeKy |
|---|---|---|---|---|---|
| T1 | After resume, all timers fire at once, or the network is not up yet, so the first fetch fails | Error banner right after waking | Sleep 10 min, wake, watch the logs | Common, no link found | Not verified (no resume handling found; grep for suspend/resume/`WM_POWERBROADCAST` hit nothing besides a comment) |
| T2 | Wall-clock deltas break with clock skew or DST, giving negative "ago" values or a refresh that never comes due | "-3 h ago", stale data | Set the clock back 2 h; cross a DST boundary | Common, no link found | Partly: `github_login.py` uses `monotonic` (good). Refresh cadence not verified. |
| T3 | Naive and aware datetimes compared raise `TypeError` | Crash in "time ago" code | Feed timestamps with and without `Z` and offset | Common, no link found | Mostly guarded (`storage.py:117`, `qt_panel.py:161`) |
| T4 | Clock skew makes TLS fail ("certificate not yet valid") or makes token-expiry warnings wrong | SSL errors, "token expired" when it isn't | Set the clock 2 years ahead or behind | Common, no link found | Not verified (`tokens.py:31` `parse_expiry`) |
| T5 | Scheduled task or cron runs while the PC is asleep or off and is missed | Weekly run never happens | Sleep over Monday 09:00 | [schtasks docs](https://learn.microsoft.com/windows-server/administration/windows-commands/schtasks-create) | **Exposed** (A10) |
| T6 | A long `time.sleep` inside a worker (rate-limit wait) blocks quitting and refreshing | Panel will not quit; refresh hangs | Mock `X-RateLimit-Remaining: 0` with reset +3600 | n/a | **Exposed** (`github_client.py:43-47`) |

### 3. Data files: JSON/JSONL, paths, concurrency

| ID | Failure | Symptom | Test | Source | myGeeKy |
|---|---|---|---|---|---|
| D1 | Non-atomic write truncated by a crash, power loss or full disk | App won't start or settings reset | Kill -9 the process in a loop during `save_config`; fill the disk (small VHD) | [atomic write pattern](https://pypi.org/project/safewrite/) | **Exposed** (A1, A3) |
| D2 | Truncated or corrupt last JSONL line breaks every reader | Suggestions or history empty, or a traceback | Append `{"a":` to `suggestions_history.jsonl`, start the panel | n/a | **Exposed** (A2) |
| D3 | `os.replace` fails with WinError 5 because AV, indexer or OneDrive briefly holds the file | Intermittent "Access is denied" on save | Hold the file open with a second process while saving | [mypy#3215](https://github.com/python/mypy/issues/3215) | Watch for this once atomic writes are added: they need retry logic |
| D4 | UTF-8 BOM in a hand-edited JSON (old Notepad, PowerShell 5 `Set-Content`) | "Unexpected UTF-8 BOM" | Save config.json with a BOM, start the app | Common, no link found | **Exposed** (`config.py:259` reads `utf-8`, not `utf-8-sig`) |
| D5 | Two processes writing the same file (panel + weekly task + CLI) | Lost updates, interleaved JSONL lines | Run `mygeeky pipeline` while the panel refreshes | n/a | **Partly exposed**: the lock covers the panel only, not CLI or scheduled runs (`app.py:1030`) |
| D6 | Stale lock after a crash blocks launch | "Nothing happens when I click the icon" | Kill -9 the panel, relaunch | [QLockFile docs](https://doc.qt.io/qt-6/qlockfile.html) | **[handled]** QLockFile stale detection, but a 200 ms `tryLock` returns silently (`app.py:1031`). The second launch gives no feedback and does not raise the existing window. |
| D7 | Non-ASCII Windows username (`C:\Users\José`) breaks subprocess or encoding paths | Install or launch fails with UnicodeDecodeError | Create a local user with non-ASCII/CJK chars, install fresh | Common, no link found | Mostly guarded (`encoding="utf-8", errors="replace"` in `setup_wizard.py:163`). Cron and schtasks quoting not verified. |
| D8 | Path with spaces unquoted in cron or schtasks | Scheduled job silently broken | Install Python under `C:\Program Files\` or `~/My Apps` | n/a | **Exposed** for cron (`scheduler.py:52`). schtasks is quoted (`:35`). |
| D9 | OneDrive Known Folder Move or Files-On-Demand makes Documents/Desktop placeholders; a CV or `.desktop` path points into cloud-only files | Reading a CV PDF hangs or fails | Point `cv_path` at an online-only OneDrive file | [MS Known Folders](https://learn.microsoft.com/windows/win32/shell/working-with-known-folders) | Low: data dir is `%LOCALAPPDATA%` (not redirected). CV path is user-chosen; not verified. |
| D10 | Roaming or redirected `%APPDATA%` on corporate domains (folder redirection to a network share) | Slow saves, files locked, git repo on SMB | Domain PC with redirected AppData | Common, no link found | Not verified (which `platformdirs` folder is used: roaming or local?) |
| D11 | Windows 260-char path limit for deep packages | pip install of PySide6 fails | Python under a deep path, `LongPathsEnabled=0` | [MS long paths](https://learn.microsoft.com/windows/win32/fileio/maximum-file-path-limitation) | **[handled]** `bootstrap.py` private Qt dir |
| D12 | Settings written by a newer version and read by an older one (sync between machines) | Crash or reset on the older machine | Sync a config with a new key or version to an older install | n/a | **[handled]** unknown keys are ignored (`config.py:261-263`) |
| D13 | Disk full or quota: writes raise OSError mid-run | Cascading errors | Small RAM disk as `XDG_DATA_HOME` | n/a | Not verified |

### 4. Keyring / secrets

| ID | Failure | Symptom | Test | Source | myGeeKy |
|---|---|---|---|---|---|
| K1 | No keyring backend (headless Linux, WSL, minimal WM) gives `NoKeyringError` | "Could not access an OS keyring" | `PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring mygeeky auth login` | [keyring docs: headless](https://keyring.readthedocs.io/en/latest/#using-keyring-on-headless-linux-systems), [KBI0023](https://knowledge-base.psychoinformatics.de/kbi/0023/index.html) | **[handled]** for get (`auth.py:75-79`). Set raises a clear error (`auth.py:123-131`). |
| K2 | Secret Service locked collection: the call hangs waiting for an unlock prompt nobody sees (autostart before login keyring unlock, cron, SSH) | Panel freezes at startup or the token is "missing" | Lock the keyring (`seahorse`), then start the panel or the cron job | Same as K1; [Arch BBS](https://bbs.archlinux.org/viewtopic.php?id=269593) | **Likely exposed**: no timeout around `keyring.get_password`. Not verified whether it is called on the UI thread. |
| K3 | Cron or systemd has no DBus session, so the Secret Service is unreachable | Scheduled runs are unauthenticated and rate-limited | Run the cron line from `env -i` | Same as K1 | **Exposed** (A9) |
| K4 | KWallet vs gnome-keyring vs KeePassXC backend chosen differently in different contexts | Token "disappears" between terminal and GUI | Log `keyring.get_keyring()` in both contexts | [Doppler/KeePassXC thread](https://community.doppler.com/t/trouble-with-the-keepassxc-secrets-service-integration/1730) | Not verified |
| K5 | Windows Credential Locker 2560-byte blob limit | Store fails for long secrets | Store a 3 KB string | jaraco/keyring issue (direct link not opened) | Low (GitHub tokens are short) |
| K6 | macOS Keychain "allow access" prompt reappears after each update, because the Python binary changed | Repeated prompts | Upgrade Python or the venv, re-read the token | Common, no link found | Not verified (macOS path) |
| K7 | A keyring in a venv picks up `keyrings.alt` (plaintext) if installed | Token stored unencrypted | `python -c "import keyring; print(keyring.get_keyring())"` | keyring docs | Not verified |

### 5. Network: GitHub API and other feeds

| ID | Failure | Symptom | Test | Source | myGeeKy |
|---|---|---|---|---|---|
| N1 | Primary rate limit (60/h unauthenticated, 5000/h with a token) | Empty lists, "nothing new" | Unset the token, run a refresh twice | [GitHub rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) | Handled crudely (sleep) |
| N2 | Secondary rate limit: 403/429 with `Retry-After` on search or bursts | Search silently returns nothing | Mock a 403 with `Retry-After: 60`; burst 40 searches | Same as N1 | **Exposed** (A6) |
| N3 | Fine-grained PAT lacks a permission, giving 403/404 on followers or private endpoints | Feature silently empty | Token with only public repos and no Followers scope | [Fine-grained PAT docs](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) | Mostly handled (`token_check.py`) |
| N4 | Token expired or revoked: 401 everywhere | Everything fails | Revoke the token on github.com | Same | **[handled]** expiry header (`tokens.py:21`). 401 at runtime not verified. |
| N5 | Organisation SSO not authorised for the token gives 403 with an `X-GitHub-SSO` header | Org data missing | Org with SAML | [GitHub SSO docs](https://docs.github.com/en/rest/authentication/authenticating-to-the-rest-api) | Not verified |
| N6 | Device flow: `slow_down` ignored, code expires, or the user closes the browser | Sign-in loops or fails | Poll faster than the interval; wait more than 15 min | [GitHub device flow](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps#device-flow) | **[handled]** `github_login.py:46-74` |
| N7 | Corporate TLS interception: certifi does not trust the corporate root | SSLError, shown as "no internet" | Run behind mitmproxy with its CA only in the Windows store | [pip HTTPS certs / truststore](https://pip.pypa.io/en/stable/topics/https-certificates/) | **Exposed** (A7). pip during install and the bootstrap Qt download are hit too. |
| N8 | Proxy only via PAC/WPAD, which requests does not support | Every call times out | Set a PAC-only proxy in Windows | [requests proxies](https://requests.readthedocs.io/en/latest/user/advanced/#proxies) | Not verified (requests does read the WinINet static proxy from the registry) |
| N9 | Captive portal returns HTML with status 200 | JSON decode error or garbage in feeds | Hotel Wi-Fi, or point DNS at a local HTML server | Common, no link found | Not verified (`.json()` used without try in places, e.g. `admin.py:269`) |
| N10 | Blocked domains at work (pypistats, producthunt, huggingface, openalex) | One section always errors | Block each host in `hosts` | n/a | Not verified per source. mygeeky.org itself is blocked on the author's work network. |
| N11 | RSS/Atom with bad encoding, BOM, HTML entities, or a feed switched to a different format | Headlines empty or a parse crash | Fixture feeds (Latin-1, BOM, empty, 404, HTML) | Common, no link found | Not verified (`headlines.py:138`) |
| N12 | API schema drift (fields removed or renamed, e.g. Product Hunt GraphQL or HF `trendingScore`) | `KeyError` and an empty section | Contract tests against live endpoints weekly | Common, no link found | Not verified (`hfmodels.py:68`) |
| N13 | Pagination stops early or `Link` headers are ignored | Missing followers or repos | Account with more than 300 repos | Common, no link found | Hard cap `max_pages=3` (`github_client.py:62`). By design? |
| N14 | IPv6-only or broken IPv6 makes connects slow, close to the timeout | 20-second hangs | Disable IPv4 or route IPv6 into a black hole | Common, no link found | Not verified |
| N15 | Avatar or image download returns WebP/SVG that the Qt image plugins can't decode | Blank avatars | Feed WebP when the qwebp plugin is absent | Common, no link found | Not verified. PyInstaller excludes do not apply to the pip-installed panel. |

### 6. git / gh sync

| ID | Failure | Symptom | Test | Source | myGeeKy |
|---|---|---|---|---|---|
| G1 | Hidden credential prompt or Git Credential Manager GUI blocks a background git | Sync hangs forever | Remove gh, clear credentials, trigger a sync | [gitlab-runner#4134](https://gitlab.com/gitlab-org/gitlab-runner/-/issues/4134), [git docs: GIT_TERMINAL_PROMPT](https://git-scm.com/docs/git#Documentation/git.txt-codeGITTERMINALPROMPTcode) | **Exposed** (A4) |
| G2 | No timeout on git subprocesses (slow proxy, huge repo) | Stuck "Syncing…" | `tc`/clumsy to throttle to 10 kB/s | n/a | **Exposed** (`sync.py:112`) |
| G3 | `-X theirs` loses local edits | User changes revert | Edit excluded or config on both machines, sync both | [git merge-strategies](https://git-scm.com/docs/merge-strategies) | **Exposed** (A5) |
| G4 | Push race gives non-fast-forward | Sync error after the other machine synced | Two machines push within seconds | n/a | **Exposed** |
| G5 | `merge=union` on JSONL can splice or duplicate lines, or join lines if one lacks a final newline | Duplicate history or a corrupt line (then D2) | Write a JSONL without a trailing newline on one side, merge | [gitattributes union](https://git-scm.com/docs/gitattributes#_built_in_merge_drivers) | Partly exposed (D2 makes it fatal) |
| G6 | Stale `.git/index.lock` after a crash or AV | "Another git process seems to be running" forever | Create `.git/index.lock`, sync | Common, no link found | Not verified |
| G7 | `core.autocrlf`, safe.directory ("dubious ownership") on a shared or redirected folder, or a global hooks path running the user's own hooks | Sync fails with odd messages | Set `core.hooksPath` to a failing hook; take ownership as another user | [git safe.directory](https://git-scm.com/docs/git-config#Documentation/git-config.txt-safedirectory) | Not verified |
| G8 | git missing from PATH for the GUI process (installed after login; cron PATH) | "git not found" though the user has it | Install git and launch from the existing Explorer session without re-logging in | n/a | Partly handled (`git_exe()` lookup) |
| G9 | `gh auth git-credential` with gh logged into a different account than the token's user | Push denied (403) | gh logged in as user A, myGeeKy configured for user B | n/a | Not verified |
| G10 | Accidentally committing secrets or big files to the private repo | Repo bloat or a leak | Inspect the `.gitignore` list against the actual data-dir contents | n/a | Mostly handled (`sync.py:31-55`). Confirm `crash-*.txt` and error reports (which contain argv and paths) are excluded: `logs/` is, but `errors.py:78` writes to a `folder` not traced. |

### 7. Windows installer (PyInstaller wizard, winget, pip into the user's Python)

| ID | Failure | Symptom | Test | Source | myGeeKy |
|---|---|---|---|---|---|
| W1 | AV false positive or quarantine of an unsigned onefile exe | Download deleted; "Trojan:Win32/Wacatac" | Upload to VirusTotal each release | [discuss.python.org](https://discuss.python.org/t/pyinstaller-false-positive/43171), [false-positive reporting](https://github.com/hankhank10/false-positive-malware-reporting) | **Exposed** (A13) |
| W2 | SmartScreen "Windows protected your PC" for a new unsigned binary | Users think it's malware | Download the fresh exe on a clean VM | Same | **Exposed** |
| W3 | Onefile extracts to `%TEMP%\_MEIxxxx`; AV or temp cleaners delete it, or `%TEMP%` is noexec or redirected | "Failed to load Python DLL" | Run with AV real-time scanning; set TEMP to a non-ASCII path | [pythonguis FAQ](https://www.pythonguis.com/faq/dll-loading-error-with-pyinstaller-ctypes-cdll/) | Exposed by design (onefile) |
| W4 | `python` resolves to the Microsoft Store stub | Silent exit 9009 or 49 | Clean Windows 11 with the alias on | [bobbyhadz](https://bobbyhadz.com/blog/python-was-not-found-run-without-arguments-to-install) | **[handled]** (`setup_wizard.py:202-212`) |
| W5 | winget missing (LTSC/Server, or App Installer outdated) or blocked by policy | Python/Git install fails | Windows Server or LTSC VM; set the GPO "EnableAppInstaller=0" | [winget docs](https://learn.microsoft.com/windows/package-manager/winget/) | Fallback to the python.org download exists (`setup_wizard.py:232-243`). Verify the error text. |
| W6 | PATH not refreshed after installing Python/Git in the same session | "Installed but not found" | Fresh VM: let the wizard install both, check the next step | Common, no link found | Partly handled (LOCALAPPDATA glob). Git not verified. |
| W7 | Conda/pyenv/venv Python picked as "the user's Python", then breaks when the env is removed or updated | Panel won't start after `conda update` | Have conda base first on PATH | Common, no link found | Not verified (`py -3` preferred first, good) |
| W8 | pip into a system or locked Python (Program Files, no write access) goes to user site; or `PIP_REQUIRE_VIRTUALENV`, `pip.conf` index, or an offline mirror on corporate machines | pip fails or installs elsewhere | Set `PIP_REQUIRE_VIRTUALENV=1`; set a corporate `index-url` | [pip config](https://pip.pypa.io/en/stable/topics/configuration/) | Not verified |
| W9 | AppLocker/WDAC blocks unsigned exes in `%TEMP%`/Downloads or blocks `pythonw` in user folders | Installer or panel blocked at work | Corporate machine test | Common, no link found | Unknown, the user's own work PC is the test |
| W10 | `schtasks /Create` needs elevation or is blocked by policy | "Access denied" creating the task | Standard user under GPO | [schtasks](https://learn.microsoft.com/windows-server/administration/windows-commands/schtasks-create) | Errors are surfaced (`scheduler.py:80-82`) |
| W11 | Uninstall leaves the scheduled task, startup shortcut, keyring entries or data dir behind | Ghost runs after uninstall | Uninstall, then check `schtasks /Query`, Credential Manager, `%LOCALAPPDATA%` | n/a | Partly handled (`setup_wizard.py:454-467`). Keyring cleanup not verified. |
| W12 | Updating while the panel runs: DLLs locked during `pip install --upgrade` | "Access is denied" on `PySide6\*.dll` | Run the update with the panel open | Common, no link found | `updates.py:100-136` relaunches; verify it closes the panel first |
| W13 | ARM64 Windows: PySide6 wheels or x64 Python mismatch | Install fails or runs emulated slowly | Windows-on-ARM VM | Common, no link found | Not verified |

### 8. Linux installer and desktop integration

| ID | Failure | Symptom | Test | Source | myGeeKy |
|---|---|---|---|---|---|
| L1 | PEP 668 "externally-managed-environment" | pip refuses | Ubuntu 24.04 `pip install mygeeky` | [pythonspeed](https://pythonspeed.com/articles/externally-managed-environment-pep-668) | **[handled]** venv. The README's "`pip install mygeeky` still works" line will hit this. |
| L2 | `python3-venv`/ensurepip missing on Debian/Ubuntu | venv creation fails | Minimal Ubuntu container | Same | **[handled]** with a message |
| L3 | `libxcb-cursor0` and other xcb libs missing | Qt plugin load failure | Fresh Ubuntu, Fedora, Arch | [Qt Linux reqs](https://doc.qt.io/qt-6/linux-requirements.html), [Rocky forum](https://forums.rockylinux.org/t/pyside6-on-rocky-linux-9-6-is-missing-xcb-plugin/19828) | **[handled]** for cursor; other libs (libEGL, libxkbcommon-x11, libgl1) only get the generic message |
| L4 | glibc too old for PySide6 manylinux wheels (RHEL/CentOS 7/8, old Debian) | pip "no matching distribution" | RHEL 8 / Debian 10 container | [PySide6 on PyPI](https://pypi.org/project/PySide6/) | Not verified |
| L5 | A newly released Python (3.14 at a distro's launch) has no PySide6 wheel yet | Qt install fails | Fedora rawhide | Same | **Possible**: `install.sh` tries `python3.13…python3.9`, then `python3`, so a distro whose only Python is 3.14 lands on `python3` |
| L6 | Truncated curl \| sh | Partial execution | `head -c 2000 install.sh \| sh` | [Sandstorm on curl\|sh](https://sandstorm.io/news/2015-09-24-is-curl-bash-insecure-pgp-verified-install) | **Exposed** (A12) |
| L7 | `~/.local/bin` not on PATH (common on Debian, zsh, fish) | "command not found" | Fresh user shell | n/a | **[handled]** with a warning |
| L8 | `.desktop` file invalid (Exec path with spaces, missing `StartupWMClass`) | No icon, duplicate dock icons, or no launch | `desktop-file-validate`; check the dock icon under GNOME | [Desktop Entry spec](https://specifications.freedesktop.org/desktop-entry-spec/latest/) | Partly (`setDesktopFileName`, `app.py:1041`). Validate. |
| L9 | Autostart starts before the session is ready (no tray/compositor or keyring yet) | Panel in the wrong place, token missing | Reboot with autostart on, slow login | Common, no link found | Not verified (`gui/desktop.py:99-105`) |
| L10 | Flatpak/Snap/immutable distros (Silverblue, SteamOS) with a read-only or odd `$HOME` layout | Installer quirks | Fedora Silverblue VM | Common, no link found | Not verified |
| L11 | Emoji or CJK font missing (minimal installs, WSLg) | Tofu boxes | Container without noto fonts | Common, no link found | **Likely** (Q15) |
| L12 | Dark/light detection fails on non-GNOME desktops or portals | Wrong theme, terminal spam | KDE, XFCE, Sway | n/a | Partly handled (`app.py:1015-1018` silences `qt.qpa.theme`) |

### 9. Process and lifecycle

| ID | Failure | Symptom | Test | Source | myGeeKy |
|---|---|---|---|---|---|
| P1 | A second instance launched from Start menu, autostart or the installer | Two panels, or nothing with no feedback | Double-click the shortcut twice fast | n/a | Handled, but the second launch is silent (D6) |
| P2 | `pythonw` has no stdout/stderr, so code that writes to them or reads `sys.stdout.encoding` crashes | Silent crash on start under pythonw | Run `pythonw -m mygeeky.gui.app` with a code path that prints | [Python docs: sys.stdout None](https://docs.python.org/3/library/sys.html#sys.__stdout__) | Mostly handled (`bootstrap.py:88`). `print()` with None stdout is a no-op, but `sys.stdout.write`/`flush` would raise. Not verified project-wide. |
| P3 | Unhandled exception in a Qt slot terminates the app (PySide6 6.x default) | Panel vanishes | Raise inside a timer slot | n/a | **[handled]** by `crashreport.py`. Worker exceptions are also caught (`qt_panel.py:248`). |
| P4 | Self-update relaunch fails, leaving the app closed | "Updated and disappeared" | Update with a broken new wheel | n/a | Not verified (`updates.py:130-136`) |
| P5 | Log files grow without bound | Disk use over months | Check sizes of `logs/` and `*.jsonl` after simulated months | n/a | Not verified. JSONL is append-only with no rotation seen. |
| P6 | Memory growth: avatar cache in memory, workers list, per-refresh widgets never deleted | RAM climbs over days | Run 48 h, sample RSS hourly | n/a | Not verified (`qt_panel.py:261` `_memory` dict unbounded) |

### 10. Phone app (Expo / React Native)

| ID | Failure | Symptom | Test | Source | myGeeKy |
|---|---|---|---|---|---|
| M1 | `fetch` has no timeout; stalls on captive portals | Endless spinner | Airplane mode, then Wi-Fi with a portal | [RN networking](https://reactnative.dev/docs/network) | **[handled]** `net.ts`, except **github-login.ts:12,60** (A14) |
| M2 | Android blocks cleartext HTTP (API 28+) | "Network request failed" in release builds only | Release APK hitting any `http://` URL | [Expo forum](https://forums.expo.dev/t/cant-communicate-with-server-from-android-api-28/24794) | No `http://` found in `mobile/src` (good). Feed URLs from user data not verified. |
| M3 | SecureStore unreadable after reinstall or backup restore ("Could not decrypt") | Token lost or crash on start | Uninstall, reinstall, restore from Google backup | [Expo SecureStore docs](https://docs.expo.dev/versions/v57.0.0/sdk/securestore/), [Expo forum](https://forums.expo.io/t/could-not-decrypt-the-item-in-securestore-and-rewriting-the-encryption-keys/48644) | **Check**: `getToken` (`storage.ts:42`) has no try/catch around `getItemAsync`. AsyncStorage *is* backed up, so restored settings plus an undecryptable token is possible. |
| M4 | Corrupt AsyncStorage JSON | Crash on start | Write garbage to the key | n/a | **[handled]** (`storage.ts:29-33`, `:59-63`, `badges.ts:36-40`) |
| M5 | Android hardware back / predictive back exits the app from deep routes, or ignores a modal | App closes unexpectedly | Back from scan or person screens | [expo-router docs](https://docs.expo.dev/router/introduction/) | Not verified (`predictiveBackGestureEnabled: false` in app.json) |
| M6 | Safe-area problems: notch, Android 15 edge-to-edge (enforced at targetSdk 35), gesture bar overlap | Content under the status bar or nav bar | Android 15 device with gesture nav; iPhone with Dynamic Island | [Android edge-to-edge](https://developer.android.com/develop/ui/views/layout/edge-to-edge) | Mostly handled. `home.tsx:145` uses `edges={['top']}` only, so check bottom-tab overlap. |
| M7 | Background timers or `setInterval` are suspended in the background, and stale data shows on resume | Old data after reopening | Background for 1 h, reopen | [RN AppState](https://reactnative.dev/docs/appstate) | **Possible**: no `AppState` listener found in `mobile/src` |
| M8 | Camera permission permanently denied: the QR scan screen has no "open settings" path | Can't pair | Deny twice, open scan | [expo-camera](https://docs.expo.dev/versions/latest/sdk/camera/) | Not verified (`scan.tsx:34-41`) |
| M9 | Large QR payload (profile + token + interests) fails to scan on low-end cameras | Pairing fails | Max-size profile, budget phone | n/a | Not verified (`pairing.py` packs interests, field, badges) |
| M10 | GitHub rate limits from phone IPs (shared carrier NAT) when no token is stored | Empty screens | Use without a token on mobile data | Same as N1 | Not verified |
| M11 | `fast-xml-parser` on huge feeds blocks the JS thread | UI jank | 5 MB feed fixture | n/a | Not verified |
| M12 | OTA updates or SDK upgrades break the native-module mismatch (Expo SDK 57, RN 0.86) | Crash on start after an update | Install an older build, push a newer JS bundle | [Expo updates](https://docs.expo.dev/eas-update/introduction/) | Not verified |

---

## C. A minimal automated harness for the items above

1. **Data-file fuzz test** (pytest, `tmp_path` as the data dir). For every file in `config.py`'s constants, write the following variants and assert the panel and CLI still load with a warning, not a traceback:
   - empty
   - truncated JSON
   - BOM-prefixed
   - a JSONL whose last line is partial
   - a non-UTF-8 file

   This covers D1, D2, D4 and G5.
2. **Kill-during-save test.** Spawn a subprocess that loops on `save_config`, send SIGKILL at random times 200 times, then `load_config()`. Covers D1.
3. **Network fault test.** Use `responses` or `pytest-httpserver` to inject each of these and assert the UI message and that no worker exceeds N seconds:
   - 403/429 with `Retry-After`
   - `X-RateLimit-Remaining: 0`
   - 401
   - an HTML 200 (captive portal)
   - SSLError
   - a 30 s stall

   Covers N1–N12 and T6.
4. **git test.** Run `sync.push()` with `PATH` stripped of `gh`, `GIT_ASKPASS` unset and a bogus remote. Assert it returns within 60 s. Covers G1 and G2.
5. **Qt smoke test** under `QT_QPA_PLATFORM=offscreen` with `QT_FATAL_WARNINGS=1`: start the panel, fire every refresh, call `quit()` after 100 ms, repeat 50 times. Covers Q9 and Q10.
6. **Install matrix VMs and containers:**
   - Windows 11 clean, with a non-ASCII username, Store alias on, Python in Program Files, behind mitmproxy
   - Ubuntu 24.04 minimal (X11 and Wayland)
   - Fedora latest
   - Debian 12
   - Each one: run the scheduled or cron job from `env -i`

All file:line references are under `src/mygeeky/` and `mobile/src/`, plus `website/install.sh` and `installer/build.py`, as of 2026-10-09.
