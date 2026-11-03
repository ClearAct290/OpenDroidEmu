"""Instances: data model, persistence, and the stock-emulator AVD files ODE writes for them."""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import paths, sdk

ARCH_LABELS = {
    "x86": "x86",
    "x86_64": "x86_64",
    "x86+arm": "x86 + ARM apps",
    "x86_64+arm": "x86_64 + ARM apps",
    "arm64": "Standalone ARM (arm64)",
}
# arch key -> ABI of the system image it uses ("+arm" = x86 image with ARM app translation)
ABI_OF = {"x86": "x86", "x86_64": "x86_64", "x86+arm": "x86", "x86_64+arm": "x86_64", "arm64": "arm64-v8a"}
# ABI -> value of hw.cpu.arch in the AVD config
CPU_ARCH_OF = {"x86": "x86", "x86_64": "x86_64", "arm64-v8a": "arm64"}
# Google's x86 images translate ARM apps from Android 9, x86_64 images from Android 11.
ARM_MIN_API = {"x86": 28, "x86_64": 30}


def abi_for(arch: str) -> str:
    return ABI_OF.get(arch, "x86_64")


def translates_arm(arch: str) -> bool:
    """x86 / x86_64 image with ARM app translation (not the standalone ARM option)."""
    return arch.endswith("+arm")


GFX_LABELS = {"dx": "DirectX", "gl": "OpenGL", "vk": "Vulkan"}
GPU_MODE = {"dx": "angle_indirect", "gl": "host", "vk": "host"}

ALLOC_LABELS = {
    "dynamic": "Dynamic expansion (grows as used)",
    "prealloc": "Pre-allocated (full size up front)",
}

# key -> (label, width, height, dpi, orientation)
DISPLAYS = {
    "phone": ("Phone, portrait (1080 x 2400)", 1080, 2400, 420, "portrait"),
    "phone_land": ("Phone, landscape (2400 x 1080)", 2400, 1080, 420, "landscape"),
    "tablet": ("Tablet, landscape (2560 x 1600)", 2560, 1600, 320, "landscape"),
    "hd": ("HD, portrait (720 x 1280)", 720, 1280, 320, "portrait"),
}


def min_ram_for(api: int) -> int:
    """Android 17 (API 37) phone AVDs need at least 4 GB of RAM."""
    return 4096 if api >= 37 else 1024


@dataclass
class Instance:
    id: str
    title: str
    avd_id: str
    arch: str
    api: int
    api_label: str
    flavor: str
    image_pkg: str
    gfx: str
    install_dir: str
    shared_dir: str
    disk_mb: int
    alloc: str
    cores: int
    ram_mb: int
    fps: int
    vsync: bool
    display: str
    created: float
    starred: bool = False
    star_ts: float = 0.0

    @property
    def abi(self) -> str:
        return abi_for(self.arch)

    @property
    def cpu_arch(self) -> str:
        return CPU_ARCH_OF[self.abi]

    @property
    def arm(self) -> bool:
        """ARM *app translation* on an x86 image."""
        return translates_arm(self.arch)

    @property
    def standalone_arm(self) -> bool:
        return self.arch == "arm64"

    @property
    def root(self) -> Path:
        return Path(self.install_dir) / self.avd_id

    @property
    def avd_home(self) -> Path:
        return self.root / "avd"

    @property
    def avd_dir(self) -> Path:
        return self.avd_home / f"{self.avd_id}.avd"

    @property
    def log_path(self) -> Path:
        return self.root / "emulator.log"


class Store:
    def __init__(self):
        self.items: list = []
        self.load()

    def load(self):
        try:
            raw = json.loads(paths.INSTANCES_FILE.read_text(encoding="utf-8"))
        except Exception:
            raw = []
        known = {f.name for f in fields(Instance)}
        self.items = []
        for d in raw:
            try:
                self.items.append(Instance(**{k: v for k, v in d.items() if k in known}))
            except TypeError:
                continue

    def save(self):
        paths.INSTANCES_FILE.write_text(json.dumps([asdict(i) for i in self.items], indent=2),
                                        encoding="utf-8")

    def sorted(self) -> list:
        """Starred first (in the order they were starred), then newest first."""
        return sorted(self.items, key=lambda i: (not i.starred, i.star_ts if i.starred else -i.created))

    def add(self, inst: Instance):
        self.items.append(inst)
        self.save()

    def remove(self, inst: Instance):
        self.items = [i for i in self.items if i.id != inst.id]
        self.save()

    def toggle_star(self, inst: Instance):
        inst.starred = not inst.starred
        inst.star_ts = time.time() if inst.starred else 0.0
        self.save()


