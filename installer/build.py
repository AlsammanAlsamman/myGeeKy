"""Build MyGeeKySetup.exe: the setup wizard plus the current myGeeKy wheel.

    python installer/build.py          ->  dist/MyGeeKySetup-<version>.exe

Needs `pip install pyinstaller build`. The .exe carries only PySide6's core
Qt modules and the wheel; it installs that wheel into the user's own
Python, so the app itself is never frozen.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "build" / "installer"
ASSETS = ROOT / "src" / "mygeeky" / "gui" / "assets"


def main() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from mygeeky import __version__

    shutil.rmtree(WORK, ignore_errors=True)
    payload = WORK / "payload"
    payload.mkdir(parents=True)
    subprocess.run([sys.executable, "-m", "build", "--wheel", "--outdir", str(payload), str(ROOT)], check=True)
    wheels = list(payload.glob(f"mygeeky-{__version__}-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected one mygeeky {__version__} wheel, found {wheels}")

    name = f"MyGeeKySetup-{__version__}"
    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", name, "--icon", str(ASSETS / "icon.ico"),
        "--distpath", str(ROOT / "dist"), "--workpath", str(WORK / "pyi"), "--specpath", str(WORK),
        "--paths", str(ROOT / "src"),
        "--add-data", f"{payload}{sep}payload",
        "--add-data", f"{ASSETS / 'icon_128.png'}{sep}assets",
        "--add-data", f"{ASSETS / 'icon_64.png'}{sep}assets",
        # the wizard needs only these three Qt modules; leave the rest of PySide6 out
        "--exclude-module", "PySide6.QtNetwork", "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "PySide6.QtQuick", "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtMultimedia", "--exclude-module", "PySide6.QtPdf",
        "--exclude-module", "PySide6.Qt3DCore", "--exclude-module", "PySide6.QtCharts",
        "--exclude-module", "sklearn", "--exclude-module", "numpy", "--exclude-module", "scipy",
        "--exclude-module", "tkinter",
        str(Path(__file__).parent / "setup_entry.py"),
    ]
    subprocess.run(cmd, check=True)
    exe = ROOT / "dist" / f"{name}.exe"
    report = WORK / "selftest.json"
    subprocess.run([str(exe), "--selftest", str(report)], check=True, timeout=120)
    print("selftest:", report.read_text(encoding="utf-8"))
    print(f"\nBuilt {exe} ({exe.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
