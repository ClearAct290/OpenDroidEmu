"""One running emulator: starts the stock emulator, watches adb for boot / recovery,
sends key events for the sidebar and syncs the shared folder."""
from __future__ import annotations

import subprocess
import threading
import time

from PyQt5.QtCore import QObject, pyqtSignal

from . import instances, sdk, system
from .instances import Instance

SHARED_DEVICE_DIR = "/sdcard/ODE_Shared"

KEYS = {"vol_up": 24, "vol_down": 25, "home": 3, "back": 4, "tasks": 187, "power": 26}


class Session(QObject):
    # starting | booting | booted | recovery | stopped
    state = pyqtSignal(str)
    message = pyqtSignal(bool, str)        # (ok, text) - result of a sync etc.

    def __init__(self, inst: Instance, recovery: bool = False):
        super().__init__()
        self.inst = inst
        self.want_recovery = recovery
        self.port = 0
        self.proc = None
        self.current = "starting"
        self._stop = threading.Event()
        self._thread = None
        self._reboot_sent = False

    # ------------------------------------------------------------------ props
    @property
    def serial(self) -> str:
        return f"emulator-{self.port}"

    @property
    def window_title_part(self) -> str:
        return f"Android Emulator - {self.inst.avd_id}:{self.port}"

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    # ------------------------------------------------------------------ start / stop
    def start(self) -> None:
        inst = self.inst
        instances.write_avd(inst)                      # (re)create AVD files if they went missing
        self.port = system.free_emulator_port()
        args = instances.emulator_args(inst, self.port, self.want_recovery)
        inst.root.mkdir(parents=True, exist_ok=True)
        log = open(inst.log_path, "ab")
        log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')}  {' '.join(args)}\n".encode("utf-8", "replace"))
        log.flush()
        kwargs = {}
        if system.IS_WIN:
            kwargs["creationflags"] = system.hidden_flags()
        else:
            kwargs["start_new_session"] = True
        self.proc = subprocess.Popen(args, env=instances.emulator_env(inst), cwd=str(sdk.emulator_exe().parent),
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **kwargs)
        self._set("starting")
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def kill(self) -> None:
        """Force close: kill the emulator and everything it spawned."""
        self._stop.set()
        if self.proc is not None:
            system.kill_tree(self.proc.pid)

    # ------------------------------------------------------------------ adb
    def adb(self, *args, timeout: float = 20, serial: bool = True):
        cmd = [str(sdk.adb_exe())]
        if serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        try:
            r = system.run_hidden(cmd, timeout=timeout)
            return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
        except Exception as exc:                       # noqa: BLE001 - timeout / missing adb
            return 1, "", str(exc)

    def _set(self, st: str) -> None:
        if st != self.current:
            self.current = st
            self.state.emit(st)

    def _watch(self) -> None:
        self.adb("start-server", serial=False, timeout=30)
        while not self._stop.is_set():
            if self.proc.poll() is not None:
                break
            code, out, _err = self.adb("get-state", timeout=10)
            st = out.splitlines()[-1].strip() if (code == 0 and out) else ""
            if st == "recovery":
                self._set("recovery")
            elif st == "device":
                code, out, _err = self.adb("shell", "getprop", "sys.boot_completed", timeout=10)
                if code == 0 and out.strip().endswith("1"):
                    if self.want_recovery and not self._reboot_sent and not self._has_recovery_ramdisk():
                        # no dedicated recovery ramdisk in this image: boot, then reboot into recovery
                        self._reboot_sent = True
                        self.adb("reboot", "recovery", timeout=15)
                        self._set("booting")
                    elif not (self.want_recovery and self._reboot_sent and self.current != "recovery"):
                        self._set("booted")
                elif self.current == "starting":
                    self._set("booting")
            elif st in ("offline", "bootloader", "unauthorized") and self.current == "starting":
                self._set("booting")
            if self._stop.wait(1.5 if self.current in ("starting", "booting") else 2.5):
                break
        if self.proc is not None:
            try:
                self.proc.wait(timeout=5)
            except Exception:                          # noqa: BLE001
                pass
        self._set("stopped")

    def _has_recovery_ramdisk(self) -> bool:
        return instances.recovery_ramdisk(self.inst) is not None

    # ------------------------------------------------------------------ sidebar actions
    def _bg(self, fn) -> None:
        threading.Thread(target=fn, daemon=True).start()

    def press(self, name: str) -> None:
        code = KEYS.get(name)
        if code is None or self.current != "booted":
            return
        self._bg(lambda: self.adb("shell", "input", "keyevent", str(code), timeout=15))

    # ------------------------------------------------------------------ shared folder
    def push_shared(self) -> None:
        """Host folder -> /sdcard/ODE_Shared on the device."""
        folder = self.inst.shared_dir

        def work():
            if not folder:
                self.message.emit(False, "This instance has no shared folder.")
                return
            self.adb("shell", "mkdir", "-p", SHARED_DEVICE_DIR, timeout=15)
            code, out, err = self.adb("push", folder.rstrip("\\/") + "/.", SHARED_DEVICE_DIR, timeout=3600)
            self.message.emit(code == 0, "Sent the shared folder to the device (" + SHARED_DEVICE_DIR + ")."
                              if code == 0 else f"Sending failed: {err or out}")
        self._bg(work)

    def pull_shared(self) -> None:
        """/sdcard/ODE_Shared on the device -> host folder."""
        folder = self.inst.shared_dir

        def work():
            if not folder:
                self.message.emit(False, "This instance has no shared folder.")
                return
            code, out, err = self.adb("pull", SHARED_DEVICE_DIR + "/.", folder, timeout=3600)
            self.message.emit(code == 0, "Copied files from the device into the shared folder."
                              if code == 0 else f"Getting files failed: {err or out}")
        self._bg(work)
