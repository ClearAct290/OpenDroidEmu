"""Instance manager page: instance cards (star / launch / settings / delete / Dev Control)."""
from __future__ import annotations

import time

from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton, QScrollArea,
                             QToolButton, QVBoxLayout, QWidget)

from . import sdcard, sdk, theme
from .instances import ARCH_LABELS, GFX_LABELS, Instance
from .util import asset_pixmap


def demo_instance() -> Instance:
    return Instance(id="demo", title="Example - Android 11 for Games", avd_id="Example", arch="x86_64+arm",
                    api=30, api_label="Android 11 (API 30)", flavor="google_apis",
                    image_pkg="system-images;android-30;google_apis;x86_64", gfx="dx", install_dir="",
                    disk_mb=8192, alloc="dynamic", cores=4, ram_mb=4096,
                    fps=120, vsync=True, display="phone", created=time.time(), starred=True, star_ts=1.0)


def open_folder(path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class LaunchButton(QPushButton):
    rightClicked = pyqtSignal()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.RightButton:
            if self.isEnabled() and self.rect().contains(e.pos()):
                self.rightClicked.emit()
            e.accept()
            return
        super().mouseReleaseEvent(e)


class InstanceCard(QFrame):
    launch = pyqtSignal(object, bool)       # inst, recovery
    edit = pyqtSignal(object)
    star = pyqtSignal(object)
    delete = pyqtSignal(object)
    kill = pyqtSignal(object)
    devcontrol = pyqtSignal(object)
    apks = pyqtSignal(object, list)         # inst, .apk files dropped on the card

    def __init__(self, inst: Instance, demo: bool = False, parent=None):
        super().__init__(parent)
        self.inst = inst
        self.demo = demo
        self.state = "idle"
        self.core_ok = True
        self.setObjectName("card")
        self.setProperty("demo", "true" if demo else "false")
        self.setAcceptDrops(True)                      # drop .apk files on a running instance to install them

        icon = QLabel()
        icon.setPixmap(asset_pixmap("icon.png", 56))
        icon.setFixedSize(60, 60)
        icon.setAlignment(Qt.AlignCenter)
        self.lb_title = QLabel(inst.title)
        self.lb_title.setObjectName("cardTitle")
        flavor = sdk.FLAVORS.get(inst.flavor, (inst.flavor,))[0]
        self.lb_sub = QLabel(f"{inst.api_label}  \u2022  {flavor}  \u2022  {ARCH_LABELS.get(inst.arch, inst.arch)}")
        extra = f"{GFX_LABELS.get(inst.gfx, inst.gfx)}  \u2022  {inst.cores} cores  \u2022  {inst.ram_mb:,} MB RAM" \
                f"  \u2022  {inst.fps} FPS" + ("  \u2022  V-Sync" if inst.vsync else "") \
                + ("  \u2022  Cold Boot" if inst.boot == "cold" else "  \u2022  Quick Boot") \
                + (f"  \u2022  {sdcard.label_for(inst.sd_mb)} SD" if inst.sd_mb > 0 else "  \u2022  No SD card")
        self.lb_detail = QLabel(extra)
        self.lb_sub.setObjectName("muted")
        self.lb_detail.setObjectName("muted")
        self.lb_status = QLabel("")
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setMaximumHeight(8)
        self.bar.setTextVisible(False)
        self.bar.hide()

        self.btn_star = QToolButton()
        self.btn_star.setAutoRaise(True)
        self.btn_star.setStyleSheet("QToolButton { font-size: 18pt; padding: 0 4px; }")
        self.btn_star.setCursor(Qt.PointingHandCursor)
        self.btn_star.clicked.connect(lambda: None if self.demo else self.star.emit(self.inst))
        self.btn_dev = QPushButton("Dev Control")
        self.btn_dev.clicked.connect(lambda: None if self.demo else self.devcontrol.emit(self.inst))
        self.btn_edit = QPushButton("Settings")
        self.btn_edit.clicked.connect(lambda: None if self.demo else self.edit.emit(self.inst))
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setObjectName("dangerBtn")
        self.btn_delete.clicked.connect(lambda: None if self.demo else self.delete.emit(self.inst))
        self.btn_launch = LaunchButton("Launch")
        self.btn_launch.setObjectName("primary")
        self.btn_launch.setMinimumWidth(110)
        self.btn_launch.clicked.connect(lambda: None if self.demo else self.launch.emit(self.inst, False))
        self.btn_launch.rightClicked.connect(lambda: None if self.demo else self.launch.emit(self.inst, True))

        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.lb_title)
        text.addWidget(self.lb_sub)
        text.addWidget(self.lb_detail)
        text.addWidget(self.lb_status)
        text.addWidget(self.bar)
        for lab in (self.lb_title, self.lb_sub, self.lb_detail):
            lab.setWordWrap(True)                        # long text wraps instead of widening the card
            lab.setMinimumWidth(40)
        top = QHBoxLayout()                              # Dev Control + star on top, main buttons below
        top.setSpacing(8)
        top.addStretch(1)
        top.addWidget(self.btn_dev)
        top.addWidget(self.btn_star)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.btn_edit)
        buttons.addWidget(self.btn_delete)
        buttons.addWidget(self.btn_launch)
        right = QVBoxLayout()
        right.addLayout(top)
        right.addStretch(1)
        right.addLayout(buttons)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(14)
        lay.addWidget(icon, 0, Qt.AlignTop)
        lay.addLayout(text, 1)
        lay.addLayout(right)
        self._refresh()

    # ------------------------------------------------------------------ state
    def set_core_ok(self, ok: bool):
        self.core_ok = ok
        self._refresh()

    def set_state(self, state: str, text: str = ""):
        self.state = state
        self._status_text = text
        self._refresh()

    def _refresh(self):
        inst = self.inst
        self.btn_star.setText("\u2605" if inst.starred else "\u2606")
        self.btn_star.setStyleSheet("QToolButton { font-size: 18pt; padding: 0 4px; color: %s; }"
                                    % ("#e5a50a" if inst.starred else theme.hexcol("muted")))
        self.btn_star.setToolTip("Starred - kept at the top. Click to unstar" if inst.starred
                                 else "Star this instance to keep it at the top")
        idle = self.state == "idle"
        busy = self.state in ("checking", "starting", "booting")
        running = self.state in ("booted", "recovery")
        self.bar.setVisible(busy)
        text = getattr(self, "_status_text", "")
        if running:
            text = "Running" if self.state == "booted" else "Running in Recovery mode"
        self.lb_status.setText(text)
        self.lb_status.setObjectName("" if (busy or running) else "muted")
        if running:
            self.lb_status.setStyleSheet(f"color: {theme.hexcol('accent')}; font-weight: 600;")
        else:
            self.lb_status.setStyleSheet("")
        self.lb_status.setVisible(bool(text))
        self.btn_launch.setText("Launch" if idle else ("Running" if running else "Starting..."))
        self.btn_launch.setEnabled(self.demo or (self.core_ok and idle))
        if not self.core_ok and not self.demo:
            self.btn_launch.setToolTip("The emulator core isn't installed - press Download Core first.")
        else:
            self.btn_launch.setToolTip("Left click: start Android\nRight click: start in Android Recovery mode")

        self.btn_edit.setEnabled(self.demo or idle)
        self.btn_edit.setToolTip("Change this instance's settings" if (self.demo or idle)
                                 else "Close the instance before changing its settings.")
        self.btn_delete.setEnabled(self.demo or idle)
        self.btn_delete.setToolTip("Delete this instance and all of its files" if (self.demo or idle)
                                   else "Close the instance before deleting it.")
        can_dev = self.demo or self.state == "booted"
        self.btn_dev.setEnabled(can_dev)
        self.btn_dev.setToolTip("ADB tools for this instance: install APKs, browse files, logs, screenshots...\n"
                                "Tip: you can also drop .apk files on this card to install them." if can_dev
                                else "Available while Android is running.")

    # ------------------------------------------------------------------ drop .apk files to install
    @staticmethod
    def _dropped_apks(mime) -> list:
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile() and u.toLocalFile().lower().endswith(".apk")]

    def dragEnterEvent(self, e):
        if not self.demo and self.state == "booted" and self._dropped_apks(e.mimeData()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        files = self._dropped_apks(e.mimeData())
        if files and self.state == "booted":
            e.acceptProposedAction()
            self.apks.emit(self.inst, files)
        else:
            e.ignore()

    # ------------------------------------------------------------------ context menu
    def contextMenuEvent(self, e):
        if self.demo:
            return
        idle = self.state == "idle"
        menu = QMenu(self)
        a_rec = menu.addAction("Launch to Recovery mode")
        a_rec.setEnabled(self.core_ok and idle)
        a_dev = menu.addAction("Dev Control")
        a_dev.setEnabled(self.state == "booted")
        a_set = menu.addAction("Settings")
        a_set.setEnabled(idle)
        a_dir = menu.addAction("Open instance folder")
        a_dir.setEnabled(self.inst.root.exists())
        menu.addSeparator()
        a_kill = menu.addAction("Force close")
        a_kill.setEnabled(not idle)
        a_del = menu.addAction("Delete instance...")
        a_del.setEnabled(idle)
        act = menu.exec_(e.globalPos())
        if act == a_rec:
            self.launch.emit(self.inst, True)
        elif act == a_dev:
            self.devcontrol.emit(self.inst)
        elif act == a_set:
            self.edit.emit(self.inst)
        elif act == a_dir:
            open_folder(self.inst.root)
        elif act == a_kill:
            self.kill.emit(self.inst)
        elif act == a_del:
            self.delete.emit(self.inst)


class ManagerPage(QWidget):
    create_requested = pyqtSignal()
    launch = pyqtSignal(object, bool)
    edit = pyqtSignal(object)
    star = pyqtSignal(object)
    delete = pyqtSignal(object)
    kill = pyqtSignal(object)
    devcontrol = pyqtSignal(object)
    apks = pyqtSignal(object, list)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.core_ok = False
        self.cards: dict = {}
        self.states: dict = {}                       # inst.id -> (state, text), survives rebuilds

        title = QLabel("Instance manager")
        title.setObjectName("pageTitle")
        self.btn_create = QPushButton("+  Create instance")
        self.btn_create.setObjectName("primary")
        self.btn_create.setMinimumHeight(34)
        self.btn_create.clicked.connect(self.create_requested.emit)
        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.btn_create)

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(12, 8, 12, 8)
        self.lb_banner = QLabel("The emulator core is not installed. Everything that needs it is grayed out - "
                                "press Download Core at the top to get started.")
        self.lb_banner.setWordWrap(True)
        bl.addWidget(self.lb_banner)

        self.list_host = QWidget()
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 8, 0)
        self.list_lay.setSpacing(10)
        self.demo_card = InstanceCard(demo_instance(), demo=True)
        self.demo_card.hide()
        self.list_lay.addWidget(self.demo_card)
        self.empty = QLabel("No instances yet.\nPress \"Create instance\" to make your first Android device.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setObjectName("muted")
        self.list_lay.addWidget(self.empty)
        self.list_lay.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.list_host)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.addLayout(head)
        lay.addWidget(self.banner)
        lay.addWidget(self.scroll, 1)
        self.refresh()

    # ------------------------------------------------------------------ API
    def set_core_ok(self, ok: bool):
        self.core_ok = ok
        self.btn_create.setEnabled(ok)
        self.btn_create.setToolTip("" if ok else "Download the emulator core first")
        self.banner.setVisible(not ok)
        for c in self.cards.values():
            c.set_core_ok(ok)

    def set_demo(self, on: bool):
        self.demo_card.setVisible(on)
        self.empty.setVisible(not on and not self.store.items)

    def refresh(self):
        for c in self.cards.values():
            self.list_lay.removeWidget(c)
            c.deleteLater()
        self.cards = {}
        pos = self.list_lay.indexOf(self.demo_card) + 1
        for inst in self.store.sorted():
            card = InstanceCard(inst)
            card.launch.connect(self.launch)
            card.edit.connect(self.edit)
            card.star.connect(self.star)
            card.delete.connect(self.delete)
            card.kill.connect(self.kill)
            card.devcontrol.connect(self.devcontrol)
            card.apks.connect(self.apks)
            card.set_core_ok(self.core_ok)
            st = self.states.get(inst.id)
            if st:
                card.set_state(*st)
            self.list_lay.insertWidget(pos, card)
            pos += 1
            self.cards[inst.id] = card
        self.empty.setVisible(not self.store.items and not self.demo_card.isVisible())

    def set_state(self, inst: Instance, state: str, text: str = ""):
        if state == "idle":
            self.states.pop(inst.id, None)
        else:
            self.states[inst.id] = (state, text)
        card = self.cards.get(inst.id)
        if card:
            card.set_state(state, text)

    def running_ids(self) -> list:
        return [i for i, (s, _t) in self.states.items() if s != "idle"]