def make_avd_id(title: str, taken) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", title.strip()).strip("._-")[:48] or "ODE_Instance"
    low = {t.lower() for t in taken}
    name, n = base, 2
    while name.lower() in low:
        name, n = f"{base}_{n}", n + 1
    return name


# ------------------------------------------------------------- AVD files for the emulator
def config_text(inst: Instance) -> str:
    _label, width, height, dpi, orient = DISPLAYS[inst.display]
    flavor_label = sdk.FLAVORS[inst.flavor][0]
    sysdir = os.sep.join(inst.image_pkg.split(";")) + os.sep
    heap = 256 if inst.ram_mb <= 2048 else 512
    cfg = [
        ("AvdId", inst.avd_id),
        ("PlayStore.enabled", "true" if inst.flavor == "google_apis_playstore" else "false"),
        ("abi.type", inst.abi),
        ("avd.ini.displayname", inst.title),
        ("avd.ini.encoding", "UTF-8"),
        # "Dynamic" = thin-provisioned qcow2 userdata, "Pre-allocated" = raw image at full size
        ("disk.dataPartition.size", f"{inst.disk_mb}M"),
        ("userdata.useQcow2", "yes" if inst.alloc == "dynamic" else "no"),
        ("fastboot.forceColdBoot", "no"),
        ("hw.accelerometer", "yes"),
        ("hw.audioInput", "yes"),
        ("hw.audioOutput", "yes"),
        ("hw.battery", "yes"),
        ("hw.camera.back", "virtualscene" if inst.api >= 29 else "emulated"),
        ("hw.camera.front", "emulated"),
        ("hw.cpu.arch", inst.cpu_arch),
        ("hw.cpu.ncore", str(inst.cores)),
        ("hw.dPad", "no"),
        ("hw.device.manufacturer", "Google"),
        ("hw.device.name", "pixel"),
        ("hw.gps", "yes"),
        ("hw.gpu.enabled", "yes"),
        ("hw.gpu.mode", GPU_MODE[inst.gfx]),
        ("hw.initialOrientation", orient),
        ("hw.keyboard", "yes"),
        ("hw.lcd.density", str(dpi)),
        ("hw.lcd.height", str(height)),
        ("hw.lcd.width", str(width)),
        ("hw.lcd.vsync", str(inst.fps)),           # guest refresh rate = FPS cap
        ("hw.mainKeys", "no"),
        ("hw.ramSize", str(inst.ram_mb)),
        ("hw.sdCard", "no"),
        ("hw.sensors.orientation", "yes"),
        ("hw.sensors.proximity", "yes"),
        ("hw.trackBall", "no"),
        ("image.sysdir.1", sysdir),
        ("runtime.network.latency", "none"),
        ("runtime.network.speed", "full"),
        ("showDeviceFrame", "no"),
        ("skin.dynamic", "yes"),
        ("tag.display", flavor_label),
        ("tag.id", inst.flavor),
        ("vm.heapSize", str(heap)),
    ]
    return "\n".join(f"{k}={v}" for k, v in cfg) + "\n"


def write_avd(inst: Instance) -> None:
    """Create <install>/<id>/avd/<id>.avd/config.ini and <id>.ini (so no Java / avdmanager is needed)."""
    inst.avd_dir.mkdir(parents=True, exist_ok=True)
    (inst.avd_dir / "config.ini").write_text(config_text(inst), encoding="utf-8")
    target = inst.image_pkg.split(";")[1]
    ini = (f"avd.ini.encoding=UTF-8\npath={inst.avd_dir}\n"
           f"path.rel=avd{os.sep}{inst.avd_id}.avd\ntarget={target}\n")
    (inst.avd_home / f"{inst.avd_id}.ini").write_text(ini, encoding="utf-8")


