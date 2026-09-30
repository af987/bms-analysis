"""givcap-netcheck: restart Wi-Fi only when it claims to be connected but the gateway is dead.

On the first real box the Wi-Fi went silent while still "connected" after a mesh roaming
request, which is what the restart is for. When the Wi-Fi is not connected, NetworkManager is
already retrying, and an earlier version made things worse by restarting a connection that had
just come back. So a disconnected Wi-Fi is left alone, except that after 15 minutes the radio is
switched off and on once. The check runs every minute from a systemd timer; these tests run it
with fake ip, ping, nmcli, logger and sleep commands on PATH.
"""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "capture-box" / "givcap-netcheck"


def _fakes(tmp_path, ping_ok, wifi_state="connected", name="bin"):
    """Fake commands in tmp_path/<name>; every set logs to the same tmp_path/calls.txt."""
    bin_ = tmp_path / name
    bin_.mkdir(parents=True, exist_ok=True)
    calls = tmp_path / "calls.txt"
    scripts = {
        "ip": "echo 'default via 192.168.1.1 dev wlan0'",
        "ping": "exit 0" if ping_ok else "exit 1",
        "nmcli": (f'echo "nmcli $*" >> {calls}\n'
                  'case "$*" in\n'
                  '  *"con show --active"*) echo "home-wifi:802-11-wireless";;\n'
                  f'  *"dev"*) echo "wifi:{wifi_state}"; echo "ethernet:unavailable";;\n'
                  'esac'),
        "logger": f'echo "logger $*" >> {calls}',
        "sleep": "exit 0",
    }
    for name, body in scripts.items():
        (bin_ / name).write_text("#!/bin/bash\n" + body + "\n")
        (bin_ / name).chmod(0o755)
    return bin_, calls


def _run(tmp_path, bin_, times=1):
    env = {"PATH": f"{bin_}:/usr/bin:/bin", "GIVCAP_NETCHECK_STATE": str(tmp_path / "state")}
    for _ in range(times):
        subprocess.run(["bash", str(SCRIPT)], check=True, env=env)


def _calls(calls):
    return calls.read_text() if calls.exists() else ""


def test_restarts_connected_but_dead_wifi_after_three_checks(tmp_path):
    bin_, calls = _fakes(tmp_path, ping_ok=False)
    _run(tmp_path, bin_, times=2)
    assert "con down" not in _calls(calls)
    _run(tmp_path, bin_)
    assert "nmcli con down home-wifi" in _calls(calls) and "nmcli con up home-wifi" in _calls(calls)


def test_a_good_check_resets_the_count(tmp_path):
    bad, calls = _fakes(tmp_path, ping_ok=False)
    _run(tmp_path, bad, times=2)
    good, _ = _fakes(tmp_path, ping_ok=True, name="ok")
    _run(tmp_path, good)
    _run(tmp_path, bad, times=2)
    assert "con down" not in _calls(calls)


def test_leaves_a_disconnected_wifi_to_networkmanager(tmp_path):
    bin_, calls = _fakes(tmp_path, ping_ok=False, wifi_state="disconnected")
    _run(tmp_path, bin_, times=14)
    assert "con down" not in _calls(calls) and "radio" not in _calls(calls)


def test_a_disconnect_resets_the_dead_link_count(tmp_path):
    # Two dead-link checks, then NetworkManager reconnects: the count starts again.
    dead, calls = _fakes(tmp_path, ping_ok=False)
    _run(tmp_path, dead, times=2)
    down, _ = _fakes(tmp_path, ping_ok=False, wifi_state="disconnected", name="down")
    _run(tmp_path, down)
    _run(tmp_path, dead, times=2)
    assert "con down" not in _calls(calls)


def test_toggles_the_radio_after_fifteen_minutes_disconnected(tmp_path):
    bin_, calls = _fakes(tmp_path, ping_ok=False, wifi_state="disconnected")
    _run(tmp_path, bin_, times=15)
    assert "nmcli radio wifi off" in _calls(calls) and "nmcli radio wifi on" in _calls(calls)
    assert "con down" not in _calls(calls)
