"""Linux / macOS: status-bar icon through pystray (optional) and the UI in a Chromium --app window.

Without pystray (or when its backend cannot start) the app runs as a plain window: closing it quits.
Either way a watcher thread raises low-battery notifications through the system's own channel.
ponytail: the icon is static here (no battery digits); the tooltip carries the battery.
"""
import os
import shutil
import subprocess
import sys
import threading
import time

from . import APP_NAME

HERE = os.path.dirname(os.path.abspath(__file__))


def notify_cmd(title, text, platform=sys.platform):
    """argv that shows a desktop notification, or None when the system has no way to.
    Linux: notify-send (libnotify) with our name and icon, else gdbus to org.freedesktop.Notifications.
    macOS: Notification Center via osascript (attributed to Script Editor; a signed bundle could use
    UNUserNotificationCenter instead, ponytail: not worth it without a Mac to test on)."""
    icon = os.path.join(HERE, "icon.png")
    if platform == "darwin":
        q = lambda s: '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
        return ["osascript", "-e", f"display notification {q(text)} with title {q(APP_NAME)} subtitle {q(title)}"]
    if shutil.which("notify-send"):
        return ["notify-send", "--app-name", APP_NAME, "--icon", icon, "--urgency", "normal", title, text]
    if shutil.which("gdbus"):
        return ["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
                "--object-path", "/org/freedesktop/Notifications", "--method", "org.freedesktop.Notifications.Notify",
                APP_NAME, "0", icon, title, text, "[]", "{}", "8000"]
    return None


def notify(title, text):
    cmd = notify_cmd(title, text)
    if cmd:
        try:
            subprocess.run(cmd, timeout=10, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            pass


def battery_line(bat):
    return "  ".join(f"{k.upper() if k != 'case' else 'Case'} {b['lvl']}%{' +' if b['chg'] else ''}" for k, b in bat.items())


class Window:
    """Plain window mode: show() opens the browser window, loop() waits for it to close."""
    POPUP = False  # a normal window: the page must not hide itself on blur

    def __init__(self, buds, settings, browser_cmd, size):
        self.buds, self.settings, self.browser_cmd, self.size = buds, settings, browser_cmd, size
        self.proc = None

    def show(self):
        if self.proc and self.proc.poll() is None:
            return  # already open
        cmd = self.browser_cmd(self.size, hidden=False)
        if not cmd:  # no Chromium: a normal browser tab
            import webbrowser
            from .app import PORT
            webbrowser.open(f"http://127.0.0.1:{PORT}/")
            return
        self.proc = subprocess.Popen(cmd)

    def hide(self):
        pass

    def set_cap(self, cap, inner=0):
        pass

    def status(self, text):
        """Tooltip hook; nothing to update without a tray icon."""

    def watch(self):
        """Low-battery notifications and the status text, from the live state."""
        from .app import LowBattery
        ver, low_alert = -1, LowBattery()
        while True:
            with self.buds.cv:
                self.buds.cv.wait_for(lambda: self.buds.ver != ver, timeout=5)
                ver, st = self.buds.ver, dict(self.buds.state)
            name = (st.get("model") or {}).get("name", APP_NAME)
            if not st.get("connected"):
                self.status(f"{name}: not connected")
                continue
            bat = st.get("battery") or {}
            if crossed := low_alert.check(bat, self.settings.get("low_battery")):
                notify(*LowBattery.message(name, crossed, self.settings.get("lang")))
            self.status(f"{name}  {battery_line(bat)}")

    def quit(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        os._exit(0)

    def loop(self):
        threading.Thread(target=self.watch, daemon=True, name="watch").start()
        self.show()
        while True:
            time.sleep(1)
            if self.proc is not None and self.proc.poll() is not None:
                os._exit(0)


class Tray(Window):
    """pystray icon + Window. Raises ImportError when pystray/Pillow are missing."""

    def __init__(self, buds, settings, browser_cmd, size):
        import pystray
        from PIL import Image
        super().__init__(buds, settings, browser_cmd, size)
        self.icon = pystray.Icon("nothingx", Image.open(os.path.join(HERE, "icon.png")), APP_NAME, menu=pystray.Menu(
            pystray.MenuItem("Open", lambda: self.show(), default=True),
            pystray.MenuItem("Quit", lambda: self.quit())))

    def status(self, text):
        self.icon.title = text

    def quit(self):
        self.icon.stop()
        super().quit()

    def loop(self):
        threading.Thread(target=self.watch, daemon=True, name="watch").start()
        self.icon.run()  # blocks; on macOS this is the NSApplication run loop IOBluetooth callbacks need
