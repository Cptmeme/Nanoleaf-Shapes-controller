# WLED for the Nanoleaf Shapes controller

[WLED](https://github.com/wled/WLED) runs on the controller through a usermod, a drop-in folder that needs no
changes to WLED itself. Every panel becomes one WLED pixel, a 2D map of the real panel layout is generated so
2D effects follow the wall, the case's buttons and panel touch become WLED button presses, and the panel bus
runs in a background task.

Build, flashing and setup are in [`usermod/nanoleaf_shapes/`](usermod/nanoleaf_shapes/).

An earlier version patched WLED's own LED output code instead. It is the WLED build the hardware tests in the
main README were done with, and it is in this repository's history up to commit `095528c`.

## License

WLED is licensed under EUPL-1.2. The usermod builds into WLED and is provided under WLED's licence.
