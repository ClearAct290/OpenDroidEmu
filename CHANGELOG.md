# Changelog

All notable changes to OpenDroidEmu (ODE). A new entry is added with every update.

## 1.0.1

### Added
- **Standalone ARM (arm64)** in the architecture list, next to x86, x86_64 and the two "+ ARM apps" options.
  It lists Google's `arm64-v8a` system images. Google's emulator only runs images that match your PC's CPU type, so
  ODE shows a warning when you pick ARM on an x86 PC (or x86 on an ARM64 PC), and explains the emulator's error if
  such an instance stops right after launching.
- **Editing instances**: the new **Settings** button on every card opens the creation page filled with the
  instance. Title, display, graphics API, shared folder, CPU cores, RAM, max FPS and V-Sync can be changed.
  Architecture, Android version (with the system image type) and disk space are greyed out. The install folder can
  be changed until the instance has been started once (moving an existing disk image could damage it).
- **Delete** button on every card (it was only hidden in the right-click menu). Asks for confirmation, removes
  read-only files too, and keeps the instance in the list - with a message - if some files couldn't be removed.
- **Force close** in the card's right-click menu (it used to live on the sidebar).
- **ODE update check**: at startup ODE reads `version.json` from the GitHub repository. If a newer version exists it
  shows a notice with an *Open GitHub* button and keeps an "ODE x.y.z available" button in the top bar. Nothing is
  downloaded or installed automatically, and being offline never shows an error.
- **Get Android's Downloads** in the shared-folder menu: copies `/sdcard/Download` into a `Download` subfolder of
  your shared folder.

### Changed
- The "settings are fixed after saving" rules are gone: the create page no longer asks for a confirmation, and the
  read-only *Config Info* window is replaced by the editable Settings page.
- The Quick Setup guide was updated (no sidebar steps; new Settings, Shared folder and Delete steps).
- Instance cards wrap their text, so all buttons stay visible at the minimum window size.

### Fixed
- **Shared folder: "remote location doesn't exist"**. *Get files* failed whenever `/sdcard/ODE_Shared` didn't exist
  yet. ODE now creates the folder first, waits (up to 45 s) for Android's storage to be ready after boot, copies
  item by item (no more Windows path trouble with `\.`), and reports clear results - including "folder is empty".

### Removed
- The **floating sidebar** (volume, Home, Back, Tasks, power, force close, shared-folder button): the emulator
  window already has these controls. The shared-folder actions moved onto the instance card.

## 1.0.0

- First release: core download / update, instance manager, create instance, Quick Setup guide, floating sidebar.
