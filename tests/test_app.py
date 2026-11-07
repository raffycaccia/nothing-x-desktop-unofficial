"""HTTP/SSE server, settings and the link state machine, without Bluetooth hardware."""
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from nothingx import app as A
from nothingx.link import Buds
from nothingx.protocol import Model, packet


class FakeTray:
    POPUP = True

    def __init__(self):
        self.calls = []

    def hide(self): self.calls.append("hide")
    def show(self): self.calls.append("show")
    def quit(self): self.calls.append("quit")
    def set_cap(self, cap, inner=0): self.calls.append(("cap", cap))


class FakeSock:
    def __init__(self):
        self.sent = []

    def send(self, data): self.sent.append(bytes(data))
    def settimeout(self, t): pass
    def close(self): pass


@pytest.fixture
def server(tmp_path, monkeypatch):
    buds = Buds(str(tmp_path / "channels.json"), start=False)
    buds.model = Model("2B353E", "x")
    buds.sock = FakeSock()
    buds.update(connected=True, model=buds.model.info())
    monkeypatch.setattr(A.autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(A.autostart, "set_enabled", lambda on: on)
    A.Handler.buds, A.Handler.tray, A.Handler.settings = buds, FakeTray(), A.Settings(str(tmp_path / "settings.json"))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), A.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", buds, A.Handler.tray
    srv.shutdown()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read()


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def test_index_serves_ui(server):
    url, _, _ = server
    status, body = get(url + "/")
    assert status == 200 and b"<title>Nothing X Desktop (unofficial)</title>" in body
    assert get(url + "/state")[0] == 200


def test_events_stream_state_with_ui_block(server):
    url, buds, _ = server
    with urllib.request.urlopen(url + "/events", timeout=5) as r:
        line = r.readline()
    d = json.loads(line[6:])
    assert d["connected"] is True and d["model"]["name"] == "CMF Buds Pro 2"
    assert d["ui"]["popup"] is True and d["ui"]["lang"] == "auto" and d["ui"]["version"]


def test_action_sends_set_then_get(server):
    url, buds, _ = server
    assert post(url + "/", {"k": "anc", "v": 7})[0] == 204
    assert buds.sock.sent == [packet(0xF00F, [1, 7, 0]), packet(0xC01E)]


def test_bad_action_is_400(server):
    url, buds, _ = server
    assert post(url + "/", {"k": "nope", "v": 1})[0] == 400
    assert post(url + "/", {"k": "bass", "v": {"on": True}})[0] == 400  # missing lvl
    assert buds.sock.sent == []


def test_window_endpoints(server):
    url, _, tray = server
    assert post(url + "/hide", {})[0] == 204 and post(url + "/show", {})[0] == 204
    assert post(url + "/frame", {"cap": 31})[0] == 204
    assert tray.calls == ["hide", "show", ("cap", 31.0)]
    assert post(url + "/nope", {})[0] == 404
    with pytest.raises(urllib.error.HTTPError):
        get(url + "/nope")


def test_open_link_uses_default_browser_and_is_restricted(server, monkeypatch):
    url, _, _ = server
    opened = []
    monkeypatch.setattr(A.webbrowser, "open", opened.append)
    repo = "https://github.com/raffycaccia/nothing-x-desktop-unofficial"
    assert post(url + "/open", {"url": repo})[0] == 204
    assert post(url + "/open", {"url": "https://evil.example/x"})[0] == 400
    assert post(url + "/open", {"url": "file:///C:/Windows/system32/calc.exe"})[0] == 400
    assert opened == [repo]


def test_settings_round_trip(server, tmp_path):
    url, _, _ = server
    status, body = post(url + "/settings", {"lang": "it", "low_battery": 15, "autostart": True})
    assert status == 200 and json.loads(body)["lang"] == "it"
    assert json.loads(get(url + "/settings")[1])["low_battery"] == 15
    assert json.loads((tmp_path / "settings.json").read_text()) == {"lang": "it", "low_battery": 15, "tray_battery": True}
    assert post(url + "/settings", {"lang": "xx"})[0] == 400
    assert post(url + "/settings", {"low_battery": 99})[0] == 400


