"""Nothing earbuds RFCOMM protocol: framing, per-model command tables, decoders.

Packet: 55 60 01 <cmd lo> <cmd hi> <len> 00 <op> <payload> <crc16 lo> <crc16 hi>
Commands: 0xCxxx get, 0xFxxx set, 0x4xxx reply to a get, 0x7xxx reply to a set, 0xExxx unsolicited push.

Sources: the official Nothing X app (com.nothing.core.ext.TWSDeviceExtKt, ProtocolConstant) and the
ear-web project (https://github.com/radiance-project/ear-web, AGPL-3.0), from which models.json is derived.
Verified on hardware: CMF Buds Pro 2 (base B172).
"""
import json
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "models.json"), encoding="utf-8") as _f:
    MODELS = json.load(_f)  # {"models": {sku: [name, base]}, "eq": {base: [[value, label], ...]}}

NTAPP_UUID = "aeac4a03-dff5-498f-843a-34487cf133eb"  # Nothing's control service (RFCOMM)

LISTENING_MODE = {"B172", "B195", "B168", "B179", "B197", "B184", "B185", "B175", "B189"}  # EQ via 0xC050/0xF01D
BASS_3_STAGE = {"B189", "B186", "B195", "B197"}
RING_SINGLE = {"B181": [], "B170": [6], "B164": [6], "B175": [6], "B186": [6], "B192": [6]}  # "find" payload prefix
SIDES = {0x02: "L", 0x03: "R", 0x04: "case"}
PUSH = {0xE001: "battery", 0xE003: "anc", 0xE00D: "fit"}
# One-byte settings from the official app: name -> (get, set). Shown only when the buds answer the get.
TOGGLES = {"smart_anc": (0xC055, 0xF059), "smart_free": (0xC054, 0xF058), "personal_anc": (0xC020, 0xF011),
           "codec": (0xC029, 0xF01C)}
DEFAULT_EQ = [[0, "Balanced"], [3, "More Bass"], [2, "More Treble"], [1, "Voice"]]


def crc16(data):
    """CRC-16/MODBUS."""
    c = 0xFFFF
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c


def packet(cmd, payload=b""):
    p = bytes([0x55, 0x60, 0x01, cmd & 0xFF, cmd >> 8, len(payload), 0, 1]) + bytes(payload)
    c = crc16(p)
    return p + bytes([c & 0xFF, c >> 8])


def parse(buf):
    """Split a byte stream -> ([(cmd, payload), ...], leftover bytes of an incomplete packet)."""
    out = []
    while (i := buf.find(b"\x55")) != -1:
        buf = buf[i:]
        if len(buf) < 8 or len(buf) < 10 + buf[5]:
            break
        n = buf[5]
        out.append((buf[3] | buf[4] << 8, buf[8:8 + n]))
        buf = buf[10 + n:]
    else:
        buf = b""
    return out, buf


