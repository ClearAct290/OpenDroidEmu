"""Dev Control: a window of ADB tools for one running instance.

It uses the adb that ODE already downloaded with the emulator (core/platform-tools) - nothing extra is
installed. Every action runs as a "job" in a worker thread with its output shown in the console at the bottom;
the pages are greyed out while a job runs and the Stop button ends it. APK files dropped on the window (or on
the instance card) are installed in the background and queued if another job is still running.
"""
from __future__ import annotations

import os
import posixpath
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path

from PyQt5.QtCore import QObject, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QFontDatabase
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                             QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
                             QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout,
                             QWidget)

from . import paths, sdk, system
from .util import app_icon

OUTPUT_ROOT = paths.BASE_DIR / "dev-output"          # screenshots, recordings, logs, saved APKs ... (per instance)

INFO_ROWS = [("title", "Instance"), ("model", "Model"), ("manufacturer", "Manufacturer"), ("device", "Codename"),
             ("android", "Android version"), ("api", "API level"), ("patch", "Security patch"), ("build", "Build"),
             ("abi", "CPU architecture"), ("screen", "Screen"), ("battery", "Battery"), ("ip", "Wi-Fi IP"),
             ("uptime", "Uptime"), ("serial", "ADB serial")]
PROP_OF = {"model": "ro.product.model", "manufacturer": "ro.product.manufacturer", "device": "ro.product.device",
           "android": "ro.build.version.release", "api": "ro.build.version.sdk",
           "patch": "ro.build.version.security_patch", "build": "ro.build.display.id", "abi": "ro.product.cpu.abi"}

KEYS = [("Home", "KEYCODE_HOME"), ("Back", "KEYCODE_BACK"), ("Recent apps", "KEYCODE_APP_SWITCH"),
        ("Power (lock / unlock)", "KEYCODE_POWER"), ("Volume up", "KEYCODE_VOLUME_UP"),
        ("Volume down", "KEYCODE_VOLUME_DOWN"), ("Mute", "KEYCODE_VOLUME_MUTE"), ("Enter", "KEYCODE_ENTER"),
        ("Backspace", "KEYCODE_DEL"), ("Menu", "KEYCODE_MENU"), ("Play / pause media", "KEYCODE_MEDIA_PLAY_PAUSE"),
        ("Next track", "KEYCODE_MEDIA_NEXT"), ("Previous track", "KEYCODE_MEDIA_PREVIOUS"),
        ("Camera button", "KEYCODE_CAMERA"), ("Open notification shade", "CMD:statusbar expand-notifications"),
        ("Open quick settings", "CMD:statusbar expand-settings"), ("Close shade", "CMD:statusbar collapse")]

COMMON_PERMISSIONS = ["CAMERA", "RECORD_AUDIO", "ACCESS_FINE_LOCATION", "READ_CONTACTS", "READ_EXTERNAL_STORAGE",
                      "WRITE_EXTERNAL_STORAGE", "POST_NOTIFICATIONS", "READ_PHONE_STATE", "READ_SMS"]
SETTINGS_SCREENS = [("Main settings", "android.settings.SETTINGS"), ("Wi-Fi", "android.settings.WIFI_SETTINGS"),
                    ("Bluetooth", "android.settings.BLUETOOTH_SETTINGS"), ("Display", "android.settings.DISPLAY_SETTINGS"),
                    ("Apps", "android.settings.APPLICATION_SETTINGS"),
                    ("Location", "android.settings.LOCATION_SOURCE_SETTINGS"),
                    ("Developer options", "android.settings.APPLICATION_DEVELOPMENT_SETTINGS"),
                    ("Accessibility", "android.settings.ACCESSIBILITY_SETTINGS"),
                    ("Date & time", "android.settings.DATE_SETTINGS"), ("Security", "android.settings.SECURITY_SETTINGS")]
APP_ACTIONS = [("launch", "Open (launch) the app"), ("launcher", "Set as default launcher / home app"),
               ("stop", "Force stop"), ("clear", "Clear data & cache"), ("toggle", "Disable / enable"),
               ("perm", "Grant / revoke a permission"), ("details", "Show app details & permissions"),
               ("pull", "Save the APK to this PC"), ("settings", "Open its settings page on the device"),
               ("uninstall", "Uninstall")]
LOG_MODES = ["Watch the live log (press Stop to end)", "Save the current log to a file", "Clear the log"]
LOG_LEVELS = ["Verbose (everything)", "Debug", "Info", "Warning", "Error only"]
INSTALL_HINTS = [
    ("INSTALL_FAILED_NO_MATCHING_ABIS", "This app has no build for this instance's CPU type. Use an instance "
     "made with an \"+ ARM apps\" architecture for ARM-only apps."),
    ("INSTALL_FAILED_VERSION_DOWNGRADE", "A newer version is already installed - tick \"Allow a version "
     "downgrade\" to replace it."),
    ("INSTALL_FAILED_UPDATE_INCOMPATIBLE", "The installed copy was signed with a different key - uninstall it first."),
    ("INSTALL_FAILED_OLDER_SDK", "This app needs a newer Android version than this instance runs."),
    ("INSTALL_FAILED_ALREADY_EXISTS", "It is already installed - tick \"Replace the app if it is already installed\"."),
    ("INSTALL_FAILED_INSUFFICIENT_STORAGE", "Android is out of storage space."),
    ("INSTALL_PARSE_FAILED_NOT_APK", "That file isn't an APK. For several files of one app use \"Install split APKs\"."),
    ("INSTALL_FAILED_MISSING_SPLIT", "This app comes in several parts - use \"Install split APKs\" and pick all of them."),
]


def safe_name(text: str) -> str:
    return re.sub(r"[^\w.-]+", "_", text).strip("_") or "instance"


# ============================================================================ small dialogs
def field(key, label, kind="text", default=None, options=None):
    """One input of ask_form. kind: text | int (options = (min, max)) | check | choice | combo (editable)."""
    return (key, label, kind, default, options)


