"""HTTP/SSE server, settings and the link state machine, without Bluetooth hardware."""
import json
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
    def set_cap(self, cap): self.calls.append(("cap", cap))


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


def test_main_version_flag(capsys):
    assert A.main(["--version"]) == 0
    assert "Nothing X Desktop" in capsys.readouterr().out
