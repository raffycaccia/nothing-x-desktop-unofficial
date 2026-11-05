"""Local UI server (HTTP + Server-Sent Events), settings, browser launcher and the entry point."""
import json
import os
import shutil
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import APP_NAME, __version__, autostart
from .link import Buds

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 47816
POPUP_SIZE = (380, 500)  # CSS px

if sys.platform == "win32":
    DATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "NothingX")
elif sys.platform == "darwin":
    DATA = os.path.expanduser("~/Library/Application Support/NothingX")
else:
    DATA = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "nothingx")

DEFAULTS = {"lang": "auto", "low_battery": 20, "tray_battery": True}
VALID = {"lang": lambda v: v in ("auto", "en", "it"), "low_battery": lambda v: isinstance(v, int) and 5 <= v <= 50,
         "tray_battery": lambda v: isinstance(v, bool)}


class Settings:
    def __init__(self, path):
        self.path = path
        self.data = dict(DEFAULTS)
        try:
            with open(path) as f:
                self.data.update({k: v for k, v in json.load(f).items() if k in VALID and VALID[k](v)})
        except (OSError, ValueError):
            pass

    def get(self, key):
        return self.data[key]

    def set(self, key, value):
        if key not in VALID or not VALID[key](value):
            raise ValueError(key)
        self.data[key] = value
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self.data, f)

    def public(self):
        return {**self.data, "autostart": autostart.is_enabled(), "platform": sys.platform, "version": __version__}


def find_browser():
    """Path of a Chromium-based browser (for --app mode) or None."""
    if sys.platform == "win32":
        pf = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
              os.environ.get("LOCALAPPDATA", "")]
        rel = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe",
               r"BraveSoftware\Brave-Browser\Application\brave.exe", r"Chromium\Application\chrome.exe"]
        cands = [os.path.join(p, r) for r in rel for p in pf if p]
    elif sys.platform == "darwin":
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                 "/Applications/Chromium.app/Contents/MacOS/Chromium",
                 "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"]
    else:
        cands = [shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                                           "microsoft-edge", "brave-browser", "brave")]
    return next((c for c in cands if c and os.path.exists(c)), None)


def browser_cmd(size, hidden):
    exe = find_browser()
    if not exe:
        return None
    cmd = [exe, f"--app=http://127.0.0.1:{PORT}/", f"--window-size={size[0]},{size[1]}",
           f"--user-data-dir={os.path.join(DATA, 'browser')}", "--no-first-run", "--no-default-browser-check",
           "--disable-sync", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
           "--disable-features=Translate,CalculateNativeWinOcclusion,msImplicitSignIn,msSyncOnboarding,msEdgeSyncPromo"]
    if sys.platform == "win32":
        cmd.append("--disable-direct-composition")  # window regions do not apply to DirectComposition surfaces
    if hidden:
        cmd.append("--window-position=-4000,-4000")  # off-screen until the tray places it
    return cmd


class Handler(BaseHTTPRequestHandler):
    buds: Buds = None
    tray = None
    settings: Settings = None

    def log_message(self, *a):
        pass

    def reply(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def payload(self, st):
        return {**st, "ui": {"popup": self.tray.POPUP, **self.settings.public()}}

    def do_GET(self):
        if self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            ver = -1
            try:
                while True:
                    with self.buds.cv:
                        self.buds.cv.wait_for(lambda: self.buds.ver != ver, timeout=15)
                        ver, st = self.buds.ver, dict(self.buds.state)
                    self.wfile.write(f"data: {json.dumps(self.payload(st))}\n\n".encode())
                    self.wfile.flush()
            except OSError:
                pass
            return
        if self.path == "/settings":
            return self.reply(200, json.dumps(self.settings.public()).encode())
        if self.path == "/state":
            with self.buds.cv:
                st = dict(self.buds.state)
            return self.reply(200, json.dumps(self.payload(st)).encode())
        if self.path == "/":
            with open(os.path.join(HERE, "ui.html"), "rb") as f:
                return self.reply(200, f.read(), "text/html; charset=utf-8")
        self.reply(404)

    def do_POST(self):
        try:
            msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path == "/hide":
                self.tray.hide()
            elif self.path == "/show":
                self.tray.show()
            elif self.path == "/quit":
                threading.Timer(0.2, self.tray.quit).start()
            elif self.path == "/frame":
                self.tray.set_cap(float(msg["cap"]))
            elif self.path == "/settings":
                for k, v in msg.items():
                    if k == "autostart":
                        autostart.set_enabled(bool(v))
                    else:
                        self.settings.set(k, v)
                self.buds.update()  # push the new settings to every open page
                return self.reply(200, json.dumps(self.settings.public()).encode())
            elif self.path == "/":
                self.buds.act(msg["k"], msg["v"])
            else:
                return self.reply(404)
            self.reply(204)
        except (ValueError, KeyError, TypeError):
            self.reply(400)


def make_tray(buds, settings):
    if sys.platform == "win32":
        from .tray_win import Tray
        return Tray(buds, settings, browser_cmd, POPUP_SIZE)
    from .tray_any import Tray, Window
    try:
        return Tray(buds, settings, browser_cmd, (POPUP_SIZE[0], POPUP_SIZE[1] + 100))
    except Exception:  # pystray missing or no usable backend: plain window
        return Window(buds, settings, browser_cmd, (POPUP_SIZE[0], POPUP_SIZE[1] + 100))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--version" in argv:
        print(APP_NAME, __version__)
        return 0
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:  # already running: pop its window and leave
        try:
            urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/show", b"{}"), timeout=3)
        except OSError:
            pass
        return 0
    os.makedirs(DATA, exist_ok=True)
    Handler.settings = Settings(os.path.join(DATA, "settings.json"))
    Handler.buds = Buds(os.path.join(DATA, "channels.json"))
    Handler.tray = make_tray(Handler.buds, Handler.settings)
    threading.Thread(target=srv.serve_forever, daemon=True, name="http").start()
    Handler.tray.loop()
    return 0
