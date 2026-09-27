"""Tests for capture_checks: the three questions a G3 capture has to answer (see docs/02 G3 LV note)."""
import pandas as pd

from tools.capture_checks import cold_boots, end_of_charge, limit_roles

T0 = pd.Timestamp("2026-09-24 12:00:00", tz="UTC")


def _hr(rows):
    """rows: (seconds, current_A, hr26_A, hr27_A, volts) -> joined-style HR poll rows."""
    return pd.DataFrame([{
        "ts": T0 + pd.Timedelta(seconds=s), "device": 1, "fc": 3,
        "hr23_pack_current_cA": round(i * 100), "hr26_limit_cA": round(l26 * 100),
        "hr27_limit_cA": round(l27 * 100), "hr22_pack_voltage_cV": round(v * 100),
    } for s, i, l26, l27, v in rows])


def test_limit_roles_identifies_the_limit_charging_current_follows():
    # Charging at 20 A while HR26 says 50 A and HR27 says 20 A: current follows HR27.
    df = _hr([(s, 20.0, 50.0, 20.0, 53.0) for s in range(100)])
    r = limit_roles(df)
    assert r["charge"]["follows"] == "hr27"
    assert r["charge"]["rows"] == 100


def test_limit_roles_identifies_the_limit_discharging_current_follows():
    # Discharging at 30 A (negative) while HR26 = 30 A and HR27 = 10 A: current exceeds HR27, follows HR26.
    df = _hr([(s, -30.0, 30.0, 10.0, 51.0) for s in range(50)])
    assert limit_roles(df)["discharge"]["follows"] == "hr26"


def test_limit_roles_is_inconclusive_when_limits_are_equal():
    df = _hr([(s, 20.0, 40.0, 40.0, 53.0) for s in range(50)])
    assert limit_roles(df)["charge"]["follows"] == "inconclusive (limits equal)"


def test_limit_roles_ignores_rows_from_other_devices_and_fcs():
    df = _hr([(s, 20.0, 50.0, 20.0, 53.0) for s in range(10)])
    other = df.copy(); other["fc"] = 4
    r = limit_roles(pd.concat([df, other]))
    assert r["charge"]["rows"] == 10


def test_end_of_charge_bins_charging_current_by_voltage():
    rows = [(s, 40.0, 50, 50, 54.0) for s in range(20)] + [(100 + s, 10.0, 50, 50, 56.0) for s in range(20)]
    table = end_of_charge(_hr(rows), bin_V=0.2)
    assert list(table["volts"]) == [54.0, 56.0]
    assert list(table["median_current_A"]) == [40.0, 10.0]
    assert table.attrs["max_volts"] == 56.0


def test_cold_boots_measures_time_from_first_poll_to_first_current():
    before = [(s, 5.0, 50, 50, 52.0) for s in range(0, 10)]
    # 10-minute gap (inverter off), then polls resume idle and current starts 12 s later.
    after = [(600 + s, 0.0, 50, 50, 52.0) for s in range(0, 12)] + [(612 + s, 8.0, 50, 50, 52.0) for s in range(10)]
    boots = cold_boots(_hr(before + after), min_gap_s=60, min_current_A=1.0)
    assert len(boots) == 1
    assert boots[0]["gap_s"] == 591
    assert boots[0]["first_current_after_s"] == 12.0


def test_report_runs_what_it_can_when_columns_are_missing():
    from tools.capture_checks import report
    df = _hr([(s, 5.0, 50, 50, 52.0) for s in range(10)]).drop(columns=["hr26_limit_cA", "hr27_limit_cA", "hr22_pack_voltage_cV"])
    text = report(df)
    assert "HR26 / HR27: skipped, missing hr26_limit_cA, hr27_limit_cA" in text
    assert "End of charge: skipped, missing hr22_pack_voltage_cV" in text
    assert "Poll gaps: 0 found" in text


# A poll gap is a capture gap if the logger (re)started inside it; otherwise it's an inverter restart.

def _two_gaps():
    before = [(s, 5.0, 50, 50, 52.0) for s in range(0, 10)]
    mid = [(600 + s, 5.0, 50, 50, 52.0) for s in range(0, 10)]
    after = [(1200 + s, 5.0, 50, 50, 52.0) for s in range(0, 10)]
    return _hr(before + mid + after)


def test_logger_starts_are_read_from_the_wire_log(tmp_path):
    from tools.capture_checks import logger_starts
    log = tmp_path / "wire.log"
    log.write_text("# 2026-09-24 12:05:00.000Z logger started\n"
                   "2026-09-24 12:05:01.000Z  00000000  01 03 00 00 00 1C 44 03  |......D.|\n")
    assert logger_starts([log]) == [pd.Timestamp("2026-09-24 12:05:00", tz="UTC")]


def test_gap_containing_a_logger_start_is_a_capture_gap():
    boots = cold_boots(_two_gaps(), logger_starts=[T0 + pd.Timedelta(seconds=300)])
    assert [b["kind"] for b in boots] == ["capture gap", "inverter restart"]


def test_gaps_are_unknown_without_logger_markers():
    boots = cold_boots(_two_gaps())
    assert [b["kind"] for b in boots] == ["restart or capture gap"] * 2
