#!/usr/bin/env python3
"""Places the parts still parked below the board, around the work already done on it.

Run with KiCad's own Python. It touches ONLY the refs in PLACE -- every other footprint, every track, via
and zone is left exactly as found, so the USB block and auto-reset you have already placed and routed are
safe.

    /Applications/KiCad/.../bin/python3 revb_place_rest.py

Where things go, and why
------------------------
Four free areas are left once the USB block, the linker and the module are accounted for:

  A  x 62..77, y 46..64   right of the auto-reset, left of the linker's plate recess
  B  x 96..104, y 46..64  the slot between the plate recess and the module's left edge
  C  x 62..104, y 65..75  the full-width strip below the linker
  D  x 104..124, y 65..75 below the module

A takes the buck's hot loop, because that is the only placement that is electrically critical and A is the
one area big enough to hold it whole: U1 with its input caps hard against VIN, the catch diode on SW, and
the inductor after it. Everything else in the buck -- output caps, feedback, compensation -- is not timing
critical and goes into C beneath it, where there is room to spread out.

B is narrow but it is the only thing adjacent to the module's left edge, so it takes the parts that serve
the module's pins: the 3V3 decoupling, the button debounce caps for pads 7/19/20, and the status LED.

C takes the bus buffers, sitting between the COM escape that drops into it from the linker and the module's
RX/TX pads to its right. D takes what serves the module's top row plus the reset network.

Note for routing: the module's top row (pads 1-8) has only 1.8 mm of board above it, so those five used nets
want a via straight down to the back under the module rather than a squeeze along the top edge. The back is
empty apart from the buttons, which have no holes.
"""
import pathlib
import shutil
import sys
import time

import pcbnew

HERE = pathlib.Path(__file__).resolve().parent
PCB = HERE.parent / "nanoleaf_shapes.kicad_pcb"
F, B = "F", "B"

PLACE = {
    # ---- A: the buck's hot loop ---------------------------------------------------------------
    "U1":  ( 67.00, 51.50,  90, F),
    "C1":  ( 73.80, 52.13,   0, F),   # input cap, hard against VIN
    "C2":  ( 73.80, 48.40,   0, F),
    "D1":  ( 64.23, 58.00, 270, F),   # catch diode on SW
    "L1":  ( 69.50, 58.50,   0, F),
    # ---- C left: the rest of the buck ----------------------------------------------------------
    "C3":  ( 64.50, 66.50,   0, F),
    "C11": ( 70.50, 66.50,   0, F),
    "C14": ( 76.50, 66.50,   0, F),
    "C15": ( 81.00, 66.50,   0, F),
    "C16": ( 64.50, 70.00,   0, F),
    "C10": ( 68.50, 70.00,   0, F),   # bootstrap
    "R2":  ( 71.50, 70.00,   0, F),   # feedback divider
    "R3":  ( 74.50, 70.00,   0, F),
    "R5":  ( 77.50, 70.00,   0, F),   # switching frequency
    "R4":  ( 80.50, 70.00,   0, F),   # compensation
    "C12": ( 64.50, 73.00,   0, F),
    "C13": ( 68.50, 73.00,   0, F),
    "D5":  ( 84.50, 73.00,   0, F),   # USB VBUS -> buck input
    "D3":  ( 88.00, 66.50,   0, F),   # TVS, 3.5 mm from the 42 V escape
    # ---- C right: the bus interface ------------------------------------------------------------
    "R15": ( 85.00, 70.00,   0, F),   # bus pull-up, beside the COM escape
    "U3":  ( 90.00, 70.50,  90, F),   # receive buffer
    "U4":  ( 94.50, 70.50, 270, F),   # transmit buffer
    "C18": ( 90.95, 74.00,   0, F),
    "C19": ( 93.55, 66.50,   0, F),
    "R6":  ( 98.00, 66.50,   0, F),
    "R7":  (101.50, 66.50,   0, F),
    "R1":  ( 98.00, 70.00,   0, F),
    "R10": (101.50, 70.00,   0, F),
    "D2":  ( 98.00, 73.80,   0, F),
    "C17": (102.50, 73.50,   0, F),
    # ---- B: everything that serves the module's own pins ---------------------------------------
    "C5":  (102.50, 48.00,   0, F),   # 3V3, nearest pad 8
    "C4":  ( 99.00, 48.00,   0, F),
    "C27": (102.50, 50.60,   0, F),   # debounce, pad 7
    "C6":  ( 99.00, 50.60,   0, F),
    "C7":  (102.50, 53.20,   0, F),
    "R17": ( 99.00, 53.20,   0, F),   # LED series, pad 18
    "C8":  (102.50, 55.80,   0, F),
    "D4":  ( 99.00, 55.80,   0, F),
    "C25": (102.50, 58.40,   0, F),   # debounce, pad 19
    "C9":  ( 99.00, 58.40,   0, F),
    "C26": (102.50, 61.00,   0, F),   # debounce, pad 20
    # ---- D: module top row, reset network, test points ------------------------------------------
    "R16": (108.00, 67.00,   0, F),   # pull-up on pad 11
    "TP1": (112.00, 67.00,   0, F),
    "TP2": (116.00, 67.00,   0, F),
    "C23": (120.00, 67.00,   0, F),   # debounce, pad 1
    "R9":  (108.00, 70.00,   0, F),   # EN pull-up
    "C21": (112.00, 70.00,   0, F),
    "R8":  (116.00, 70.00,   0, F),
    "C24": (120.00, 70.00,   0, F),   # debounce, pad 2
    "C20": (108.00, 73.00,   0, F),
    # ---- the two developer buttons, on the back with the other five ----------------------------
    "SW1": (108.00, 60.00,   0, B),
    "SW2": (115.00, 60.00,   0, B),
    # ---- USB leftovers, at the stubs already routed for them -----------------------------------
    "R11": ( 47.50, 64.50,   0, F),   # CC1 -- below the USB block; its stub extends down to it
    "R12": ( 51.00, 64.50,   0, F),   # CC2
    "C22": ( 50.50, 62.00,   0, F),   # U5 decoupling, hard under it
}

