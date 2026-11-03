"""The 'Create instance' page."""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
                             QSpinBox, QVBoxLayout, QWidget)

from . import instances, paths, sdk, system
from .instances import ARCH_LABELS, ARM_MIN_API, DISPLAYS, GFX_LABELS, ALLOC_LABELS, Instance
from .util import run_task


def _row(*widgets) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    for x in widgets:
        lay.addWidget(x, 1 if isinstance(x, (QLineEdit, QComboBox)) else 0)
    return w


class CreatePage(QWidget):
    created = pyqtSignal(object)         # Instance
    cancelled = pyqtSignal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._all: list = []             # system image packages of the current flavor
        self._req = 0
        self._display_touched = False
        self._loading = False
        self._error = ""

        title = QLabel("Create instance")
        title.setObjectName("pageTitle")
        sub = QLabel("Pick what you need. Settings can't be changed after the instance is saved.")
        sub.setObjectName("muted")

        # ---- Basics
        self.grp_basic = QGroupBox("Basics")
        self.ed_title = QLineEdit()
        self.ed_title.setPlaceholderText("e.g. Android 11 - Games")
        self.ed_title.setMaxLength(60)
        self.cb_arch = QComboBox()
        for key, label in ARCH_LABELS.items():
            self.cb_arch.addItem(label, key)
        self.cb_arch.setCurrentIndex(self.cb_arch.findData("x86_64"))
        self.cb_flavor = QComboBox()
        for key, (label, _sub) in sdk.FLAVORS.items():
            self.cb_flavor.addItem(label, key)
        self.cb_version = QComboBox()
        self.cb_version.setMinimumWidth(260)
        self.lb_version = QLabel("")
        self.lb_version.setObjectName("muted")
        self.lb_version.setWordWrap(True)
        self.cb_display = QComboBox()
        for key, d in DISPLAYS.items():
            self.cb_display.addItem(d[0], key)
        f = QFormLayout(self.grp_basic)
        f.setLabelAlignment(Qt.AlignRight)
        f.addRow("Title", self.ed_title)
        f.addRow("Architecture", self.cb_arch)
        f.addRow("System image", self.cb_flavor)
        f.addRow("Android version", self.cb_version)
        f.addRow(self.lb_version)
        f.addRow("Display", self.cb_display)

        # ---- Graphics
        self.grp_gfx = QGroupBox("Graphics API")
        self.cb_gfx = QComboBox()
        self.lb_gfx = QLabel("")
        self.lb_gfx.setWordWrap(True)
        g = QVBoxLayout(self.grp_gfx)
        g.addWidget(self.cb_gfx)
        g.addWidget(self.lb_gfx)
        self._fill_graphics()

        # ---- Storage
        self.grp_storage = QGroupBox("Storage")
        self.ed_install = QLineEdit(str(paths.INSTANCES_DIR))
        self.ed_install.setMinimumWidth(60)
        self.btn_install = QPushButton("Browse...")
        self.ed_shared = QLineEdit()
        self.ed_shared.setPlaceholderText("Optional - exchange files with Android")
        self.ed_shared.setMinimumWidth(60)
        self.btn_shared = QPushButton("Browse...")
        self.btn_shared_clear = QPushButton("\u2715")
        self.btn_shared_clear.setToolTip("Clear the shared folder")
        self.btn_shared_clear.setFixedWidth(34)
        self.sp_disk = QSpinBox()
        self.sp_disk.setRange(2048, 1048576)
        self.sp_disk.setSingleStep(1024)
        self.sp_disk.setSuffix(" MB")
        self.sp_disk.setValue(8192)
        self.sp_disk.setGroupSeparatorShown(True)
        self.cb_alloc = QComboBox()
        for key, label in ALLOC_LABELS.items():
            self.cb_alloc.addItem(label, key)
        self.lb_free = QLabel("")
        self.lb_free.setObjectName("muted")
        self.lb_free.setWordWrap(True)
        s = QFormLayout(self.grp_storage)
        s.setLabelAlignment(Qt.AlignRight)
        s.addRow("Install to", _row(self.ed_install, self.btn_install))
        s.addRow("Shared folder", _row(self.ed_shared, self.btn_shared, self.btn_shared_clear))
        s.addRow("Disk limit", self.sp_disk)
        s.addRow("Allocation", self.cb_alloc)
        s.addRow(self.lb_free)

        # ---- Performance
        self.grp_perf = QGroupBox("Performance")
        self.sp_cores = QSpinBox()
        self.sp_cores.setRange(1, system.max_cores())
        self.sp_cores.setValue(min(4, system.max_cores()))
        self.lb_cores = QLabel(f"of {system.max_cores()}")
        self.lb_cores.setToolTip(f"Your CPU has {system.host_cpus()} threads; 2 always stay free for Windows.")
        self.lb_cores.setObjectName("muted")
        self.sp_ram = QSpinBox()
        self.sp_ram.setSingleStep(256)
        self.sp_ram.setSuffix(" MB")
        self.sp_ram.setGroupSeparatorShown(True)
        self.lb_ram = QLabel("")
        self.lb_ram.setObjectName("muted")
        self.lb_ram.setWordWrap(True)
        self.sp_fps = QSpinBox()
        self.sp_fps.setRange(30, 240)
        self.sp_fps.setValue(60)
        self.sp_fps.setSuffix(" FPS")
        self.ck_vsync = QCheckBox("Enable V-Sync")
        p = QFormLayout(self.grp_perf)
        p.setLabelAlignment(Qt.AlignRight)
        p.addRow("CPU cores", _row(self.sp_cores, self.lb_cores))
        p.addRow("RAM", self.sp_ram)
        p.addRow(self.lb_ram)
        p.addRow("Max FPS", self.sp_fps)
        p.addRow("", self.ck_vsync)

        # ---- buttons
        self.btn_cancel = QPushButton("Cancel")
        self.btn_create = QPushButton("Create")
        self.btn_create.setObjectName("primary")
        self.btn_create.setMinimumWidth(110)
        self.lb_status = QLabel("")
        self.lb_status.setWordWrap(True)
        self.lb_status.setObjectName("danger")
        bottom = QHBoxLayout()
        bottom.addWidget(self.lb_status, 1)
        bottom.addWidget(self.btn_cancel)
        bottom.addWidget(self.btn_create)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 8, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.addWidget(self.grp_basic)
        left.addWidget(self.grp_gfx)
        left.addStretch(1)
        right.addWidget(self.grp_storage)
        right.addWidget(self.grp_perf)
        right.addStretch(1)
        grid.addLayout(left, 0, 0)
        grid.addLayout(right, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(grid_host)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addSpacing(4)
        lay.addWidget(self.scroll, 1)
        lay.addLayout(bottom)

        # ---- wiring
        self.cb_arch.currentIndexChanged.connect(self._arch_changed)
        self.cb_flavor.currentIndexChanged.connect(self._reload_versions)
        self.cb_version.currentIndexChanged.connect(self._version_changed)
        self.cb_gfx.currentIndexChanged.connect(self._gfx_changed)
        self.cb_display.activated.connect(lambda _i: setattr(self, "_display_touched", True))
        self.btn_install.clicked.connect(lambda: self._browse(self.ed_install))
        self.btn_shared.clicked.connect(lambda: self._browse(self.ed_shared))
        self.btn_shared_clear.clicked.connect(self.ed_shared.clear)
        self.ed_install.textChanged.connect(self._update_free)
        self.sp_disk.valueChanged.connect(self._update_free)
        self.cb_alloc.currentIndexChanged.connect(self._update_free)
        self.btn_cancel.clicked.connect(self.cancelled.emit)
        self.btn_create.clicked.connect(self._on_create)
        self._arch_changed()
        self._update_free()

    # ------------------------------------------------------------------ public
    def reset(self):
        """Fresh form each time the page is opened."""
        self.ed_title.clear()
        self.lb_status.setText("")
        self.ed_shared.clear()
        self.ed_install.setText(str(paths.INSTANCES_DIR))
        self._display_touched = False
        if not self._all or self._error:
            self._reload_versions()

    # ------------------------------------------------------------------ graphics
    def _fill_graphics(self):
        gfx = system.detect_graphics()
        self.cb_gfx.blockSignals(True)
        self.cb_gfx.clear()
        first_ok = -1
        for i, key in enumerate(("dx", "gl", "vk")):
            ok, _msg = gfx[key]
            label = GFX_LABELS[key] + ("" if ok else "  - not supported on your system")
            self.cb_gfx.addItem(label, key)
            self.cb_gfx.model().item(i).setEnabled(ok)
            if ok and first_ok < 0:
                first_ok = i
        self.cb_gfx.setCurrentIndex(max(first_ok, 0))
        self.cb_gfx.blockSignals(False)
        self._gfx_changed()

    def _gfx_changed(self):
        key = self.cb_gfx.currentData()
        ok, msg = system.detect_graphics()[key]
        if ok:
            self.lb_gfx.setObjectName("muted")
            self.lb_gfx.setText(f"{GFX_LABELS[key]} is supported. {msg}")
        else:
            self.lb_gfx.setObjectName("danger")
            self.lb_gfx.setText(f"The {GFX_LABELS[key]} API is not supported on your system. {msg}")
        self.lb_gfx.style().unpolish(self.lb_gfx)
        self.lb_gfx.style().polish(self.lb_gfx)

    # ------------------------------------------------------------------ versions
    def _arch_changed(self):
        arm = self.cb_arch.currentData().endswith("+arm")
        item = self.cb_flavor.model().item(self.cb_flavor.findData("default"))
        item.setEnabled(not arm)                       # ARM translation ships with the Google images
        if arm and self.cb_flavor.currentData() == "default":
            self.cb_flavor.setCurrentIndex(self.cb_flavor.findData("google_apis"))
            return                                     # flavor change reloads the list
        if self._all:
            self._fill_versions()

    def _reload_versions(self):
        flavor = self.cb_flavor.currentData()
        self._req += 1
        req = self._req
        self._loading = True
        self._error = ""
        self.cb_version.blockSignals(True)
        self.cb_version.clear()
        self.cb_version.addItem("Loading Android versions...")
        self.cb_version.blockSignals(False)
        self.cb_version.setEnabled(False)
        self.lb_version.setText("")
        self.lb_version.hide()
        self.btn_create.setEnabled(False)
        run_task(lambda: sdk.get_system_images(flavor), lambda res, err: self._got_versions(req, res, err))

    def _got_versions(self, req, res, err):
        if req != self._req:
            return                                     # a newer request replaced this one
        self._loading = False
        if err:
            self._all = []
            self._error = str(err)
            self.cb_version.clear()
            self.cb_version.addItem("Couldn't load the version list")
            self.lb_version.setText(f"{err}\nReopen this page or change the image type to try again.")
            self.lb_version.show()
            return
        self._all = res
        self._fill_versions()

    def _fill_versions(self):
        abi = self.cb_arch.currentData().split("+")[0]
        arm = self.cb_arch.currentData().endswith("+arm")
        pkgs = [p for p in self._all if p.abi == abi and (not arm or p.api >= ARM_MIN_API[abi])]
        self.cb_version.blockSignals(True)
        self.cb_version.clear()
        for p in pkgs:                                  # already sorted oldest -> newest
            self.cb_version.addItem(p.api_label, p)
        self.cb_version.blockSignals(False)
        if pkgs:
            self.cb_version.setEnabled(True)
            self.cb_version.setCurrentIndex(len(pkgs) - 1)
        else:
            self.cb_version.addItem("No matching Android versions")
            self.cb_version.setEnabled(False)
        self._version_changed()

    def current_pkg(self):
        return self.cb_version.currentData() if self.cb_version.isEnabled() else None

    def _version_changed(self):
        pkg = self.current_pkg()
        self.btn_create.setEnabled(pkg is not None)
        if pkg is None:
            arm = self.cb_arch.currentData().endswith("+arm")
            self.lb_version.setText("ARM app translation needs Android 9+ (x86) or Android 11+ (x86_64)."
                                    if arm else "")
            self.lb_version.setVisible(arm)
            return
        arm = self.cb_arch.currentData().endswith("+arm")
        notes = []
        if arm:
            notes.append("ARM apps run through Google's translation layer.")
        if pkg.api < 21:
            notes.append("Old Android versions may not work perfectly with the newest emulator.")
        self.lb_version.setText(" ".join(notes))
        self.lb_version.setVisible(bool(notes))
        if not self._display_touched:
            self.cb_display.setCurrentIndex(self.cb_display.findData("hd" if pkg.api <= 24 else "phone"))
        self._update_ram_limits(pkg.api)

    def _update_ram_limits(self, api: int):
        need = instances.min_ram_for(api)
        cap = system.max_ram_mb()
        lo, hi = need, max(need, cap)
        first = not getattr(self, "_ram_inited", False)
        self.sp_ram.setRange(lo, hi)                    # Qt clamps an existing value into the new range
        if first:
            self.sp_ram.setValue(min(max(2048, lo), hi))
            self._ram_inited = True
        if cap < need:
            self.lb_ram.setObjectName("warn")
            self.lb_ram.setText(f"This Android version needs at least {need:,} MB, but ODE allows at most half of "
                                f"your RAM ({cap:,} MB). It may not run well.")
        else:
            self.lb_ram.setObjectName("muted")
            self.lb_ram.setText(f"Allowed: {lo:,} - {hi:,} MB (max is half of your {system.total_ram_mb():,} MB).")
        self.lb_ram.style().unpolish(self.lb_ram)
        self.lb_ram.style().polish(self.lb_ram)

    # ------------------------------------------------------------------ storage
    def _browse(self, edit: QLineEdit):
        start = edit.text() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder", start)
        if folder:
            edit.setText(os.path.normpath(folder))

    def _update_free(self):
        free = system.free_mb(self.ed_install.text().strip() or paths.INSTANCES_DIR)
        need = self.sp_disk.value()
        prealloc = self.cb_alloc.currentData() == "prealloc"
        txt = f"Free space on that drive: {free:,} MB."
        bad = prealloc and free < need + 512
        if prealloc:
            txt += " Pre-allocated reserves the full disk limit right away."
        else:
            txt += " Dynamic only uses the space Android actually needs, up to the limit."
        self.lb_free.setObjectName("danger" if bad else "muted")
        if bad:
            txt += " Not enough room for pre-allocation!"
        self.lb_free.setText(txt)
        self.lb_free.style().unpolish(self.lb_free)
        self.lb_free.style().polish(self.lb_free)

    # ------------------------------------------------------------------ create
    def _fail(self, text: str):
        self.lb_status.setText(text)

    def _on_create(self):
        self.lb_status.setText("")
        title = self.ed_title.text().strip()
        pkg = self.current_pkg()
        gfx = self.cb_gfx.currentData()
        if not title:
            return self._fail("Please type a title for the instance.")
        if pkg is None:
            return self._fail("Please pick an Android version.")
        if not system.detect_graphics()[gfx][0]:
            return self._fail(f"The {GFX_LABELS[gfx]} API is not supported on your system - pick another one.")
        install = self.ed_install.text().strip()
        if not install:
            return self._fail("Please choose where to install the instance files.")
        shared = self.ed_shared.text().strip()
        if shared and not Path(shared).is_dir():
            return self._fail("The shared folder doesn't exist.")
        try:
            Path(install).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return self._fail(f"Can't use that install location: {exc}")
        free = system.free_mb(install)
        disk = self.sp_disk.value()
        if self.cb_alloc.currentData() == "prealloc" and free < disk + 512:
            return self._fail("Not enough free disk space to pre-allocate that much. Lower the disk limit "
                              "or use dynamic expansion.")
        if free < 1536:
            return self._fail("The install drive has less than 1.5 GB free.")

        r = QMessageBox.question(self, "Save instance?",
                                 f"Are you sure you want to save \"{title}\"?\n\n"
                                 "An instance can't be reconfigured afterwards. To change anything "
                                 "you have to create a new instance.",
                                 QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
        if r != QMessageBox.Ok:
            return
        taken = [i.avd_id for i in self.store.items]
        try:
            taken += os.listdir(install)
        except OSError:
            pass
        inst = Instance(
            id=uuid.uuid4().hex[:12], title=title, avd_id=instances.make_avd_id(title, taken),
            arch=self.cb_arch.currentData(), api=pkg.api, api_label=pkg.api_label,
            flavor=self.cb_flavor.currentData(), image_pkg=pkg.path, gfx=gfx,
            install_dir=install, shared_dir=shared, disk_mb=disk, alloc=self.cb_alloc.currentData(),
            cores=self.sp_cores.value(), ram_mb=self.sp_ram.value(), fps=self.sp_fps.value(),
            vsync=self.ck_vsync.isChecked(), display=self.cb_display.currentData(), created=time.time())
        try:
            instances.write_avd(inst)
        except OSError as exc:
            return self._fail(f"Couldn't write the instance files: {exc}")
        self.store.add(inst)
        self.created.emit(inst)
