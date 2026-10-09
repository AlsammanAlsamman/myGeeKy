#!/bin/sh
# myGeeKy for Linux (and macOS): one line, then a setup window.
#
#   curl -fsSL https://mygeeky.org/install.sh | sh
#
# It installs myGeeKy into its own folder (~/.local/share/mygeeky-app), so it never
# clashes with your system Python, conda, or the "externally managed" rule on new
# Ubuntu and Debian; puts the `mygeeky` command in ~/.local/bin; adds myGeeKy to
# your applications menu; then asks whether to set up in a window or right here in
# the terminal. No sudo, nothing outside your home folder. Running it again updates.
#
# `pip install mygeeky` still works exactly as before, if you prefer it.
# Uninstall: myGeeKy's ⚙ -> Uninstall..., or `mygeeky uninstall`.
#
# For testing: MYGEEKY_SPEC=<wheel or requirement> installs that instead of the
# latest from PyPI; MYGEEKY_NO_LAUNCH=1 stops before setup; MYGEEKY_TERMINAL=1
# skips the question and sets up in the terminal.

set -eu

APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/mygeeky-app"
BIN_DIR="$HOME/.local/bin"
SPEC="${MYGEEKY_SPEC:-mygeeky}"

if [ -t 1 ]; then B=$(printf '\033[1m'); P=$(printf '\033[1;35m'); G=$(printf '\033[1;32m'); R=$(printf '\033[1;31m'); N=$(printf '\033[0m')
else B=""; P=""; G=""; R=""; N=""; fi
say()  { printf '%s>%s %s\n' "$P" "$N" "$*"; }
ok()   { printf '%s✓%s %s\n' "$G" "$N" "$*"; }
fail() { printf '%s✗ %s%s\n' "$R" "$*" "$N" >&2; exit 1; }

printf '\n%smyGeeKy%s: the people, projects, papers and pulse of your field.\n\n' "$B" "$N"

# 1. Python 3.9 or newer
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$c" >/dev/null 2>&1 &&
     "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PY=$(command -v "$c"); break
  fi
done
[ -n "$PY" ] || fail "myGeeKy needs Python 3.9 or newer. Install it (Ubuntu/Debian: sudo apt install python3 python3-venv), then run this again."
ok "Python: $PY ($("$PY" -c 'import platform; print(platform.python_version())'))"

# 2. myGeeKy's own environment
VPY="$APP_DIR/venv/bin/python"
if [ ! -x "$VPY" ]; then
  say "Creating myGeeKy's own Python environment in $APP_DIR"
  mkdir -p "$APP_DIR"
  if ! "$PY" -m venv --clear "$APP_DIR/venv" >/dev/null 2>&1; then
    rm -rf "$APP_DIR/venv"
    fail "Python's venv module is missing. On Ubuntu/Debian: sudo apt install python3-venv  (then run this again)."
  fi
fi

# 3. myGeeKy and Qt
say "Installing myGeeKy and Qt for its window (about 100 MB the first time, a minute or two)..."
"$VPY" -m pip install --quiet --upgrade --disable-pip-version-check pip >/dev/null 2>&1 || true
"$VPY" -m pip install --quiet --upgrade --disable-pip-version-check "$SPEC" "PySide6-Essentials>=6.5" ||
  fail "pip couldn't install myGeeKy (see the messages above). Check your internet connection and try again."
ok "myGeeKy $("$VPY" -c 'import mygeeky; print(mygeeky.__version__)') installed"

# 4. the `mygeeky` command and the applications menu
mkdir -p "$BIN_DIR"
ln -sf "$APP_DIR/venv/bin/mygeeky" "$BIN_DIR/mygeeky"
ok "The mygeeky command: $BIN_DIR/mygeeky"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "Note: $BIN_DIR isn't on your PATH yet. Open a new terminal (or log out and in) to use plain \`mygeeky\`." ;;
esac
if [ "$(uname -s)" = "Linux" ]; then
  "$VPY" -m mygeeky desktop install >/dev/null 2>&1 && ok "Added myGeeKy to your applications menu" ||
    say "Couldn't add the menu entry (you can still start it with: mygeeky gui)"
fi

[ "${MYGEEKY_NO_LAUNCH:-}" = 1 ] && { ok "Done (setup skipped: MYGEEKY_NO_LAUNCH=1)."; exit 0; }

# 5. set up: in a window, or here in the terminal
can_window=0
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] || [ "$(uname -s)" = "Darwin" ]; then
  err=$("$VPY" -c 'import sys
from PySide6.QtWidgets import QApplication
QApplication(sys.argv)' 2>&1) && can_window=1 || {
    if printf '%s' "$err" | grep -q "xcb-cursor"; then
      say "Qt needs one small system package to open windows: sudo apt install libxcb-cursor0"
      say "(Fedora: sudo dnf install xcb-util-cursor; Arch: sudo pacman -S xcb-util-cursor). Install it, then run: mygeeky setup"
    else
      say "Qt couldn't open a window here, so setup continues in the terminal."
    fi
  }
fi

choice=t
if [ "$can_window" = 1 ] && [ "${MYGEEKY_TERMINAL:-}" != 1 ]; then
  choice=w
  if [ -r /dev/tty ]; then
    printf '\nSet up myGeeKy in a %swindow%s (w) or here in the %sterminal%s (t)? [W/t] ' "$B" "$N" "$B" "$N"
    read -r ans </dev/tty || ans=""
    case "$ans" in t|T) choice=t ;; esac
  fi
fi

if [ "$choice" = w ]; then
  ok "Opening the setup window..."
  nohup "$VPY" -m mygeeky.gui.setup_wizard >/dev/null 2>&1 &
  printf '\nIf it doesn'"'"'t appear, run: %smygeeky setup%s\n' "$B" "$N"
else
  say "Setting up in the terminal (any time later: mygeeky setup opens the window instead)."
  if [ -r /dev/tty ]; then exec "$VPY" -m mygeeky init </dev/tty; else exec "$VPY" -m mygeeky init; fi
fi
