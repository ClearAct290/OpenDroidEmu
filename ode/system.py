"""Host-system helpers: CPU/RAM, graphics API detection, free ports, window lookup."""
from __future__ import annotations

import ctypes
import os
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

if IS_WIN:
    from ctypes import wintypes


def hidden_flags() -> int:
    """Keep helper processes from flashing console windows on Windows."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WIN else 0


def run_hidden(args, timeout=None, env=None, cwd=None):
    return subprocess.run(args, capture_output=True, text=True, errors="replace",
                          timeout=timeout, env=env, cwd=cwd, creationflags=hidden_flags())


# --------------------------------------------------------------------- CPU / RAM
def host_cpus() -> int:
    return os.cpu_count() or 2


def max_cores() -> int:
    """Host logical CPUs minus 2 (always at least 1)."""
    return max(1, host_cpus() - 2)


class _MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]


def total_ram_mb() -> int:
    try:
        if IS_WIN:
            st = _MemStatus()
            st.dwLength = ctypes.sizeof(st)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return int(st.ullTotalPhys // (1024 * 1024))
        if IS_MAC:
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout
            return int(out.strip()) // (1024 * 1024)
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024)
    except Exception:
        return 8192


def max_ram_mb() -> int:
    """Half of the host's RAM."""
    return max(512, total_ram_mb() // 2)


def free_mb(path) -> int:
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return int(shutil.disk_usage(p).free // (1024 * 1024))
    except OSError:
        return 0


# ----------------------------------------------------------------- graphics APIs
def _com_release(ptr) -> None:
    if not ptr.value:
        return
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    release_addr = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[2]
    ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(release_addr)(ptr)


def _check_dx():
    if not IS_WIN:
        return False, "DirectX is only available on Windows."
    try:
        fn = ctypes.WinDLL("d3d11").D3D11CreateDevice
        fn.restype = ctypes.c_long
        dev, ctx, level = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_uint()
        # (adapter, HARDWARE, software, flags, levels*, nlevels, SDK 7, &dev, &level, &ctx)
        hr = fn(None, 1, None, 0, None, 0, 7, ctypes.byref(dev), ctypes.byref(level), ctypes.byref(ctx))
        if hr == 0:
            _com_release(dev)
            _com_release(ctx)
            return True, "Direct3D 11 hardware device available."
        return False, "No Direct3D 11 capable GPU or driver was found."
    except Exception as exc:
        return False, f"Direct3D could not be initialised ({exc})."


def _check_gl():
    try:
        if IS_WIN:
            ctypes.WinDLL("opengl32")
        elif not IS_MAC:
            import ctypes.util
            if not ctypes.util.find_library("GL"):
                return False, "libGL was not found."
        return True, "OpenGL is available."
    except Exception as exc:
        return False, f"OpenGL could not be loaded ({exc})."


def _check_vk():
    try:
        if IS_WIN:
            ctypes.WinDLL("vulkan-1")
        elif IS_MAC:
            return False, "The stock emulator does not use Vulkan on macOS."
        else:
            ctypes.CDLL("libvulkan.so.1")
        return True, "Vulkan runtime found."
    except OSError:
        return False, "No Vulkan runtime found - update your GPU driver."


_GFX_CACHE: dict = {}


def detect_graphics() -> dict:
    """{'dx'|'gl'|'vk': (supported, message)} - computed once."""
    if not _GFX_CACHE:
        _GFX_CACHE.update({"dx": _check_dx(), "gl": _check_gl(), "vk": _check_vk()})
    return _GFX_CACHE


# ----------------------------------------------------------------- ports / windows
def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def free_emulator_port() -> int:
    """An even console port; adb uses port+1."""
    for port in range(5554, 5586, 2):
        if _port_free(port) and _port_free(port + 1):
            return port
    return 5554


def find_window_rect(title_part: str):
    """(left, top, right, bottom) in physical pixels of the first visible window whose
    title contains title_part (Windows only), else None."""
    if not IS_WIN:
        return None
    try:
        user32 = ctypes.windll.user32
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        found = []

        def callback(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    if title_part in buf.value:
                        r = wintypes.RECT()
                        if user32.GetWindowRect(hwnd, ctypes.byref(r)):
                            found.append((r.left, r.top, r.right, r.bottom))
                            return False
            return True

        proc = enum_proc(callback)
        user32.EnumWindows(proc, 0)
        return found[0] if found else None
    except Exception:
        return None


def kill_tree(pid: int) -> None:
    """Kill a process and everything it spawned (emulator.exe -> qemu-system-*.exe)."""
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, creationflags=hidden_flags())
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except Exception:
                os.kill(pid, signal.SIGKILL)
    except Exception:
        pass
