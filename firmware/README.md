# ESP-IDF firmware

Standalone firmware for the interface board. It drives the panels directly and gives you:

- **Serial and network console** for testing the bus and exploring the protocol.
- **Automatic pin detection**, so the same image works with different ESP-12F-footprint modules.
- **Automatic enumeration** at boot and after hot-plugs, with `C0` polling every 50 ms.
- **Wi-Fi:** a network console on port 23, a status page, and OTA updates with rollback.
- **A DDP receiver**, so WLED, LedFx, xLights or Hyperion can stream colours to the panels over the network.
- **A touch-light demo:** a touched panel lights up white.

It was written for bring-up and is tested on an ESP32-C5 (ESPC5-12 module) with 9 Mini Triangles. For
everyday use, [native WLED](../wled/) is the more complete option.

## Build

You need [ESP-IDF](https://docs.espressif.com/projects/esp-idf/) **5.5 or newer**. Earlier versions don't
support ESP32-C5 chip revision 1.0.

```sh
cd firmware
idf.py build
```

`sdkconfig.defaults` selects the ESP32-C5, 4 MB flash, a custom partition table with two 1.875 MB OTA slots
(the app is about 1 MB), rollback, and the console on UART0.

**Other chips:** run `idf.py set-target <chip>` first. The bus pins are detected at runtime. The `download`
command writes a C5-specific register (`LP_AON_SYS_CFG_REG`) and needs adapting on chips that don't have it.

## First flash

Put the chip into download mode (see [Flashing](../README.md#flashing)), then:

```sh
idf.py -p /dev/cu.usbserial-XXXX flash
```

The board has no auto-reset lines. After flashing, press EN or power-cycle to start the firmware.

On first boot the firmware runs `pinscan` to find the bus pins and saves them in NVS:

```
pinscan: TX=GPIO26 RX=GPIO27 RC=GPIO6
```

## Console

The serial console runs on `J2` at 115200 8N1 (`idf.py monitor`). Once Wi-Fi is set up, the same console is
also reachable over the network:

```sh
nc nanoleaf-bus.local 23
```

| Command | What it does |
|---|---|
| `pins [<tx> <rx> <rc>]` | Show or set the bus GPIOs (saved in NVS; `rc` -1 = unknown) |
| `pinscan` | Find the bus GPIOs through the on-board loopback |
| `echo [tries]` | Loopback test TX → `U4` → `U3` → RX. Doesn't involve the panels |
| `listen [ms]` | Print bus traffic without transmitting. An unenumerated panel probes with `C0` every 50 ms |
| `enum` | Send `00` then `80`, print the layout string and panel table, and start polling |
| `color <r> <g> <b> [w] [t]` | Set every panel (`w` = white LEDs, `t` = fade time) |
| `panel <pos> <r> <g> <b> [w] [t]` | Set one panel (`pos` as listed by `enum`, 0 = the panel the board is plugged into) |
| `bright <0-255>` | Hardware brightness (`FC 04`) |
| `touchlight [on\|off]` | A touched panel lights white until it's released |
| `poll [on\|off]` | `C0` polling and automatic enumeration (`off` gives a quiet bus for experiments) |
| `trace [on\|off]` | Log every frame and reply in hex; identical repeats are counted instead of printed |
| `raw <read_ms> <hex>...` | Send any frame and print the reply, e.g. `raw 60 C0` |
| `stats` | Poll, miss and echo-error counters, plus DDP statistics |
| `wifi [<ssid> <password> \| clear]` | Show or set Wi-Fi credentials |
| `restart` | Reboot |
| `download` | Reboot into the ROM's UART download mode, for serial flashing without BOOT/EN |

A typical first session on a new assembly:

```
leaf> listen          # expect C0 every 50 ms: receive path and idle level are fine
leaf> enum            # layout string and panel table
leaf> color 255 0 0
leaf> touchlight on   # touch each panel: it should light up itself, and nothing else
```

## Wi-Fi

```
leaf> wifi "MyNetwork" "my password"
leaf> restart
```

Wi-Fi starts at the next boot. If the last reset was a brownout or power glitch, Wi-Fi is skipped for that
boot, so the serial console stays usable on a weak supply such as a USB-serial adapter's 3.3 V.

Once the board is connected:

| | |
|---|---|
| Console | `nc nanoleaf-bus.local 23` (log output is mirrored there) |
| Status page | `http://nanoleaf-bus.local/` (pins, counters, layout string, panel list) |
| OTA update | `curl --data-binary @build/nanoleaf_bus.bin http://nanoleaf-bus.local/ota` |

An OTA image marks itself valid once it has joined Wi-Fi. An image that never gets that far is rolled back on
the next reset.

> The console and the OTA endpoint have no authentication. Anyone on your network can use them.

## DDP (network pixel stream)

The board listens for DDP on UDP port 4048: one pixel per panel, RGB or RGBW, in layout order (pixel 0 = the
panel the board is plugged into). It shows at most 40 frames per second; when frames arrive faster, it shows
the newest and drops the rest.

In another WLED instance, add an LED output of type **DDP RGBW (network)** with the board's IP address and
one LED per panel. DDP needs a fixed IP (reserve one in your router).

## How the bus engine works

The engine is in `main/panelbus.c`:

- **Transactions:** each transaction sends a frame, reads back and checks its own echo (`U3` always listens),
  then reads the reply.
- **Enumeration:** `00`, a 20 ms pause, then `80`, reading up to the `40` terminator. The string is read again
  until the same value comes back twice, because the head of the string can arrive corrupted on large
  assemblies.
- **Automatic enumeration:** runs at boot and straight after a hot-plug. A hot-plug is a `CC` marker at the
  end of a poll reply, pairs from panels that were never enumerated, three short replies in a row, or a
  layout string that differs from the enumerated one. The layout is re-read once a second, because a panel
  plugged in while running stays unclaimed (dim white) until the next `00` + `80`. While nothing answers,
  enumeration retries after 0.25, 0.5, 1 and 2 s, then every 3 s, like the stock controller; bursts of
  hot-plugs are spaced out the same way. A hot-plug marker always shows up once after the controller itself
  restarts.
- **Colour frames (`E0 03` + one chunk per panel):** chunks go in reverse layout order. **The poll reply
  (`C0`) comes in layout order.** See [protocol notes](../docs/protocol-notes.md).
