"""Helpers to run `mygeeky pipeline` (learn + run) automatically once a week.

myGeeKy never registers a scheduled task by itself. `mygeeky schedule show`
always just prints the exact command for your platform; `mygeeky schedule
install` only registers it if you pass `--yes`, since creating a recurring
OS-level task is the kind of change that should be an explicit, visible
choice you make, not something a library does quietly on your behalf.
"""

from __future__ import annotations

import platform
import subprocess
import sys

TASK_NAME = "myGeeKyWeeklyRun"


def _python_and_module() -> tuple[str, str]:
    return sys.executable, "mygeeky.cli"


def windows_command() -> str:
    python, _ = _python_and_module()
    return (
        f'schtasks /Create /SC WEEKLY /D MON /ST 09:00 /TN "{TASK_NAME}" '
        f'/TR "\\"{python}\\" -m mygeeky pipeline" /F'
    )


def cron_line() -> str:
    python, _ = _python_and_module()
    return f"0 9 * * 1 {python} -m mygeeky pipeline >> ~/.local/share/mygeeky/logs/weekly.log 2>&1"


def describe() -> str:
    system = platform.system()
    if system == "Windows":
        return (
            "Windows Task Scheduler (runs every Monday at 09:00):\n\n"
            f"  {windows_command()}\n\n"
            "Run that in an elevated PowerShell/cmd yourself, or re-run this command with\n"
            "`mygeeky schedule install --yes` to have myGeeKy run it for you."
        )
    return (
        "cron (runs every Monday at 09:00) -- add this line via `crontab -e`:\n\n"
        f"  {cron_line()}\n\n"
        "Or re-run this command with `mygeeky schedule install --yes` to have myGeeKy\n"
        "append it to your crontab for you."
    )


def install(confirmed: bool) -> str:
    if not confirmed:
        return describe() + "\n\n(Nothing was installed -- pass --yes to actually install it.)"

    system = platform.system()
    if system == "Windows":
        cmd = windows_command()
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            return f"Failed to create scheduled task:\n{result.stderr or result.stdout}"
        return f"Scheduled task '{TASK_NAME}' created. It will run `mygeeky pipeline` every Monday at 09:00."

    line = cron_line()
    result = subprocess.run("crontab -l", shell=True, capture_output=True, text=True)
    existing = result.stdout if result.returncode == 0 else ""
    if line in existing:
        return "That cron entry already exists -- nothing to do."
    new_crontab = existing.rstrip("\n") + f"\n{line}\n"
    proc = subprocess.run("crontab -", shell=True, input=new_crontab, capture_output=True, text=True)
    if proc.returncode != 0:
        return f"Failed to update crontab:\n{proc.stderr}"
    return f"Added to your crontab. myGeeKy will run `mygeeky pipeline` every Monday at 09:00.\n  {line}"


def remove() -> str:
    system = platform.system()
    if system == "Windows":
        result = subprocess.run(f'schtasks /Delete /TN "{TASK_NAME}" /F', shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            return f"Could not remove scheduled task (maybe it wasn't installed):\n{result.stderr or result.stdout}"
        return f"Scheduled task '{TASK_NAME}' removed."

    line = cron_line()
    result = subprocess.run("crontab -l", shell=True, capture_output=True, text=True)
    existing = result.stdout if result.returncode == 0 else ""
    if line not in existing:
        return "No matching cron entry found -- nothing to do."
    new_crontab = "\n".join(l for l in existing.splitlines() if l != line) + "\n"
    proc = subprocess.run("crontab -", shell=True, input=new_crontab, capture_output=True, text=True)
    if proc.returncode != 0:
        return f"Failed to update crontab:\n{proc.stderr}"
    return "Removed myGeeKy's cron entry."
