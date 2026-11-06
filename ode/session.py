"""One running emulator: starts the stock emulator and watches adb for boot / recovery."""
from __future__ import annotations

import subprocess
import threading
import time

from PyQt5.QtCore import QObject, pyqtSignal

from . import adbctl, instances, sdk, system
from .instances import Instance


class Session(QObject):
    # starting | booting | booted | recovery | stopped
    state = pyqtSignal(str)

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
        self._counted = False                          # reported to adbctl as a running instance

    # ------------------------------------------------------------------ props
    @property
    def serial(self) -> str:
        return f"emulator-{self.port}"

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
        adbctl.session_started()                       # from now on adb must not be shut down
        self._counted = True
        try:
            self.proc = subprocess.Popen(args, env=instances.emulator_env(inst), cwd=str(sdk.emulator_exe().parent),
                                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **kwargs)
        except Exception:
            self._release()
            raise
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
        try:
            self._watch_loop()
        finally:
            self._release()                            # even if the watcher dies, adb must not stay "in use"

    def _watch_loop(self) -> None:
        adbctl.start_server(30)                        # never at the same moment as an adb kill
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

    def _release(self) -> None:
        """This emulator is gone: tell adbctl (the last one out shuts adb down)."""
        if self._counted:
            self._counted = False
            adbctl.session_ended()

    def _has_recovery_ramdisk(self) -> bool:
        return instances.recovery_ramdisk(self.inst) is not None
