# GivEnergy BMS Analysis

Documentation and analysis of the GivEnergy LV battery BMS protocol (Gen 1 / Gen 2 batteries, BMS firmware 30xx; a Gen 3 battery on firmware 4009 has been seen on the wire too). With GivEnergy in administration as of 2026, the goal is to keep installed kit useful by opening up the protocol enough for two complementary integrations:

1. **Third-party LFP battery + GivEnergy inverter** - an emulator pretends to be a GivEnergy BMS so a cheaper LFP pack can be used in place of an out-of-warranty / unobtainable original. See [docs/07-emulator-implications.md](docs/07-emulator-implications.md). My own route is a GivEnergy LV RS485 inverter module for [Battery-Emulator](https://github.com/dalathegreat/Battery-Emulator), fed by its Growatt LV CAN battery reader (fork PR [abedegno/Battery-Emulator#1](https://github.com/abedegno/Battery-Emulator/pull/1)).

2. **GivEnergy battery + third-party inverter** - a bridge reads the GivEnergy battery and re-presents it on a standard protocol (Pylontech CAN being the prime target, supported by Victron, Deye, Goodwe, Sungrow, Sofar and many others). See [docs/08-bridge-implementation.md](docs/08-bridge-implementation.md).

Plus the obvious side-benefit: BMS health monitoring and diagnostics directly from the battery, without going through GivEnergy's cloud.

## Background

The original empirical analysis - hardware setup, RS485 captures, raw hex traces, and field-by-field interpretations - was started by @kenbell in [NOTES.md](NOTES.md). This documentation expands on that empirical work with:

- Static analysis of the official BMS firmware (multiple versions: 3017, 3020, 3022)
- Static analysis of multiple inverter firmware variants (FA-series, A316/D316 Hybrid Gen 3 LV, A920 Hybrid Gen 2, etc.), including how the G3 LV inverter's DSP uses each BMS register
- Wire-capture parsing and timing analysis
- Implementation guidance for both emulator (Goal 1) and bridge (Goal 2) directions

## Documentation index

| File | Topic |
|---|---|
| [docs/00-glossary.md](docs/00-glossary.md) | Glossary of terms (Modbus, FCs, embedded, battery, etc.) - **start here if jargon trips you up** |
| [docs/01-protocol.md](docs/01-protocol.md) | Modbus framing, baud rate, CRC, function-code support, FC=4 non-standard format |
| [docs/02-holding-registers.md](docs/02-holding-registers.md) | HR(0..27) layout, field-by-field interpretation, polling cadence |
| [docs/03-input-registers.md](docs/03-input-registers.md) | IR Block 1/2/3, layouts, cell voltages, device rotation, "absent device" pattern |
| [docs/04-bms-firmware.md](docs/04-bms-firmware.md) | BMS firmware static analysis - MCU, register table, FC handlers, internal architecture |
| [docs/05-inverter-firmware.md](docs/05-inverter-firmware.md) | Inverter firmware analysis - variants, validation rules, "BMS protocol is the constant" insight, and what the G3 LV DSP does with each BMS register |
| [docs/06-wire-captures.md](docs/06-wire-captures.md) | Cadence, latency, IR rotation pattern, capture methodology, and findings from G3 captures (charge, discharge to the reserve, full charge) |
| [docs/07-emulator-implications.md](docs/07-emulator-implications.md) | **Goal 1** - Emulator implementation (3rd-party battery -> GivEnergy inverter) |
| [docs/08-bridge-implementation.md](docs/08-bridge-implementation.md) | **Goal 2** - Bridge implementation (GivEnergy battery -> 3rd-party inverter). An earlier plan, now superseded by the Battery-Emulator route (GivEnergy LV RS485 module with the Growatt LV CAN reader, fork PR abedegno/Battery-Emulator#1) |
| [docs/09-pace-comparison.md](docs/09-pace-comparison.md) | Field-by-field comparison between the GivEnergy Modbus layout and PACE / Pylontech - useful background for both goals |
| [docs/10-pace-bms-tools.md](docs/10-pace-bms-tools.md) | Guide on accessing the PACE BMS directly |
| [docs/11-seplos-emulator-design.md](docs/11-seplos-emulator-design.md) | **Goal 1** - An earlier design for a Seplos BMS battery (e.g. Fogstar 32 kWh) on a GivEnergy G3 inverter. Superseded by the Battery-Emulator route (GivEnergy LV RS485 module with the Growatt LV CAN reader, fork PR abedegno/Battery-Emulator#1) |

## Tools

| File | Purpose |
|---|---|
| [tools/serial_hexdump_logger.c](tools/serial_hexdump_logger.c) | Logs all RS485 traffic with timestamps to a file. Useful for protocol analysis. |
| [tools/modbus_register_logger.c](tools/modbus_register_logger.c) | Passively watches the bus for reads/responses involving a specific register, logs that register's value over time (text or CSV). Useful for tracking how a single field varies under known conditions. |
| [tools/modbus_proxy.c](tools/modbus_proxy.c) | Requires two USB RS485 dongles, sits actively in the path, able to modify in-flight register values and dump RS485 traffic to file on-command. |
| [tools/extract_fields.py](tools/extract_fields.py) | Pulls chosen register values out of a `serial_hexdump_logger` log into a CSV, one row per request/response pair, as words, signed words or bits. |
| [tools/parse_log.py](tools/parse_log.py) | Parses serial_hexdump_logger output into Modbus frames with cadence/latency analysis. Handles GivEnergy's non-standard FC=4 framing. |
| [tools/tcp_poller.py](tools/tcp_poller.py) | Polls the inverter's local Modbus TCP API at a fixed cadence and emits NDJSON. Used as a labelled ground-truth stream during a wire-capture campaign. |
| [tools/mqtt_logger.py](tools/mqtt_logger.py) | Records GivTCP's MQTT output as NDJSON snapshots in the same format as `tcp_poller.py`, without polling the inverter. Used by the capture box. |
| [tools/givcap_status.py](tools/givcap_status.py) | Capture box health check (`givcap-status`): service state, age of the last line in today's files, free disk and clock sync. |
| [capture-box/](capture-box/README.md) | Raspberry Pi capture box: systemd services, udev rule and setup script for recording the BMS bus and GivTCP's MQTT output around the clock. |
| [tools/tag.py](tools/tag.py) | Manual + auto scenario annotation helper. Manual mode appends one timestamped tag; auto mode tails a TCP NDJSON file and emits tags on state changes. |
| [tools/decode_fields.py](tools/decode_fields.py) | Field-level decoder: takes a parsed Modbus response frame and returns a dict of named BMS fields per `docs/02` and `docs/03`. |
| [tools/pace_reference.py](tools/pace_reference.py) | Reference data for PACE / Pylontech v2.5 protocol fields and bit positions. Used by analysis notebooks to test PACE hypotheses against decoded GivEnergy fields. |
| [tools/join_streams.py](tools/join_streams.py) | Time-align wire + TCP + tag streams from a campaign into a single parquet for analysis. |
| [tools/capture_checks.py](tools/capture_checks.py) | Runs three checks on a joined capture: which of HR26/HR27 the charge and discharge current follows, charging current by pack voltage near full, and the time from the first poll to battery current after each cold boot. |
| [tools/redact.py](tools/redact.py) | Privacy filter -- strips configured serials and IPs from capture artefacts before sharing. Reads `~/.givenergy-redact.toml` or env vars. |
| [tools/build_notebook.py](tools/build_notebook.py) | Generates `analysis_template.ipynb`, the per-campaign analysis scaffold. |
| [tools/analysis_template.ipynb](tools/analysis_template.ipynb) | Jupyter starting point for analysing a campaign capture -- PACE-hypothesis-first per-unknown sections. |

## System scope

The analysis started on a GivEnergy "classic" Low-Voltage system: an AC 3.0 inverter with two Gen 2 9.5 kWh LiFePO4 batteries (Ken's captures in [NOTES.md](NOTES.md)). Later captures come from Hybrid Gen 3 LV inverters: mine with a Gen 1 8.2 kWh battery (BMS firmware 3020), and @af987's 3.6 kW with a Gen 3 9.5 kWh battery (BMS firmware 4009). The batteries are compatible with:

- AC 3.0 inverters
- Gen 1 Hybrid inverters
- Gen 2 Hybrid inverters
- Gen 3 Hybrid LV inverters (firmware A316/D316)

Because the same BMS works with all of these, **the wire protocol is invariant across inverter variants** - inverters' internal firmware differs but they all produce the same Modbus requests on the wire. See [docs/05-inverter-firmware.md](docs/05-inverter-firmware.md) for details.

This analysis does **not** cover High-Voltage (HV) batteries or All-In-One (AIO) inverters; those use different battery families.

## Status

| Topic | State |
|---|---|
| Wire protocol fundamentals | Well-understood |
| Function codes used | Confirmed: FC=3 read, FC=4 read, FC=6 write (rare) |
| HR(0..27) field meanings | ~70% mapped (see [docs/02](docs/02-holding-registers.md)) |
| IR field meanings | Most fields mapped (see [docs/03](docs/03-input-registers.md)) |
| FC=4 framing format | **Non-standard** - resolved (see [docs/01](docs/01-protocol.md)) |
| Inverter validation rules | Lenient on FA, stricter on older variants - mapped |
| BMS alerts / mode flags | Partially understood. What the G3 LV DSP does with HR15, HR19 and HR20 is traced (see [docs/05](docs/05-inverter-firmware.md)) |
| BMS firmware versions covered | 3017, 3020, 3022 (LV) by static analysis; 4009 (Gen 3) on the wire only; not HV |

## Contributing

Contributions welcome. Common useful contributions:

- More wire captures, especially under specific conditions (charge / discharge / fault / balancing)
- Captures from different inverter variants
- Additional firmware versions
- Emulator (Goal 1) implementations and test reports against real GivEnergy inverters
- Bridge (Goal 2) implementations - especially Pylontech-CAN bridges tested against Victron / Deye / etc.
- Corrections to field interpretations
- Cell-monitor protocol details (currently incompletely documented)