mm = pcbnew.FromMM
LAYER = {F: pcbnew.F_Cu, B: pcbnew.B_Cu}


def main():
    backup = PCB.with_name(f"{PCB.stem}-{time.strftime('%Y-%m-%d_%H%M%S')}-pre-rest.kicad_pcb")
    shutil.copy2(PCB, backup)
    print(f"backup   {backup.name}")
    b = pcbnew.LoadBoard(str(PCB))
    before = {"tracks": len(list(b.GetTracks())), "zones": b.GetAreaCount(),
              "fps": len(list(b.GetFootprints()))}
    fps = {f.GetReference(): f for f in b.GetFootprints()}
    missing = [r for r in PLACE if r not in fps]
    if missing:
        sys.exit(f"not on the board: {', '.join(missing)}")

    for ref, (x, y, rot, side) in PLACE.items():
        fp = fps[ref]
        if fp.GetLayer() != LAYER[side]:
            fp.Flip(fp.GetPosition(), False)
        fp.SetOrientationDegrees(0)
        fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        fp.SetOrientationDegrees(rot)
    print(f"placed   {len(PLACE)} parked parts")

    # U1's four built-in thermal vias sit inside its exposed pad but were left with no net, which DRC reads
    # as a clearance violation and a mask bridge against pad 9. They are what ties the pad through to the
    # back for heat and ground, so put them on GND and connect them solidly rather than through spokes.
    u1 = next(f for f in b.GetFootprints() if f.GetReference() == "U1")
    gnd = b.FindNet("GND")
    tied = 0
    for p in u1.Pads():
        if p.GetDrillSizeX() > 0 and not p.GetNetname():
            p.SetNet(gnd)
            tied += 1
        if p.GetNetname() == "GND":
            p.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
    print(f"thermal  {tied} netless vias under U1's exposed pad tied to GND")

    after = {"tracks": len(list(b.GetTracks())), "zones": b.GetAreaCount(),
             "fps": len(list(b.GetFootprints()))}
    assert before == after, f"something else changed: {before} -> {after}"
    print(f"intact   {after['tracks']} track/via items, {after['zones']} zones, {after['fps']} footprints")
    pcbnew.SaveBoard(str(PCB), b)
    print(f"wrote    {PCB.name}")


if __name__ == "__main__":
    main()
