# Capture box

A Raspberry Pi that sits next to a GivEnergy inverter and records, around the clock:

- every byte on the inverter's BMS RS485 bus, via a USB RS485 dongle wired as a passive tap (`wire.log`)
- GivTCP's view of the inverter and battery, from its MQTT output (`tcp.ndjson`)

The box only listens. It never transmits on the RS485 bus and never polls the inverter.

Captures land in `~/captures/YYYY-MM-DD/` on the Pi, one folder per UTC day. Finished days are compressed at 00:30 UTC.

## What you need

- A Raspberry Pi 3 B+ or newer, its power supply, and a 16 GB or larger microSD card (a "high endurance" card is best)
- A USB RS485 dongle, e.g. the Waveshare isolated one, tapped into the inverter's BMS terminal block (see [docs/06-wire-captures.md](../docs/06-wire-captures.md#tap-point))
- Home Assistant with the GivTCP add-on publishing to MQTT, and an MQTT user for the Pi

## Build

1. Write Raspberry Pi OS Lite (64-bit) to the card with Raspberry Pi Imager. In Imager's settings, set the hostname to `givcap`, your wifi, your username, and SSH with your public key.
2. Boot the Pi, then from your computer: `ssh givcap.local`.
3. Clone the repo: `git clone https://github.com/open-giv/bms-analysis.git && cd bms-analysis`
4. Plug in the dongle and read its IDs: `udevadm info -a -n /dev/ttyUSB0 | grep -E 'idVendor|idProduct|serial'`. Use the first value of each, which belong to the dongle itself. Dongles with a CH343 or other USB CDC chip (e.g. some Waveshare models) appear as `/dev/ttyACM0` instead, so use that name. `ls /dev/ttyUSB* /dev/ttyACM*` shows which.
5. Run `sudo capture-box/setup.sh VENDOR PRODUCT SERIAL` with those three values.
6. Edit `/etc/givcap/mqtt.env` (`sudo nano /etc/givcap/mqtt.env`) with your broker address, the Pi's MQTT username and password, and GivTCP's topic prefix including the inverter serial (e.g. `GivEnergy/XXXXXXXXXX`), so the serial doesn't end up in column names. Then run `sudo systemctl restart givcap-mqtt`.

## Check

- `givcap-status` shows whether both loggers are running, how old the last line of each of today's files is, free disk space, and whether the clock is synchronised.
- `journalctl -u givcap-wire -u givcap-mqtt -n 50` shows recent log messages.

## Try the setup without a Pi

`capture-box/dev/Dockerfile` builds a Debian 13 (trixie) image with systemd, the base of current Raspberry Pi OS. On an arm64 machine it runs natively. It lets you run `setup.sh` and check the services, but not the dongle, because udev can't see a USB device from inside the container.

```
docker build -t givcap-pi capture-box/dev
docker run -d --name givcap --privileged --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw -v "$PWD":/src:ro givcap-pi
docker exec -u givcapuser -w /home/givcapuser givcap git clone -q /src bms-analysis
docker exec -u givcapuser -w /home/givcapuser/bms-analysis givcap sudo capture-box/setup.sh 0403 6001 TESTSERIAL
docker exec -u givcapuser givcap givcap-status
```

## Wi-Fi on a mesh network

The Pi's built-in Broadcom Wi-Fi firmware mishandles mesh roaming requests (802.11v, e.g. from
Google/Nest Wifi) and WPA3. On the first real box it went silent while still reporting
"connected" (`WNM: Preferred List Available`, then `brcmf_p2p_send_action_frame: Unknown Frame`
in the journal). `setup.sh` loads the driver with `roamoff=1 feature_disable=0x82000`, which hands
roaming and authentication to wpa_supplicant, as Home Assistant OS does. It takes effect after a
reboot. Pinning the connection to 2.4 GHz helps range:
`sudo nmcli con modify <connection> 802-11-wireless.band bg`.

A USB adapter is not a reliable way round it. A TP-Link Archer T3U (RTL8812BU, in-kernel driver
`rtw88_8822bu`) logged USB errors at every boot and dropped with `failed to get tx report from
firmware`, a known problem with that driver on Raspberry Pi kernels. If you do use a USB adapter
and the mesh uses WPA2/WPA3 mixed mode, it will try WPA3 first, which needs the real passphrase:
the hashed key Raspberry Pi Imager saves only works for WPA2.

## If the box drops off the network

`setup.sh` keeps the journal on disk and turns on the hardware watchdog, so a hang reboots the Pi
and leaves logs (`journalctl -b -1` shows the boot before). On the first real box a hang left
NetworkManager's Wi-Fi profile in `/etc/netplan/90-NM-*.yaml` as a 0-byte file, and the Pi
booted with no network after that. If `ls -l /etc/netplan` shows empty files, plug in Ethernet,
delete them, and recreate the Wi-Fi connection with `nmcli device wifi connect`.

## Copy captures to your computer

```
rsync -av givcap.local:captures/ ~/givenergy/captures/
```

Keep raw captures out of git. They contain your battery and inverter serial numbers. Run [tools/redact.py](../tools/redact.py) before sharing anything.

## GivTCP topic names

`tools/mqtt_logger.py` gives GivTCP's register topics, `raw/invertor/<name>` and
`raw/batteries/<serial>/<name>` (first battery only), the same column names that
`tools/tcp_poller.py` uses (`soc`, `t_max`, `v_cell_01` and so on), so the analysis notebook works
unchanged. Every other topic is recorded under a name made from its path, with each `/` or other
symbol replaced by `_` and the case kept. GivTCP can leave retained `raw/batteries//<name>` topics
with an empty serial and frozen values; those keep their path names and are not mistaken for the
live battery.

To see what the broker publishes, record a sample (this reads the broker details from
`/etc/givcap/mqtt.env`, so the password doesn't end up in your shell history):

```
sudo bash -c 'set -a; . /etc/givcap/mqtt.env; mosquitto_sub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USER" -P "$MQTT_PASSWORD" -t "$MQTT_TOPIC_PREFIX/#" -v -W 120' > givtcp_sample.txt
```

Replace serial numbers with `XXXXXXXXXX` before sharing it.