def ask_form(parent, title, fields, intro="", ok_text="OK"):
    """A small dialog built from field() tuples. Returns {key: value} or None when cancelled."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    dlg.setMinimumWidth(440)
    lay = QVBoxLayout(dlg)
    if intro:
        lb = QLabel(intro)
        lb.setWordWrap(True)
        lb.setObjectName("muted")
        lay.addWidget(lb)
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignLeft)
    widgets = {}
    for key, label, kind, default, options in fields:
        if kind == "check":
            w = QCheckBox(label)
            w.setChecked(bool(default))
            form.addRow(w)
        else:
            if kind == "int":
                w = QSpinBox()
                lo, hi = options or (0, 100000)
                w.setRange(lo, hi)
                w.setValue(int(default if default is not None else lo))
            elif kind in ("choice", "combo"):
                w = QComboBox()
                w.addItems(list(options or []))
                if kind == "combo":
                    w.setEditable(True)
                    w.setEditText(str(default or ""))
                elif default in (options or []):
                    w.setCurrentIndex(list(options).index(default))
            else:
                w = QLineEdit(str(default or ""))
            form.addRow(label + ":", w)
        widgets[key] = (kind, w)
    lay.addLayout(form)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.button(QDialogButtonBox.Ok).setText(ok_text)
    box.button(QDialogButtonBox.Ok).setObjectName("primary")
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    if dlg.exec_() != QDialog.Accepted:
        return None
    out = {}
    for key, (kind, w) in widgets.items():
        if kind == "check":
            out[key] = w.isChecked()
        elif kind == "int":
            out[key] = w.value()
        elif kind in ("choice", "combo"):
            out[key] = w.currentText().strip()
        else:
            out[key] = w.text().strip()
    return out


class PackageDialog(QDialog):
    """Pick one app (package name) from a filterable list."""

    def __init__(self, parent, title: str, packages: list):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumSize(460, 480)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Type to filter by name...")
        self.edit.textChanged.connect(self._filter)
        self.list = QListWidget()
        self.list.addItems(packages)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())
        self.count = QLabel(f"{len(packages)} app(s)")
        self.count.setObjectName("muted")
        self.box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.edit)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.count)
        lay.addWidget(self.box)
        self.list.currentItemChanged.connect(lambda *_: self._sync())
        self.list.setCurrentRow(0)
        self._sync()
        self.edit.setFocus()

    def _filter(self, text: str):
        term = text.strip().lower()
        first = None
        shown = 0
        for i in range(self.list.count()):
            item = self.list.item(i)
            hide = term not in item.text().lower()
            item.setHidden(hide)
            if not hide:
                shown += 1
                first = first or item
        self.count.setText(f"{shown} app(s)")
        if first is not None:
            self.list.setCurrentItem(first)
        self._sync()

    def _sync(self):
        item = self.list.currentItem()
        self.box.button(QDialogButtonBox.Ok).setEnabled(item is not None and not item.isHidden())

    def selected(self):
        item = self.list.currentItem()
        return item.text() if item is not None and not item.isHidden() else None

    @staticmethod
    def choose(parent, title: str, packages: list):
        dlg = PackageDialog(parent, title, packages)
        return dlg.selected() if dlg.exec_() == QDialog.Accepted else None


class AppDialog(QDialog):
    """The things you can do with one app; choose() returns the action key or None."""

    def __init__(self, parent, pkg: str):
        super().__init__(parent)
        self.setWindowTitle("App")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(380)
        self.key = None
        lay = QVBoxLayout(self)
        head = QLabel(f"<b>{pkg}</b><br>What do you want to do with this app?")
        head.setWordWrap(True)
        lay.addWidget(head)
        for key, text in APP_ACTIONS:
            b = QPushButton(text.replace("&", "&&"))      # a single & would make a keyboard shortcut
            if key == "uninstall":
                b.setObjectName("dangerBtn")
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            lay.addWidget(b)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        lay.addWidget(cancel)

    def _pick(self, key: str):
        self.key = key
        self.accept()

    @staticmethod
    def choose(parent, pkg: str):
        dlg = AppDialog(parent, pkg)
        return dlg.key if dlg.exec_() == QDialog.Accepted else None


# ============================================================================ jobs
class _Sig(QObject):
    line = pyqtSignal(str)
    done = pyqtSignal(object, object, bool)       # result, error, was stopped


class JobCtx:
    """Handed to a job function (it runs in a worker thread). Wraps adb for this instance."""

    def __init__(self, serial: str, sig: _Sig):
        self.serial = serial
        self._sig = sig
        self._stop = threading.Event()
        self._proc = None
        self._stop_kills = True
        self.on_stop = None             # optional: do this on Stop instead of killing the running adb

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def say(self, text: str) -> None:
        self._sig.line.emit(text)

    def _cmd(self, args) -> list:
        return [str(sdk.adb_exe()), "-s", self.serial] + [str(a) for a in args]

    def _run(self, args, stream=True, timeout=None, out_file=None):
        """Run adb, returns (exit code, output text). Output goes to the console while it arrives if stream."""
        kw = {"creationflags": system.hidden_flags()} if system.IS_WIN else {}
        try:
            if out_file is not None:
                proc = subprocess.Popen(self._cmd(args), stdin=subprocess.DEVNULL, stdout=out_file,
                                        stderr=subprocess.PIPE, **kw)
            else:
                proc = subprocess.Popen(self._cmd(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                        **kw)
        except OSError as exc:
            self.say(f"[-] Couldn't run adb: {exc}")
            return 1, ""
        self._proc = proc
        timer = None
        if timeout:
            timer = threading.Timer(timeout, proc.kill)
            timer.daemon = True
            timer.start()
        if self._stop.is_set() and self._stop_kills:
            proc.kill()
        lines = []
        try:
            if out_file is not None:
                _out, err = proc.communicate()
                lines = (err or b"").decode("utf-8", "replace").strip().splitlines()
            else:
                for raw in proc.stdout:
                    line = raw.rstrip("\r\n")
                    lines.append(line)
                    if stream:
                        self.say(line)
                proc.wait()
        finally:
            if timer is not None:
                timer.cancel()
            self._proc = None
        return proc.returncode, "\n".join(lines).strip()

    def adb(self, *args, stream=True, timeout=None):
        return self._run(args, stream, timeout)

    def shell(self, command: str, stream=True, timeout=None):
        return self._run(["shell", command], stream, timeout)

    def adb_to_file(self, path, *args, timeout=300):
        """adb output (binary, e.g. screencap) straight into a file; returns (exit code, error text)."""
        with open(path, "wb") as f:
            return self._run(args, False, timeout, out_file=f)

    def quick(self, *args, timeout=20):
        """A short side command that doesn't touch the running one (used by on_stop hooks)."""
        try:
            r = system.run_hidden(self._cmd(args), timeout=timeout)
            return r.returncode, (r.stdout or "").strip()
        except Exception as exc:                          # noqa: BLE001
            return 1, str(exc)

    def stop(self) -> None:
        hook = self.on_stop
        self._stop_kills = hook is None
        self._stop.set()
        proc = self._proc
        if hook is not None:
            def run_hook():
                try:
                    hook()
                except Exception:                         # noqa: BLE001
                    pass
                if proc is not None:
                    try:
                        proc.wait(timeout=10)
                    except Exception:                     # noqa: BLE001
                        try:
                            proc.kill()
                        except Exception:                 # noqa: BLE001
                            pass
            threading.Thread(target=run_hook, daemon=True).start()
        elif proc is not None:
            try:
                proc.kill()
            except Exception:                             # noqa: BLE001
                pass


