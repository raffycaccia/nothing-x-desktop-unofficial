"""Protocol framing, decoders and the per-model command table. Captures below come from a CMF Buds Pro 2."""
import pytest

from nothingx import protocol as P
from nothingx.protocol import MODELS, Model, crc16, packet, parse

BATTERY_REPLY = bytes.fromhex("556001074003000101026448a1")          # 0x4007: 1 part, L=100%
ANC_REPLY = bytes.fromhex("5560011e40060001010500020400b57a")        # 0x401E: anc off
CEQ_REPLY = bytes.fromhex("030000c0c0010000803f00007544c3f5283f020000803f00c05a450000803f000000c04000000c43cdcc4c3f")


def test_crc16_modbus_check_value():
    assert crc16(b"123456789") == 0x4B37


def test_packet_matches_capture():
    assert packet(0x4007, [1, 2, 100]) == BATTERY_REPLY
    assert packet(0xC007) == bytes.fromhex("556001" "07c0" "00" "00" "01") + packet(0xC007)[8:]


def test_parse_splits_stream_and_keeps_partial_tail():
    pkts, rest = parse(BATTERY_REPLY + ANC_REPLY + b"\x55\x60\x01")
    assert pkts == [(0x4007, bytes([1, 2, 100])), (0x401E, bytes.fromhex("010500020400"))]
    assert rest == b"\x55\x60\x01"


def test_parse_skips_garbage_before_header():
    assert parse(b"\x00\x11" + ANC_REPLY)[0] == [(0x401E, bytes.fromhex("010500020400"))]


def test_parse_waits_for_full_payload():
    assert parse(ANC_REPLY[:-3]) == ([], ANC_REPLY[:-3])


@pytest.fixture
def b172():
    return Model("2B353E", "fallback")


def test_model_lookup(b172):
    assert (b172.name, b172.base) == ("CMF Buds Pro 2", "B172")
    assert (b172.eq_get, b172.eq_set) == (0xC050, 0xF01D)       # listening-mode family
    assert Model("", "Ear (1)").name == "Ear (1)" and Model("", "x").eq_get == 0xC01F


def test_decode_battery(b172):
    assert b172.decode("battery", bytes([3, 2, 100, 3, 0x80 | 55, 4, 90])) == {
        "L": {"lvl": 100, "chg": False}, "R": {"lvl": 55, "chg": True}, "case": {"lvl": 90, "chg": False}}


def test_decode_simple_fields(b172):
    assert b172.decode("anc", bytes.fromhex("010700020400")) == 7
    assert b172.decode("inear", bytes([1, 1, 0])) is False
    assert b172.decode("lowlat", bytes([1])) is True and b172.decode("lowlat", bytes([2])) is False
    assert b172.decode("fw", b"0.0.8.8") == "0.0.8.8"
    assert b172.decode("fit", bytes([0, 1])) == {"L": 0, "R": 1}
    assert b172.decode("gestures", bytes.fromhex("0203010209020103080401")) == [[3, 1, 2, 9], [2, 1, 3, 8]]


def test_bass_levels_round_trip(b172):
    for lvl in range(1, 6):
        pkt, _ = b172.command("bass", {"on": True, "lvl": lvl})
        assert b172.decode("bass", pkt[8:10]) == {"on": True, "lvl": lvl}
    assert b172.decode("bass", bytes([0, 10])) == {"on": False, "lvl": 5}


def test_three_stage_bass_models():
    m = Model("", "x")
    m.base, m.bass_wire = "B189", [0, 5, 10]
    assert m.command("bass", {"on": True, "lvl": 2})[0][8:10] == bytes([1, 5])
    assert m.decode("bass", bytes([1, 10])) == {"on": True, "lvl": 3}
    assert Model("", "x").info()["bass_levels"] == 5


def test_custom_eq_round_trip(b172):
    bands = b172.decode("ceq", CEQ_REPLY)
    assert [b[:2] for b in bands] == [[1, 1.0], [2, 1.0], [0, 6.0]]
    assert [round(b[2]) for b in bands] == [980, 3500, 140]
    assert b172.command("ceq", bands)[0] == packet(0xF041, CEQ_REPLY)


def test_custom_eq_clamps_gain(b172):
    pkt, get = b172.command("ceq", [[0, 40, 140, 0.8]])
    assert get == 0xC044 and b172.decode("ceq", pkt[8:-2])[0][1] == 6.0


def test_commands(b172):
    assert b172.command("anc", 3) == (packet(0xF00F, [1, 3, 0]), 0xC01E)
    assert b172.command("eq", 4) == (packet(0xF01D, [4, 0]), 0xC050)
    assert b172.command("inear", True)[0] == packet(0xF004, [1, 1, 1])
    assert b172.command("lowlat", False)[0] == packet(0xF040, [2, 0])
    assert b172.command("spatial", True)[0] == packet(0xF052, [1, 0])
    assert b172.command("dual", False)[0] == packet(0xF01A, [0])
    assert b172.command("gesture", {"dev": 4, "ctx": 9, "type": 2, "action": 25})[0] == packet(0xF003, [1, 4, 9, 2, 25])
    assert b172.command("codec", 2) == (packet(0xF01C, [2]), 0xC029)
    assert b172.command("fit", 1) == (packet(0xF014, [1]), None)
    assert b172.command("ring", {"side": "L", "on": True})[0] == packet(0xF002, [2, 1])
    with pytest.raises(KeyError):
        b172.command("nope", 1)


def test_ring_single_models():
    for base, prefix in P.RING_SINGLE.items():
        m = Model("", "x")
        m.base = base
        assert m.command("ring", {"side": "R", "on": True})[0] == packet(0xF002, prefix + [1])


def test_models_json_is_consistent():
    bases = {b for _, b in MODELS["models"].values()}
    assert "B172" in bases and len(MODELS["models"]) >= 70
    assert set(MODELS["eq"]) <= bases
    for sku, (name, base) in MODELS["models"].items():
        assert len(sku) == 6 and sku == sku.upper() and name and base.startswith("B")
    for presets in MODELS["eq"].values():
        assert all(isinstance(v, int) and label for v, label in presets)
