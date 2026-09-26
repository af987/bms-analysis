"""givcap-netcheck restarts Wi-Fi after 3 failed gateway checks in a row.

On the first real box the Pi's Wi-Fi went silent while still "connected" after a mesh roaming
request. The check runs every minute from a systemd timer; this test runs it with fake ip,
ping, nmcli and logger commands on PATH.
"""
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "capture-box" / "givcap-netcheck"


def _fakes(tmp_path, ping_ok):
    bin_ = tmp_path / "bin"
    bin_.mkdir(parents=True)
    calls = tmp_path / "calls.txt"
    scripts = {
        "ip": "echo 'default via 192.168.1.1 dev wlan0'",
        "ping": "exit 0" if ping_ok else "exit 1",
        "nmcli": (f'echo "nmcli $*" >> {calls}\n'
                  'case "$*" in *"con show --active"*) echo "home-wifi:802-11-wireless"; echo "Wired:802-3-ethernet";; esac'),
        "logger": f'echo "logger $*" >> {calls}',
        "sleep": "exit 0",
    }
    for name, body in scripts.items():
        (bin_ / name).write_text("#!/bin/bash\n" + body + "\n")
        (bin_ / name).chmod(0o755)
    return bin_, calls


def _run(tmp_path, bin_):
    env = {"PATH": f"{bin_}:/usr/bin:/bin", "GIVCAP_NETCHECK_STATE": str(tmp_path / "fails")}
    subprocess.run(["bash", str(SCRIPT)], check=True, env=env)


def test_restarts_active_wifi_after_three_failures(tmp_path):
    bin_, calls = _fakes(tmp_path, ping_ok=False)
    for _ in range(2):
        _run(tmp_path, bin_)
    assert "con down" not in calls.read_text()
    _run(tmp_path, bin_)
    log = calls.read_text()
    assert "nmcli con down home-wifi" in log and "nmcli con up home-wifi" in log
    assert (tmp_path / "fails").read_text().strip() == "0"


def test_a_good_check_resets_the_count(tmp_path):
    bin_, calls = _fakes(tmp_path, ping_ok=False)
    _run(tmp_path, bin_)
    _run(tmp_path, bin_)
    ok_bin, _ = _fakes(tmp_path / "ok", ping_ok=True)
    _run(tmp_path, ok_bin)
    assert (tmp_path / "fails").read_text().strip() == "0"
    assert "con down" not in calls.read_text()
