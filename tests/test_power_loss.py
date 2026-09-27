"""Wire logs that lost power mid-write still parse.

After a hard power-off, ext4 can leave the end of a file that was being extended filled with NUL
bytes, and the logger then carries on appending after them. On the first real capture box that
put a run of NULs directly in front of the next line's timestamp, and parse_log (and
extract_fields) read the NULs as part of the timestamp and stopped with an error.
"""
import pytest

from tools import extract_fields, parse_log

LINES = [
    "2026-09-26 19:45:59.900Z  00000000  01 03 00 00 00 1C 44 03                          |......D.|\n",
    "2026-09-26 19:46:02.119Z  00000008  01 03 00 00 00 1C 44 03                          |......D.|\n",
]


@pytest.mark.parametrize("module", [parse_log, extract_fields], ids=["parse_log", "extract_fields"])
def test_nul_run_before_a_line_is_ignored(tmp_path, module):
    clean = tmp_path / "clean.log"
    clean.write_text("".join(LINES))
    damaged = tmp_path / "damaged.log"
    damaged.write_text(LINES[0] + "\x00" * 4096 + LINES[1])
    assert module.load_byte_stream(damaged) == module.load_byte_stream(clean)
