"""Bluetooth link to the buds: find paired devices, open RFCOMM, keep one connection and mirror its state.

Transports:
  Windows, Linux  socket.AF_BLUETOOTH (stdlib; BlueZ on Linux)
  macOS           IOBluetooth through pyobjc (optional dependency, experimental: no hardware to test on)
"""
import json
import os
import re
import struct
import subprocess
import sys
import threading
import time

from .protocol import PUSH, Model, packet, parse

NAME_HINT = re.compile(r"nothing|cmf|\bear\b|headphone", re.I)  # paired devices worth probing


# ---------------------------------------------------------------- paired devices

def paired_devices():
    """[(mac 'AA:BB:CC:DD:EE:FF', name)] of paired devices that look like Nothing/CMF audio products."""
    if sys.platform == "win32":
        return _paired_windows()
    if sys.platform == "darwin":
        return _paired_macos()
    return _paired_linux()


def _paired_windows():
    import winreg
    from .protocol import NTAPP_UUID
    out = []
    try:
        enum = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Enum\BTHENUM")
        names = [winreg.EnumKey(enum, i) for i in range(winreg.QueryInfoKey(enum)[0])]
        for n in (n for n in names if n.lower().startswith("{" + NTAPP_UUID)):  # devices exposing the NTAPP service
            sk = winreg.OpenKey(enum, n)
            for j in range(winreg.QueryInfoKey(sk)[0]):
                mac = winreg.EnumKey(sk, j).split("&")[-1].split("_")[0].lower()
                try:
                    dk = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                        rf"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices\{mac}")
                    name = winreg.QueryValueEx(dk, "Name")[0].rstrip(b"\0").decode(errors="replace")
                except OSError:
                    name = "Nothing"
                out.append((":".join(mac[i:i + 2] for i in range(0, 12, 2)).upper(), name))
    except OSError:
        pass
    return out


