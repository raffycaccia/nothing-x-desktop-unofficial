"""Launch-at-login entries are created and removed in a sandboxed home."""
import os
import sys

import pytest

from nothingx import autostart


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(tmp_path)))
    return tmp_path


def test_launch_command_points_at_this_interpreter():
    cmd = autostart.launch_command()
    assert cmd[-2:] == ["-m", "nothingx"] and os.path.exists(cmd[0])


def test_enable_disable_round_trip(home):
    assert not autostart.is_enabled()
    assert autostart.set_enabled(True) is True
    path = autostart._path()
    assert os.path.exists(path) and str(home) in path
    if sys.platform == "linux":
        assert "Exec=" in open(path).read()
    assert autostart.set_enabled(False) is False
    autostart.disable()  # idempotent
