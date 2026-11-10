#!/usr/bin/env python3
"""Reset a rev B board, because esptool's own auto-reset does not work on it.

Rev B wires the CH340C's handshake lines to the two reset transistors the other way round from the
DevKitC circuit esptool assumes:

    Q1  collector -> BOOT   base <- R13 <- ~DTR (U5 pin 13)   emitter <- ~RTS
    Q2  collector -> EN     base <- R14 <- ~RTS (U5 pin 14)    emitter <- ~DTR

esptool's `classic_reset` drives DTR and RTS expecting the opposite pairing, so on this board it
asserts BOOT where it means to assert EN. The result is that `idf.py flash` and plain
`esptool --before default_reset` never reach the ROM loader: the chip just reboots into the app and
esptool reports "Invalid head of packet", which looks like a bad cable rather than a wiring swap.

Measured on the first assembled rev B board, 2026-11-10:

    DTR asserted + RTS released  ->  EN low   (chip held in reset)
    DTR released + RTS asserted  ->  BOOT low (strap for UART download)

Those two are mutually exclusive, which is the point of the cross-coupled pair: releasing EN and
pulling BOOT low is a single transition, and the ROM samples the strap just after EN rises.

Usage, from the build directory:

    python ../tools/revb_reset.py download
    python -m esptool --chip esp32c5 -p PORT -b 460800 --before no_reset --after no_reset \
        write_flash @flash_args
    python ../tools/revb_reset.py run

`--before no_reset` is required. Closing the port between the two steps is safe: it leaves DTR
released, and EN only goes low when DTR is asserted, so the chip stays in the ROM loader.

Once this firmware is on the board none of this is needed. Type `download` on the console, or push
an update to `/ota` over Wi-Fi.

Fix for rev C: swap ~DTR and ~RTS at the transistors, so that EN is driven from the DTR side.
"""
import sys
import time

import serial

DEFAULT_PORT = "/dev/cu.usbserial-110"
HOLD = 0.20             # EN held low; the module's own RC on EN needs a moment
STRAP = 0.10            # BOOT held low across the EN release, while the ROM samples it


def reset(port, download):
    s = serial.Serial(port, 115200, timeout=0.1)
    s.setDTR(True)                      # EN low: chip in reset
    s.setRTS(False)
    time.sleep(HOLD)
    s.setDTR(False)                     # release EN
    s.setRTS(download)                  # with BOOT low, this straps for UART download
    time.sleep(STRAP)
    s.setRTS(False)                     # let BOOT go; the strap has already been read
    time.sleep(0.05)
    s.close()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    port = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PORT
    if mode not in ("run", "download"):
        raise SystemExit(f"usage: {sys.argv[0]} [run|download] [port]")
    reset(port, mode == "download")
    print(f"{port}: reset into {'UART download mode' if mode == 'download' else 'the application'}")
