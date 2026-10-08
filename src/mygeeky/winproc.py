"""Run helper programs (git, gh, pip, schtasks...) without ever flashing a window.

On Windows every console program -- git.exe, gh.exe, python.exe -- gets its
own black console window when started from the panel (which has none), unless
told otherwise. A user sees those flash open and shut, with an
"...\\AppData\\..." title, and rightly wonders what's wrong with their
computer. So every background command goes through here: no console at all
(CREATE_NO_WINDOW), and should one be created anyway, it starts hidden.
Elsewhere these are plain subprocess calls.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def hidden(kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
    """`kwargs` plus what keeps the child's window hidden on Windows."""
    kw = dict(kwargs or {})
    if sys.platform != "win32":
        return kw
    flags = kw.get("creationflags", 0)
    # DETACHED_PROCESS / CREATE_NEW_CONSOLE make Windows ignore CREATE_NO_WINDOW;
    # only callers starting a GUI program (pythonw) pass those.
    if not flags & (0x00000008 | 0x00000010):
        flags |= CREATE_NO_WINDOW
    kw["creationflags"] = flags
    if "startupinfo" not in kw:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0                        # SW_HIDE
        kw["startupinfo"] = si
    return kw


def run(cmd, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, **hidden(kwargs))


def popen(cmd, **kwargs) -> subprocess.Popen:
    return subprocess.Popen(cmd, **hidden(kwargs))
