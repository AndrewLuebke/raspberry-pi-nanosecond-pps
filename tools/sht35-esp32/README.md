# SHT35 on an Arduino Nano ESP32 (bench sensor check)

A way to test an SHT3x away from the Pis, and a portable temperature/humidity logger for
enclosure work. Used 2026-09-09 to validate the replacement SHT35 after the first module's
power path failed (see `docs/MEASUREMENTS.md`).

- `sht35_probe.py` — MicroPython: scans the likely I2C pin pairs, identifies the part by status
  word and serial with CRC, then takes ten single-shot high-repeatability readings.
- `mprun.py` — runs a MicroPython file on the board over the raw REPL from a Linux host and
  prints its output. Needs only `pyserial`.

Wiring: SHT35 VIN to 3V3 (**not** 5 V, the ESP32's pins are not 5 V tolerant and the breakout's
pull-ups follow the supply), GND to GND, SDA to A4 (GPIO11), SCL to A5 (GPIO12), ADR unconnected
for address 0x44.

```sh
python3 mprun.py sht35_probe.py            # first /dev/ttyACM* by default
```

## Getting MicroPython onto a Nano ESP32 (the part that fights back)

esptool cannot drive this board: its native USB CDC rejects the DTR/RTS toggling esptool uses to
reset, with `OSError: [Errno 71] Protocol error`. The board instead carries an Arduino DFU
bootloader, so `dfu-util` and the **`.app-bin`** image are the right pair; that also leaves the
Arduino bootloader intact, so the board goes back to Arduino use later.

```sh
curl -LO https://micropython.org/resources/firmware/ARDUINO_NANO_ESP32-<ver>.app-bin
# enter DFU: double-tap RESET *fast* (two presses well under half a second), or open the port at
# 1200 baud and close it; the USB product name changes to ARDUINO_NANO_NORA
sudo dfu-util -d 0x2341:0x0070 -a 0 -R -D ARDUINO_NANO_ESP32-<ver>.app-bin
```

Two traps that cost most of the time on 2026-09-09:

- A slow double-tap (ours was 1.7 s apart) resets the board twice instead of entering the
  bootloader. The ROM bootloader `303a:1001` also flashes past for about a second on any reset,
  which looks like success and is not.
- After failed attempts the board's control endpoint wedges: `dfu-util` reports "Failed to
  retrieve language identifiers" and `Cannot set alternate interface: LIBUSB_ERROR_OTHER`, and
  no amount of unbinding `cdc_acm` helps. **Unplug and replug the cable**, then flash
  immediately; it succeeds first try.

After flashing, MicroPython enumerates as `2341:056b`.