class Model:
    """Per-model differences. Everything else is feature-detected: a get with an empty reply = unsupported."""

    def __init__(self, sku, fallback_name="Nothing"):
        self.sku = sku
        self.name, self.base = MODELS["models"].get(sku, [fallback_name, ""])
        lm = self.base in LISTENING_MODE
        self.eq_get, self.eq_set = (0xC050, 0xF01D) if lm else (0xC01F, 0xF010)
        self.bass_wire = [0, 5, 10] if self.base in BASS_3_STAGE else [2, 4, 6, 8, 10]
        self.gets = {0xC007: "battery", 0xC01E: "anc", self.eq_get: "eq", 0xC00E: "inear", 0xC041: "lowlat",
                     0xC04E: "bass", 0xC04F: "spatial", 0xC027: "dual", 0xC018: "gestures", 0xC042: "fw",
                     0xC044: "ceq", **{g: k for k, (g, _) in TOGGLES.items()}}

    def info(self):
        return {"name": self.name, "base": self.base, "sku": self.sku,
                "eq": MODELS["eq"].get(self.base) or DEFAULT_EQ,
                "bass_levels": len(self.bass_wire), "ring_single": self.base in RING_SINGLE}

    def decode(self, key, p):
        if key == "battery":
            return {SIDES.get(p[1 + 2 * i], str(p[1 + 2 * i])): {"lvl": p[2 + 2 * i] & 0x7F, "chg": bool(p[2 + 2 * i] & 0x80)}
                    for i in range(p[0]) if 2 + 2 * i < len(p)}
        if key == "anc":
            return p[1]
        if key == "inear":
            return bool(p[2])
        if key == "lowlat":
            return p[0] == 1
        if key == "bass":
            lvl = min(range(len(self.bass_wire)), key=lambda i: abs(self.bass_wire[i] - p[1]))
            return {"on": bool(p[0]), "lvl": lvl + 1}
        if key in ("spatial", "dual", "smart_anc", "smart_free", "personal_anc"):
            return bool(p[0])
        if key == "gestures":  # [device, context, type, action]
            return [list(p[1 + 4 * i:5 + 4 * i]) for i in range(p[0]) if 4 + 4 * i < len(p)]
        if key == "fit":  # per side: 0 good, 1 adjust, 2 not detected
            return {"L": p[0], "R": p[1]}
        if key == "fw":
            return p.decode(errors="replace")
        if key == "ceq":  # custom EQ: count, total gain, then per band [type, gain, freq, Q] (floats LE)
            return [[p[5 + 13 * i], *struct.unpack_from("<3f", p, 6 + 13 * i)] for i in range(p[0]) if 18 + 13 * i <= len(p)]
        return p[0]  # eq preset, codec

    def command(self, name, v):
        """UI action -> (set packet, get command to read the result back or None)."""
        if name == "anc":
            return packet(0xF00F, [0x01, int(v), 0x00]), 0xC01E
        if name == "eq":
            return packet(self.eq_set, [int(v), 0x00]), self.eq_get
        if name == "inear":
            return packet(0xF004, [0x01, 0x01, 1 if v else 0]), 0xC00E
        if name == "lowlat":
            return packet(0xF040, [1 if v else 2, 0x00]), 0xC041
        if name == "bass":
            lvl = max(1, min(len(self.bass_wire), int(v["lvl"])))
            return packet(0xF051, [1 if v["on"] else 0, self.bass_wire[lvl - 1]]), 0xC04E
        if name == "spatial":
            return packet(0xF052, [1 if v else 0, 0x00]), 0xC04F
        if name == "dual":
            return packet(0xF01A, [1 if v else 0]), 0xC027
        if name == "gesture":  # [1, device (2 L, 3 R, 4 case), context (1 normal, 9 in call), type, action]
            return packet(0xF003, [0x01, int(v["dev"]), int(v.get("ctx", 1)), int(v["type"]), int(v["action"])]), 0xC018
        if name in TOGGLES:  # codec: 0 AAC, 1 LHDC, 2 LDAC (the buds reboot)
            get, set_ = TOGGLES[name]
            return packet(set_, [int(v)]), get
        if name == "ceq":  # [[type, gain, freq, q]], gains clamped to the app's -6..6 dB
            bands = [[int(t), max(-6.0, min(6.0, float(g))), float(f), float(q)] for t, g, f, q in v]
            out = bytes([len(bands)]) + struct.pack("<f", -max([0.0] + [b[1] for b in bands]))
            for t, g, f, q in bands:
                out += bytes([t]) + struct.pack("<3f", g, f, q)
            return packet(0xF041, out), 0xC044
        if name == "fit":
            return packet(0xF014, [0x01]), None
        if name == "ring":
            on = 1 if v["on"] else 0
            if self.base in RING_SINGLE:
                return packet(0xF002, RING_SINGLE[self.base] + [on]), None
            return packet(0xF002, [0x02 if v["side"] == "L" else 0x03, on]), None
        raise KeyError(name)
