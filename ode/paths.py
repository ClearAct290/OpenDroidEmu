"""Filesystem locations. Works from source and from a PyInstaller (onedir) build."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def resource_dir() -> Path:
    """Where bundled read-only resources (assets/) live."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """Folder that contains the program (the .exe when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".ode_write_test"
        probe.write_text("x")
        probe.unlink()
        return True
    except OSError:
        return False


def _pick_base() -> Path:
    """Portable by default (core/ sits next to the program). If that folder is
    read-only (e.g. Program Files) fall back to the user's profile."""
    here = app_dir()
    if _writable(here):
        return here
    if sys.platform.startswith("win"):
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    alt = root / "OpenDroidEmu"
    alt.mkdir(parents=True, exist_ok=True)
    return alt


BASE_DIR = _pick_base()
CORE_DIR = BASE_DIR / "core"                    # emulator + platform-tools + system images
DOWNLOAD_DIR = CORE_DIR / "_downloads"
EXTRACT_DIR = CORE_DIR / "_extract"
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
INSTANCES_DIR = BASE_DIR / "instances"          # default place for instance files
SETTINGS_FILE = DATA_DIR / "settings.json"
INSTANCES_FILE = DATA_DIR / "instances.json"
ASSETS_DIR = resource_dir() / "assets"

for _d in (CORE_DIR, DATA_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def asset(name: str) -> str:
    return str(ASSETS_DIR / name)
