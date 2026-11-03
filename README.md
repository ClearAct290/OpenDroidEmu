# OpenDroidEmu (ODE)

An open-source GUI that downloads, configures and launches Google's **stock Android Emulator** (the
one from Android Studio) - without installing Android Studio, Java or the command-line tools.
For gaming, app testing and everyday use. Free, no ads, no accounts, no bundled software.

> **OpenDroidEmu is not related to the OpenDroid Custom ROM project.**

## Features

- **Quick Setup guide** on first launch (Bugdroid points at every button, including an example instance and the
  floating sidebar). Reopen it any time with the **Guide** button. Has a *Don't show me again* checkbox and a
  light / dark switch.
- **Core download / update**: downloads only the emulator (+ ADB platform-tools) from Google into `core/`, with
  progress bar, speed and ETA. Downloads are SHA-1 verified. At startup ODE tells you when a newer emulator is out
  and shows its changelog; if you say no, an **Update Core** button appears where **Download Core** was.
- **Instance manager**: star instances to keep them on top, **Launch** (right click = Android *Recovery* mode),
  **Config Info**, delete.
- **Create instance**: title; x86 / x86_64 / x86 + ARM apps / x86_64 + ARM apps; Android version (oldest to newest
  available); graphics API (DirectX / OpenGL / Vulkan - unsupported ones are marked); install folder; optional
  shared folder; disk limit with *dynamic* or *pre-allocated* storage; CPU cores (host threads - 2); RAM (half of the
  host RAM); max FPS 30-240; V-Sync. Instances can't be reconfigured after saving.
- **First launch of an instance** asks before downloading its system image (size shown in MB).
- **Floating sidebar** once Android has booted (normal or Recovery): volume, Home, Back, Tasks, power, shared-folder
  send / get, and *Force close* (kills the emulator). Drag the **ODE** grip to move it; it follows the emulator window.

## Run from source

```
pip install -r requirements.txt
python OpenDroidEmu.py
```

Needs Python 3.9+ and PyQt5. Windows is the main target (DirectX detection and the sidebar following the emulator
window are Windows-only); it also starts on Linux / macOS.

## Build the .exe

Double-click **`build_exe.cmd`** (needs `pip install -r requirements.txt` once). It calls `pyinstaller` directly and
makes a folder build (not one-file) with no console window and `assets\icon.ico` as the icon:

```
dist\OpenDroidEmu\OpenDroidEmu.exe
```

Ship the whole `dist\OpenDroidEmu` folder. ODE is portable: next to the exe it creates

| Folder       | Contents                                                        |
|--------------|-----------------------------------------------------------------|
| `core\`      | emulator, platform-tools and downloaded system images           |
| `data\`      | `settings.json`, `instances.json`, cache, `ode_error.log`       |
| `instances\` | default place for instance files (you can pick another per instance) |

If the program folder is read-only (e.g. *Program Files*), ODE falls back to `%LOCALAPPDATA%\OpenDroidEmu`.

## Notes

- **Hardware acceleration**: the emulator needs virtualization enabled in the BIOS and, on Windows, *Windows
  Hypervisor Platform* (or Hyper-V). ODE checks this on the first launch and warns you.
- **ARM apps**: Google's x86 images translate ARM apps from Android 9 (API 28), x86_64 images from Android 11 (API 30),
  so the ARM options only list those versions and newer.
- **Old Android versions** (2.x - 4.x) may not run perfectly on the newest emulator, and Google may no longer offer
  some images. ODE lists whatever Google's repository currently provides.
- **Storage**: *dynamic* uses a thin-provisioned (qcow2) data image that grows as needed up to the limit;
  *pre-allocated* uses a raw data image of the full size.
- **Shared folder**: the sidebar's sync button copies your host folder to `/sdcard/ODE_Shared` on the device (and back)
  using ADB.
- The emulator, platform-tools and system images come straight from Google's servers and are covered by the
  [Android SDK License Agreement](https://developer.android.com/studio/terms). Android is a trademark of Google LLC;
  ODE is not affiliated with Google.
- Unexpected errors are written to `data\ode_error.log`.
