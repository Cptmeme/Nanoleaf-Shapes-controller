# Matter over Thread firmware

Makes the whole panel assembly one **Matter light** that works with Apple Home, Google Home, Home Assistant
and other Matter controllers, plus a **rainbow switch** that runs a moving rainbow across the panels. The
board talks **Thread** (802.15.4) to your network and is commissioned over **Bluetooth LE**, so it needs no
Wi-Fi.

| | |
|---|---|
| Endpoint 1 | Extended Color Light: on/off, brightness, colour wheel (hue/saturation), xy colour, white temperature |
| Endpoint 2 | On/Off Plug-in Unit: the rainbow switch |
| Panels | All panels together are one light |
| Chips | ESP32-C5 (ESPC5-12) and ESP32-C6 (WT0132C6-S5); both have a Thread radio |
| Based on | [esp-matter](https://github.com/espressif/esp-matter) v1.5, ESP-IDF 5.5 |
| Status | Working on the ESP32-C5 board: the light, the rainbow switch (a colour choice switches it off), brightness restore on "on", and adding and removing panels while it runs |

## How it drives the panels

- **Colour** goes to the panels' RGB and white LEDs. The white share of a colour moves to the white LEDs,
  because the panels' RGB-only white looks bluish while their white LEDs are neutral.
- **Brightness** uses the panels' own hardware dimming (`FC 04`), so dim colours keep full colour
  resolution.
- **White temperature** is rendered as white LEDs plus a warm or cool tint from the RGB LEDs.
- **The panel bus** is the same engine as the [ESP-IDF firmware](../firmware/)
  (`firmware/main/panelbus.c`). It enumerates at start-up, polls every 50 ms, re-reads the layout once a
  second and re-enumerates when it changes, so you can add or remove panels while it runs. Within 50 ms of
  each enumeration, every panel gets the light's current state, and the rainbow spreads over the new panel
  count. Don't unplug a panel between the board and the power supply: that cuts the board's power.
- **The rainbow** spreads a full colour wheel over the panels in chain order and turns it 2° every 40 ms,
  so the colours travel along the chain and pass each panel in about 7 seconds. It replaces the light's
  colour while it's on. The light's on/off and brightness still apply, so the rainbow only shows while the
  light is on. Picking a colour or a white temperature in the app switches the rainbow off, even if it's the
  colour the light already had. Both the light and the rainbow switch come back in their last state after a
  power cut.
- **Turning the light on** returns to its last brightness, and so does a power cut.

## What you need

- ESP-IDF 5.5.x and esp-matter v1.5, set up as in the
  [esp-matter guide](https://docs.espressif.com/projects/esp-matter/en/latest/esp32/developing.html).
- A **Thread Border Router** on your network, for example an Apple TV 4K or HomePod mini, a Google Nest Hub
  (2nd gen) or Nest Wifi Pro, or Home Assistant with an OpenThread Border Router.
- A Matter controller app (Apple Home, Google Home, Home Assistant, SmartThings…).

## Build

```sh
cd matter-over-thread
./build.sh set-target esp32c5      # ESPC5-12; use esp32c6 for the WT0132C6-S5
./build.sh build
```

`build.sh` is a thin wrapper around `idf.py` for setups where ESP-IDF's `export.sh` doesn't work. If
`source $IDF_PATH/export.sh && source $ESP_MATTER_PATH/export.sh` works for you, plain `idf.py` does the
same.

The panel bus pins default to each module's pins (C5: TX 26, RX 27; C6: TX 3, RX 10). Change them under
`idf.py menuconfig` → *Nanoleaf Shapes panel bus*.

## Flash

This firmware has its own partition layout, so the first flash goes over serial and replaces everything on
the chip. Put the board into download mode (see [Flashing](../README.md#flashing)); from the ESP-IDF
firmware, `download` on its console does it. Then:

```sh
./build.sh -p /dev/cu.usbserial-XXXX erase-flash flash
```

The board has no auto-reset, so press EN afterwards to start the firmware. Later versions can be
delivered by Matter OTA (see [Updating the firmware](#updating-the-firmware)).

To update a board that's already paired, leave out `erase-flash`. The pairing lives in the `nvs`
partition, which `flash` doesn't touch.

## Updating the firmware

### Versions

Bump all three for every release, or the board ignores the update. The build fails if the two numbers
differ.

- `PROJECT_VER` (e.g. `"1.1"`) and `PROJECT_VER_NUMBER` (e.g. `2`) in `CMakeLists.txt`
- `CONFIG_DEVICE_SOFTWARE_VERSION_NUMBER` in `sdkconfig` / `sdkconfig.defaults` (same number)

### Over serial

`./build.sh -p /dev/cu.usbserial-XXXX flash`, as under [Flash](#flash), still works. It is also the only
way to write the bootloader, and the automatic rollback below needs the bootloader from this build. A
board that is only ever updated over the air still updates fine; it just won't roll back.

### Over the air (Matter OTA over Thread)

The build also produces `build/nanoleaf_matter-ota.bin`, a Matter OTA image. Build it for the board's
chip (C5 or C6): both use the same product ID, so an image for the other chip is only rejected after the
download. Apple Home and Google Home only update certified devices, so you serve it yourself with the
Matter SDK's host tools. Build them from the SDK with
`./scripts/build/build_examples.py --target darwin-arm64-chip-tool --target darwin-arm64-ota-provider build`.

One-time setup: in your controller app, turn on pairing mode for the board, then add the provider and the
board to `chip-tool`'s fabric:

```sh
chip-tool pairing code 2 <setup-code-from-home-app>              # board = node 2
chip-ota-provider-app -f build/nanoleaf_matter-ota.bin --discriminator 3841 --secured-device-port 5565 &
chip-tool pairing onnetwork-long 1 20202021 3841                 # provider = node 1
chip-tool accesscontrol write acl '[{"fabricIndex": 1, "privilege": 5, "authMode": 2, "subjects": [112233], "targets": null}, {"fabricIndex": 1, "privilege": 3, "authMode": 2, "subjects": null, "targets": [{"cluster": 41, "endpoint": null, "deviceType": null}]}]' 1 0
```

Each update (with the provider running and serving the new `nanoleaf_matter-ota.bin`):

```sh
chip-tool otasoftwareupdaterequestor announce-otaprovider 1 0 2 0 2 0
chip-tool basicinformation read software-version 2 0              # afterwards: the new number
```

Thread is slow for this: about 12 minutes per 1.5 MB, so roughly 15 minutes for this image. The board
then restarts into the new version and keeps it once it has run for a minute while attached to the Thread
network. If it doesn't get there within 5 minutes, or crashes before that, the bootloader automatically
returns to the previous version.

## Commission

Power the board from the panels. The USB-serial adapter's 3.3 V can't supply the radio, and the firmware
resets as soon as it switches the radio on. The pairing codes are fixed, so you don't need the serial log:

| | |
|---|---|
| QR code | [`MT:Y.K9042C00KA0648G00`](https://project-chip.github.io/connectedhomeip/qrcode.html?data=MT:Y.K9042C00KA0648G00) (the link shows it as a QR code) |
| Manual pairing code | `3497-011-2332` |

Scan the QR code, or type the manual code, in your controller app. The board advertises over Bluetooth for
15 minutes after power-up. If you miss that window, power-cycle the board.

- **These are esp-matter's shared test codes** (passcode 20202021, discriminator 3840), the same for every
  board flashed with this firmware. That's fine at home. Anything you distribute should get its own factory
  data (`esp-matter-mfg-tool`).
- **The device uses development attestation certificates.** Apple Home asks you to confirm an uncertified
  accessory ("Add Anyway"). Google Home only accepts test devices after you register the test vendor and
  product ID in the Google Home Developer Console. Home Assistant accepts them directly.

## Use

| Action | Result |
|---|---|
| Controller: on/off, brightness, colour, white temperature | All panels follow |
| Controller: rainbow switch on / off | Moving rainbow / back to the light's colour |
| Controller: pick a colour while the rainbow runs | Rainbow switches off, panels show the colour |
| BOOT button (`SW2`) tap | Toggle the light |
| BOOT button, hold 5 s | Factory reset: removes all pairings, so the board can be commissioned again |
| Serial console (`J2`, 115200) | Matter shell, e.g. `matter onboardingcodes ble` and `matter config` |

## Limitations

- **All panels are one light.** There's no per-panel colour control.
- **Touch isn't exposed yet.** It would suit Matter "generic switch" endpoints (one per panel, usable in
  automations).
- **One effect.** Matter has no standard for light effects, so each effect needs its own switch
  endpoint. The rainbow is the only one so far.
- **Thread only.** Wi-Fi is switched off on the C5 and C6.
