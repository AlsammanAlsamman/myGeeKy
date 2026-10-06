"""PyInstaller entry point for MyGeeKySetup.exe (see build.py)."""
import sys

from mygeeky.gui.setup_wizard import main

sys.exit(main())
