"""ODE main window: top bar, instance manager / create pages, core + launch flows, guide hooks."""
from __future__ import annotations

from PyQt5.QtCore import Qt, QUrl, pyqtSlot
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                             QPlainTextEdit, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from . import (APP_NAME, APP_SHORT, APP_VERSION, DISCLAIMER, GITHUB_URL, adbctl, instances, paths, sdcard, sdk,
               system, theme, updater)
from .create_page import CreatePage
from .devcontrol import DevControl
from .download import run_download
from .guide import GuideOverlay, Step
from .instances import Store
from .manager import ManagerPage
from .session import Session
from .settings import Settings
from .util import app_icon, asset_pixmap, run_task

LICENSE_URL = "https://developer.android.com/studio/terms"


class UpdateDialog(QDialog):
    """'A new emulator version is released' - shows versions + the changelog."""

    def __init__(self, parent, installed: str, new: str, size_mb: float):
        super().__init__(parent)
        self.setWindowTitle("Emulator update available")
        self.setMinimumSize(560, 460)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        head = QLabel(f"<b>A new version of the Android Emulator has been released.</b><br>"
                      f"Installed: {installed or 'unknown'} &nbsp;&nbsp;\u2192&nbsp;&nbsp; New: <b>{new}</b> "
                      f"&nbsp;({size_mb:,.0f} MB)")
        head.setWordWrap(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlainText("Loading changelog...")
        yes = QPushButton("Update now")
        yes.setObjectName("primary")
        no = QPushButton("Not now")
        yes.clicked.connect(self.accept)
        no.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(no)
        row.addWidget(yes)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.addWidget(head)
        lay.addWidget(QLabel("Changelog (from developer.android.com):"))
        lay.addWidget(self.log, 1)
        lay.addLayout(row)
        run_task(lambda: sdk.fetch_changelog(new), self._got_log)

    def _got_log(self, text, err):
        self.log.setPlainText(text if not err else f"The changelog couldn't be loaded: {err}")


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.store = Store()
        self.sessions: dict = {}
        self.devwins: dict = {}             # inst.id -> its Dev Control window
        self._reached: set = set()          # instance ids that finished booting at least once
        self.core_info = None
        self.update_available = False
        self.new_app_version = ""           # newer ODE release found on GitHub ("" = none)
        self._guide = None
        self._guide_core = False
        self._accel_checked = False

        self.setWindowTitle(f"{APP_NAME} ({APP_SHORT})")
        self.setWindowIcon(app_icon())
        self.resize(1040, 740)
        self.setMinimumSize(900, 620)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- top bar
        bar = QFrame()
        bar.setObjectName("topbar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 8, 16, 8)
        bl.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(asset_pixmap("icon.png", 40))
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        ver = QLabel(f"v{APP_VERSION}")
        ver.setObjectName("muted")
        self.lb_core = QLabel("")
        self.lb_core.setObjectName("muted")
        self.btn_update = QPushButton("")
        self.btn_update.setObjectName("primary")
        self.btn_update.setToolTip("A new version of ODE is available on GitHub")
        self.btn_update.clicked.connect(self.show_app_update_dialog)
        self.btn_update.hide()
        self.btn_core = QPushButton("Download Core")
        self.btn_core.setObjectName("primary")
        self.btn_core.clicked.connect(self.on_core_button)
        self.btn_guide = QPushButton("Guide")
        self.btn_guide.clicked.connect(lambda: self.open_guide(False))
        self.btn_theme = QPushButton("")
        self.btn_theme.clicked.connect(self.toggle_theme)
        self.btn_about = QPushButton("About")
        self.btn_about.clicked.connect(self.show_about)
        bl.addWidget(logo)
        bl.addWidget(title)
        bl.addWidget(ver, 0, Qt.AlignBottom)
        bl.addStretch(1)
        bl.addWidget(self.btn_update)
        bl.addWidget(self.lb_core)
        bl.addWidget(self.btn_core)
        bl.addWidget(self.btn_guide)
        bl.addWidget(self.btn_theme)
        bl.addWidget(self.btn_about)
        root.addWidget(bar)

        # ---- pages
        self.stack = QStackedWidget()
        self.manager = ManagerPage(self.store)
        self.create = CreatePage(self.store)
        self.stack.addWidget(self.manager)
        self.stack.addWidget(self.create)
        root.addWidget(self.stack, 1)

        # ---- footer
        foot = QFrame()
        foot.setObjectName("footer")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 5, 16, 5)
        free = QLabel("Free \u2022 open source \u2022 no ads")
        free.setObjectName("muted")
        fl.addStretch(1)
        fl.addWidget(free, 0)
        root.addWidget(foot)

        # ---- wiring
        self.manager.create_requested.connect(self.open_create)
        self.manager.launch.connect(self.on_launch)
        self.manager.edit.connect(self.on_edit)
        self.manager.star.connect(self.on_star)
        self.manager.delete.connect(self.on_delete)
        self.manager.kill.connect(self.on_kill)
        self.manager.devcontrol.connect(self.open_devcontrol)
        self.manager.apks.connect(self.on_apks)
        self.create.created.connect(self.on_created)
        self.create.saved.connect(self.on_created)
        self.create.cancelled.connect(lambda: self.stack.setCurrentWidget(self.manager))

        self._update_theme_button()
        self.update_core_ui()

    # ================================================================== startup
    def start(self):
        run_task(adbctl.kill_if_idle, lambda _r, _e: None)       # a stray adb from a crashed run would break launches
        if self.settings.get("show_guide", True):
            self.open_guide(True)
        else:
            self.run_startup_checks()

    def run_startup_checks(self):
        self.lb_core.setText("Checking for updates...")
        run_task(updater.check_for_update, self._app_update_checked)

    def _app_update_checked(self, newer, err):
        """err is ignored on purpose: being offline (or GitHub being slow) must never bother the user."""
        if newer and not err:
            self.new_app_version = newer
            self.btn_update.setText(f"ODE {newer} available")
            self.btn_update.show()
            self.show_app_update_dialog()
        run_task(sdk.core_info, self._startup_info)

    def show_app_update_dialog(self):
        new = self.new_app_version
        if not new:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("ODE update available")
        box.setText(f"A new version of {APP_NAME} is available!\n\nInstalled: {APP_VERSION}\nNew: {new}")
        box.setInformativeText(f"Go to the GitHub page to download it:\n{GITHUB_URL}")
        go = box.addButton("Open GitHub", QMessageBox.AcceptRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.setDefaultButton(go)
        box.exec_()
        if box.clickedButton() is go:
            QDesktopServices.openUrl(QUrl(GITHUB_URL))

    def _startup_info(self, info, err):
        installed = sdk.core_installed()
        if err:
            self.core_info = None
            self.update_core_ui()
            if not installed:
                QMessageBox.warning(self, "Can't reach Google",
                                    f"{err}\n\nThe emulator core is not installed. Connect to the internet and "
                                    "press Download Core.")
            return
        self.core_info = info
        if not installed:
            self.update_core_ui()
            self.offer_core_download()
        else:
            self.check_update(announce=True)
            self.update_core_ui()

    # ================================================================== core
    def update_core_ui(self):
        installed = sdk.core_installed()
        rev = sdk.installed_revision("emulator")
        rev_s = ".".join(map(str, rev)) if rev else ""
        if not installed:
            self.lb_core.setText("Core: not installed")
            self.btn_core.setText("Download Core")
            self.btn_core.setVisible(True)
        elif self.update_available and self.core_info:
            self.lb_core.setText(f"Core {rev_s} \u2192 {self.core_info.emulator.rev_str}")
            self.btn_core.setText("Update Core")
            self.btn_core.setVisible(True)
        else:
            self.lb_core.setText(f"Core {rev_s}" if rev_s else "Core installed")
            self.btn_core.setText("Update Core" if self._guide_core else "Download Core")
            self.btn_core.setVisible(self._guide_core)
        self.manager.set_core_ok(installed)

    def on_core_button(self):
        if sdk.core_installed() and self.update_available:
            self.show_update_dialog()
        else:
            self.with_core_info(self.offer_core_download)

    def with_core_info(self, then):
        """Run then() once Google's repository info is available."""
        if self.core_info:
            then()
            return
        self.btn_core.setEnabled(False)
        self.lb_core.setText("Contacting Google's servers...")

        def got(info, err):
            self.btn_core.setEnabled(True)
            self.update_core_ui()
            if err:
                QMessageBox.warning(self, "Can't reach Google", str(err))
                return
            self.core_info = info
            then()
        run_task(sdk.core_info, got)

    def offer_core_download(self):
        info = self.core_info
        if info is None:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Emulator core")
        box.setText("The emulator core is not installed. Would you like to download it?\n"
                    f"Size: {info.emulator.size_mb:,.0f} MB")
        box.setInformativeText(f"By downloading you accept the Android SDK License Agreement:\n{LICENSE_URL}")
        yes = box.addButton("Download", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(yes)
        box.exec_()
        if box.clickedButton() is yes:
            self.download_core(update=False)
        else:
            QMessageBox.information(self, "Emulator core",
                                    "ODE won't work until you download the emulator core.\n\n"
                                    "Everything that needs it is grayed out. Press Download Core at the top "
                                    "whenever you're ready.")

    def download_core(self, update: bool):
        info = self.core_info
        if self.sessions:
            QMessageBox.warning(self, "Emulators running",
                                "Close all running instances before installing the emulator core.")
            return
        jobs = [sdk.job_for(info.emulator, "Android Emulator")]
        pt_rev = sdk.installed_revision("platform-tools")
        if not sdk.adb_exe().exists() or (pt_rev and sdk.rev_newer(info.platform_tools.revision, pt_rev)):
            adbctl.kill_if_idle()                       # a running adb.exe would block replacing platform-tools
            jobs.append(sdk.job_for(info.platform_tools, "Platform tools (ADB)"))
        ok = run_download(self, "Updating the emulator core" if update else "Downloading the emulator core", jobs,
                          "The emulator core was installed successfully. Everything is ready to use now."
                          if not update else "The emulator core was updated successfully.")
        if ok:
            self.update_available = False
        self.update_core_ui()

    def check_update(self, announce: bool):
        info = self.core_info
        local = sdk.installed_revision("emulator")
        if info and local and sdk.rev_newer(info.emulator.revision, local):
            self.update_available = True
            if announce:
                self.show_update_dialog()
        else:
            self.update_available = False

    def show_update_dialog(self):
        info = self.core_info
        local = sdk.installed_revision("emulator")
        dlg = UpdateDialog(self, ".".join(map(str, local)) if local else "", info.emulator.rev_str,
                           info.emulator.size_mb)
        if dlg.exec_() == QDialog.Accepted:
            self.download_core(update=True)
        else:
            QMessageBox.information(self, "Update later",
                                    "No problem! You can still update the emulator any time with the "
                                    "Update Core button at the top of the window.")
        self.update_core_ui()

    # ================================================================== instances
    def open_create(self):
        self.create.reset()
        self.stack.setCurrentWidget(self.create)

    def on_created(self, inst):                 # also used after saving edited settings
        self.manager.refresh()
        self.stack.setCurrentWidget(self.manager)

    def on_edit(self, inst):
        if inst.id in self.sessions:
            QMessageBox.information(self, "Instance running", "Close the instance before changing its settings.")
            return
        self.create.edit(inst)
        self.stack.setCurrentWidget(self.create)

    def on_star(self, inst):
        self.store.toggle_star(inst)
        self.manager.refresh()

    def on_delete(self, inst):
        if inst.id in self.sessions:
            return
        r = QMessageBox.question(self, "Delete instance",
                                 f"Delete \"{inst.title}\" and all of its files?\n\n{inst.root}\n\n"
                                 "This can't be undone.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            problem = instances.delete_files(inst)
        finally:
            QApplication.restoreOverrideCursor()
        if problem:                              # keep the entry so the user can try again
            QMessageBox.warning(self, "Couldn't delete everything", problem)
            return
        self.store.remove(inst)
        self.manager.states.pop(inst.id, None)
        self.manager.refresh()

    def on_kill(self, inst):
        s = self.sessions.get(inst.id)
        if s is None:
            return
        r = QMessageBox.question(self, "Force close",
                                 f"Force close \"{inst.title}\"?\nThe emulator is killed immediately and "
                                 "anything unsaved inside Android is lost.",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r == QMessageBox.Yes:
            s.kill()

    def open_devcontrol(self, inst, page: str = None):
        """The Dev Control window of a running instance (created on first use)."""
        s = self.sessions.get(inst.id)
        if s is None or s.current != "booted":
            QMessageBox.information(self, "Dev Control", "Start the instance and wait until Android has booted - "
                                    "Dev Control talks to Android while it is running.")
            return None
        win = self.devwins.get(inst.id)
        if win is None:
            win = DevControl(inst, s.serial)
            self.devwins[inst.id] = win
        win.show()
        win.raise_()
        win.activateWindow()
        if page:
            win.show_page(page)
        return win

    def on_apks(self, inst, files: list):
        """.apk files dropped on a running instance's card: install them through Dev Control."""
        win = self.open_devcontrol(inst, "Apps")
        if win is not None:
            win.install_apks(files)

    # ================================================================== launching
    def on_launch(self, inst, recovery: bool):
        if not sdk.core_installed() or inst.id in self.sessions:
            return
        need_adb = not sdk.adb_exe().exists()
        need_img = not sdk.image_installed(inst.image_pkg)
        if not (need_adb or need_img):
            self._after_files(inst, recovery)
            return
        self.manager.set_state(inst, "checking", "Checking which files are needed...")

        def work():
            jobs = []
            if need_adb:
                jobs.append(sdk.job_for(sdk.core_info().platform_tools, "Platform tools (ADB)"))
            if need_img:
                pkg = next((p for p in sdk.get_system_images(inst.flavor) if p.path == inst.image_pkg), None)
                if pkg is None:
                    raise RuntimeError(f"Google no longer offers the system image for {inst.api_label}.")
                jobs.append(sdk.job_for(pkg, f"{inst.api_label} system image"))
            return jobs

        run_task(work, lambda jobs, err: self._files_checked(inst, recovery, jobs, err))

    def _files_checked(self, inst, recovery, jobs, err):
        if err:
            self.manager.set_state(inst, "idle")
            QMessageBox.warning(self, "Can't check the files", str(err))
            return
        size = sum(j.size for j in jobs)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Files needed")
        box.setText("There are files that need to be downloaded before your first run.\n"
                    f"Size: {size / 1048576.0:,.0f} MB")
        box.setInformativeText(f"By downloading you accept the Android SDK License Agreement:\n{LICENSE_URL}")
        ok_btn = box.addButton("Confirm", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is not ok_btn:
            self.manager.set_state(inst, "idle")
            return
        self.manager.set_state(inst, "checking", "Downloading system files...")
        ok = run_download(self, f"Downloading files for {inst.title}", jobs)
        if not ok:
            self.manager.set_state(inst, "idle")
            return
        self._after_files(inst, recovery)

    def _after_files(self, inst, recovery: bool):
        if self._accel_checked or inst.standalone_arm:       # the x86 hypervisor check doesn't apply to ARM
            self._start_session(inst, recovery)
            return
        self.manager.set_state(inst, "checking", "Checking hardware acceleration...")
        run_task(sdk.accel_check, lambda res, err: self._accel_done(inst, recovery, res, err))

    def _accel_done(self, inst, recovery, res, err):
        ok, out = (res if res else (False, str(err)))
        self._accel_checked = True
        if not ok and not system.IS_MAC:
            r = QMessageBox.question(
                self, "No hardware acceleration",
                "The emulator reports that hardware acceleration isn't available. Android will be very slow "
                "or may not start.\n\nTurn on Virtualization in your BIOS and enable Windows Hypervisor Platform "
                f"(or the Hyper-V feature).\n\nDetails:\n{out[:500]}\n\nStart anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                self._accel_checked = False
                self.manager.set_state(inst, "idle")
                return
        self._start_session(inst, recovery)

    def _start_session(self, inst, recovery: bool):
        if sdcard.needs_prepare(inst):                              # (re)create the virtual SD card first
            self.manager.set_state(inst, "checking", "Preparing the SD card...")
            run_task(lambda: sdcard.prepare(inst), lambda _res, err: self._sd_ready(inst, recovery, err))
            return
        self._launch_session(inst, recovery)

    def _sd_ready(self, inst, recovery: bool, err):
        if err:
            self.manager.set_state(inst, "idle")
            QMessageBox.warning(self, "SD card", f"The SD card couldn't be prepared:\n\n{err}")
            return
        self._launch_session(inst, recovery)

    def _launch_session(self, inst, recovery: bool):
        s = Session(inst, recovery)
        s.state.connect(self._session_state)
        try:
            s.start()
        except Exception as exc:                                   # noqa: BLE001
            self.manager.set_state(inst, "idle")
            QMessageBox.critical(self, "Couldn't start the emulator", str(exc))
            return
        self.sessions[inst.id] = s
        self.manager.set_state(inst, "starting", "Starting the emulator...")

    @pyqtSlot(str)
    def _session_state(self, st: str):
        s = self.sender()
        if not isinstance(s, Session):
            return
        inst = s.inst
        if st == "starting":
            self.manager.set_state(inst, "starting", "Starting the emulator...")
        elif st == "booting":
            self.manager.set_state(inst, "booting", "Booting Android...")
        elif st in ("booted", "recovery"):
            self._reached.add(inst.id)
            self.manager.set_state(inst, st)
        elif st == "stopped":
            self.sessions.pop(inst.id, None)
            dev = self.devwins.pop(inst.id, None)
            if dev is not None:
                dev.shutdown()
            self.manager.set_state(inst, "idle")
            if inst.id not in self._reached and s.proc is not None and s.proc.returncode not in (None, 0):
                why = instances.diagnose_log(inst)
                QMessageBox.warning(self, "The emulator closed",
                                    f"\"{inst.title}\" closed before Android finished booting (exit code "
                                    f"{s.proc.returncode}).\n\n" + (why + "\n\n" if why else "")
                                    + f"The log is here:\n{inst.log_path}")
            self._reached.discard(inst.id)

    # ================================================================== theme / about
    def toggle_theme(self):
        name = "dark" if theme.current() == "light" else "light"
        theme.apply_theme(QApplication.instance(), name)
        self.settings.set("theme", name)
        self._update_theme_button()
        for c in self.manager.cards.values():
            c._refresh()
        self.manager.demo_card._refresh()

    def _update_theme_button(self):
        self.btn_theme.setText("\u2600  Light mode" if theme.current() == "dark" else "\u263E  Dark mode")

    def show_about(self):
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<h3>{APP_NAME} ({APP_SHORT}) {APP_VERSION}</h3>"
            "<p>An open-source GUI that downloads, configures and launches Google's stock Android Emulator - "
            "for gaming, app testing and everyday use. No ads, no bundled software, no accounts.</p>"
            f"<p><b>{DISCLAIMER}</b></p>"
            "<p>The emulator, platform-tools and system images are downloaded directly from Google's servers "
            f"and are covered by the <a href=\"{LICENSE_URL}\">Android SDK License Agreement</a>. "
            "Android is a trademark of Google LLC; ODE isn't affiliated with Google.</p>"
            f"<p>Files are kept next to the program:<br>{paths.CORE_DIR}</p>")

    # ================================================================== guide
    def open_guide(self, startup: bool):
        if self._guide is not None:
            return
        self._guide = GuideOverlay(self, dont_show=not self.settings.get("show_guide", True))
        self._guide.closed.connect(lambda dont: self._guide_closed(dont, startup))

    def _guide_closed(self, dont: bool, startup: bool):
        self._guide = None
        self.settings.set("show_guide", not dont)
        if startup:
            self.run_startup_checks()

    def guide_target(self, name: str):
        m, c = self.manager, self.create
        return {
            "core": self.btn_core, "guide": self.btn_guide, "theme": self.btn_theme, "about": self.btn_about,
            "list": m.scroll, "card_star": m.demo_card.btn_star, "card_edit": m.demo_card.btn_edit,
            "card_dev": m.demo_card.btn_dev, "card_delete": m.demo_card.btn_delete,
            "card_launch": m.demo_card.btn_launch, "create_button": m.btn_create,
            "grp_basic": c.grp_basic, "grp_gfx": c.grp_gfx, "grp_storage": c.grp_storage,
            "grp_perf": c.grp_perf, "create_buttons": c.btn_create,
        }.get(name)

    def guide_enter(self, step: Step):
        if step.page == "create" and self.create.edit_inst is not None:
            self.create.reset()                  # the guide shows the 'create' form, not an instance being edited
        self.stack.setCurrentWidget(self.create if step.page == "create" else self.manager)
        self.manager.set_demo(step.demo_card)
        self._guide_core = step.show_core
        self.update_core_ui()
        if self._guide:
            self._guide.raise_()
        QApplication.processEvents()

    def guide_exit(self):
        self._guide_core = False
        self.manager.set_demo(False)
        self.stack.setCurrentWidget(self.manager)
        self.update_core_ui()

    # ================================================================== closing
    def closeEvent(self, e):
        if self.sessions:
            r = QMessageBox.question(self, "Emulators running",
                                     "Some instances are still running. Closing ODE force closes them.\n\nClose anyway?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                e.ignore()
                return
            for s in list(self.sessions.values()):
                s.kill()
        for dev in list(self.devwins.values()):
            dev.shutdown()
        self.devwins.clear()
        adbctl.kill_now()                                 # nothing runs any more: don't leave adb behind
        e.accept()
