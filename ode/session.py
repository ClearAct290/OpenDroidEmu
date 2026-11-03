"""One running emulator: starts the stock emulator, watches adb for boot / recovery
and copies files between the PC's shared folder and the device."""
from __future__ import annotations

import re
import subprocess
import threading
import time
from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSignal

from . import instances, sdk, system
from .instances import Instance

SHARED_DEVICE_DIR = "/sdcard/ODE_Shared"
DOWNLOADS_DEVICE_DIR = "/sdcard/Download"
_OK = "ODE_OK"                                    # printed by our device-side shell commands on success
_SKIP = {"desktop.ini", "thumbs.db", ".ds_store"}  # host junk that isn't worth copying to Android


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

    # ------------------------------------------------------------------ shared folder
    # ODE copies files with ADB (the stock emulator has no live shared folders). Everything below runs
    # in a worker thread and reports through the `message` signal.
    def _bg(self, fn) -> None:
        threading.Thread(target=fn, daemon=True).start()

    def _shell_ok(self, command: str, timeout: float = 20):
        """Run a command on the device; (True, "") only if it succeeded."""
        code, out, err = self.adb("shell", f"{command} && echo {_OK}", timeout=timeout)
        return (_OK in out), (err or out.replace(_OK, "").strip())

    def _ensure_device_dir(self, path: str, wait: float = 45) -> str:
        """Create the folder on the device and return "" - or an error text. Right after boot the
        storage (/sdcard) can take a moment to appear, so this retries for up to `wait` seconds."""
        end = time.time() + wait
        while True:
            ok, why = self._shell_ok(f"mkdir -p '{path}'")
            if ok:
                return ""
            if time.time() >= end or self._stop.is_set() or not self.running:
                return why or "The device storage isn't ready yet."
            time.sleep(2)

    def push_shared(self) -> None:
        """PC shared folder -> /sdcard/ODE_Shared on the device."""
        self._bg(self._do_push)

    def pull_shared(self) -> None:
        """/sdcard/ODE_Shared on the device -> PC shared folder."""
        self._bg(lambda: self._do_pull(SHARED_DEVICE_DIR, "", "ODE_Shared"))

    def pull_downloads(self) -> None:
        """Android's Download folder -> <shared folder>/Download on the PC."""
        self._bg(lambda: self._do_pull(DOWNLOADS_DEVICE_DIR, "Download", "Download"))

    def _host_folder(self):
        folder = self.inst.shared_dir
        if not folder:
            self.message.emit(False, "This instance has no shared folder. Add one in the instance's Settings.")
            return None
        host = Path(folder)
        if not host.is_dir():
            self.message.emit(False, f"The shared folder doesn't exist on this PC:\n{folder}\n\n"
                                     "Create it again or pick another one in the instance's Settings.")
            return None
        return host

    def _do_push(self) -> None:
        host = self._host_folder()
        if host is None:
            return
        items = [p for p in sorted(host.iterdir(), key=lambda p: p.name.lower()) if p.name.lower() not in _SKIP]
        if not items:
            self.message.emit(False, f"The shared folder on your PC is empty - there is nothing to send.\n\n{host}")
            return
        err = self._ensure_device_dir(SHARED_DEVICE_DIR)
        if err:
            self.message.emit(False, f"Couldn't create {SHARED_DEVICE_DIR} on the device:\n{err}")
            return
        sent, errors = 0, []
        for item in items:                              # one by one: no trouble with Windows paths
            code, out, e = self.adb("push", str(item), SHARED_DEVICE_DIR + "/", timeout=3600)
            if code == 0:
                sent += 1
            else:
                errors.append(f"{item.name}: {e or out}")
        if not errors:
            self.message.emit(True, f"Sent {sent} item(s) to {SHARED_DEVICE_DIR} on the device.\n\n"
                                    "In Android, open the Files app and look for the ODE_Shared folder.")
        else:
            self.message.emit(False, f"Sent {sent} of {len(items)} item(s).\n\nFailed:\n" + "\n".join(errors[:4]))

    def _do_pull(self, src: str, subfolder: str, label: str) -> None:
        host = self._host_folder()
        if host is None:
            return
        if src == SHARED_DEVICE_DIR:                    # our own folder: create it so pulling never fails
            err = self._ensure_device_dir(src)
            if err:
                self.message.emit(False, f"Couldn't reach {src} on the device:\n{err}")
                return
        else:
            ok, _why = self._shell_ok(f"test -d '{src}'")
            if not ok:
                self.message.emit(True, f"Android has no {label} folder yet - nothing to get.")
                return
        dest = host / subfolder if subfolder else host
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.message.emit(False, f"Couldn't use the folder on your PC:\n{exc}")
            return
        code, out, err = self.adb("pull", src + "/.", str(dest), timeout=3600)
        text = (out + "\n" + err)
        m = re.search(r"(\d+) files? pulled", text)
        count = int(m.group(1)) if m else None
        if code != 0:
            self.message.emit(False, f"Getting files failed:\n{(err or out).strip()}")
        elif count == 0:
            self.message.emit(True, f"The {label} folder on the device is empty - nothing to copy."
                              + ("\n\nPut files into the ODE_Shared folder in Android's Files app first."
                                 if src == SHARED_DEVICE_DIR else ""))
        else:
            self.message.emit(True, (f"Copied {count} file(s) " if count else "Copied the files ")
                              + f"from {src} on the device into:\n{dest}")
