"""The 'Create instance' page. The same page edits an existing instance: architecture, Android version
(with the system image type) and disk space are greyed out then, everything else can be changed."""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSpinBox,
                             QVBoxLayout, QWidget)

from . import instances, paths, sdk, system
from .instances import ARCH_LABELS, ARM_MIN_API, DISPLAYS, GFX_LABELS, ALLOC_LABELS, Instance
from .util import run_task

CREATE_SUB = ("Pick what you need. " + instances.LOCKED_NOTE.replace(" after an instance is created", " afterwards")
              + " Everything else can be changed later with Settings.")
EDIT_SUB = ("Greyed-out settings can't be changed after an instance is created. Everything else can be edited "
            "here while the instance is closed.")


def _row(*widgets) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    for x in widgets:
        lay.addWidget(x, 1 if isinstance(x, (QLineEdit, QComboBox)) else 0)
    return w


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


class CreatePage(QWidget):
    created = pyqtSignal(object)         # Instance
    saved = pyqtSignal(object)           # Instance (edited)
    cancelled = pyqtSignal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.edit_inst = None            # the Instance being edited, or None when creating
        self._all: list = []             # system image packages of the current flavor
        self._all_flavor = ""
        self._req = 0
        self._display_touched = False
        self._loading = False
        self._error = ""

        self.lb_page = QLabel("Create instance")
        self.lb_page.setObjectName("pageTitle")
        self.lb_sub = QLabel(CREATE_SUB)
        self.lb_sub.setObjectName("muted")
        self.lb_sub.setWordWrap(True)
        self.lb_files = QLabel("")
        self.lb_files.setObjectName("muted")
        self.lb_files.setWordWrap(True)
        self.lb_files.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lb_files.hide()

        # ---- Basics
        self.grp_basic = QGroupBox("Basics")
        self.ed_title = QLineEdit()
        self.ed_title.setPlaceholderText("e.g. Android 11 - Games")
        self.ed_title.setMaxLength(60)
        self.cb_arch = QComboBox()
        for key, label in ARCH_LABELS.items():
            self.cb_arch.addItem(label, key)
        self.cb_arch.setCurrentIndex(self.cb_arch.findData("x86_64"))
        self.lb_host = QLabel("")
        self.lb_host.setObjectName("warn")
        self.lb_host.setWordWrap(True)
        self.lb_host.hide()
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
        f.addRow(self.lb_host)
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
        self.sp_disk.setToolTip("The size of Android's internal storage (its data partition).")
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
        lay.addWidget(self.lb_page)
        lay.addWidget(self.lb_sub)
        lay.addWidget(self.lb_files)
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
        self.btn_create.clicked.connect(self._on_save)
        self._arch_changed()
        self._update_free()

    # ------------------------------------------------------------------ public
    def reset(self):
        """A fresh 'create' form each time the page is opened."""
        self._set_editing(None)
        self.ed_title.clear()
        self.lb_status.setText("")
        self.ed_shared.clear()
        self.ed_install.setText(str(paths.INSTANCES_DIR))
        self._display_touched = False
        self._apply_defaults()
        self._arch_changed()                       # flavor items, host note (+ versions if already loaded)
        loaded = self._all and not self._error and self._all_flavor == self.cb_flavor.currentData()
        if not loaded:
            self._reload_versions()
        self._update_free()

    def edit(self, inst: Instance):
        """Open the form filled with an existing instance."""
        self._req += 1                             # forget any version list still being loaded
        self._loading = False
        self._set_editing(inst)
        self.lb_status.setText("")
        self._display_touched = True
        started = time.strftime("%Y-%m-%d %H:%M", time.localtime(inst.created))
        self.lb_files.setText(f"Instance files: {inst.root}     \u2022     Created {started}")

        for w in (self.cb_arch, self.cb_flavor, self.cb_version):
            w.blockSignals(True)
        self.cb_arch.setCurrentIndex(self.cb_arch.findData(inst.arch))
        self.cb_flavor.setCurrentIndex(self.cb_flavor.findData(inst.flavor))
        self.cb_version.clear()
        self.cb_version.addItem(inst.api_label)
        for w in (self.cb_arch, self.cb_flavor, self.cb_version):
            w.blockSignals(False)
        self.lb_version.setText("")
        self.lb_version.hide()
        self._update_host_note()

        self.ed_title.setText(inst.title)
        self.cb_display.setCurrentIndex(max(0, self.cb_display.findData(inst.display)))
        gfx_i = self.cb_gfx.findData(inst.gfx)
        if gfx_i >= 0:
            self.cb_gfx.setCurrentIndex(gfx_i)
        self._gfx_changed()
        self.ed_shared.setText(inst.shared_dir)
        self.ed_install.setText(inst.install_dir)
        movable = not instances.has_disk_data(inst)
        for w in (self.ed_install, self.btn_install):
            w.setEnabled(movable)
        self.ed_install.setToolTip("" if movable else
                                   "Can't be moved after the first launch - that could damage the disk image. "
                                   "Create a new instance to use another folder.")
        self.sp_disk.setRange(min(2048, inst.disk_mb), max(1048576, inst.disk_mb))
        self.sp_disk.setValue(inst.disk_mb)
        self.cb_alloc.setCurrentIndex(max(0, self.cb_alloc.findData(inst.alloc)))
        self.sp_cores.setRange(1, max(system.max_cores(), inst.cores))
        self.sp_cores.setValue(inst.cores)
        self._update_ram_limits(inst.api, keep=inst.ram_mb)
        self.sp_fps.setValue(inst.fps)
        self.ck_vsync.setChecked(inst.vsync)
        self.btn_create.setEnabled(True)
        self._update_free()

    # ------------------------------------------------------------------ mode
    def _set_editing(self, inst):
        self.edit_inst = inst
        editing = inst is not None
        self.lb_page.setText("Edit instance" if editing else "Create instance")
        self.lb_sub.setText(EDIT_SUB if editing else CREATE_SUB)
        self.btn_create.setText("Save" if editing else "Create")
        self.lb_files.setVisible(editing)
        for w in (self.cb_arch, self.cb_flavor, self.sp_disk, self.cb_alloc):
            w.setEnabled(not editing)
        if editing:
            self.cb_version.setEnabled(False)
        for w in (self.ed_install, self.btn_install):
            w.setEnabled(True)
        self.ed_install.setToolTip("")

    def _apply_defaults(self):
        """Default values of a new instance (the form may still hold an edited instance's values)."""
        combos = (self.cb_arch, self.cb_flavor, self.cb_display, self.cb_alloc)
        for w in combos:
            w.blockSignals(True)
        self.cb_arch.setCurrentIndex(self.cb_arch.findData("x86_64"))
        self.cb_flavor.setCurrentIndex(0)
        self.cb_display.setCurrentIndex(0)
        self.cb_alloc.setCurrentIndex(0)
        for w in combos:
            w.blockSignals(False)
        self.sp_disk.setRange(2048, 1048576)
        self.sp_disk.setValue(8192)
        self.sp_cores.setRange(1, system.max_cores())
        self.sp_cores.setValue(min(4, system.max_cores()))
        self.sp_fps.setValue(60)
        self.ck_vsync.setChecked(False)
        self._ram_inited = False
        self._fill_graphics()

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
        arch = self.cb_arch.currentData()
        translated = instances.translates_arm(arch)
        item = self.cb_flavor.model().item(self.cb_flavor.findData("default"))
        item.setEnabled(not translated)                # ARM translation ships with the Google images
        if translated and self.cb_flavor.currentData() == "default":
            self.cb_flavor.setCurrentIndex(self.cb_flavor.findData("google_apis"))
            self._update_host_note()
            return                                     # flavor change reloads the list
        self._update_host_note()
        if self._all and self._all_flavor == self.cb_flavor.currentData():
            self._fill_versions()

    def _update_host_note(self):
        """Google's emulator only runs system images made for the PC's own CPU type."""
        arch = self.cb_arch.currentData()
        text = ""
        if arch == "arm64" and not system.host_is_arm():
            text = ("Heads up: on an x86 PC Google's emulator generally can't run standalone ARM images - the instance "
                    "stops right after launch with a \"CPU architecture not supported\" error. This option is for "
                    "ARM64 PCs. To run ARM-only apps on this PC use \"x86 / x86_64 + ARM apps\".")
        elif arch != "arm64" and system.host_is_arm():
            text = "Heads up: this is an ARM64 PC. x86 images can't run on it - choose Standalone ARM instead."
        self.lb_host.setText(text)
        self.lb_host.setVisible(bool(text))

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
        run_task(lambda: sdk.get_system_images(flavor),
                 lambda res, err: self._got_versions(req, flavor, res, err))

    def _got_versions(self, req, flavor, res, err):
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
        self._all_flavor = flavor
        self._fill_versions()

    def _fill_versions(self):
        arch = self.cb_arch.currentData()
        abi = instances.abi_for(arch)
        translated = instances.translates_arm(arch)
        pkgs = [p for p in self._all if p.abi == abi and (not translated or p.api >= ARM_MIN_API[abi])]
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
        if self.edit_inst is not None:
            return
        pkg = self.current_pkg()
        self.btn_create.setEnabled(pkg is not None)
        arch = self.cb_arch.currentData()
        translated = instances.translates_arm(arch)
        if pkg is None:
            if translated:
                self.lb_version.setText("ARM app translation needs Android 9+ (x86) or Android 11+ (x86_64).")
            elif arch == "arm64":
                self.lb_version.setText("Google doesn't offer standalone ARM images of this type right now.")
            else:
                self.lb_version.setText("")
            self.lb_version.setVisible(bool(self.lb_version.text()))
            return
        notes = []
        if translated:
            notes.append("ARM apps run through Google's translation layer.")
        if pkg.api < 21:
            notes.append("Old Android versions may not work perfectly with the newest emulator.")
        self.lb_version.setText(" ".join(notes))
        self.lb_version.setVisible(bool(notes))
        if not self._display_touched:
            self.cb_display.setCurrentIndex(self.cb_display.findData("hd" if pkg.api <= 24 else "phone"))
        self._update_ram_limits(pkg.api)

    def _update_ram_limits(self, api: int, keep: int = None):
        need = instances.min_ram_for(api)
        cap = system.max_ram_mb()
        lo, hi = need, max(need, cap)
        first = not getattr(self, "_ram_inited", False)
        self.sp_ram.setRange(lo, max(hi, keep or 0))    # Qt clamps an existing value into the new range
        if keep is not None:
            self.sp_ram.setValue(keep)
            self._ram_inited = True
        elif first:
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
        inst = self.edit_inst
        free = system.free_mb(self.ed_install.text().strip() or paths.INSTANCES_DIR)
        txt = f"Free space on that drive: {free:,} MB."
        bad = False
        if inst is not None:
            if instances.has_disk_data(inst):
                txt += " Disk size and location are fixed after the first launch."
            else:
                txt += " Not started yet, so the folder can still be moved."
        else:
            need = self.sp_disk.value()
            prealloc = self.cb_alloc.currentData() == "prealloc"
            bad = prealloc and free < need + 512
            if prealloc:
                txt += " Pre-allocated reserves the full disk limit right away."
            else:
                txt += " Dynamic only uses the space Android actually needs, up to the limit."
            if bad:
                txt += " Not enough room for pre-allocation!"
        self.lb_free.setObjectName("danger" if bad else "muted")
        self.lb_free.setText(txt)
        self.lb_free.style().unpolish(self.lb_free)
        self.lb_free.style().polish(self.lb_free)

    # ------------------------------------------------------------------ save
    def _fail(self, text: str):
        self.lb_status.setText(text)

    def _on_save(self):
        self.lb_status.setText("")
        title = self.ed_title.text().strip()
        gfx = self.cb_gfx.currentData()
        if not title:
            return self._fail("Please type a title for the instance.")
        if not system.detect_graphics()[gfx][0]:
            return self._fail(f"The {GFX_LABELS[gfx]} API is not supported on your system - pick another one.")
        shared = self.ed_shared.text().strip()
        if shared and not Path(shared).is_dir():
            return self._fail("The shared folder doesn't exist.")
        if self.edit_inst is not None:
            return self._save_edit(title, gfx, shared)
        return self._save_new(title, gfx, shared)

    def _save_new(self, title: str, gfx: str, shared: str):
        pkg = self.current_pkg()
        if pkg is None:
            return self._fail("Please pick an Android version.")
        install = self.ed_install.text().strip()
        if not install:
            return self._fail("Please choose where to install the instance files.")
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

    def _save_edit(self, title: str, gfx: str, shared: str):
        inst = self.edit_inst
        install = self.ed_install.text().strip()
        move = False
        if instances.has_disk_data(inst):
            install = inst.install_dir                  # locked once the emulator has created disk images
        else:
            if not install:
                return self._fail("Please choose where to install the instance files.")
            if _norm(install) != _norm(inst.install_dir):
                if (Path(install) / inst.avd_id).exists():
                    return self._fail(f"There is already a folder named \"{inst.avd_id}\" in that location.")
                try:
                    Path(install).mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    return self._fail(f"Can't use that install location: {exc}")
                free = system.free_mb(install)
                need = inst.disk_mb + 512 if inst.alloc == "prealloc" else 1536
                if free < need:
                    return self._fail("The new install drive doesn't have enough free space.")
                move = True

        keep = (inst.title, inst.gfx, inst.display, inst.shared_dir, inst.cores, inst.ram_mb, inst.fps,
                inst.vsync, inst.install_dir)
        inst.title, inst.gfx, inst.display, inst.shared_dir = title, gfx, self.cb_display.currentData(), shared
        inst.cores, inst.ram_mb, inst.fps = self.sp_cores.value(), self.sp_ram.value(), self.sp_fps.value()
        inst.vsync = self.ck_vsync.isChecked()
        try:
            if move:
                instances.relocate_unused(inst, install)
            else:
                instances.write_avd(inst)
            self.store.save()
        except OSError as exc:
            (inst.title, inst.gfx, inst.display, inst.shared_dir, inst.cores, inst.ram_mb, inst.fps,
             inst.vsync, inst.install_dir) = keep
            return self._fail(f"Couldn't save the changes: {exc}")
        self.saved.emit(inst)
