# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.1] - 2026-11-07

### Fixed
- Windows: the app could crash at startup (access violation) and never show up, including when launched
  at login. Win32 handles were truncated to 32 bits; every handle-returning call now declares a
  pointer-wide type, with a regression test.

## [0.2.0] - 2026-11-06

### Added
- Low-battery notification: one system notification per bud when it reaches the threshold set in
  Settings, re-armed after charging. Windows: toast with the app's name and icon; Linux: notify-send
  (gdbus fallback); macOS: Notification Center. Works in plain-window mode too.

## [0.1.1] - 2026-11-05

### Fixed
- RFCOMM channel probing could cache a wrong channel when the real one was busy; a channel now has to
  answer a battery get, and the cached channel is re-validated on every connect.
- Popup: even 10 px margins (browser title bar measured, not estimated), no stray scrollbar on the main
  view, no 1 px frame line, no duplicate browser launch, no Edge sync dialog.

### Changed
- Release builds: macOS Apple Silicon only (Intel Macs: install with pip).
- CI tests a single Python version on macOS.

## [0.1.0] - 2026-11-05

### Added
- Tray icon with live battery digits (Windows) and a borderless popup panel in the Nothing widget style.
- Battery for left, right and case; charging and low-battery indication.
- Noise control: off, transparency, ANC low / mid / high / adaptive.
- Equalizer presets per model and a custom equalizer with a three-band radial dial.
- Ultra Bass, spatial audio, low latency, in-ear detection, dual connection, smart ANC, personalised ANC,
  Smart Free and codec, each shown only when the earbuds support it.
- Gestures for left, right and the case dial, including in-call actions.
- Find earbuds and ear tip fit test.
- Settings: language (English, Italian), launch at login, tray battery digits, low-battery threshold.
- Model table for 76 SKUs (22 model bases) of Nothing and CMF products.
- Linux (BlueZ) and macOS (IOBluetooth, experimental) transports; pystray status-bar icon.
- GitHub Actions: tests on three platforms, PyInstaller builds attached to tagged releases.

[Unreleased]: https://github.com/raffycaccia/nothing-x-desktop-unofficial/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/raffycaccia/nothing-x-desktop-unofficial/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/raffycaccia/nothing-x-desktop-unofficial/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/raffycaccia/nothing-x-desktop-unofficial/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/raffycaccia/nothing-x-desktop-unofficial/releases/tag/v0.1.0
