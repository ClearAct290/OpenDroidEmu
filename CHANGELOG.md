# Changelog

All notable changes to OpenDroidEmu (ODE). A new entry is added with every update.

## 1.0.4

### Added
- **Virtual SD card**, with a size setting on the Create page and in an instance's Settings (64 MB to 100 GB, or
  *No SD card*; default 2 GB). Before every start ODE makes sure the card image exists with the configured size and
  passes it to the emulator, and the AVD config gets `hw.sdCard=yes` and `sdcard.size`. Apps like the camera and
  file managers now have a card to save photos and downloads to, on older and newer Android versions alike.
  Instances created before 1.0.4 get a 2 GB card on their next start.
- Changing the SD card size replaces the card with an empty one of the new size (the old card, its overlay and the
  saved Quick Boot state are removed, so the next start is a full boot). ODE asks for confirmation first. Android's
  own storage and installed apps are not touched.
- The instance card shows the SD card size.

### Fixed
- A stray `adb` left behind (after a crash, a kill, or a power loss) could break reopening ODE or launching an
  instance. ODE now shuts adb down whenever no instance is running (after the last emulator stops, when ODE closes,
  and at startup), and never while a launch is starting adb.

## 1.0.3

### Added
- **Boot mode** setting in an instance's Settings (and on the Create page, under Performance): **Quick Boot** or
  **Cold Boot**. Quick Boot is the default and resumes the state Android saved when the emulator window was last
  closed, so Android starts in seconds instead of doing a full startup. Cold Boot starts from scratch every time.
  It can be changed at any time while the instance is closed. Instances created before 1.0.3 use Quick Boot.
  The first start of an instance, and any start after a Force close, is still a full boot (nothing was saved yet).
- New instances are titled **My Android Instance #1**, **#2**, ... automatically (the lowest free number). Type your
  own title to replace it; leaving the field empty also uses the automatic title.
- The instance card shows the boot mode next to the other settings.

### Changed
- The Quick Setup guide describes the boot mode and the automatic titles.
- The OpenGL check on Linux also tries the usual library names directly, so OpenGL is no longer reported as
  "not supported" on systems where the library exists but could not be found by name.

### Removed
- The **shared folder** feature (the *Shared folder* button on instance cards, the shared folder field in Settings
  and the matching Quick Setup guide step). Copying files through the device's `/sdcard` did not work reliably.
  Installing apps (Dev Control, or dropping `.apk` files on a card) is unchanged.

## 1.0.2

### Added
- **Dev Control** button on every instance card, available only while Android is running (greyed out otherwise).
  It opens a window of ADB tools for that instance, laid out like a menu-driven ADB front end: **Device info**,
  **Apps**, **Files**, **Screen & input**, **Display**, **Power**, **System & logs**, **Network & ports** and
  **Shell & advanced**. It uses the ADB that ODE already downloads with the emulator - nothing extra is installed.
  Every action runs in the background with live output in a console and a **Stop** button.
- **APK install**: drop `.apk` files on a running instance's card, or anywhere in the Dev Control window, and they are
  installed in the background through ADB (queued if another command is still running). Options for replacing,
  granting permissions, downgrades and test-only APKs; a separate action installs split APKs as one app. Common
  install errors are explained in plain words.
- Dev Control is also in the card's right-click menu and in the Quick Setup guide.

### Changed
- The "not related to the OpenDroid Custom ROM project" notice was removed from the window footer. It is still in
  **About** and in the README.

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
