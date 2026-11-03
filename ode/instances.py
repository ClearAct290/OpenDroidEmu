"""Instances: data model, persistence, and the stock-emulator AVD files ODE writes for them."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import paths, sdk

ARCH_LABELS = {
    "x86": "x86",
    "x86_64": "x86_64",
    "x86+arm": "x86 + ARM apps",
    "x86_64+arm": "x86_64 + ARM apps",
}
# Google's x86 images translate ARM apps from Android 9, x86_64 images from Android 11.
ARM_MIN_API = {"x86": 28, "x86_64": 30}

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
        return "x86_64" if self.arch.startswith("x86_64") else "x86"

    @property
    def arm(self) -> bool:
        return self.arch.endswith("+arm")

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
        ("hw.cpu.arch", inst.abi),
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


def delete_files(inst: Instance) -> None:
    shutil.rmtree(inst.root, ignore_errors=True)


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


def describe(inst: Instance) -> list:
    return [
        ("Title", inst.title),
        ("Android version", inst.api_label),
        ("System image", f"{sdk.FLAVORS[inst.flavor][0]}  ({inst.image_pkg})"),
        ("Architecture", ARCH_LABELS[inst.arch]),
        ("Graphics API", GFX_LABELS[inst.gfx]),
        ("Display", DISPLAYS[inst.display][0]),
        ("CPU cores", str(inst.cores)),
        ("RAM", f"{inst.ram_mb:,} MB"),
        ("Disk limit", f"{inst.disk_mb:,} MB"),
        ("Disk allocation", ALLOC_LABELS[inst.alloc]),
        ("Max FPS", f"{inst.fps}   (V-Sync {'on' if inst.vsync else 'off'})"),
        ("Instance files", str(inst.root)),
        ("Shared folder", inst.shared_dir or "None"),
        ("Created", time.strftime("%Y-%m-%d %H:%M", time.localtime(inst.created))),
    ]
