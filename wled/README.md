# WLED for the Nanoleaf Shapes controller

There are two ways to run [WLED](https://github.com/wled/WLED) on the interface board. Both make every panel
one WLED pixel, generate a 2D map of the real panel layout so 2D effects follow the wall, and run the panel
bus in a background task. **Start with the usermod.**

| | [**Usermod**](usermod/nanoleaf_shapes/) (recommended) | [Core patch](core-patch/) (the original build) |
|---|---|---|
| Changes to WLED | None: a drop-in usermod folder | Patches WLED's LED output code |
| Newer WLED versions | Rebuild with the new WLED | The patches have to be rebased |
| How it gets the colours | Reads the pixels WLED renders for an LED output you configure (an RGBW type on an unused GPIO) | Adds its own "Nanoleaf Shapes" LED output type |
| Settings | Config → Usermods: bus pins, automatic 2D map, rotation | Config → LED Preferences |
| Status | Builds for the ESP32-C5 and ESP32-C6; not yet run on hardware | **Tested** on the rev A board (ESP32-C5) with 9 Mini Triangles |

The usermod uses the same bus driver as the core patch, restructured so WLED itself stays untouched. The core
patch came first and is kept for reference, and for anyone who wants the exact build that was tested on the
board.

| Folder | Contents |
|---|---|
| [`usermod/nanoleaf_shapes/`](usermod/nanoleaf_shapes/) | The usermod, with build and setup instructions |
| [`core-patch/`](core-patch/) | Two WLED patches (`0001`, `0002`), `build.sh`, and the instructions for the patched build |

## License

WLED is licensed under EUPL-1.2. Both variants build into WLED and are provided under WLED's licence.
