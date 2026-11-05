# Protocol notes

What the app knows about the Nothing earbuds control protocol. Sources: captures from a CMF Buds Pro 2
(firmware 0.0.8.8), the official Nothing X app (`com.nothing.base.protocol.constant.ProtocolConstant`,
`com.nothing.core.ext.TWSDeviceExtKt`) and [ear-web](https://github.com/radiance-project/ear-web).

## Transport

The earbuds expose several RFCOMM services. Two matter:

| Service UUID | Purpose |
|---|---|
| `aeac4a03-dff5-498f-843a-34487cf133eb` (NTAPP) | Control protocol below. On the CMF Buds Pro 2 it is channel 16, but the channel is assigned by the device: the app probes 1–30 once and caches the result in `channels.json`. |
| `df21fe2c-2515-4fdb-8886-f12c4d67927c` (Fast Pair) | Greets with 7 bytes, e.g. `03 01 00 03 2B 35 3E`; the last three are the SKU (`2B353E`), the key into `models.json`. |

## Framing

```
55 60 01 | cmd lo | cmd hi | len | 00 | op | payload (len bytes) | crc lo | crc hi
```

* `op` is `01` for host→device. Replies echo the packet shape.
* CRC-16/MODBUS over everything before it (poly 0xA001, init 0xFFFF, check value `0x4B37` for `123456789`).
* Several packets can arrive in one read; a packet can be split across reads. `protocol.parse` handles both.

Command spaces:

| Range | Meaning |
|---|---|
| `0xC0xx` | get |
| `0xF0xx` | set |
| `0x40xx` | reply to get (`cmd \| 0x8000`) |
| `0x70xx` | ack of set |
| `0xE0xx` | unsolicited push |

A get that the model does not support is answered with an **empty payload**. The app uses that as feature
detection: a control is shown only after a non-empty reply.

## Commands used

| Feature | Get | Set | Payload / decoding |
|---|---|---|---|
| Battery | `C007` | | `count, (device, level)*` – device `02` L, `03` R, `04` case; bit 7 of level = charging. Push `E001`. |
| Noise control | `C01E` | `F00F` | set `01 <mode> 00`; reply byte 1 = mode: `05` off, `07` transparency, `01` high, `02` mid, `03` low, `04` adaptive. Push `E003`. |
| EQ preset (B172 family) | `C050` | `F01D` | one byte preset id (`0` Dirac Opteo … `6` Custom). Other models: `C01F` / `F010`. |
| Custom EQ | `C044` | `F041` | `count, totalGain f32, (type u8, gain f32, freq f32, Q f32)*`, little-endian; type `0` low shelf, `1` peak, `2` high shelf; app range −6…+6 dB. |
| Bass enhance / Ultra Bass | `C04E` | `F051` | `on, level` – level wire values 2…10 step 2 (five levels) or 0/5/10 on three-stage models. |
| Spatial audio | `C04F` | `F052` | `on, head_tracking` |
| Low latency | `C041` | `F040` | `01` on, `02` off |
| In-ear detection | `C00E` | `F004` | set `01 01 <on>`; reply byte 2 |
| Dual connection | `C027` | `F01A` | one byte |
| Gestures | `C018` | `F003` | reply `count, (device, context, type, action)*`; set `01 device context type action`. Context `1` normal, `9` in call. Types: `1` press, `2` double, `3` triple, `7` hold, `9` double-tap-hold, `10` rotate. |
| Find earbuds | | `F002` | `side, on` (side `02`/`03`); some models take `06, on` or just `on`. |
| Ear tip fit test | | `F014` | `01`; result pushed as `E00D`: `left, right` with `0` good, `1` adjust, `2` not detected. |
| Firmware | `C042` | | ASCII |
| Smart ANC / Smart Free / Personalised ANC | `C055` / `C054` / `C020` | `F059` / `F058` / `F011` | one byte |
| Codec | `C029` | `F01C` | `0` AAC, `1` LHDC, `2` LDAC; the earbuds reboot |

Gesture action codes: `1` none, `2` play/pause, `3` answer, `8` previous, `9` next, `11` voice assistant,
`17` low latency, `18`/`19` volume, `22` ANC/transparency, `10` ANC/transp/off, `20` transp/off, `21` ANC/off,
`23` volume (rotate), `25` answer/mute, `26` hang up/decline.

## Adding a model

1. Connect it: the Settings page shows base code and SKU. If the SKU is missing from `models.json`, add it
   (`"SKU": ["Name", "Bxxx"]`).
2. If the EQ presets differ, add the base to `MODELS["eq"]`; if it uses the listening-mode EQ commands,
   add the base to `LISTENING_MODE` in `protocol.py`; three-stage bass → `BASS_3_STAGE`; single "find"
   payload → `RING_SINGLE`.
3. Capture a reply for anything new and add it to `tests/test_protocol.py`.