def test_settings_ignores_corrupt_file(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"lang": "de", "low_battery": "no", "junk": 1')
    assert A.Settings(str(p)).data == A.DEFAULTS


def test_link_handles_replies_and_pushes(tmp_path):
    buds = Buds(str(tmp_path / "c.json"), start=False)
    buds.model = Model("2B353E", "x")
    buds.handle(0x4007, bytes([2, 2, 80, 3, 0x80 | 50]))
    buds.handle(0xE003, bytes.fromhex("010200020400"))  # push: anc mid
    buds.handle(0x4042, b"1.2.3")
    buds.handle(0x4018, b"")                              # empty reply = unsupported: ignored
    buds.handle(0x4007, bytes([9]))                       # truncated: ignored
    assert buds.state["battery"] == {"L": {"lvl": 80, "chg": False}, "R": {"lvl": 50, "chg": True}}
    assert buds.state["anc"] == 2 and buds.state["fw"] == "1.2.3" and "gestures" not in buds.state


def test_link_pump_reads_until_close(tmp_path):
    class Stream:
        def __init__(self, chunks): self.chunks = list(chunks)
        def settimeout(self, t): pass
        def recv(self, n): return self.chunks.pop(0) if self.chunks else b""
        def send(self, d): pass

    buds = Buds(str(tmp_path / "c.json"), start=False)
    buds.model = Model("2B353E", "x")
    reply = packet(0x4007, [1, 2, 42])
    buds.pump(Stream([reply[:5], reply[5:] + packet(0x401E, bytes.fromhex("010500020400"))]))
    assert buds.state["battery"]["L"]["lvl"] == 42 and buds.state["anc"] == 5


class ChanSock:
    """Fake RFCOMM channel: a greeting, then canned replies to whatever is sent."""
    def __init__(self, greeting=b"", reply=b""):
        self.inbox = [greeting] if greeting else []
        self.reply = reply
    def settimeout(self, t): pass
    def close(self): pass
    def send(self, d): self.inbox.append(self.reply)
    def recv(self, n):
        if not self.inbox:
            raise TimeoutError
        return self.inbox.pop(0)


def test_probe_accepts_only_battery_replies(monkeypatch):
    from nothingx import link
    chans = {16: ChanSock(reply=packet(0x4007, [1, 2, 100])),
             17: ChanSock(greeting=bytes.fromhex("030100032b353e")),
             29: ChanSock(greeting=b"CAPSENSOR" + bytes.fromhex("5560010740000001") * 2)}  # junk with a 0x55 inside
    monkeypatch.setattr(link, "rfcomm", lambda mac, ch, t: chans.get(ch))
    assert link.probe("AA", channels=[1, 29, 17, 16]) == {"sku": "2B353E", "ntapp": 16}
    assert link.probe("AA", channels=[29]) == {}
    assert link.hello(ChanSock(reply=packet(0xE001, [1, 2, 9]) + packet(0x4007, [1, 2, 9]))) is True  # push first


def test_connect_revalidates_cached_channel(tmp_path, monkeypatch):
    from nothingx import link
    conf = tmp_path / "c.json"
    conf.write_text('{"AA": {"ntapp": 29, "sku": "2B353E"}}')
    chans = {16: lambda: ChanSock(reply=packet(0x4007, [1, 2, 100])), 29: lambda: ChanSock(greeting=b"junk")}
    monkeypatch.setattr(link, "paired_devices", lambda: [("AA", "CMF Buds Pro 2")])
    monkeypatch.setattr(link, "rfcomm", lambda mac, ch, t: chans[ch]() if ch in chans else None)
    buds = Buds(str(conf), start=False)
    s, model = buds.connect()
    assert s is not None and model.name == "CMF Buds Pro 2"
    assert json.loads(conf.read_text())["AA"]["ntapp"] == 16


def test_low_battery_notifies_once_and_rearms():
    lb, b = A.LowBattery(), lambda lvl, chg=False: {"lvl": lvl, "chg": chg}
    assert lb.check({"L": b(50), "R": b(40), "case": b(5)}, 20) == []        # case never alerts
    assert lb.check({"L": b(20), "R": b(40)}, 20) == [("L", 20)]
    assert lb.check({"L": b(15), "R": b(40)}, 20) == []                      # already told
    assert lb.check({"L": b(22), "R": b(18)}, 20) == [("R", 18)]             # 22 is within the 5 % band: L stays armed-off
    assert lb.check({"L": b(14, chg=True), "R": b(18)}, 20) == []            # charging re-arms L
    assert lb.check({"L": b(14), "R": b(18)}, 20) == [("L", 14)]
    title, text = A.LowBattery.message("CMF Buds Pro 2", [("L", 14), ("R", 18)], "it")
    assert title == "Batteria scarica" and "sinistra 14%, destra 18%" in text
    assert A.LowBattery.message("X", [("R", 9)], "en")[1] == "X: right 9%. Time to charge."


def test_main_version_flag(capsys):
    assert A.main(["--version"]) == 0
    assert "Nothing X Desktop" in capsys.readouterr().out


def test_notify_commands_per_platform(monkeypatch):
    from nothingx import tray_any
    mac = tray_any.notify_cmd("Low battery", 'Buds "Pro": left 9%', platform="darwin")
    assert mac[:2] == ["osascript", "-e"] and 'subtitle "Low battery"' in mac[2] and '\\"Pro\\"' in mac[2]
    monkeypatch.setattr(tray_any.shutil, "which", lambda n: "/usr/bin/" + n if n == "notify-send" else None)
    lin = tray_any.notify_cmd("Low battery", "left 9%", platform="linux")
    assert lin[0] == "notify-send" and lin[lin.index("--app-name") + 1] == "Nothing X Desktop (unofficial)"
    assert lin[lin.index("--icon") + 1].endswith("icon.png") and lin[-2:] == ["Low battery", "left 9%"]
    monkeypatch.setattr(tray_any.shutil, "which", lambda n: "/usr/bin/gdbus" if n == "gdbus" else None)
    assert tray_any.notify_cmd("t", "x", platform="linux")[:2] == ["gdbus", "call"]
    monkeypatch.setattr(tray_any.shutil, "which", lambda n: None)
    assert tray_any.notify_cmd("t", "x", platform="linux") is None


def test_window_watch_notifies_on_low_battery(tmp_path, monkeypatch):
    from nothingx import tray_any
    sent = []
    monkeypatch.setattr(tray_any, "notify", lambda title, text: sent.append((title, text)))
    buds = Buds(str(tmp_path / "c.json"), start=False)
    w = tray_any.Window(buds, A.Settings(str(tmp_path / "s.json")), lambda *a, **k: None, (1, 1))
    threading.Thread(target=w.watch, daemon=True).start()
    buds.update(connected=True, model={"name": "CMF Buds Pro 2"}, battery={"L": {"lvl": 12, "chg": False}})
    for _ in range(50):
        if sent:
            break
        import time; time.sleep(0.05)
    assert len(sent) == 1 and "12%" in sent[0][1]


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")
def test_win32_handles_are_pointer_wide():
    """Regression: handle-returning Win32 calls left at the ctypes default (32-bit int) truncate 64-bit
    handles and crash the tray at startup whenever Windows hands out a high address."""
    import ctypes
    from nothingx import tray_win as T
    for fn in (T.k32.GetModuleHandleW, T.u32.CreateWindowExW, T.u32.CreatePopupMenu, T.u32.LoadImageW,
               T.u32.CreateIconFromResourceEx, T.gdi.CreateRoundRectRgn):
        assert ctypes.sizeof(fn.restype) == ctypes.sizeof(ctypes.c_void_p), fn.__name__
