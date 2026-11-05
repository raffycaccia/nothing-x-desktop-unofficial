"""Linux / macOS: status-bar icon through pystray (optional) and the UI in a Chromium --app window.

Without pystray (or when its backend cannot start) the app runs as a plain window: closing it quits.
ponytail: the icon is static here (no battery digits); the tooltip carries the battery.
"""
import os
import subprocess
import threading
import time

from . import APP_NAME

HERE = os.path.dirname(os.path.abspath(__file__))


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

    def set_cap(self, cap):
        pass

    def quit(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        os._exit(0)

    def loop(self):
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

    def watch(self):
        ver = -1
        while True:
            with self.buds.cv:
                self.buds.cv.wait_for(lambda: self.buds.ver != ver, timeout=5)
                ver, st = self.buds.ver, dict(self.buds.state)
            name = (st.get("model") or {}).get("name", APP_NAME)
            if not st.get("connected"):
                self.icon.title = f"{name}: not connected"
                continue
            bat = st.get("battery") or {}
            parts = [f"{k.upper() if k != 'case' else 'Case'} {b['lvl']}%{' +' if b['chg'] else ''}" for k, b in bat.items()]
            self.icon.title = f"{name}  " + "  ".join(parts)

    def quit(self):
        self.icon.stop()
        super().quit()

    def loop(self):
        threading.Thread(target=self.watch, daemon=True, name="tray-watch").start()
        self.icon.run()  # blocks; on macOS this is the NSApplication run loop IOBluetooth callbacks need
