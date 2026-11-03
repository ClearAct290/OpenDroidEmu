# OpenDroidEmu (ODE)

An open-source GUI that downloads, configures and launches Google's **stock Android Emulator** (the
one from Android Studio) - without installing Android Studio, Java or the command-line tools.
For gaming, app testing and everyday use. Free, no ads, no accounts, no bundled software.

> **OpenDroidEmu is not related to the OpenDroid Custom ROM project.**
<img width="432" height="319" alt="image" src="https://github.com/user-attachments/assets/c26867c7-490b-4b2c-a537-dd2126703a20" />

## Features

- **Quick Setup guide** on first launch (Bugdroid points at every button, including an example instance). Reopen it any time with the **Guide** button. Has a *Don't show me again* checkbox and a
  light / dark switch.
- **Core download / update**: downloads only the emulator (+ ADB platform-tools) from Google into `core/`, with
  progress bar, speed and ETA. Downloads are SHA-1 verified. At startup ODE tells you when a newer emulator is out
  and shows its changelog; if you say no, an **Update Core** button appears where **Download Core** was.
- **Instance manager**: star instances to keep them on top, **Launch** (right click = Android *Recovery* mode),
  **Settings**, **Delete**, and a **Shared folder** menu. Right click a card for *Force close* and more.
- **Create instance**: title; x86 / x86_64 / x86 + ARM apps / x86_64 + ARM apps / **Standalone ARM (arm64)**; Android
  version (oldest to newest available); graphics API (DirectX / OpenGL / Vulkan - unsupported ones are marked);
  install folder; optional shared folder; disk limit with *dynamic* or *pre-allocated* storage; CPU cores (host
  threads - 2); RAM (half of the host RAM); max FPS 30-240; V-Sync.
- **Edit instance**: press **Settings** on a card. Title, display, graphics API, shared folder, CPU cores, RAM, max FPS
  and V-Sync can be changed any time the instance is closed. **Architecture, Android version (with the system image
  type) and disk space are fixed** once the instance is created. The install folder can be changed until the
  instance has been started for the first time.
- **First launch of an instance** asks before downloading its system image (size shown in MB).
- **Shared folder** while Android is running: send your folder to Android, get files back, or get Android's
  Downloads onto your PC (see the notes below).
- **ODE updates**: at startup ODE reads `version.json` from this GitHub repository and tells you when a newer
  version is available - you then download it from GitHub yourself. See [CHANGELOG.md](CHANGELOG.md).

## Run from source

```
pip install -r requirements.txt
python OpenDroidEmu.py
```

Needs Python 3.9+ and PyQt5. Windows is the main target (DirectX detection is Windows-only); it also starts on Linux / macOS.

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
- **Standalone ARM**: Google's emulator runs system images made for your PC's own CPU type. On an **x86 PC** it
  generally refuses ARM images (it stops right after launch with *"CPU architecture 'arm64' is not supported"*), and
  on an **ARM64 PC** (Apple Silicon, Windows on ARM) it refuses x86 images. ODE lets you pick any option and warns you
  when it doesn't match your PC. To run ARM-only *apps* on an x86 PC use the *x86 / x86_64 + ARM apps* options.
- **Storage**: the disk limit is the size of Android's internal storage (its data partition). *Dynamic* uses a
  thin-provisioned (qcow2) data image that grows as needed up to the limit; *pre-allocated* uses a raw data image of
  the full size.
- **Shared folder**: the stock emulator has no live shared folders, so ODE copies files with ADB while Android is
  running. *Send* copies the items of your folder into `/sdcard/ODE_Shared` on the device (look for `ODE_Shared` in
  Android's Files app); *Get files* copies `ODE_Shared` back into your folder; *Get Android's Downloads* copies
  `/sdcard/Download` into a `Download` subfolder of your folder. ODE creates `ODE_Shared` when needed and waits for
  Android's storage to be ready after boot.
- **Updating ODE**: `version.json` in the root of the repository holds the current version number, e.g.
  `{"version": "1.0.1"}`. Bump it (and `APP_VERSION` in `ode/__init__.py`) for every release.
- The emulator, platform-tools and system images come straight from Google's servers and are covered by the
  [Android SDK License Agreement](https://developer.android.com/studio/terms). Android is a trademark of Google LLC;
  ODE is not affiliated with Google.
- Unexpected errors are written to `data\ode_error.log`.
