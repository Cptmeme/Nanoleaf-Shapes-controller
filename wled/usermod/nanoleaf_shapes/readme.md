# Nanoleaf Shapes usermod

Drives **Nanoleaf Shapes** light panels from WLED over their own panel bus, using the
[interface board](../../../hardware) in place of the stock Nanoleaf controller. One panel = one pixel.

Needs no changes to WLED itself — this replaces the earlier `TYPE_LEAFBUS` core patch.

## How it works

WLED renders as usual into whatever LED output you have configured. `handleOverlayDraw()` copies the
first *N* rendered pixels into a buffer, and a background FreeRTOS task enumerates the panels, polls
them every 50 ms and pushes colour frames. Nothing bus-related runs in WLED's loop, so a slow or
absent panel chain cannot stall effects.

Protocol: <https://github.com/MyrikLD/LeafBus> (`PROTOCOL.md`, MIT). Two details differ from that
document and were verified on hardware:

- bulk pull (`C0`) replies arrive in layout-string order, while bulk push (`E0`) chunks are reversed
- the panel hosting the power supply ORs `0x20` into its status byte

## Build

```ini
[platformio]
default_envs = esp32c5_nanoleaf

[env:esp32c5_nanoleaf]
extends = env:esp32c5dev
custom_usermods = nanoleaf_shapes
build_flags = ${env:esp32c5dev.build_flags}
  -D LEAFBUS_TX_PIN=26
  -D LEAFBUS_RX_PIN=27
  -D LED_TYPES=TYPE_SK6812          ; RGBW so the panels' white channel survives
  -D DATA_PINS=2                    ; unused GPIO: this output only feeds the usermod
  -D PIXEL_COUNTS=9                 ; one pixel per panel
  -D BTNPIN=28
  -D SERVERNAME='"Nanoleaf Shapes"'
  -D MDNS_NAME='"nanoleaf-wled"'
board_build.flash_mode = dio
board_build.arduino.memory_type = dio_qspi
board_upload.before_reset = no-reset
board_upload.after_reset = watchdog-reset
```

Pin defaults are the tested ESPC5-12 (ESP32-C5) values; the WT0132C6-S5 (ESP32-C6) build uses
TX 3 / RX 10 and is **untested**. Both can also be set at runtime in the usermod settings.

## Setup

1. Flash, then open **Config → LED Preferences** and configure an LED output with **as many pixels as
   you have panels**. Its rendered pixels are what this usermod reads, so point it at a GPIO you
   aren't using. **Pick an RGBW type** (e.g. SK6812 RGBW): the panels have separate white LEDs, and an
   RGB-only output loses the W channel — `R=G=B=255, W=0` comes out visibly blue.
2. Open **Config → Usermods** and set **TX GPIO** and **RX GPIO** to the panel bus pins.
3. The panels enumerate within a few seconds. Panel count appears in the info panel on the main UI.

| Setting | Meaning |
|---|---|
| `enabled` | turn the bus off without reflashing |
| `txPin` / `rxPin` | panel bus UART pins; changing them restarts the bus |
| `autoMap` | maintain `/ledmap.json` from the panel layout so 2D effects follow the wall |
| `rotation` | degrees, rotates that generated map |

`autoMap` only ever replaces a map it wrote itself (tagged with `"generator":"nanoleaf-shapes"`); a
hand-made `/ledmap.json` is left alone.

## Known limitations

- ESP32 only (`ARDUINO_ARCH_ESP32`); it uses the IDF UART driver directly.
- Pixel 0 is the panel the controller is plugged into. **Keep WLED's pixel count equal to the panel
  count.** With fewer pixels than panels the surplus panels get a "leave unchanged" chunk, and the
  generated ledmap will reference LED indices that don't exist — in the core version these were the
  same number by construction, here they are two separate settings.
- Panel brightness is set to full at enumeration; WLED does its own scaling.
- Hexagons are untested — the geometry is implemented but only Mini Triangles and Triangles have been
  verified on hardware.
