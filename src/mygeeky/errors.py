"""Turning unexpected failures into messages people can act on, plus a saved
crash report with the full details.

Standard library only: the frozen installer imports this too.

The classic offender is Windows' bare "[WinError 2] The system cannot find the
file specified", which never says *what* wasn't found. When it comes from
starting a program, the program is still in the traceback (subprocess's
`args`), so we name it.
"""

from __future__ import annotations

import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path

ISSUES_URL = "https://github.com/AlsammanAlsamman/myGeeKy/issues"

PROGRAM_HINTS = {
    "git": "git isn't installed (or isn't on PATH). Install it from https://git-scm.com/download/win and try again.",
    "gh": "the GitHub CLI (gh) isn't installed. Install it from https://cli.github.com, or skip this step.",
    "winget": "winget (Windows' app installer) isn't on this PC.",
    "powershell": "PowerShell isn't available on this PC.",
    "schtasks": "Windows Task Scheduler (schtasks) isn't available on this PC.",
}


def failed_program(exc: BaseException) -> str | None:
    """The program a failed subprocess launch tried to start, if that's what this is."""
    tb = exc.__traceback__
    while tb is not None:
        frame = tb.tb_frame
        if frame.f_code.co_name in ("_execute_child", "__init__") and "subprocess" in frame.f_code.co_filename:
            args = frame.f_locals.get("args")
            if isinstance(args, (list, tuple)) and args:
                return str(args[0])
            if isinstance(args, str) and args:
                return args.split()[0]
        tb = tb.tb_next
    return None


def describe(exc: BaseException) -> str:
    """One sentence that says what went wrong, naming the file or program."""
    if isinstance(exc, FileNotFoundError):
        if exc.filename:
            return f"A file myGeeKy needed wasn't found: {exc.filename}"
        program = failed_program(exc)
        if program:
            name = Path(program).stem.lower()
            hint = PROGRAM_HINTS.get(name, f"'{program}' isn't installed or isn't on PATH.")
            return f"Couldn't start {Path(program).name}: {hint}"
        return f"Something myGeeKy needed wasn't found ({exc})."
    if isinstance(exc, PermissionError):
        where = f": {exc.filename}" if exc.filename else ""
        return f"Windows didn't allow access{where}. Close other myGeeKy windows and try again."
    if type(exc).__name__ in ("ConnectionError", "Timeout", "ConnectTimeout", "ReadTimeout", "SSLError"):
        return "Couldn't reach the internet (GitHub or PyPI). Check your connection and try again."
    if isinstance(exc, OSError):
        where = f" ({exc.filename})" if exc.filename else ""
        return f"{exc.strerror or exc}{where}"
    return f"{type(exc).__name__}: {exc}"


def save_crash_report(exc: BaseException, folder: Path, where: str) -> Path | None:
    """Write the full traceback and some context to `folder`; None if even that fails."""
    try:
        from . import __version__
    except ImportError:
        __version__ = "?"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"error-{datetime.now():%Y%m%d-%H%M%S}.txt"
        path.write_text(
            f"myGeeKy {__version__} ({where})\n"
            f"Python {sys.version.split()[0]} at {sys.executable}\n"
            f"{platform.platform()}\n"
            f"Command: {' '.join(sys.argv)}\n\n"
            f"What went wrong: {describe(exc)}\n\n"
            + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            encoding="utf-8")
        return path
    except OSError:
        return None


def show_message_box(title: str, text: str) -> None:
    """A native message box without Qt (works even if Qt itself is what failed)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)   # MB_ICONERROR
            return
        except Exception:
            pass
    print(f"{title}: {text}", file=sys.stderr)
