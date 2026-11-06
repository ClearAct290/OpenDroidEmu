"""Keeps adb from lingering once no instance is running.

A stray adb.exe left behind (ODE crashed, was killed, or the machine lost power) can keep its old server state
and get in the way of a later launch, of a platform-tools update, or of simply reopening ODE. ODE tracks how many
emulator sessions are currently alive; when that count drops to zero it shuts adb down. A lock serializes every
kill against every "start the adb server" call, so a kill issued as the last session ends can never land on an
adb server that a brand-new session just started.
"""
from __future__ import annotations

import threading

from . import sdk, system

_lock = threading.RLock()
_running = 0                        # number of emulator sessions currently alive


def _run(args, timeout):
    try:
        return system.run_hidden(args, timeout=timeout)
    except Exception:              # noqa: BLE001 - adb missing / unresponsive: nothing more to do
        return None


def _kill_adb() -> None:
    exe = sdk.adb_exe()
    if not exe.exists():
        return                                     # core not installed: no adb of ours can be running
    _run([str(exe), "kill-server"], 8)             # the polite way first
    system.kill_tree_by_name("adb.exe" if system.IS_WIN else "adb")  # in case kill-server itself is stuck


def session_started() -> None:
    """Call right before an emulator process is launched (not merely requested)."""
    global _running
    with _lock:
        _running += 1


def session_ended() -> None:
    """Call once a started session's emulator process has actually stopped."""
    global _running
    with _lock:
        _running = max(0, _running - 1)
        if _running == 0:
            _kill_adb()


def kill_now() -> None:
    """Kill adb unconditionally (ODE is closing: every emulator was killed just before)."""
    with _lock:
        _kill_adb()


def start_server(timeout: float = 30):
    """Start the adb server, holding the same lock a kill uses, so the two can't interleave."""
    with _lock:
        exe = sdk.adb_exe()
        if not exe.exists():
            return 1, "", "adb not found"
        r = _run([str(exe), "start-server"], timeout)
        if r is None:
            return 1, "", "adb start-server failed"
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def kill_if_idle() -> None:
    """Startup / safety net: if ODE doesn't think any instance is running, make sure adb really isn't either."""
    with _lock:
        if _running == 0:
            _kill_adb()
