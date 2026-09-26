# WLED with a native Nanoleaf Shapes output

This patch adds an LED output type **"Nanoleaf Shapes"** to [WLED](https://github.com/wled/WLED). WLED then
drives the panels directly from the interface board. Each panel is one LED, and everything else in WLED
works as usual: effects, palettes, segments, presets, sync, the apps and Home Assistant.

It also generates a **2D map of the real panel layout** automatically, so WLED's 2D effects move across
the wall the way the panels are actually arranged.

| | |
|---|---|
| Patch | `0001-Add-Nanoleaf-Shapes-LeafBus-LED-output-type.patch` |
| Based on | WLED `main`, commit `961961fd` (17.0.0-dev) |
| Tested | ESP32-C5 (ESPC5-12) on the rev A board, with 9 Mini Triangles |
| Builds | ESP32-C3, ESP32-C6, ESP32-S3 |
| Not supported | ESP8266 (its second UART can't receive) |

WLED's own ESP32-C5 support is still marked experimental upstream.

## Build

```sh
wled/build.sh            # clones WLED into ./WLED-nanoleaf, applies the patch, builds
```

Or by hand:

```sh
git clone https://github.com/wled/WLED.git && cd WLED
git checkout -b nanoleaf-shapes 961961fdde8c22150a0212243621ee71bc9a7639
git am /path/to/this/repo/wled/*.patch
npm ci && npm run build
pio run -e esp32c5_nanoleaf
```

The patch adds `platformio_override.ini` with the `esp32c5_nanoleaf` environment:

- **Panel output as the default LED output:** TX GPIO26, RX GPIO27, 9 LEDs. Change these in the settings
  after flashing.
- **BOOT button** (GPIO28) as WLED's button: a short press toggles the lights.
- **mDNS name** `nanoleaf-wled`.
- **DIO flash mode:** the ESPC5-12's factory firmware runs in DIO, so QIO was not risked.

For another module, copy the environment and change the chip, the pins (the module pin table is in the
[main README](../README.md#module-pins)) and, if your module supports it, the flash mode.

## Flash

The first time, write the full image over serial. WLED needs its own partition layout, including a
filesystem for its settings. Get the chip into download mode (see [Flashing](../README.md#flashing)); if the
board runs the [ESP-IDF firmware](../firmware/), just type `download` on its console. Then:

```sh
cd WLED-nanoleaf/.pio/build/esp32c5_nanoleaf
esptool.py --chip esp32c5 -p /dev/cu.usbserial-XXXX -b 460800 --before no_reset --after watchdog_reset \
  write_flash --erase-all 0x2000 bootloader.bin 0x8000 partitions.bin 0x10000 firmware.bin
```

`--erase-all` removes the ESP-IDF firmware's partitions and settings.

**First boot:**

1. **Run it on panel power.** On an adapter's 3.3 V, WLED reset-loops as soon as it starts Wi-Fi.
2. **Check the panels.** They should turn **orange** within seconds (WLED's default colour), before Wi-Fi
   is even set up.
3. **Set up Wi-Fi.** Join the Wi-Fi network `WLED-AP` (password `wled1234`), open `4.3.2.1` and enter your
   Wi-Fi details.

**Later updates** go through WLED's update page (Config → Security & Updates). You can also upload from the
command line:

```sh
curl -F update=@firmware.bin http://nanoleaf-wled.local/update
```

Upstream WLED at this commit has a bug in its firmware check: the release name it reads from the uploaded
file gets random bytes appended, so the upload is refused with "release name mismatch". The patch fixes that
for later updates. To install the patched build over a device that still has the bug, tick
**Ignore firmware validation**, or add `-F skipValidation=1` to the `curl` command.

## Configure

**Config → LED Preferences** shows one output of type **Nanoleaf Shapes**:

| Field | Meaning |
|---|---|
| TX GPIO / RX GPIO | Bus pins (ESP32-C5 board: 26 and 27) |
| Length | Number of panels. LED 0 is the panel the board is plugged into; the rest follow the layout order |
| 2D map rotation | Degrees counter-clockwise, applied to the automatic 2D map. `off` leaves `ledmap.json` alone |
| Auto-calculate white | Recommended: the panels have separate white LEDs |

There's no current limiter for this output; the panels have their own power supply.

## The automatic 2D map

After each stable enumeration, the output does the following:

1. **Places the panels.** It works out each panel's position from the layout string, using the LeafBus
   geometry.
2. **Builds a grid.** Every Shapes panel has a 67 mm side, so every panel centre (mini triangles, large
   triangles and hexagons) lies on a **16.75 × 19.341 mm lattice**. Each panel gets its own cell on that
   lattice, which keeps neighbours evenly spaced: horizontal neighbours are always two cells apart.
3. **Writes the map.** It writes `/ledmap.json` with the matrix `width` and `height`, and reloads it without a
   reboot.

Rearranging the panels updates the map by itself. Rotations in steps of 60° keep the lattice exact. Other
angles fall back to a grid of square cells.

- **View it** at `http://nanoleaf-wled.local/liveview2D`, or with the **Peek** button in the main UI.
- **Hand-made maps are safe.** The generated file is tagged `"generator":"nanoleaf-shapes"`. A `ledmap.json`
  without that tag is never overwritten, so you can replace the automatic map with your own.
- **A layout change resets the segments.** When the layout changes, the segments are rebuilt to span the new
  matrix (the same thing happens when you change WLED's 2D settings).

## How it works

The output is `wled00/bus_leafbus.cpp`; the geometry is `wled00/leafbus_geometry.h`, which has no Arduino
dependencies and can be tested on a PC.

- **A background FreeRTOS task owns the UART** (UART1, or UART2 where the chip has one) at 1 Mbaud:
  - enumerates at start-up, every 5 s while nothing answers, and after a hot-plug;
  - polls every 50 ms with `C0`;
  - sends at most 40 colour frames per second.
- **WLED's `show()` only hands over the frame,** so a slow bus never holds up the effect loop.
- **Brightness is scaled by WLED.** After each enumeration the output sets the panels' own brightness to full
  (`FC 04 FF`).
- **Colour chunks go in reverse layout order, and poll replies come in layout order.** See the
  [protocol notes](../docs/protocol-notes.md).

## Limitations

- **Touch isn't connected to WLED yet.** It's read on the bus but not yet mapped to WLED button actions.
- **It needs the interface board's buffer circuit.** The simple LeafBus wiring (open-drain TX with a
  pull-up) isn't supported, because TX is push-pull.
- **The UART isn't tracked by WLED's pin manager,** so it can clash with other features that use the same
  UART, such as DMX.
- **The rotation setting reuses** the text field that network outputs use for their host name.

## License

WLED is licensed under EUPL-1.2. This patch modifies WLED and is provided under the same licence.