def _paired_linux():
    for args in (["bluetoothctl", "devices", "Paired"], ["bluetoothctl", "paired-devices"]):
        try:
            text = subprocess.run(args, capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        found = re.findall(r"Device ([0-9A-F:]{17}) (.+)", text)
        if found:
            return [(mac, name.strip()) for mac, name in found if NAME_HINT.search(name)]
    return []


def _paired_macos():
    try:
        import IOBluetooth  # noqa: F401  (pyobjc-framework-IOBluetooth)
    except ImportError:
        return []
    out = []
    for d in IOBluetooth.IOBluetoothDevice.pairedDevices() or []:
        name = d.name() or ""
        if NAME_HINT.search(name):
            out.append((d.addressString().replace("-", ":").upper(), name))
    return out


# ---------------------------------------------------------------- RFCOMM transport

def rfcomm(mac, ch, timeout):
    """Open an RFCOMM channel -> socket-like object (send/recv/settimeout/close) or None."""
    if sys.platform == "darwin":
        return _MacChannel.open(mac, ch, timeout)
    import socket
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    s.settimeout(timeout)
    try:
        s.connect((mac, ch))
        return s
    except OSError:
        s.close()
        return None


class _MacChannel:
    """IOBluetoothRFCOMMChannel wrapped to look like a socket. Delegate callbacks arrive on the main run loop
    (the pystray/NSApplication loop), recv() waits on a condition from the worker thread.
    ponytail: experimental, written against the pyobjc API without a Mac to test on."""

    @classmethod
    def open(cls, mac, ch, timeout):
        try:
            import objc
            import IOBluetooth
            from Foundation import NSObject
        except ImportError:
            return None
        self = cls()
        self.cv, self.buf, self.closed, self.timeout = threading.Condition(), b"", False, timeout

        class Delegate(NSObject):
            def rfcommChannelData_data_length_(d, channel, data, length):
                with self.cv:
                    self.buf += bytes(data)
                    self.cv.notify_all()

            def rfcommChannelClosed_(d, channel):
                with self.cv:
                    self.closed = True
                    self.cv.notify_all()

        self.delegate = Delegate.alloc().init()
        dev = IOBluetooth.IOBluetoothDevice.deviceWithAddressString_(mac.replace(":", "-"))
        res, chan = dev.openRFCOMMChannelSync_withChannelID_delegate_(None, ch, self.delegate)
        if res != 0 or chan is None:
            return None
        self.chan = chan
        return self

    def settimeout(self, t):
        self.timeout = t

    def send(self, data):
        if self.chan.writeSync_length_(bytes(data), len(data)) != 0:
            raise OSError("rfcomm write failed")

    def recv(self, n):
        with self.cv:
            if not self.cv.wait_for(lambda: self.buf or self.closed, self.timeout):
                raise TimeoutError
            if not self.buf:
                return b""  # closed
            out, self.buf = self.buf[:n], self.buf[n:]
            return out

    def close(self):
        try:
            self.chan.closeChannel()
        except Exception:
            pass


# ---------------------------------------------------------------- channel probe

def hello(s):
    """True when the channel answers a battery get with 0x4007: that is what makes it the NTAPP channel.
    Other services greet with arbitrary bytes (some even contain 0x55), so parse() alone is not proof."""
    try:
        s.settimeout(1.5)
        s.send(packet(0xC007))
        buf = b""
        for _ in range(3):
            buf += s.recv(1024)
            if any(cmd == 0x4007 for cmd, _ in parse(buf)[0]):
                return True
    except OSError:
        pass
    return False


def probe(mac, channels=range(1, 31)):
    """Scan RFCOMM channels once -> {'ntapp': ch, 'sku': 'XXXXXX'}.
    The FastPair channel greets with 7 bytes holding the SKU; the NTAPP channel answers hello()."""
    found = {}
    for ch in channels:
        s = rfcomm(mac, ch, 3)
        if not s:
            continue
        try:
            s.settimeout(1.2)
            try:
                data = s.recv(64)
            except TimeoutError:
                data = b""
            if len(data) == 7 and data[0] != 0x55:
                found["sku"] = data[4:7].hex().upper()
            elif hello(s):
                found["ntapp"] = ch
        except OSError:
            pass
        finally:
            s.close()
        if len(found) == 2:
            break
    return found


# ---------------------------------------------------------------- live link

class Buds:
    """Background thread: connect to the first reachable device, mirror its state in `state`, bump `ver`
    and notify `cv` on every change. `conf_path` caches the probed channel/SKU per device."""

    POLL_S = 30         # battery pushes are not reliable: poll too
    RETRY_S = 10        # when nothing is reachable

    def __init__(self, conf_path, start=True):
        self.state = {"connected": False}
        self.cv = threading.Condition()
        self.ver = 0
        self.sock = None
        self.model = None
        self.conf_path = conf_path
        try:
            with open(conf_path) as f:
                self.conf = json.load(f)
        except (OSError, ValueError):
            self.conf = {}
        if start:
            threading.Thread(target=self.run, daemon=True, name="buds-link").start()

    def update(self, reset=False, **kw):
        with self.cv:
            if reset:
                self.state = {}
            self.state.update(kw)
            self.ver += 1
            self.cv.notify_all()

    def connect(self):
        for mac, name in paired_devices():
            c = self.conf.get(mac, {})
            s = rfcomm(mac, c["ntapp"], 4) if "ntapp" in c else None
            if s and not hello(s):  # cached channel no longer the right one
                s.close()
                s = None
            if not s and (c := probe(mac)).get("ntapp"):  # first run, or the channel moved
                self.conf[mac] = c
                os.makedirs(os.path.dirname(self.conf_path), exist_ok=True)
                with open(self.conf_path, "w") as f:
                    json.dump(self.conf, f)
                s = rfcomm(mac, c["ntapp"], 4)
            if s:
                return s, Model(c.get("sku", ""), name)
        return None, None

    def run(self):
        while True:
            s, self.model = self.connect()
            if not s:
                self.update(reset=True, connected=False)
                time.sleep(self.RETRY_S)
                continue
            self.sock = s
            self.update(reset=True, connected=True, model=self.model.info())
            for c in self.model.gets:
                self.send(packet(c))
            self.pump(s)
            self.sock = None
            s.close()
            self.update(reset=True, connected=False)
            time.sleep(2)

    def pump(self, s):
        """Read packets until the link drops."""
        buf, last_poll = b"", time.time()
        s.settimeout(5)
        try:
            while True:
                try:
                    data = s.recv(2048)
                    if not data:
                        return
                    pkts, buf = parse(buf + data)
                    for cmd, p in pkts:
                        self.handle(cmd, p)
                except TimeoutError:
                    pass
                if time.time() - last_poll > self.POLL_S:
                    self.send(packet(0xC007))
                    last_poll = time.time()
        except OSError:
            return

    def handle(self, cmd, p):
        key = self.model.gets.get(cmd | 0x8000) or PUSH.get(cmd)
        if key and p:
            try:
                val = self.model.decode(key, p)
            except (IndexError, struct.error):
                return
            if isinstance(val, (dict, list)) and not val:
                return  # truncated reply: keep what we had
            self.update(**{key: val})

    def send(self, data):
        if s := self.sock:
            try:
                s.send(data)
            except OSError:
                pass

    def act(self, name, value):
        if not self.model:
            return
        pkt, get = self.model.command(name, value)
        self.send(pkt)
        if get:
            time.sleep(0.15)
            self.send(packet(get))

