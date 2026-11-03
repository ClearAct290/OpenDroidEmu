"""Instance manager page: instance cards (star / launch / config info) and the info dialog."""
from __future__ import annotations

import time

from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QMenu, QProgressBar,
                             QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget)

from . import instances, sdk, theme
from .instances import ARCH_LABELS, GFX_LABELS, Instance
from .util import asset_pixmap


def demo_instance() -> Instance:
    return Instance(id="demo", title="Example - Android 11 for Games", avd_id="Example", arch="x86_64+arm",
                    api=30, api_label="Android 11 (API 30)", flavor="google_apis",
                    image_pkg="system-images;android-30;google_apis;x86_64", gfx="dx", install_dir="",
                    shared_dir="", disk_mb=8192, alloc="dynamic", cores=4, ram_mb=4096, fps=120, vsync=True,
                    display="phone", created=time.time(), starred=True, star_ts=1.0)


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
    info = pyqtSignal(object)
    star = pyqtSignal(object)
    delete = pyqtSignal(object)

    def __init__(self, inst: Instance, demo: bool = False, parent=None):
        super().__init__(parent)
        self.inst = inst
        self.demo = demo
        self.state = "idle"
        self.core_ok = True
        self.setObjectName("card")
        self.setProperty("demo", "true" if demo else "false")

        icon = QLabel()
        icon.setPixmap(asset_pixmap("icon.png", 56))
        icon.setFixedSize(60, 60)
        icon.setAlignment(Qt.AlignCenter)
        self.lb_title = QLabel(inst.title)
        self.lb_title.setObjectName("cardTitle")
        flavor = sdk.FLAVORS.get(inst.flavor, (inst.flavor,))[0]
        self.lb_sub = QLabel(f"{inst.api_label}  \u2022  {flavor}  \u2022  {ARCH_LABELS.get(inst.arch, inst.arch)}")
        extra = f"{GFX_LABELS.get(inst.gfx, inst.gfx)}  \u2022  {inst.cores} cores  \u2022  {inst.ram_mb:,} MB RAM" \
                f"  \u2022  {inst.fps} FPS" + ("  \u2022  V-Sync" if inst.vsync else "")
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
        self.btn_info = QPushButton("Config Info")
        self.btn_info.clicked.connect(lambda: None if self.demo else self.info.emit(self.inst))
        self.btn_launch = LaunchButton("Launch")
        self.btn_launch.setObjectName("primary")
        self.btn_launch.setMinimumWidth(110)
        self.btn_launch.setToolTip("Left click: start Android\nRight click: start in Android Recovery mode")
        self.btn_launch.clicked.connect(lambda: None if self.demo else self.launch.emit(self.inst, False))
        self.btn_launch.rightClicked.connect(lambda: None if self.demo else self.launch.emit(self.inst, True))

        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.lb_title)
        text.addWidget(self.lb_sub)
        text.addWidget(self.lb_detail)
        text.addWidget(self.lb_status)
        text.addWidget(self.bar)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.btn_info)
        buttons.addWidget(self.btn_launch)
        right = QVBoxLayout()
        right.addWidget(self.btn_star, 0, Qt.AlignRight)
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
        self.btn_launch.setText("Launch" if self.state == "idle" else ("Running" if running else "Starting..."))
        self.btn_launch.setEnabled(self.demo or (self.core_ok and self.state == "idle"))
        if not self.core_ok and not self.demo:
            self.btn_launch.setToolTip("The emulator core isn't installed - press Download Core first.")
        else:
            self.btn_launch.setToolTip("Left click: start Android\nRight click: start in Android Recovery mode")

    # ------------------------------------------------------------------ context menu
    def contextMenuEvent(self, e):
        if self.demo:
            return
        menu = QMenu(self)
        a_rec = menu.addAction("Launch to Recovery mode")
        a_rec.setEnabled(self.core_ok and self.state == "idle")
        a_info = menu.addAction("Config Info")
        a_dir = menu.addAction("Open instance folder")
        a_dir.setEnabled(self.inst.root.exists())
        menu.addSeparator()
        a_del = menu.addAction("Delete instance...")
        a_del.setEnabled(self.state == "idle")
        act = menu.exec_(e.globalPos())
        if act == a_rec:
            self.launch.emit(self.inst, True)
        elif act == a_info:
            self.info.emit(self.inst)
        elif act == a_dir:
            open_folder(self.inst.root)
        elif act == a_del:
            self.delete.emit(self.inst)


class ManagerPage(QWidget):
    create_requested = pyqtSignal()
    launch = pyqtSignal(object, bool)
    info = pyqtSignal(object)
    star = pyqtSignal(object)
    delete = pyqtSignal(object)

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
            card.info.connect(self.info)
            card.star.connect(self.star)
            card.delete.connect(self.delete)
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


class ConfigDialog(QDialog):
    def __init__(self, parent, inst: Instance):
        super().__init__(parent)
        self.setWindowTitle(f"Config Info - {inst.title}")
        self.setMinimumWidth(520)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(16)
        for k, v in instances.describe(inst):
            lab = QLabel(v)
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            key = QLabel(f"<b>{k}</b>")
            form.addRow(key, lab)
        note = QLabel("These settings were fixed when the instance was created.")
        note.setObjectName("muted")
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        folder = QPushButton("Open instance folder")
        folder.setEnabled(inst.root.exists())
        folder.clicked.connect(lambda: open_folder(inst.root))
        row = QHBoxLayout()
        row.addWidget(folder)
        row.addStretch(1)
        row.addWidget(close)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.addLayout(form)
        lay.addSpacing(6)
        lay.addWidget(note)
        lay.addSpacing(6)
        lay.addLayout(row)

    def showEvent(self, e):
        super().showEvent(e)
        # word-wrapped rows: make the height fit the width the dialog really has (Qt sizes it for the hint width)
        self.layout().activate()
        self.resize(self.width(), max(self.height(), self.layout().totalHeightForWidth(self.width())))
