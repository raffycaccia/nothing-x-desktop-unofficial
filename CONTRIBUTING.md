# Contributing

Thanks for helping. The most useful contributions, in order:

1. **Device reports.** Only the CMF Buds Pro 2 have been verified on hardware. Open a
   [device support issue](../../issues/new?template=device_support.yml) for any other model, even when
   everything works: that is how a model moves to the verified list.
2. **Linux and macOS testing.** The Linux transport (BlueZ RFCOMM) and the macOS one (IOBluetooth via pyobjc)
   were written without hardware at hand.
3. **Protocol work.** Features the official app has and this app lacks.

## Setup

```bash
git clone https://github.com/raffycaccia/nothing-x-desktop-unofficial
cd nothing-x-desktop-unofficial
python -m pip install -e ".[dev]"        # add ,tray on Linux, ,macos on macOS
python -m pytest
python -m nothingx                       # run from source
```

Only the standard library is used at runtime on Windows. Keep it that way; optional extras are fine for the
other platforms.

## Protocol changes

Every command or decoder must name where it comes from, in a comment: the official app class and method
(`TWSDeviceExtKt.whereAmI`), an ear-web file, or a capture from a device. Add a test with a real capture when
you have one; `tests/test_protocol.py` shows the format.

Never commit the official APK or anything extracted from it verbatim.

## UI

`nothingx/ui.html` is a single file: no build step, no framework. New strings go in both the `en` and `it`
tables. Controls for features a model may lack must carry `data-f="<state key>"` so they hide themselves
when the earbuds do not answer.

## Pull requests

Small and focused. The PR template asks how it was tested and whether hardware was involved; be precise,
a change that was not tried on earbuds is still welcome, we just want to know.
