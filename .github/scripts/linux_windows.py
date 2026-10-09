"""Open myGeeKy's setup and uninstall windows on a (virtual) Linux screen and save
a picture of each page, to check they work and look right on Linux.

    xvfb-run -a <myGeeKy's python> .github/scripts/linux_windows.py <out-dir>

Nothing is installed, signed in or uninstalled: the pages are only shown.
"""

import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

out = Path(sys.argv[1] if len(sys.argv) > 1 else "linux-windows")
out.mkdir(parents=True, exist_ok=True)
app = QApplication(sys.argv)


def pump(seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.03)


from mygeeky.gui import setup_wizard as sw  # noqa: E402
from mygeeky.gui import uninstall_wizard as uw  # noqa: E402

assert not sw.WINDOWS, "this check is for Linux"
wiz = sw.SetupWizard()
wiz.show()
pump(4)                                                     # the welcome page checks this computer
wiz.grab().save(str(out / "setup-1-welcome.png"))
welcome = wiz.page(0).found.text()
print("welcome says:", welcome)
names = {3: "setup-2-github", 4: "setup-3-sync", 6: "setup-4-finish"}
wiz.state = {"github_username": "octocat", "configured": False}
for page_id, name in names.items():
    wiz.setStartId(page_id)
    wiz.restart()
    pump(1.5)
    wiz.grab().save(str(out / f"{name}.png"))
finish = wiz.page(6)
labels = [finish.start_menu.text(), finish.startup.text(), finish.weekly.text()]
print("finish page:", labels)
assert "applications menu" in labels[0] and "log in" in labels[1] and "cron" in labels[2], labels
assert not finish.desktop.isVisible(), "the Windows desktop-shortcut option should be hidden on Linux"
wiz.close()

un = uw.UninstallWizard()
un.show()
pump(1.5)
un.grab().save(str(out / "uninstall-1-intro.png"))
un.next()
pump(1)
un.grab().save(str(out / "uninstall-2-choose.png"))
print("uninstall options:", sorted(un.choose.boxes))
un.close()
print("windows OK")