# ============================================================================ the window
class DevControl(QWidget):
    PAGES = ["Device info", "Apps", "Files", "Screen & input", "Display", "Power", "System & logs",
             "Network & ports", "Shell & advanced"]

    def __init__(self, inst, serial: str, parent=None):
        super().__init__(parent, Qt.Window)
        self.inst = inst
        self.serial = serial
        self.out_dir = OUTPUT_ROOT / safe_name(inst.title)
        self._ctx = None
        self._done_cb = None
        self._queue = []                 # jobs waiting for the running one (e.g. APK installs dropped meanwhile)
        self._closing = False
        self._info_loaded = False
        self._files_loaded = False
        self._cwd = "/sdcard"
        self._last_dir = str(Path.home() / "Downloads") if (Path.home() / "Downloads").is_dir() else str(Path.home())
        self._sig = _Sig()
        self._sig.line.connect(self.say)
        self._sig.done.connect(self._finish)
        self.setWindowTitle(f"Dev Control - {inst.title}")
        self.setWindowIcon(app_icon())
        self.setAcceptDrops(True)
        self.resize(940, 680)
        self.setMinimumSize(760, 520)

        # ---- navigation + pages
        self.nav = QListWidget()
        self.nav.setFixedWidth(170)
        self.nav.setStyleSheet("QListWidget::item { padding: 8px 10px; }")
        self.nav.addItems(self.PAGES)
        self.stack = QStackedWidget()
        for build in (self._page_info, self._page_apps, self._page_files, self._page_screen, self._page_display,
                      self._page_power, self._page_system, self._page_network, self._page_shell):
            self.stack.addWidget(build())
        self.nav.currentRowChanged.connect(self._nav_changed)

        # ---- console
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(5000)
        self.console.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.console.setAcceptDrops(False)
        self.console.viewport().setAcceptDrops(False)          # file drops fall through to the window
        self.console.setMinimumHeight(140)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("dangerBtn")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setToolTip("Stop the running command (live log, recording, install...)")
        self.btn_stop.clicked.connect(self.stop_job)
        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self.console.clear)
        btn_out = QPushButton("Open output folder")
        btn_out.setToolTip(f"Screenshots, recordings, logs and saved APKs go to:\n{self.out_dir}")
        btn_out.clicked.connect(self.open_output)
        head = QHBoxLayout()
        title = QLabel("Output")
        title.setStyleSheet("font-weight: 600;")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(btn_out)
        head.addWidget(btn_clear)
        head.addWidget(self.btn_stop)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.nav)
        top.addWidget(self.stack, 1)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        root.addLayout(top, 1)
        root.addLayout(head)
        root.addWidget(self.console)
        self.nav.setCurrentRow(0)
        self.say(f"[*] Dev Control for \"{inst.title}\" ({serial}). Drop .apk files anywhere in this window to install them.")

    # ================================================================== window plumbing
    def say(self, text: str) -> None:
        self.console.appendPlainText(text)

    def show_page(self, name: str) -> None:
        self.nav.setCurrentRow(self.PAGES.index(name))

    def _nav_changed(self, row: int) -> None:
        if row >= 0:
            self.stack.setCurrentIndex(row)
        self._maybe_load_files()

    def _maybe_load_files(self) -> None:
        """List /sdcard the first time the Files page is shown (and nothing else is running)."""
        if (not self._files_loaded and not self.busy and self.nav.currentRow() >= 0
                and self.PAGES[self.nav.currentRow()] == "Files"):
            self._files_loaded = True
            self.files_go(self._cwd)

    def showEvent(self, e):
        super().showEvent(e)
        if not self._info_loaded:
            self._info_loaded = True
            self.load_info()

    def closeEvent(self, e):
        if self._closing:
            e.accept()
        else:
            e.ignore()                   # closing the window only hides it; running jobs keep going
            self.hide()

    def shutdown(self) -> None:
        """The instance stopped (or ODE is closing): end any job and close for good."""
        self._closing = True
        self._queue.clear()
        for sig in (self._sig.line, self._sig.done):
            try:
                sig.disconnect()
            except TypeError:
                pass
        if self._ctx is not None:
            self._ctx.stop()
        self.hide()
        self.deleteLater()

    @property
    def busy(self) -> bool:
        return self._ctx is not None

    def _set_busy(self, busy: bool) -> None:
        self.stack.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)

    # ================================================================== job runner
    def run_job(self, title: str, fn, done=None, quiet: bool = False, queue: bool = False) -> bool:
        """fn(ctx) runs in a worker thread; done(result) is then called on the GUI thread.
        With queue=True a job started while another one runs waits for its turn instead of being refused."""
        if self._closing:
            return False
        if self.busy:
            if queue:
                self._queue.append((title, fn, done, quiet))
                self.say(f"[*] Queued: {title} (starts when the current command finishes)")
                return True
            self.say("[!] A command is still running - wait for it to finish or press Stop.")
            return False
        ctx = JobCtx(self.serial, self._sig)
        self._ctx = ctx
        self._done_cb = done
        self._set_busy(True)
        if not quiet:
            self.say(f"[*] {title}")

        def work():
            try:
                res, err = fn(ctx), None
            except Exception as exc:                      # noqa: BLE001
                res, err = None, exc
            self._sig.done.emit(res, err, ctx.stopped)

        threading.Thread(target=work, daemon=True).start()
        return True

    def _finish(self, result, error, cancelled: bool) -> None:
        self._ctx = None
        self._set_busy(False)
        if error is not None:
            self.say(f"[-] {error}")
        cb, self._done_cb = self._done_cb, None
        if cancelled:
            self.say("[*] Stopped.")
        if cb:
            cb(result)
        if self._queue and not self.busy and not self._closing:
            title, fn, done, quiet = self._queue.pop(0)
            self.run_job(title, fn, done, quiet)
        else:
            self._maybe_load_files()

    def stop_job(self) -> None:
        self._queue.clear()
        if self._ctx is not None:
            self.say("[*] Stopping...")
            self._ctx.stop()

    def shell_adb(self, title: str, *args, queue: bool = False) -> bool:
        """Run `adb <args>` for this instance, output into the console."""
        return self.run_job(title, lambda ctx: ctx.adb(*args), queue=queue)

    def shell_cmd(self, title: str, command: str) -> bool:
        """Run `adb shell <command>` for this instance, output into the console."""
        return self.run_job(title, lambda ctx: ctx.shell(command))

    # ================================================================== small helpers
    def new_out(self, kind: str, ext: str) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        return self.out_dir / f"{kind}_{time.strftime('%Y%m%d_%H%M%S')}.{ext}"

    def open_output(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.out_dir)))

    def _btn(self, text, slot, tip="", danger=False) -> QPushButton:
        b = QPushButton(text.replace("&", "&&"))      # a single & would make a keyboard shortcut
        if danger:
            b.setObjectName("dangerBtn")
        if tip:
            b.setToolTip(tip)
        b.clicked.connect(lambda _=False: slot())
        return b

    def _group(self, title: str, buttons: list, cols: int = 2) -> QGroupBox:
        box = QGroupBox(title)
        grid = QGridLayout(box)
        grid.setSpacing(8)
        for i, b in enumerate(buttons):
            grid.addWidget(b, i // cols, i % cols)
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        return box

    def _scroll_page(self, *items) -> QScrollArea:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(4, 4, 8, 4)
        lay.setSpacing(10)
        for it in items:
            lay.addWidget(it)
        lay.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(host)
        return sc

    @staticmethod
    def _note(text: str) -> QLabel:
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setObjectName("muted")
        return lb

    @staticmethod
    def _screen_size(ctx):
        _code, out = ctx.shell("wm size", stream=False)
        found = re.findall(r"(\d+)x(\d+)", out)
        return (int(found[-1][0]), int(found[-1][1])) if found else (1080, 1920)

    # ================================================================== drag & drop (APK install)
    @staticmethod
    def _local_files(mime) -> list:
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]

    def dragEnterEvent(self, e):
        if any(f.lower().endswith(".apk") for f in self._local_files(e.mimeData())):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dropEvent(self, e):
        files = self._local_files(e.mimeData())
        if any(f.lower().endswith(".apk") for f in files):
            e.acceptProposedAction()
            self.show_page("Apps")
            self.install_apks(files)
        else:
            e.ignore()

    # ================================================================== page: device info
    def _page_info(self) -> QWidget:
        box = QGroupBox("This instance")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignLeft)
        self.info_labels = {}
        for key, label in INFO_ROWS:
            lb = QLabel("-")
            lb.setWordWrap(True)
            lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(label + ":", lb)
            self.info_labels[key] = lb
        self.info_labels["title"].setText(self.inst.title)
        self.info_labels["serial"].setText(self.serial)
        tools = self._group("", [self._btn("Refresh", self.load_info),
                                 self._btn("Show ADB version", lambda: self.shell_adb("ADB version", "version"))])
        tools.setStyleSheet("QGroupBox { border: none; margin-top: 0; padding-top: 0; }")
        return self._scroll_page(box, tools)

    def load_info(self) -> None:
        def work(ctx):
            code, props = ctx.shell("getprop", stream=False, timeout=30)
            if code != 0:
                return None
            _c, wm = ctx.shell("wm size", stream=False)
            _c, bat = ctx.shell("dumpsys battery", stream=False)
            _c, wlan = ctx.shell("ip -f inet addr show wlan0", stream=False)
            ip = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", wlan)
            if not ip:
                _c, route = ctx.shell("ip route", stream=False)
                ip = re.search(r"src (\d+\.\d+\.\d+\.\d+)", route)
            _c, up = ctx.shell("uptime", stream=False)
            size = re.findall(r"(\d+x\d+)", wm)
            level = re.search(r"level: (\d+)", bat)
            info = dict(re.findall(r"^\[(.*?)\]: \[(.*?)\]$", props, re.M))
            out = {k: info.get(p) or "-" for k, p in PROP_OF.items()}
            out.update(screen=size[-1] if size else "-", battery=f"{level.group(1)}%" if level else "-",
                       ip=ip.group(1) if ip else "-", uptime=up or "-")
            return out

        def done(res):
            if not res:
                self.say("[-] Couldn't read the device information (is Android still starting?). Press Refresh to retry.")
                return
            for key, value in res.items():
                self.info_labels[key].setText(value)

        self.run_job("Reading device information...", work, done, quiet=True)

    # ================================================================== page: apps
    def _page_apps(self) -> QWidget:
        zone = QFrame()
        zone.setObjectName("dropzone")
        zl = QVBoxLayout(zone)
        zl.setContentsMargins(16, 14, 16, 14)
        t1 = QLabel("<b>Drop .apk files here to install them</b>")
        t1.setAlignment(Qt.AlignCenter)
        t2 = self._note("They are installed in the background through ADB. You can also drop them on the "
                        "instance card, or use the buttons below.")
        t2.setAlignment(Qt.AlignCenter)
        zl.addWidget(t1)
        zl.addWidget(t2)

        opts = QGroupBox("Install options")
        ol = QVBoxLayout(opts)
        self.ck_replace = QCheckBox("Replace the app if it is already installed")
        self.ck_replace.setChecked(True)
        self.ck_grant = QCheckBox("Grant all permissions automatically")
        self.ck_downgrade = QCheckBox("Allow a version downgrade")
        self.ck_test = QCheckBox("Allow test-only APKs")
        for ck in (self.ck_replace, self.ck_grant, self.ck_downgrade, self.ck_test):
            ol.addWidget(ck)

        install = self._group("Install", [
            self._btn("Install APK files...", self.act_install_dialog, "Pick one or more .apk files"),
            self._btn("Install split APKs as one app...", self.act_install_split,
                      "Pick the base APK and all of its split APKs together")])
        manage = self._group("Manage apps", [
            self._btn("Open / manage an app...", self.act_manage_app,
                      "Launch, force stop, clear data, permissions, save the APK, uninstall..."),
            self._btn("Uninstall an app...", self.act_uninstall),
            self._btn("Remove a system app (bloatware)...", self.act_remove_system,
                      "Removes it for the current user only - can be undone"),
            self._btn("Restore a removed system app...", self.act_restore_system),
            self._btn("List installed apps...", self.act_list_apps),
            self._btn("Open a link / dialer / Settings screen...", self.act_open_link)])
        return self._scroll_page(zone, install, opts, manage)

    def install_flags(self) -> list:
        flags = []
        if self.ck_replace.isChecked():
            flags.append("-r")
        if self.ck_grant.isChecked():
            flags.append("-g")
        if self.ck_downgrade.isChecked():
            flags.append("-d")
        if self.ck_test.isChecked():
            flags.append("-t")
        return flags

    def install_apks(self, files: list) -> bool:
        """Install .apk files one after the other (queued if a job is running). Returns False if none were usable."""
        apks = []
        for f in files:
            name = os.path.basename(f)
            if not f.lower().endswith(".apk"):
                self.say(f"[!] Skipped {name} (not an .apk file).")
            elif not os.path.isfile(f):
                self.say(f"[-] File not found: {f}")
            else:
                apks.append(f)
        if not apks:
            self.say("[-] Nothing to install.")
            return False
        flags = self.install_flags()

        def work(ctx):
            good = 0
            for i, apk in enumerate(apks, 1):
                if ctx.stopped:
                    break
                name = os.path.basename(apk)
                ctx.say(f"[*] ({i}/{len(apks)}) Installing {name}...")
                code, text = ctx.adb("install", *flags, apk, timeout=900)
                if code == 0 and "failure" not in text.lower():
                    good += 1
                    ctx.say(f"[+] Installed {name}.")
                    continue
                ctx.say(f"[-] Couldn't install {name}.")
                for key, hint in INSTALL_HINTS:
                    if key in text:
                        ctx.say(f"[!] {hint}")
                        break
            ctx.say(f"[{'+' if good == len(apks) else '!'}] {good} of {len(apks)} installed.")
            return good

        return self.run_job(f"Install {len(apks)} APK file(s)", work, queue=True)

    def _choose_apks(self, title: str) -> list:
        files, _flt = QFileDialog.getOpenFileNames(self, title, self._last_dir, "Android apps (*.apk);;All files (*)")
        if files:
            self._last_dir = os.path.dirname(files[0])
        return list(files)

    def act_install_dialog(self) -> None:
        files = self._choose_apks("Choose the APK file(s) to install")
        if files:
            self.install_apks(files)

    def act_install_split(self) -> None:
        files = [f for f in self._choose_apks("Choose the base APK and all split APKs of ONE app")
                 if os.path.isfile(f)]
        if not files:
            return
        flags = self.install_flags()

        def work(ctx):
            code, text = ctx.adb("install-multiple", *flags, *files, timeout=900)
            if code == 0 and "failure" not in text.lower():
                ctx.say("[+] Installed.")
            else:
                ctx.say("[-] Install failed.")
                for key, hint in INSTALL_HINTS:
                    if key in text:
                        ctx.say(f"[!] {hint}")
                        break

        self.run_job(f"Installing {len(files)} APK files as one app", work, queue=True)

    # ---- app list / picker
    def pick_package(self, flag: str, title: str, then) -> None:
        """Read the package list from Android, let the user pick one, then call then(pkg)."""
        def work(ctx):
            return ctx.shell(f"pm list packages {flag}".strip(), stream=False, timeout=60)

        def done(res):
            if not res:
                return
            code, text = res
            pkgs = sorted(l.replace("package:", "").strip() for l in text.splitlines() if l.startswith("package:"))
            if code != 0 or not pkgs:
                self.say("[-] Couldn't read the app list from Android.")
                return
            pkg = PackageDialog.choose(self, title, pkgs)
            if pkg:
                then(pkg)

        self.run_job("Reading the app list...", work, done, quiet=True)

    def act_manage_app(self) -> None:
        def chosen(pkg):
            key = AppDialog.choose(self, pkg)
            if key:
                self.app_action(pkg, key)
        self.pick_package("", "Choose an app", chosen)

    def act_uninstall(self) -> None:
        self.pick_package("-3", "Uninstall which app?", lambda pkg: self.app_action(pkg, "uninstall"))

    def act_remove_system(self) -> None:
        def chosen(pkg):
            r = QMessageBox.question(
                self, "Remove a system app",
                f"Remove {pkg} for the current user?\n\nRemoving the wrong system app can break Android. "
                "This only affects the current user and can be undone with \"Restore a removed system app\".",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r == QMessageBox.Yes:
                self.shell_cmd(f"Removing {pkg} for the current user...", f"pm uninstall --user 0 {shlex.quote(pkg)}")
        self.pick_package("", "Remove which app for the current user?", chosen)

    def act_restore_system(self) -> None:
        a = ask_form(self, "Restore a system app", [field("pkg", "Package name (e.g. com.android.chrome)")])
        if a and a["pkg"]:
            self.shell_cmd(f"Restoring {a['pkg']}...", f"cmd package install-existing {shlex.quote(a['pkg'])}")

    def act_list_apps(self) -> None:
        kinds = [("All apps", ""), ("User-installed apps", "-3"), ("System apps", "-s"), ("Disabled apps", "-d"),
                 ("Enabled apps", "-e")]
        a = ask_form(self, "List installed apps", [
            field("kind", "Which apps", "choice", kinds[0][0], [k for k, _f in kinds]),
            field("term", "Only names containing (optional)")])
        if a is None:
            return
        flag = dict(kinds).get(a["kind"], "")
        term = a["term"].lower()

        def work(ctx):
            code, text = ctx.shell(f"pm list packages {flag}".strip(), stream=False, timeout=60)
            pkgs = sorted(l.replace("package:", "").strip() for l in text.splitlines() if l.startswith("package:"))
            pkgs = [p for p in pkgs if term in p.lower()]
            ctx.say("\n".join(pkgs) if pkgs else "(nothing found)")
            ctx.say(f"[+] {len(pkgs)} package(s).")

        self.run_job("Listing apps...", work)

    def act_open_link(self) -> None:
        kinds = ["A web link (URL)", "The phone dialer with a number", "A Settings screen",
                 "Custom: your own \"am start\" arguments"]
        a = ask_form(self, "Open on the device", [
            field("kind", "What to open", "choice", kinds[0], kinds),
            field("value", "URL / phone number / arguments (not needed for Settings)"),
            field("screen", "Settings screen", "choice", SETTINGS_SCREENS[0][0], [n for n, _a in SETTINGS_SCREENS])])
        if a is None:
            return
        kind, value = a["kind"], a["value"]
        if kind == kinds[2]:
            cmd = "am start -a " + dict(SETTINGS_SCREENS)[a["screen"]]
        elif not value:
            self.say("[!] Type the URL, number or arguments first.")
            return
        elif kind == kinds[0]:
            cmd = f"am start -a android.intent.action.VIEW -d {shlex.quote(value)}"
        elif kind == kinds[1]:
            cmd = f"am start -a android.intent.action.DIAL -d {shlex.quote('tel:' + value)}"
        else:
            cmd = f"am start {value}"
        self.shell_cmd("Opening on the device...", cmd)

    # ---- actions for one app
    def app_action(self, pkg: str, key: str) -> None:
        q = shlex.quote(pkg)
        if key == "launch":
            self.run_job(f"Launching {pkg}...", lambda ctx: (
                ctx.shell(f"monkey -p {q} -c android.intent.category.LAUNCHER 1"), ctx.say("[+] App launched.")))
        elif key == "launcher":
            self._set_launcher(pkg)
        elif key == "stop":
            self.shell_cmd(f"Force stopping {pkg}...", f"am force-stop {q}")
        elif key == "clear":
            r = QMessageBox.question(self, "Clear data", f"Erase all data and cache of {pkg}?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r == QMessageBox.Yes:
                self.shell_cmd(f"Clearing {pkg}...", f"pm clear {q}")
        elif key == "toggle":
            a = ask_form(self, "Disable / enable", [
                field("what", "Action", "choice", "Disable the app", ["Disable the app", "Enable the app"])])
            if a:
                cmd = f"pm disable-user --user 0 {q}" if a["what"].startswith("Disable") else f"pm enable {q}"
                self.shell_cmd(a["what"] + "...", cmd)
        elif key == "perm":
            a = ask_form(self, "Permission", [
                field("perm", "Permission", "choice", COMMON_PERMISSIONS[0], COMMON_PERMISSIONS),
                field("other", "Or type another permission name (optional)"),
                field("action", "Action", "choice", "Grant", ["Grant", "Revoke"])])
            if a:
                perm = a["other"] or a["perm"]
                if "." not in perm:
                    perm = "android.permission." + perm
                verb = "grant" if a["action"] == "Grant" else "revoke"
                self.shell_cmd(f"{a['action']} {perm}...", f"pm {verb} {q} {shlex.quote(perm)}")
        elif key == "details":
            self.run_job(f"Details of {pkg}", lambda ctx: (
                ctx.shell(f"dumpsys package {q} | grep -E 'versionName|versionCode|firstInstallTime|lastUpdateTime|"
                          f"installerPackageName|targetSdk|userId='"),
                ctx.say("\nGranted permissions:"),
                ctx.shell(f"dumpsys package {q} | grep -E 'permission.*granted=true'")))
        elif key == "pull":
            self._pull_apk(pkg)
        elif key == "settings":
            self.shell_cmd("Opening the app's settings page...",
                           f"am start -a android.settings.APPLICATION_DETAILS_SETTINGS -d {shlex.quote('package:' + pkg)}")
        elif key == "uninstall":
            self._uninstall(pkg)

    def _set_launcher(self, pkg: str) -> None:
        def work(ctx):
            _c, out = ctx.shell("cmd package query-activities --brief -a android.intent.action.MAIN "
                                "-c android.intent.category.HOME", stream=False)
            comps = [l.strip() for l in out.splitlines() if l.strip().startswith(pkg + "/")]
            if not comps:
                ctx.say(f"[-] Couldn't find a launcher screen in {pkg} - it is not a launcher.")
                return
            code, _t = ctx.shell(f"cmd package set-home-activity --user 0 {shlex.quote(comps[0])}")
            if code == 0:
                ctx.say(f"[+] Default launcher set to {pkg}.")
        self.run_job(f"Setting {pkg} as the default launcher...", work)

    def _pull_apk(self, pkg: str) -> None:
        def work(ctx):
            _c, out = ctx.shell(f"pm path {shlex.quote(pkg)}", stream=False)
            remote = [l.replace("package:", "").strip() for l in out.splitlines() if l.startswith("package:")]
            if not remote:
                ctx.say("[-] Couldn't find the APK path.")
                return
            dest = self.out_dir / safe_name(pkg)
            dest.mkdir(parents=True, exist_ok=True)
            for r in remote:
                ctx.adb("pull", r, str(dest))
            ctx.say(f"[+] Saved {len(remote)} file(s) to {dest}")
        self.run_job(f"Saving the APK of {pkg}...", work)

    def _uninstall(self, pkg: str) -> None:
        a = ask_form(self, "Uninstall", [field("keep", "Keep the app's data and cache", "check", False)],
                     intro=f"Uninstall {pkg}?", ok_text="Uninstall")
        if a is None:
            return
        keep = bool(a["keep"])

        def work(ctx):
            code, text = ctx.adb("uninstall", *(["-k"] if keep else []), pkg)
            return code == 0 and "Success" in text

        def done(ok):
            if ok is None:
                return
            if ok:
                self.say(f"[+] Uninstalled {pkg}.")
                return
            r = QMessageBox.question(
                self, "Uninstall",
                "Android refused to uninstall it (normal for system apps).\n\nRemove it for the current user only "
                "instead? That works for most system apps and can be undone.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r == QMessageBox.Yes:
                self.shell_cmd(f"Removing {pkg} for the current user...",
                               f"pm uninstall {'-k ' if keep else ''}--user 0 {shlex.quote(pkg)}")

        self.run_job(f"Uninstalling {pkg}...", work, done)

    # ================================================================== page: files
    def _page_files(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 4, 8, 4)
        self.ed_path = QLineEdit(self._cwd)
        self.ed_path.returnPressed.connect(lambda: self.files_go(self.ed_path.text()))
        bar = QHBoxLayout()
        bar.addWidget(self._btn("Up", self.files_up, "Go to the parent folder"))
        bar.addWidget(self.ed_path, 1)
        bar.addWidget(self._btn("Refresh", lambda: self.files_go(self._cwd)))
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.file_list.itemDoubleClicked.connect(self._file_open)
        row = QHBoxLayout()
        row.addWidget(self._btn("Download to PC...", self.files_download, "Save the selected items on your PC"))
        row.addWidget(self._btn("Upload files...", self.files_upload, "Send files from your PC into this folder"))
        row.addWidget(self._btn("Upload folder...", self.files_upload_folder))
        row.addWidget(self._btn("New folder...", self.files_new_folder))
        row.addWidget(self._btn("Delete", self.files_delete, "Delete the selected items from Android", danger=True))
        lay.addLayout(bar)
        lay.addWidget(self._note("Double-click a folder to open it, or a file to download it."))
        lay.addWidget(self.file_list, 1)
        lay.addLayout(row)
        return page

    @staticmethod
    def _norm(base: str, path: str) -> str:
        p = (path or "").strip().replace("\\", "/") or base
        if not p.startswith("/"):
            p = posixpath.join(base, p)
        return posixpath.normpath(p)

    def files_go(self, path: str = None) -> None:
        target = self._norm(self._cwd, path or self._cwd)

        def work(ctx):
            return target, ctx.shell(f"ls -1Ap {shlex.quote(target)}", stream=False, timeout=30)

        def done(res):
            if res is None:
                return
            where, (code, text) = res
            if code != 0:
                reason = text.splitlines()[-1] if text else "no answer from Android"
                self.say(f"[-] Can't open {where}: {reason}")
                self.ed_path.setText(self._cwd)
                return
            self._cwd = where
            self.ed_path.setText(where)
            entries = [e.strip() for e in text.splitlines() if e.strip()]
            dirs = sorted((e for e in entries if e.endswith("/")), key=str.lower)
            files = sorted((e for e in entries if not e.endswith("/")), key=str.lower)
            self.file_list.clear()
            self.file_list.addItems(dirs + files)

        self.run_job(f"Opening {target}...", work, done, quiet=True)

    def files_up(self) -> None:
        self.files_go(posixpath.dirname(self._cwd.rstrip("/")) or "/")

    def _file_open(self, item) -> None:
        name = item.text()
        if name.endswith("/"):
            self.files_go(posixpath.join(self._cwd, name.rstrip("/")))
        else:
            self.file_list.clearSelection()
            item.setSelected(True)
            self.files_download()

    def _selected(self) -> list:
        return [i.text() for i in self.file_list.selectedItems()]

    def files_download(self) -> None:
        names = self._selected()
        if not names:
            self.say("[!] Select something in the list first.")
            return
        dest = QFileDialog.getExistingDirectory(self, "Save to which folder on this PC?", str(self.out_dir))
        if not dest:
            return
        remote = [posixpath.join(self._cwd, n.rstrip("/")) for n in names]

        def work(ctx):
            good = 0
            for r in remote:
                if ctx.stopped:
                    break
                code, _t = ctx.adb("pull", r, dest, timeout=3600)
                good += code == 0
            ctx.say(f"[{'+' if good == len(remote) else '!'}] Downloaded {good} of {len(remote)} item(s) to {dest}")

        self.run_job(f"Downloading {len(remote)} item(s)...", work)

    def _upload(self, sources: list) -> None:
        dest = self._cwd.rstrip("/") + "/"

        def work(ctx):
            good = 0
            for src in sources:
                if ctx.stopped:
                    break
                code, _t = ctx.adb("push", src, dest, timeout=3600)
                good += code == 0
            ctx.say(f"[{'+' if good == len(sources) else '!'}] Uploaded {good} of {len(sources)} item(s) to {dest}")

        self.run_job(f"Uploading {len(sources)} item(s)...", work, lambda _r: self.files_go(self._cwd))

    def files_upload(self) -> None:
        files, _flt = QFileDialog.getOpenFileNames(self, "Choose files to send to Android", self._last_dir,
                                                   "All files (*)")
        if files:
            self._last_dir = os.path.dirname(files[0])
            self._upload(list(files))

    def files_upload_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder to send to Android", self._last_dir)
        if folder:
            self._upload([folder])

    def files_new_folder(self) -> None:
        a = ask_form(self, "New folder", [field("name", "Folder name")], intro=f"Create a folder in {self._cwd}")
        name = (a or {}).get("name", "")
        if not name:
            return
        if "/" in name:
            self.say("[!] A folder name can't contain a slash.")
            return
        full = posixpath.join(self._cwd, name)
        self.run_job(f"Creating {full}...", lambda ctx: ctx.shell(f"mkdir -p {shlex.quote(full)}"),
                     lambda _r: self.files_go(self._cwd))

    def files_delete(self) -> None:
        names = self._selected()
        if not names:
            self.say("[!] Select something in the list first.")
            return
        shown = "\n".join(names[:6]) + (f"\n... and {len(names) - 6} more" if len(names) > 6 else "")
        r = QMessageBox.question(self, "Delete from Android",
                                 f"Delete {len(names)} item(s) (and everything inside folders) from Android?\n\n{shown}",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        remote = [posixpath.join(self._cwd, n.rstrip("/")) for n in names]

        def work(ctx):
            for p in remote:
                ctx.shell(f"rm -rf {shlex.quote(p)}")
            ctx.say(f"[+] Deleted {len(remote)} item(s).")

        self.run_job(f"Deleting {len(remote)} item(s)...", work, lambda _r: self.files_go(self._cwd))

    # ================================================================== page: screen & input
    def _page_screen(self) -> QWidget:
        capture = self._group("Capture", [
            self._btn("Take a screenshot", self.act_screenshot),
            self._btn("Record the screen...", self.act_record, "Records a video; Stop ends it early")])
        keys = self._group("Press a key / button", [self._btn(n, lambda c=c: self.press_key(c)) for n, c in KEYS]
                           + [self._btn("Other key...", self.act_other_key)], cols=3)
        touch = self._group("Text & touch", [
            self._btn("Type text...", self.act_type),
            self._btn("Tap / long-press a point...", self.act_tap),
            self._btn("Swipe up", lambda: self.swipe("up")), self._btn("Swipe down", lambda: self.swipe("down")),
            self._btn("Swipe left", lambda: self.swipe("left")), self._btn("Swipe right", lambda: self.swipe("right")),
            self._btn("Wake & unlock (swipe up)", self.act_unlock, "Wakes the screen and swipes the lock screen away")],
            cols=2)
        return self._scroll_page(capture, keys, touch)

    def act_screenshot(self) -> None:
        def work(ctx):
            path = self.new_out("screenshot", "png")
            code, err = ctx.adb_to_file(path, "exec-out", "screencap", "-p")
            if code != 0 or not path.exists() or path.stat().st_size < 100:
                ctx.say("[-] Screenshot failed: " + (err or "no image data received (is the screen off?)"))
                path.unlink(missing_ok=True)
                return None
            ctx.say(f"[+] Screenshot saved: {path}")
            return str(path)
        self.run_job("Taking a screenshot...", work)

    def act_record(self) -> None:
        a = ask_form(self, "Record the screen", [
            field("secs", "Duration in seconds (max 180)", "int", 30, (1, 180)),
            field("mbps", "Quality / bitrate in Mbps", "int", 8, (1, 100))],
            intro="Press Stop in the output bar to end the recording early - it is still saved.", ok_text="Record")
        if a is None:
            return
        secs = max(1, min(int(a["secs"]), 180))
        bps = max(1, int(a["mbps"])) * 1000000
        remote = f"/sdcard/ode_{int(time.time())}.mp4"

        def work(ctx):
            ctx.on_stop = lambda: ctx.quick("shell", "pkill -2 screenrecord")     # SIGINT: the file is finalized
            ctx.say(f"[*] Recording for up to {secs} seconds - press Stop to finish early...")
            ctx.shell(f"screenrecord --time-limit {secs} --bit-rate {bps} {remote}")
            ctx.on_stop = None
            time.sleep(0.5)
            local = self.new_out("recording", "mp4")
            code, _t = ctx.adb("pull", remote, str(local))
            ctx.shell(f"rm -f {remote}", stream=False)
            if code == 0 and local.exists():
                ctx.say(f"[+] Recording saved: {local}")
                return str(local)
            ctx.say("[-] Couldn't copy the recording from Android.")
            return None
        self.run_job("Recording the screen...", work)

    def press_key(self, code: str) -> None:
        cmd = "cmd " + code[4:] if code.startswith("CMD:") else f"input keyevent {code}"
        self.run_job("Sending a key...", lambda ctx: ctx.shell(cmd), quiet=True)

    def act_other_key(self) -> None:
        a = ask_form(self, "Press a key", [field("key", "Key name or number (e.g. KEYCODE_F or 29)")])
        if a and a["key"]:
            self.shell_cmd(f"Pressing {a['key']}...", f"input keyevent {shlex.quote(a['key'])}")

    def act_type(self) -> None:
        a = ask_form(self, "Type text", [field("text", "Text to type on the device (ASCII only)")])
        if a and a["text"]:
            self.shell_cmd("Typing...", f"input text {shlex.quote(a['text'].replace(' ', '%s'))}")

    def swipe(self, direction: str) -> None:
        def work(ctx):
            w, h = self._screen_size(ctx)
            cx, cy = w // 2, h // 2
            x1, x2, y1, y2 = w * 8 // 10, w * 2 // 10, h * 3 // 4, h // 4
            args = {"up": (cx, y1, cx, y2), "down": (cx, y2, cx, y1),
                    "left": (x1, cy, x2, cy), "right": (x2, cy, x1, cy)}[direction]
            ctx.shell("input swipe %d %d %d %d 300" % args)
        self.run_job(f"Swipe {direction}", work, quiet=True)

    def act_tap(self) -> None:
        a = ask_form(self, "Tap a point", [
            field("x", "X (pixels)", "int", 540, (0, 20000)), field("y", "Y (pixels)", "int", 1000, (0, 20000)),
            field("long", "Long-press instead of a short tap", "check", False)],
            intro="Coordinates are in screen pixels - the screen size is on the Device info page.")
        if a is None:
            return
        x, y = int(a["x"]), int(a["y"])
        cmd = f"input swipe {x} {y} {x} {y} 800" if a["long"] else f"input tap {x} {y}"
        self.shell_cmd("Touching the screen...", cmd)

    def act_unlock(self) -> None:
        def work(ctx):
            ctx.shell("input keyevent KEYCODE_WAKEUP", stream=False)
            time.sleep(0.5)
            w, h = self._screen_size(ctx)
            ctx.shell(f"wm dismiss-keyguard; input swipe {w // 2} {h * 8 // 10} {w // 2} {h * 2 // 10} 300",
                      stream=False)
            ctx.say("[+] Done.")
        self.run_job("Waking and unlocking the screen...", work)

    # ================================================================== page: display
    def _page_display(self) -> QWidget:
        return self._scroll_page(self._group("Display settings", [
            self._btn("Screen size (resolution)...", self.disp_size),
            self._btn("Screen density (DPI)...", self.disp_density),
            self._btn("Rotation...", self.disp_rotation),
            self._btn("Brightness...", self.disp_brightness),
            self._btn("Screen timeout...", self.disp_timeout),
            self._btn("Dark mode...", self.disp_dark),
            self._btn("Font size...", self.disp_font),
            self._btn("Keep screen on while charging...", self.disp_awake)]))

    def disp_size(self) -> None:
        a = ask_form(self, "Screen size", [field("v", "New size like 1080x1920, or reset")])
        v = (a or {}).get("v", "")
        if not a or not v:
            return
        if v.lower() == "reset":
            self.shell_cmd("Resetting the screen size...", "wm size reset")
        elif re.fullmatch(r"\d+x\d+", v):
            self.shell_cmd(f"Setting the screen size to {v}...", f"wm size {v}")
        else:
            self.say("[!] Enter a size like 1080x1920, or the word reset.")

    def disp_density(self) -> None:
        a = ask_form(self, "Screen density", [field("v", "New density in dpi (e.g. 420), or reset")])
        v = (a or {}).get("v", "")
        if not a or not v:
            return
        if v.lower() == "reset":
            self.shell_cmd("Resetting the density...", "wm density reset")
        elif v.isdigit():
            self.shell_cmd(f"Setting the density to {v}...", f"wm density {v}")
        else:
            self.say("[!] Enter a number like 420, or the word reset.")

    def disp_rotation(self) -> None:
        names = ["Auto-rotate on", "Portrait", "Landscape (left)", "Upside down", "Landscape (right)"]
        a = ask_form(self, "Rotation", [field("v", "Rotation", "choice", names[0], names)])
        if not a:
            return
        i = names.index(a["v"]) if a["v"] in names else 0
        cmd = ("settings put system accelerometer_rotation 1" if i == 0 else
               f"settings put system accelerometer_rotation 0; settings put system user_rotation {i - 1}")
        self.shell_cmd(f"Rotation: {names[i]}", cmd)

    def disp_brightness(self) -> None:
        a = ask_form(self, "Brightness", [field("v", "Brightness 0-100, or auto")])
        v = (a or {}).get("v", "")
        if not a or not v:
            return
        if v.lower() == "auto":
            cmd = "settings put system screen_brightness_mode 1"
        elif v.isdigit() and 0 <= int(v) <= 100:
            cmd = ("settings put system screen_brightness_mode 0; "
                   f"settings put system screen_brightness {round(int(v) * 255 / 100)}")
        else:
            self.say("[!] Enter a number from 0 to 100, or the word auto.")
            return
        self.shell_cmd("Setting the brightness...", cmd)

    def disp_timeout(self) -> None:
        a = ask_form(self, "Screen timeout", [field("v", "Screen timeout in seconds", "int", 60, (1, 36000))])
        if a:
            self.shell_cmd("Setting the screen timeout...", f"settings put system screen_off_timeout {int(a['v']) * 1000}")

    def disp_dark(self) -> None:
        names = ["On", "Off", "Automatic"]
        a = ask_form(self, "Dark mode", [field("v", "Dark mode", "choice", names[0], names)])
        if a:
            mode = ["yes", "no", "auto"][names.index(a["v"]) if a["v"] in names else 0]
            self.shell_cmd("Setting dark mode...", f"cmd uimode night {mode}")

    def disp_font(self) -> None:
        a = ask_form(self, "Font size", [field("v", "Font scale (0.85 small - 1.0 normal - 1.3 large)", "text", "1.0")])
        v = (a or {}).get("v", "")
        if not a or not v:
            return
        if re.fullmatch(r"\d(\.\d+)?", v):
            self.shell_cmd("Setting the font size...", f"settings put system font_scale {v}")
        else:
            self.say("[!] Enter a number like 1.0 or 1.15.")

    def disp_awake(self) -> None:
        names = ["While charging (any charger)", "Only while on USB", "Never (normal behaviour)"]
        a = ask_form(self, "Keep the screen on", [field("v", "Keep the screen on", "choice", names[0], names)])
        if a:
            mode = ["true", "usb", "false"][names.index(a["v"]) if a["v"] in names else 0]
            self.shell_cmd("Setting stay-awake...", f"svc power stayon {mode}")

    # ================================================================== page: power
    def _page_power(self) -> QWidget:
        return self._scroll_page(
            self._group("Reboot & power", [
                self._btn("Reboot Android", self.act_reboot, "Restarts Android inside this instance"),
                self._btn("Power off", self.act_poweroff, "Shuts Android down - the emulator closes")]),
            self._note("Reboot restarts Android and keeps the emulator window open - give it a minute before using "
                       "the other tools. Power off closes the emulator, and this window closes with it."))

    def act_reboot(self) -> None:
        r = QMessageBox.question(self, "Reboot", "Restart Android in this instance?",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r == QMessageBox.Yes:
            self.shell_adb("Rebooting Android... (wait until it has booted before using other tools)", "reboot")

    def act_poweroff(self) -> None:
        r = QMessageBox.question(self, "Power off", "Shut Android down? The emulator will close.",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r == QMessageBox.Yes:
            self.shell_cmd("Powering off...", "reboot -p")

    # ================================================================== page: system & logs
    def _run_btn(self, label: str, command: str) -> QPushButton:
        return self._btn(label, lambda: self.shell_cmd(label, command))

    def _page_system(self) -> QWidget:
        info = self._group("System info", [
            self._run_btn("Battery status", "dumpsys battery"),
            self._run_btn("Memory usage", "head -n 8 /proc/meminfo; echo; dumpsys meminfo | head -n 25"),
            self._run_btn("CPU load & top processes", "top -b -n 1 | head -n 20"),
            self._run_btn("Storage usage", "df -h"),
            self._btn("Running processes...", self.act_processes),
            self._run_btn("All system properties (getprop)", "getprop")])
        logs = self._group("Logs", [
            self._btn("Logcat (watch / save / clear)...", self.act_logcat),
            self._btn("Create a bug report (zip)", self.act_bugreport, "Can take a few minutes"),
            self._btn("Inspect a system service (dumpsys)...", self.act_dumpsys)])
        return self._scroll_page(info, logs)

    def act_processes(self) -> None:
        a = ask_form(self, "Running processes", [field("term", "Only processes containing (optional)")])
        if a is None:
            return
        cmd = f"ps -A | grep -i {shlex.quote(a['term'])}" if a["term"] else "ps -A"
        self.shell_cmd("Running processes", cmd)

    def act_logcat(self) -> None:
        a = ask_form(self, "Logcat", [
            field("mode", "What to do", "choice", LOG_MODES[0], LOG_MODES),
            field("level", "Minimum level", "choice", LOG_LEVELS[0], LOG_LEVELS),
            field("term", "Only lines containing (optional)")])
        if a is None:
            return
        if a["mode"] == LOG_MODES[2]:
            self.shell_adb("Clearing the log...", "logcat", "-c")
            return
        level = "VDIWE"[LOG_LEVELS.index(a["level"]) if a["level"] in LOG_LEVELS else 0]
        save = a["mode"] == LOG_MODES[1]
        cmd = "logcat -v threadtime" + (" -d" if save else "") + f" '*:{level}'"
        if a["term"]:
            cmd += f" | grep -i {shlex.quote(a['term'])}"
        if not save:
            self.shell_cmd("Live log - press Stop to end", cmd)
            return

        def work(ctx):
            path = self.new_out("logcat", "txt")
            code, err = ctx.adb_to_file(path, "exec-out", cmd)
            if code != 0 and not path.stat().st_size:
                ctx.say(f"[-] Couldn't save the log: {err}")
                return
            ctx.say(f"[+] Log saved: {path}")
        self.run_job("Saving the log...", work)

    def act_bugreport(self) -> None:
        def work(ctx):
            path = self.new_out("bugreport", "zip")
            ctx.adb("bugreport", str(path))
            if path.exists():
                ctx.say(f"[+] Bug report saved: {path}")
        self.run_job("Creating a bug report - this can take a few minutes...", work)

    def act_dumpsys(self) -> None:
        def work(ctx):
            _c, out = ctx.shell("dumpsys -l", stream=False, timeout=30)
            return [l.strip() for l in out.splitlines()[1:] if l.strip()]

        def done(names):
            if names is None:
                return
            a = ask_form(self, "Inspect a system service", [
                field("svc", "Service name (e.g. battery, wifi, activity, window)", "combo", "", names)])
            if a and a["svc"]:
                self.shell_cmd(f"dumpsys {a['svc']}", f"dumpsys {shlex.quote(a['svc'])}")

        self.run_job("Reading the service list...", work, done, quiet=True)

    # ================================================================== page: network & ports
    def _page_network(self) -> QWidget:
        net = self._group("Network", [self._btn("Show network info (IP addresses, Wi-Fi)", self.act_network_info),
                                      self._btn("Ping test from the device...", self.act_ping)])
        toggles = QGroupBox("Quick toggles")
        grid = QGridLayout(toggles)
        for row, (label, svc) in enumerate([("Wi-Fi", "wifi"), ("Mobile data", "data"), ("Bluetooth", "bluetooth"),
                                            ("Airplane mode", None), ("Location", None)]):
            builder = (lambda on, s=svc: f"svc {s} {'enable' if on else 'disable'}") if svc else None
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(self._btn("On", lambda l=label, b=builder: self.toggle(l, b, True)), row, 1)
            grid.addWidget(self._btn("Off", lambda l=label, b=builder: self.toggle(l, b, False)), row, 2)
        grid.setColumnStretch(0, 1)
        ports = self._group("Port forwarding", [
            self._btn("Forward a port (PC -> device)...", self.act_forward),
            self._btn("Reverse a port (device -> PC)...", self.act_reverse),
            self._btn("List forwards / reverses", self.act_list_ports),
            self._btn("Remove forwards / reverses...", self.act_remove_ports)])
        return self._scroll_page(net, toggles, ports)

    def act_network_info(self) -> None:
        def work(ctx):
            ctx.shell("ip -f inet addr show | grep -E '^[0-9]+:|inet '")
            ctx.say("\nWi-Fi:")
            ctx.shell("dumpsys wifi | grep -E 'mWifiInfo' | head -n 2")
        self.run_job("Network info", work)

    def act_ping(self) -> None:
        a = ask_form(self, "Ping test", [field("host", "Host to ping", "text", "8.8.8.8")])
        if a and a["host"]:
            self.shell_cmd(f"Pinging {a['host']}...", f"ping -c 4 {shlex.quote(a['host'])}")

    def toggle(self, label: str, builder, on: bool) -> None:
        state = "on" if on else "off"
        if builder is not None:
            self.shell_cmd(f"{label}: {state}", builder(on))
            return

        def airplane(ctx):
            code, text = ctx.shell(f"cmd connectivity airplane-mode {'enable' if on else 'disable'}")
            if code == 0 and "rror" not in text and "xception" not in text:
                return
            ctx.shell(f"settings put global airplane_mode_on {int(on)}; "
                      f"am broadcast -a android.intent.action.AIRPLANE_MODE --ez state {'true' if on else 'false'}")

        def location(ctx):
            code, text = ctx.shell(f"cmd location set-location-enabled {'true' if on else 'false'}")
            if code != 0 or "xception" in text:
                ctx.shell(f"settings put secure location_mode {3 if on else 0}")

        self.run_job(f"{label}: {state}", airplane if label == "Airplane mode" else location)

    @staticmethod
    def _port(value: str) -> str:
        return f"tcp:{value}" if value.isdigit() else value

    def act_forward(self) -> None:
        a = ask_form(self, "Forward a port", [field("local", "PC port (or a full spec like localabstract:name)"),
                                              field("remote", "Device port")],
                     intro="Connect to a port on this PC and reach a port on the device.")
        if a and a["local"] and a["remote"]:
            self.shell_adb("Forwarding...", "forward", self._port(a["local"]), self._port(a["remote"]))

    def act_reverse(self) -> None:
        a = ask_form(self, "Reverse a port", [field("remote", "Device port (or a full spec)"), field("local", "PC port")],
                     intro="Apps on the device connect to a port that reaches your PC.")
        if a and a["local"] and a["remote"]:
            self.shell_adb("Reversing...", "reverse", self._port(a["remote"]), self._port(a["local"]))

    def act_list_ports(self) -> None:
        def work(ctx):
            ctx.say("Forwards:")
            ctx.adb("forward", "--list")
            ctx.say("Reverses:")
            ctx.adb("reverse", "--list")
        self.run_job("Port forwards / reverses", work)

    def act_remove_ports(self) -> None:
        names = ["All forwards", "All reverses", "One forward", "One reverse"]
        a = ask_form(self, "Remove forwards / reverses", [
            field("what", "Remove which", "choice", names[0], names),
            field("spec", "Port to remove (PC port for a forward, device port for a reverse)")])
        if a is None:
            return
        i = names.index(a["what"]) if a["what"] in names else 0
        if i >= 2 and not a["spec"]:
            self.say("[!] Enter the port to remove.")
            return
        spec = self._port(a["spec"])
        args = [("forward", "--remove-all"), ("reverse", "--remove-all"), ("forward", "--remove", spec),
                ("reverse", "--remove", spec)][i]
        self.shell_adb("Removing...", *args)

    # ================================================================== page: shell & advanced
    def _page_shell(self) -> QWidget:
        self.ed_shell = QLineEdit()
        self.ed_shell.setPlaceholderText("e.g. getprop ro.build.fingerprint")
        self.ed_shell.returnPressed.connect(self.run_shell_line)
        self.ed_raw = QLineEdit()
        self.ed_raw.setPlaceholderText("e.g. features   or   shell getprop ro.product.model")
        self.ed_raw.returnPressed.connect(self.run_raw_line)
        box = QGroupBox("Run a command")
        form = QGridLayout(box)
        form.addWidget(QLabel("Shell command on the device:"), 0, 0, 1, 2)
        form.addWidget(self.ed_shell, 1, 0)
        form.addWidget(self._btn("Run", self.run_shell_line), 1, 1)
        form.addWidget(QLabel("Any adb command (without the word \"adb\"):"), 2, 0, 1, 2)
        form.addWidget(self.ed_raw, 3, 0)
        form.addWidget(self._btn("Run", self.run_raw_line), 3, 1)
        form.setColumnStretch(0, 1)
        adv = self._group("Advanced", [
            self._btn("Restart adb as root", lambda: self.shell_adb("Restarting adb as root...", "root")),
            self._btn("Restart adb without root", lambda: self.shell_adb("Restarting adb without root...", "unroot")),
            self._btn("Remount system partitions (needs root)", lambda: self.shell_adb("Remounting...", "remount")),
            self._btn("Settings editor...", self.act_settings_editor),
            self._btn("Send a broadcast...", self.act_broadcast),
            self._btn("List features / libraries / users...", self.act_package_lists)])
        return self._scroll_page(box, adv)

    def run_shell_line(self) -> None:
        cmd = self.ed_shell.text().strip()
        if cmd:
            self.shell_cmd(f"adb shell {cmd}", cmd)

    def run_raw_line(self) -> None:
        text = self.ed_raw.text().strip()
        if not text:
            return
        try:
            args = shlex.split(text, posix=(os.name != "nt"))
        except ValueError as exc:
            self.say(f"[-] Could not parse that: {exc}")
            return
        args = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] and a[0] in "\"'" else a for a in args]
        self.shell_adb(f"adb {text}", *args)

    def act_settings_editor(self) -> None:
        actions = ["List everything", "Read one value", "Change a value", "Delete a value"]
        a = ask_form(self, "Settings editor", [
            field("table", "Settings table", "choice", "system", ["system", "secure", "global"]),
            field("action", "Action", "choice", actions[0], actions),
            field("key", "Setting name (not needed for the list)"),
            field("value", "New value (for Change)")])
        if a is None:
            return
        table, action, key, value = a["table"], a["action"], a["key"], a["value"]
        if action == actions[0]:
            self.shell_cmd(f"settings list {table}", f"settings list {table}")
            return
        if not key:
            self.say("[!] Enter the setting name.")
            return
        if action == actions[1]:
            self.shell_cmd(f"settings get {table} {key}", f"settings get {table} {shlex.quote(key)}")
        elif action == actions[2]:
            r = QMessageBox.question(self, "Change a setting", f"Set {table}/{key} = {value}?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r == QMessageBox.Yes:
                self.shell_cmd(f"settings put {table} {key}",
                               f"settings put {table} {shlex.quote(key)} {shlex.quote(value)}")
        else:
            r = QMessageBox.question(self, "Delete a setting", f"Delete {table}/{key}?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r == QMessageBox.Yes:
                self.shell_cmd(f"settings delete {table} {key}", f"settings delete {table} {shlex.quote(key)}")

    def act_broadcast(self) -> None:
        a = ask_form(self, "Send a broadcast", [
            field("action", "Action (e.g. android.intent.action.BOOT_COMPLETED)"),
            field("pkg", "Limit to one package (optional)"),
            field("extra", "Extra arguments (optional, e.g. --es key value)")])
        if not a or not a["action"]:
            return
        cmd = f"am broadcast -a {shlex.quote(a['action'])}"
        if a["pkg"]:
            cmd += f" -p {shlex.quote(a['pkg'])}"
        if a["extra"]:
            cmd += f" {a['extra']}"
        self.shell_cmd("Sending the broadcast...", cmd)

    def act_package_lists(self) -> None:
        kinds = [("Hardware/software features", "features"), ("Shared libraries", "libraries"), ("Users", "users"),
                 ("Permission groups", "permission-groups")]
        a = ask_form(self, "List", [field("what", "List what", "choice", kinds[0][0], [k for k, _w in kinds])])
        if a:
            what = dict(kinds).get(a["what"], "features")
            self.shell_cmd(f"pm list {what}", f"pm list {what}")
