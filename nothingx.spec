# PyInstaller build: `pyinstaller nothingx.spec`
# Windows -> dist/NothingX.exe   Linux -> dist/NothingX   macOS -> dist/NothingX.app
import sys

from PyInstaller.utils.hooks import collect_submodules

datas = [(f"nothingx/{f}", "nothingx") for f in ("ui.html", "models.json", "icon.ico", "icon.png")]
hidden = []
if sys.platform != "win32":
    hidden += collect_submodules("pystray") + collect_submodules("PIL")
if sys.platform == "darwin":
    hidden += ["IOBluetooth", "objc", "Foundation"]

a = Analysis(["launcher.py"], datas=datas, hiddenimports=hidden, excludes=["tkinter", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="NothingX", console=False,
          icon="nothingx/icon.ico" if sys.platform == "win32" else None, upx=False)
if sys.platform == "darwin":
    app = BUNDLE(exe, name="NothingX.app", icon=None, bundle_identifier="com.github.nothing-x-desktop-unofficial",
                 info_plist={"LSUIElement": True, "NSBluetoothAlwaysUsageDescription": "Talks to your earbuds."})
