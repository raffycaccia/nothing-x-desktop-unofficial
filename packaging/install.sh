#!/bin/sh
# Installs the Linux release build for the current user: binary, launcher entry and icon.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
bin="$HOME/.local/bin"; apps="$HOME/.local/share/applications"; icons="$HOME/.local/share/icons/hicolor/256x256/apps"
mkdir -p "$bin" "$apps" "$icons"
install -m 755 "$here/nothingx" "$bin/nothingx"
install -m 644 "$here/icon.png" "$icons/nothingx.png"
sed "s|^Exec=.*|Exec=$bin/nothingx|" "$here/nothingx.desktop" > "$apps/nothingx.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$apps" || true
echo "Installed. Run: $bin/nothingx  (make sure ~/.local/bin is on your PATH)"
echo "Needs: bluez (bluetoothctl) and a Chromium-based browser for the panel window."
