# Wire captures

This document covers the methodology for capturing RS485 traffic between the inverter and the BMS, and the timing / cadence findings from analysing those captures.

## Hardware

A USB-RS485 dongle in monitor (passive listen) mode is sufficient. Tested with:

- [Waveshare USB to RS485](https://www.waveshare.com/usb-to-rs485.htm) (~GBP 10-15, isolated, recommended)

Any FT232R or CH340-based USB-RS485 dongle works. Cheaper CP2102+SP485E modules can have signal-integrity issues - the Waveshare with a proper isolated transceiver is more reliable.

### Tap point

RS485 is a multidrop bus, so adding a passive listener doesn't disturb existing communication. The cleanest tap is at the inverter's BMS terminal block:

- Take an Ethernet cable
- Land its A and B wires (typically pins 4 & 5, or 1 & 2 on the BMS RJ45) on a spare position in the inverter's BMS terminal block (alongside the existing battery cable)
- Connect the dongle's A/B inputs to the same wires
- (Optional) Connect ground reference if the dongle has one

The dongle will see all traffic on the bus without interfering. No splicing of the existing cable is required.

## Capture software

The tool [`tools/serial_hexdump_logger.c`](../tools/serial_hexdump_logger.c) (originally by @kenbell) logs all incoming RS485 bytes with timestamps to a file. Output format:

```
2026-05-01 07:23:39.416Z  00000000  01 03 00 00 00 1C 44 03                          |......D.|
2026-05-01 07:23:39.516Z  00000008  01 03 38 00 65 FF FF FF FF FF FF FF FF XX XX XX  |..8.e...........|
2026-05-01 07:23:39.516Z  00000018  XX XX XX XX XX XX XX FF FF 00 BA 00 30 0B CE 00  |..............0.|
...
```

(Serial bytes redacted with `XX` placeholders. In a real capture, bytes 13-22 of the HR response carry the BMS serial as ASCII.)

Each line shows: timestamp, byte offset into the capture stream, up to 16 hex bytes, and the ASCII rendering of those bytes.

Timestamps are UTC, marked with a trailing `Z`. Logs from older versions of the logger are in the logging machine's local time with no zone marker. `tools/join_streams.py` refuses those unless you pass `--wire-tz` (e.g. `--wire-tz Europe/London`), because joining local time against `tcp_poller.py`'s UTC timestamps shifts every TCP value by the UTC offset.

The log file argument can be a `strftime` template, e.g. `captures/%Y-%m-%d/wire.log`. The logger expands it with the UTC date of each read, and switches to a new file, creating its directory, when the UTC date changes. A plain file name works as before.

Timestamps are when the logger flushed - lines sharing a timestamp are bytes received in the same flush, typically belonging to one Modbus frame. **Note**: occasionally the logger splits a frame across two flushes ~1 ms apart; a parser must handle this (see [`tools/parse_log.py`](../tools/parse_log.py) for a robust approach).

## Parsing the captures

[`tools/parse_log.py`](../tools/parse_log.py) reads `serial_hexdump_logger` output and reassembles complete Modbus frames using FC-determined length, validates the CRC of each frame, and produces structured output (per-frame role, device, FC, latency, etc.).

The parser correctly handles:

- The non-standard FC=4 response format (length implicit from the matching request's count, not from a byte_count field)
- Multi-flush frames (concatenated by content, not just timestamps)
- Out-of-sync recovery (skips malformed bytes, retries decode)
- Request -> response pairing (matches each response to the immediately preceding request)

Run on a logger output file:

```bash
python3 tools/parse_log.py path/to/logger_output.log
```

## Findings from a 3.4-minute cold-start capture

The reference capture (`cold_start.log` from @kenbell) was a 3.4-minute window starting in the middle of normal inverter operation, not from inverter cold boot - meaning the HR poll loop was already running when capture started.

### Frame totals

| Metric | Value |
|---:|---|
| Total bytes captured | 58,319 |
| Modbus frames decoded | 1,698 |
| Bytes dropped during resync | 0 (clean bus) |
| Capture span | 203.6 seconds |

### Cadence by query type

| Query | Count | Avg gap | Min | Max |
|---|---:|---:|---:|---:|
| Device 1 HR poll (FC=3, start=0, count=28) | 831 | 245.2 ms | 231 ms | 481 ms |
| Device N IR Block 1 (FC=4, start=0, count=21) | 9 (= 1x 5 devices + duplicates) | ~10 s | - | - |
| Device N IR Block 2 (FC=4, start=0x15, count=19) | 5 | ~10 s | - | - |
| Device N IR Block 3 (FC=4, start=0x28, count=20) | 4 | ~10 s | - | - |

The HR poll dominates. IR queries are interleaved opportunistically.

### BMS turnaround latencies (request -> response gap)

| Query | n | mean | p50 | p95 | min | max |
|---|---:|---:|---:|---:|---:|---:|
| Device 1 HR poll | 831 | 101 ms | 101 | 103 | 90 | 114 |
| Device N IR Block 1 | 6 | 87 ms | 88 | 89 | 87 | 89 |
| Device N IR Block 2 | 5 | 84 ms | 84 | 84 | 83 | 84 |
| Device N IR Block 3 | 4 | 86 ms | 86 | 87 | 84 | 87 |

The HR turnaround is ~17 ms longer than IR because the HR response is larger (61 bytes vs 47 / 43 / 45) and that takes longer to TX at 9600 baud.

**Practical emulator latency budget**: respond within ~100 ms of a request to look like a real BMS. This is generous for a Pi or ESP32 implementation.

### Boot-sequence shape

The capture starts mid-stream with the HR poll loop already running. Observed:

- **First 12 seconds**: HR poll only, every ~250 ms to device 1
- **+12s onwards**: First IR poll fires (device 1 Block 1)
- **+12s to +180s (cycle complete)**: Full 5-device IR sweep across all 3 blocks, ~10s spacing
- **HR poll never pauses** throughout

There's no special boot probe or handshake - the inverter just immediately begins polling device 1 after it sees the BMS is responsive.

### "Absent device" pattern

Ken's setup has 2 batteries (devices 1 and 2). The inverter still polls devices 3, 4, 5 - and gets back specific empty-but-valid responses. See [03-input-registers.md](03-input-registers.md) for the byte-level pattern.

## Findings from a 90-hour G3 capture

@af987 captured a GivEnergy G3 Hybrid 3.6 kW inverter with one 9.5 kWh battery (PR #14). The capture ran from 21 to 25 August 2026, about 90 hours, and covers 1.35 million request and response pairs. It includes the RS485 wire stream and a 1 Hz `tcp_poller.py` stream from the same system, joined with `tools/join_streams.py`.

### Timestamp alignment

The wire timestamps in this capture are local time (BST) that was labelled as UTC, so the wire stream is one hour ahead of the TCP stream. Before the correction, HR23 and the inverter's reported battery current correlate at 0.47. After moving the wire stream back one hour, they correlate at 0.997, with a median difference of 0.17 A. All the results below use the corrected alignment. The logger now writes UTC, and `join_streams.py --wire-tz` handles older logs, so new captures don't have this problem.

### Poll cadence on a G3

| Query | Interval per device |
|---|---|
| HR poll (device 1, FC=3, start 0, count 28) | 240 ms, with occasional gaps of 480 ms |
| IR Block 1 (FC=4, start 0x0000, count 21) | about 10.5 s |
| IR Block 2 (FC=4, start 0x0015, count 19) | about 200 s |
| IR Block 3 (FC=4, start 0x0028, count 20) | about 200 s |

The inverter polls devices 2 to 5 as well, and with one battery fitted those slots return the absent-device pattern.

### The inverter reports the BMS values unchanged

Every battery value that the inverter publishes over Modbus TCP matches a value on the wire exactly, once you allow for a delay of 10 to 20 seconds between the wire read and the TCP value:

| TCP field (`tcp_poller.py`) | Wire source | Match after 20 s |
|---|---|---|
| `soc` | IR Block 2, SoC byte | 100% |
| `num_cycles` | IR Block 2, cycle count | 100% |
| `cap_remaining` | IR Block 2, remaining capacity | 100% |
| `v_cell_01` to `v_cell_16` | IR Block 3, cell voltages | 100% |
| `t_max` | IR Block 3, offset 32 (0.1 °C) | 100% |
| `t_min` | IR Block 3, offset 34 (0.1 °C) | 100% |
| battery current (`p_battery / v_battery`) | HR23 (0.01 A) | correlation 0.997 |

So an emulator controls what the inverter and the GivEnergy app show by setting these registers. The five temperatures in IR Block 1 are separate sensors. They don't feed `t_max` or `t_min`.

### Values that stayed fixed

- **HR11** stayed at 186 for the whole capture while SoC moved between 4% and 95%. 186 Ah at 51.2 V is 9.5 kWh, the size of this battery. HR11 behaves as the capacity of the batteries online, not the remaining charge. See [02-holding-registers.md](02-holding-registers.md).
- **HR25** stayed at 15000 (150 A).
- The inverter's charge and discharge limits over TCP changed once, from 38% to 50%, at 22:55 UTC on 23 August. The BMS registers didn't change at that moment, so the change came from an inverter setting.
- The largest currents were 65 A charging and 76 A discharging. On a 3.6 kW inverter these fit the inverter's own power limit.

### Discharge stops at the 4% SoC floor

GivEnergy inverters stop discharging at 4% SoC. Discharge stopped twice in this capture, at 18:20 UTC on 21 August and at 17:59 UTC on 24 August. The last SoC readings from IR Block 2 before each stop were 9, 7, 5% and 10, 8, 5%, falling about 2% per 200 s reading. So SoC reached 4% between the last reading and the stop. The inverter uses the SoC that the BMS sends in IR Block 2 to decide when to stop.

At the same poll that the current dropped to zero, HR19 bit 3 (0-indexed) started switching between set and clear on almost every poll. HR19 moved between 206 and 198, or between 207 and 199. The lowest cell was then between 2966 and 3039 mV. The switching continued until the battery next charged, about 8 hours later on 21 August and about 70 minutes later on 24 August. During normal discharge HR19 was always 207. The switching started after the stop, not before, so it doesn't look like the reason the inverter stopped. It matches Ken's note that bit 4 (1-indexed) "oscillates below 4% SOC".

### Gaps in this capture

The joined parquet file doesn't include HR20, HR21, HR22, HR24, HR26 or HR27, because the decoder didn't extract them when it was made. The decoder now does, so rerunning `join_streams.py` on the raw wire log adds them.

## Findings from my G3 capture (September 2026)

I captured my own Hybrid Gen3 LV (firmware D0.316-A0.316) with its GivEnergy 8.2 kWh battery (BMS firmware 3020) using the Raspberry Pi capture box in [capture-box/](../capture-box/README.md), from 17:05 UTC on 26 September to 15:57 UTC on 27 September 2026, about 23 hours. The dongle was tapped on the battery's "Batt to Batt" comms terminals, and GivTCP's MQTT output was recorded alongside. The capture covers an evening of discharge, a forced overnight charge to 100%, the night at full charge, and the next day, when SoC stayed between 83% and 100%. The inverter setting HR109 `enable_bms_read` was 1, and HR111/HR112 (charge/discharge limit) were both 44.

### Poll cadence and turnaround

The pattern matches the 90-hour capture above. In 7 hours on 27 September:

| Query | Requests | Cadence | BMS turnaround |
|---|---:|---|---|
| Device 1 FC3 HR0 to HR27 | 103,122 | every 245.8 ms (236 to 482 ms) | 101 ms median (97 to 105) |
| FC4 block 1 (start 0x00, count 21), devices 1 to 5 | about 250 each | about every 10 s in bursts, 100 s on average | 87 ms median |
| FC4 blocks 2 and 3 (0x15/19 and 0x28/20), devices 1 to 5 | about 126 each | every 200.5 s | 83 to 85 ms median |

Every request got a reply, including those for devices 2 to 5. With one battery fitted, the master battery answers for the absent packs with the empty-slot reply described in [03-input-registers.md](03-input-registers.md): all zeros, with the temperature fields at `0xF556` (-273.0 C).

### The limits during a full charge

The battery reported HR25 = 90.00 A and HR26 = HR27 = 80.00 A throughout, except at the very top of the charge.

| Time (UTC) | SoC | Pack voltage (HR22) | Charge current | HR26 | HR27 |
|---|---|---|---|---|---|
| 22:30 to 23:15 | 59% to 90% | 53.4 V to 54.35 V | 60.5 A | 80 A | 80 A |
| 23:20 to 23:35 | 93% to 98% | 54.3 V to 55.2 V | 43.6 A down to 14.6 A | 80 A | 80 A |
| 23:40 | 99% | 56.9 V | 2.9 A | **3.20 A** | 80 A |
| from 23:45 | 100% | about 56.1 V to 56.6 V | about 0 A | 3.20 A | 80 A |

Three things follow:

- **HR26 caps charging on a G3 LV.** When the BMS cut HR26 to 3.20 A and left HR27 at 80 A, the charge current dropped to about 2.9 A at once and stayed under HR26, as the labels in [02-holding-registers.md](02-holding-registers.md) say. The G3 LV DSP firmware agrees (see [05-inverter-firmware.md](05-inverter-firmware.md#a316-the-dsp-runs-the-bms-bus)).
- **The inverter tapers the charge itself before the BMS does.** The current held at about 60.5 A (the inverter's 3600 W charge rate at about 54 V) up to 90% SoC, then fell to about 14.6 A over 20 minutes with HR26 and HR27 still at 80 A. An emulator doesn't need to produce this taper; the inverter does it.
- **At full charge the BMS keeps HR26 at 3.20 A**, and the inverter tops the pack up every so often at about 3 A for a few minutes, with short discharges of about 2.9 A in between. The BMS held HR26 at 3.20 A from before midnight until 04:37 UTC. Then it released it in steps of 10 A every 11 s (13.20 A, 23.20 A and so on up to 73.20 A), and then to 80.00 A.

### Voltages at the top of the charge

The inverter's own battery voltage reading (GivTCP) was 0.2 V to 0.3 V above HR22 at rest and about 1.3 V above it at 60 A, the drop in the battery cable. At 100% the pack sat at about 56.1 V to 56.6 V (median 56.13 V by HR22). The 3 A top-ups briefly took HR22 to 57.53 V and the inverter's reading to 57.61 V, with no fault raised.

There were three top-ups after the main charge:

| Top-up (UTC) | Charge current | HR22 | Inverter's reading | HR20 while charging |
|---|---|---|---|---|
| 23:38 to 23:43, end of the main charge | 14.7 A down to 2.8 A | 55.39 V to 57.06 V | up to 57.37 V, above 57.0 V for about 3 minutes | 0 |
| 00:35 to 00:37 | 2.9 A | 56.13 V to 57.13 V | up to 57.35 V, above 57.0 V for about 2.5 minutes | 0 |
| 01:21 to 01:22 | 2.9 A | 56.66 V to 57.52 V | up to 57.61 V, above 57.0 V for about 2 minutes | 0 |

HR20 bit 2 (over-voltage) was clear during every charge. It was set only when the last top-up ended, at the 57.52 V peak of HR22, and it stayed set for 271 s while the pack discharged at about 2.8 A (HR19 bit 5, see [02-holding-registers.md](02-holding-registers.md#evidence-from-my-g3-capture-september-2026)). HR22 fell from its peak and was above 57.0 V for only about 70 s of that time.

The inverter settings HR98 and HR97 were 58.5 V and 43.2 V all night. The G3's over-voltage trip comes from HR98 and is at 59.5 V for 1 s on the inverter's own reading (see [05-inverter-firmware.md](05-inverter-firmware.md#battery-voltage-checks)), so readings up to 57.61 V for minutes with no fault are what the firmware predicts. The inverter's status stayed normal all night.

### Discharge

During the evening the battery discharged from 99% down to 58% SoC. Over the whole capture the largest discharge current was 70.45 A (about 3.6 kW), and the lowest pack voltage was 52.11 V. The largest charge current was 61.07 A. HR27 stayed at 80.00 A throughout.

### No writes to the battery

The capture holds 478,645 frames with no framing errors. The inverter sent only FC=3 and FC=4: 233,594 HR polls and 5,729 IR polls. There was no FC=6 write at all in 23 hours. So in normal running a G3 LV doesn't write to the battery. The DSP has FC=6 write paths on counters (see [05-inverter-firmware.md](05-inverter-firmware.md#a316-the-dsp-runs-the-bms-bus)), but their conditions didn't occur here.

### Status bits

Once the battery had started up, HR19 took only four values: `0xCF`, `0xCE`, `0xC7` and `0xEF`. `0xC7` is bit 3 clear at high cell voltage, and `0xEF` is bit 5 set at full charge (see [02-holding-registers.md](02-holding-registers.md#evidence-from-my-g3-capture-september-2026)). HR20 was either 0 or `0x0004` (bit 2, over-voltage), as after the last top-up described above.

### Gaps in this capture

The poll gaps in this capture were the capture box being off or restarting, not the inverter. The first box's Wi-Fi also dropped several times (see the capture-box README), which didn't affect the wire log. From 27 September the logger writes a start marker, so `tools/capture_checks.py` can tell capture gaps from inverter restarts.

### Discharge to the reserve and a full charge (27-29 September)

I ran a further capture on my G3 LV from 27 to 29 September 2026, over two million frames with no framing errors, covering a slow discharge to the reserve, a forced discharge to the reserve, and a full charge back up from there. The battery is the same GivEnergy 8.2 kWh Gen 1 pack (BMS firmware 3020).

GivEnergy's own retired-product figures for this pack give a true capacity of 10.24 kWh / 200 Ah, a usable capacity of 8.192 kWh / 160 Ah ("100% DoD"), 51.2 V nominal, and a maximum of 85 A / 4.096 kW. HR11 reports 160 Ah on my battery. Block 2's calibrated capacity had fallen to 147.66 Ah after 740 cycles.

**Discharge to the reserve.** Two runs reached the floor:

- 27 September, a slow evening discharge under about 7 A: HR21 reached 5% at 22:30 UTC. Pack voltage 50.73 V, lowest cell 3.167 V, cell spread about 10 mV.
- 28 September, a forced discharge at about 71 A: HR21 reached 4% at 21:29:01 UTC, and the inverter stopped within about a second of that reading (current stepping -71 A, -22.6 A, -0.2 A). Under 71 A at 5%, just before the stop, the pack had sagged to 49.41 V and the lowest cell to 3.087 V. At rest afterwards the pack recovered to 50.9-51.0 V and the cells to 3.18-3.19 V, still on the LFP plateau. That's a hidden buffer below the inverter's "0%", consistent with 160 Ah usable out of a true 200 Ah.

At the floor the BMS didn't soften anything: HR27 (discharge limit) stayed at 80.00 A all the way to 4%, HR20 stayed 0, and HR19 bit 3 never cleared, unlike the 90-hour G3 capture above, where bit 3 flickered at the floor. On mine, HR19 just toggled between `0xCF` and `0xCE` with the sign of the near-zero current (bit 0). The battery held at 4% for 61 minutes, within 0.1 A throughout, and SoC never went below 4%, so the DSP's floor force-charge (see [05-inverter-firmware.md](05-inverter-firmware.md#what-the-dsp-does-with-the-bms-status-registers)) never triggered.

**A full charge from the reserve.** The off-peak charge started at 28 September 22:30:12 UTC (23:30 BST) from 4% SoC and 51.09 V, straight to about 61 A with no ramp:

| SoC | Charge current | Notes |
|---|---|---|
| 4% to 91% | steady ~60.5 A | about 2 h 5 min; roughly 1% per 88 s, which is 1.6 Ah per % of 160 Ah |
| 91% to 97% | 59.8, 54.4, 48.9, 43.1, 37.6, 31.7, 25.9 A | the inverter's own taper, about -5.8 A per %, with HR26 still at 80 A |
| 98% (00:52 UTC) | cut to 8.00 A | cells jumped from about 3.43 V to 3.52-3.59 V, pack 56.62 V; BMS cuts HR26 |
| 99% | cut to 3.20 A | pack 57.40 V, highest cell 3.590 V, top spread 68 mV (against about 10 mV at the bottom) |
| 100% (00:58:18 UTC) | about -3.2 A | BMS sets HR20 = `0x0004` and HR19 = `0xEF` (bit 5); the DSP forces a small discharge |

That knee, and the HR19 bit 5 / HR20 bit 2 behaviour at full charge, match the September top-up findings above and the firmware analysis in [05-inverter-firmware.md](05-inverter-firmware.md#a316-the-dsp-runs-the-bms-bus). HR26 later released back to 80 A in +10 A steps, as in the earlier capture.

No FC=6 write appeared anywhere in this capture either.

See [07-emulator-implications.md](07-emulator-implications.md) for what the reserve behaviour and the hidden buffer mean for an emulator.

### A solar charge to full and the trickle release (29 September)

The same capture ran on into 29 September, 07:23 to 20:05 UTC, 602,677 frames with no framing errors and no FC=6 write. This stretch covers a charge from solar rather than a forced charge, and what happens after the BMS cuts the current at the top.

Solar current varies with the sun, up to 51.6 A on my system that day. At 98% SoC the BMS cut HR26 the same way it did during the forced charge on 28-29 September: 80.00 A, then 32.00 A, then 8.00 A, then 3.20 A, all within 2.5 minutes (12:24:26, 12:25:20 and 12:27:01 UTC), as the highest cell passed about 3.47-3.50 V. So the cut follows the highest cell, not how the charge is driven.

At 100% HR20 bit 2 and HR19 bit 5 pulsed 976 and 975 times that day, about 16 minutes in total, each pulse matching the DSP's small forced discharge of about -3.2 A, as in the earlier capture. At rest at 100% the highest cell sat at 3.46-3.49 V for about 2.5 hours (lowest cell 3.43-3.45 V), and the spread at the knee reached 79 mV, against 68 mV the night before.

**The trickle release.** The BMS held HR26 at 3.20 A for 2 hours 40 minutes, from 12:27 to 15:07 UTC, then released it at 15:07:43 in steps of +10 A about every 11 seconds back up to 80.00 A. The release came just after the pack started discharging and the highest cell fell through about 3.40 V:

| Time (UTC) | Highest cell | Pack current | HR26 |
|---|---|---|---|
| 14:53 | 3.480 V | at rest | 3.20 A |
| 15:03 | 3.432 V | -5 to -8 A | 3.20 A |
| 15:06 | 3.404 V | -5 to -8 A | 3.20 A |
| 15:07:43 | below 3.40 V | -5 to -8 A | releases: 13.20, 23.20, ... 80.00 A |

On the early-morning full charge from the reserve (29 September), the same hold lasted longer: 3 hours 43 minutes at 3.20 A before release. Different hold times, same trigger: the release follows the pack coming off the top and the highest cell falling to about 3.40 V, not a fixed timer.

HR15 bit 0 was set again during this solar charge, for 26,297 polls, and clear the rest of the day, matching the earlier correction that bit 0 marks charging, not 100% SoC (see [02-holding-registers.md](02-holding-registers.md#register-15-bits)).

Other ranges that day: SoC 46% to 100%, discharge current up to 71.2 A, pack voltage (HR22) 51.57 V to 57.50 V, battery temperature (HR24) 23 to 27 degC.

## Capture experiments worth running

To resolve remaining open questions, useful targeted captures would be:

| Capture scenario | Resolves |
|---|---|
| Discharge under significant load | Reg 23 (current) magnitude / sign behaviour; reg 21 (suspected SoC) decreasing |
| Charge from grid (Eco mode) | Reg 11 transition triggers; charge-mode bit positions |
| Force-charge or force-discharge | FC=06 write traces to address 0x00E7 (control byte) |
| Low-SoC condition (~10%) | Warning/fault bits in reg 19 |
| Inverter cold boot | First-byte-after-power-on probe sequence (if any) |
| Imbalance condition | Balancing-active flag identification |
| Multi-battery added/removed | "Device appears" / "device disappears" handling |

## Validation campaign methodology

The analysis in this repository was extended by running a controlled validation campaign against a real GivEnergy LV system, using three time-aligned data streams:

1. **RS485 wire sniff** via `tools/serial_hexdump_logger.c` (a USB-RS485 dongle in parallel passive-tap mode at the inverter BMS terminal block).
2. **Modbus TCP poll** of the inverter's local API via `tools/tcp_poller.py` at 1 Hz, providing the inverter's own published interpretation of BMS state -- used as ground-truth labels for wire-side decoding.
3. **Scenario annotations** via `tools/tag.py`, manual at the boundary of forced transitions (force-charge, force-discharge, current-limit step) and auto-derived from the TCP stream's mode-change events.

The three streams are post-hoc time-aligned via `tools/join_streams.py` into a single parquet keyed by NTP wall-clock timestamp. `tools/analysis_template.ipynb` provides a starting point for the analysis itself, structured as PACE-hypothesis-first per-unknown sections (see [09-pace-comparison.md](09-pace-comparison.md) for why PACE is the natural hypothesis source).

To reproduce on your own system:

1. Configure `~/.givenergy-redact.toml` with your serials and IPs (used by `tools/redact.py` before sharing any artefact).
2. Run a 48-72 hour passive capture under your normal solar/load cycle.
3. Optionally run a 30-45 minute active session forcing high-SoC dwell, low-SoC dwell, and current-limit changes.
4. Run `tools/join_streams.py` to produce the parquet.
5. Open `tools/analysis_template.ipynb`, point it at your capture directory, and work through each unknown section.
6. Run `python tools/capture_checks.py joined.parquet` for the three G3 LV checks: which of HR26/HR27 the current follows, the end-of-charge taper, and cold-boot acceptance time. Capture a full charge, a discharge to the SoC floor and at least one inverter power cycle to give it something to find.
