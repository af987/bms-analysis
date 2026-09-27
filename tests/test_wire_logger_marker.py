"""serial_hexdump_logger writes a marker line when it starts.

A gap in the HR poll can be the inverter restarting or the logger not running (the Pi was off or
rebooted). The marker, '# <UTC time>Z logger started', lets capture_checks tell the two apart.
parse_log skips it like any other line that isn't hex.
"""
import os
import pty
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

from tools import parse_log

REPO = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("cc") is None, reason="needs a C compiler")
MARKER = re.compile(r"^# \d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}Z logger started$")


def test_logger_writes_a_start_marker(tmp_path):
    exe = tmp_path / "logger"
    subprocess.run(["cc", "-O2", "-o", str(exe), str(REPO / "tools/serial_hexdump_logger.c")], check=True)
    master, slave = pty.openpty()
    log = tmp_path / "wire.log"
    proc = subprocess.Popen([str(exe), os.ttyname(slave), str(log)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not (log.exists() and log.stat().st_size):
            time.sleep(0.02)
        os.write(master, bytes.fromhex("01 03 00 00 00 1C 44 03"))
        deadline = time.time() + 5
        while time.time() < deadline and "44 03" not in log.read_text():
            time.sleep(0.02)
    finally:
        proc.send_signal(signal.SIGTERM)
        os.write(master, b"\x00")
        proc.wait(timeout=5)
        os.close(master); os.close(slave)
    lines = log.read_text().splitlines()
    assert MARKER.match(lines[0]), lines[0]
    stream, _ = parse_log.load_byte_stream(log)
    assert bytes(stream).startswith(bytes.fromhex("01 03 00 00 00 1C 44 03"))
