"""Launch at login: Startup-folder shortcut (Windows), XDG autostart entry (Linux), LaunchAgent (macOS)."""
import os
import plistlib
import subprocess
import sys

from . import APP_NAME

LABEL = "com.github.nothing-x-desktop-unofficial"


def launch_command():
    """[argv] that starts this app the way it is installed now (frozen binary or python -m nothingx)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    exe = sys.executable
    if sys.platform == "win32":  # pythonw: no console window
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        exe = w if os.path.exists(w) else exe
    return [exe, "-m", "nothingx"]


def _path():
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup", APP_NAME + ".lnk")
    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "autostart", "nothingx.desktop")


def is_enabled():
    return os.path.exists(_path())


def enable():
    path, cmd = _path(), launch_command()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if sys.platform == "win32":
        ps = (f'$s=(New-Object -ComObject WScript.Shell).CreateShortcut("{path}");'
              f'$s.TargetPath="{cmd[0]}";$s.Arguments="{" ".join(cmd[1:])}";'
              f'$s.WorkingDirectory="{os.path.dirname(cmd[0])}";$s.Description="{APP_NAME}";$s.Save()')
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30)
    elif sys.platform == "darwin":
        with open(path, "wb") as f:
            plistlib.dump({"Label": LABEL, "ProgramArguments": cmd, "RunAtLoad": True}, f)
    else:
        with open(path, "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=" + APP_NAME + "\nExec=" + " ".join(cmd)
                    + "\nIcon=nothingx\nX-GNOME-Autostart-enabled=true\n")


def disable():
    try:
        os.remove(_path())
    except FileNotFoundError:
        pass


def set_enabled(on):
    (enable if on else disable)()
    return is_enabled()