def _rmtree(path: Path) -> None:
    """rmtree that also removes read-only files (Windows keeps some of the emulator's files read-only)."""
    def handler(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass                                    # reported by the caller: the folder is still there
    kw = {"onexc": handler} if sys.version_info >= (3, 12) else {"onerror": handler}
    shutil.rmtree(path, **kw)


def delete_files(inst: Instance) -> str:
    """Delete the instance's folder. Returns "" on success, otherwise a message for the user."""
    root = inst.root
    if not root.is_absolute() or len(root.parts) < 2 or root.name != inst.avd_id:
        return f"ODE refuses to delete an unexpected location:\n{root}"
    if not root.exists():
        return ""
    _rmtree(root)
    if root.exists():
        return ("Some files couldn't be deleted - they are probably still in use (is the emulator still "
                f"shutting down?).\n\n{root}\n\nClose anything that uses them and press Delete again.")
    return ""


# ------------------------------------------------------------- editing an existing instance
# Architecture, Android version (and with it the system image type) and disk space are fixed when an
# instance is created. Everything else can be edited.
LOCKED_NOTE = "Architecture, Android version and disk space can't be changed after an instance is created."


def has_disk_data(inst: Instance) -> bool:
    """True once the emulator has created disk images for the instance (i.e. after its first launch)."""
    try:
        for p in inst.avd_dir.iterdir():
            n = p.name.lower()
            if n.startswith(("userdata", "cache", "sdcard", "encryptionkey")) or n == "snapshots":
                return True
    except OSError:
        pass
    return inst.log_path.exists()


def relocate_unused(inst: Instance, new_install_dir: str) -> None:
    """Move an instance that was never started (its folder holds only ODE's own config files)."""
    old_root = inst.root
    inst.install_dir = new_install_dir
    write_avd(inst)
    if old_root != inst.root:
        _rmtree(old_root)


def diagnose_log(inst: Instance) -> str:
    """A plain-language reason for a failed start, found at the end of the emulator log ("" if unknown)."""
    try:
        with open(inst.log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 16384))
            tail = f.read().decode("utf-8", "replace").lower()
    except OSError:
        return ""
    if "is not supported by the qemu2 emulator" in tail:
        return ("The emulator refused to run this instance because its CPU type doesn't match your PC. Google's "
                "stock emulator runs x86 images on x86 PCs and ARM images on ARM PCs (like Apple Silicon). "
                "Create a new instance with an architecture that matches your PC.")
    if "requires hardware acceleration" in tail:
        return ("The emulator needs hardware acceleration: turn on virtualization in your BIOS and, on Windows, "
                "enable Windows Hypervisor Platform (or Hyper-V).")
    return ""


def recovery_ramdisk(inst: Instance):
    f = sdk.pkg_dir(inst.image_pkg) / "ramdisk-recovery.img"
    return f if f.exists() else None


def emulator_env(inst: Instance) -> dict:
    env = os.environ.copy()
    env["ANDROID_SDK_ROOT"] = str(paths.CORE_DIR)
    env["ANDROID_HOME"] = str(paths.CORE_DIR)
    env["ANDROID_AVD_HOME"] = str(inst.avd_home)
    return env


def emulator_args(inst: Instance, port: int, recovery: bool = False) -> list:
    args = [str(sdk.emulator_exe()), "-avd", inst.avd_id, "-port", str(port),
            "-gpu", GPU_MODE[inst.gfx]]
    features = []
    if inst.gfx == "vk":
        features.append("Vulkan")
    if inst.vsync:
        features.append("-GLAsyncSwap")            # synchronous swaps follow the display refresh
    if features:
        args += ["-feature", ",".join(features)]
    if recovery:
        args.append("-no-snapshot")
        ramdisk = recovery_ramdisk(inst)
        if ramdisk:
            args += ["-ramdisk", str(ramdisk)]
    return args
