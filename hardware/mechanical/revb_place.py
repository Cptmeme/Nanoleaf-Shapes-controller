#!/usr/bin/env python3
"""Places every part of rev B on the trapezoid, and adds the ones that were only ever in the schematic.

Run after revb_outline.py. Needs KiCad's own Python:

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 revb_place.py

Why things are where they are
-----------------------------
The board is 106 mm along the joint edge, tapers to 73, and is only 29 mm deep, with the linker claiming the
middle of the top. Everything that gets machine-placed is on the FRONT, so a populated board is an option
rather than a hand-soldering job; the only rear parts are the six buttons, which are hand-fitted anyway.

  top right    the module, in the corner so its antenna has a board edge and nothing else near it. rot 180,
               because flipping it to the front mirrors it: at rot 0 the antenna would point into the middle
               of the board and all seven signal pads would face the 3 mm strip under the joint edge.
  above it     the 3V3 decoupling row and the enable network, on a 2.8 mm pitch, sitting on the module's pins.
               Rev A had all six 100 nF caps 8-14 mm away, in a tidy row, where they do nothing.
  top left     the buck, the only block whose placement is electrically critical. Rev A had the catch diode
               17.9 mm from U1 and two of three input caps 12-15 mm from VIN; here they are millimetres.
  bottom       USB on the left with J3 on the far edge, the bus buffers in the centre under the linker, and
               the LED, reset and auto-reset on the right.

Routing was the other constraint: blocks are arranged so signals flow left-to-right and power right-to-left,
which keeps the two off each other, and the back is left almost empty for the button runs.
"""
import math
import os
import pathlib
import re
import shutil
import sys
import time

import pcbnew

from board import (ANTENNA, BOARD_Y, CENTRE_X, PLATE_KEEPOUT, PLATE_MAX_H, POCKET_KEEPOUT,
                   contains, half_width)

HERE = pathlib.Path(__file__).resolve().parent
PCB = HERE.parent / "nanoleaf_shapes.kicad_pcb"
NETLIST = HERE.parent / "nanoleaf_shapes.net"
KI = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
EZ = str(pathlib.Path.home() / "Documents/KiCad/easyeda2kicad/easyeda2kicad.pretty")

F, B = "F", "B"
# ref: (x, y, rotation, side, library, footprint). Library/footprint only for parts not yet on the board.
REMOVE = {"J2"}     # the CH340C gives the same UART0 over USB, with auto-reset on top

PLACE = {
    # ---- module, top right on the FRONT, rot 180 so the antenna overhangs towards the right leg ----
    "U2":  (111.00, 57.50, 180, F),
    # 3V3 decoupling and the enable network in the strip above it, on a 2.8 mm pitch.
    # Module pad 8 (3V3) is at 104.65, 49.95; pad 3 (EN) at 114.65, 49.95.
    "C8":  ( 97.50, 47.20,   0, F),
    "C9":  (100.30, 47.20,   0, F),
    "C6":  (103.10, 47.20,   0, F),
    "C5":  (105.90, 47.20,   0, F),
    "C4":  (108.70, 47.20,   0, F),
    "C7":  (111.50, 47.20,   0, F),
    "R9":  (114.30, 47.20,   0, F),
    "C21": (117.10, 47.20,   0, F),
    # button caps: C25/C26 in the gap between the linker and the module, C23/C24 just below it
    "C25": (100.50, 56.50,  90, F, EZ, "C0402"),
    "C26": (100.50, 59.50,  90, F, EZ, "C0402"),
    "C24": (109.00, 73.00,   0, F, EZ, "C0402"),
    "C23": (105.50, 73.00,   0, F, EZ, "C0402"),
    # ---- buck, shifted right to clear J3 on the left leg ------------------------------------------
    # J3's rotated body reaches x 52.63, so D1 and L1 start at 53.3 and U1 follows. The hot loop is
    # unchanged by the shift: VIN to C1 is still 2.51 mm and SW to the catch diode 2.53 mm.
    "U1":  ( 64.00, 53.00,  90, F),
    "C1":  ( 70.80, 53.63,   0, F),     # input, hard against VIN
    "C2":  ( 70.80, 49.90,   0, F),
    "C3":  ( 70.80, 57.40,   0, F),
    "C11": ( 70.80, 61.10,   0, F, EZ, "C1210"),   # stacked under C3: x 77.97 onwards is the plate recess
    "D1":  ( 56.50, 54.90, 180, F),     # catch diode, hard against SW
    "L1":  ( 56.50, 60.20, 270, F),
    "C14": ( 63.50, 58.60,   0, F),
    "C15": ( 63.50, 60.80,   0, F),
    "C16": ( 63.50, 63.00,   0, F),
    "C10": ( 66.50, 48.00,   0, F),     # bootstrap
    "R5":  ( 63.50, 48.00,   0, F),     # switching frequency
    "R2":  ( 60.50, 48.00,   0, F),     # feedback divider
    "R3":  ( 57.50, 48.00,   0, F),
    "C12": ( 58.00, 50.30,   0, F),     # compensation, displaced by the shift
    "R4":  ( 54.50, 50.00,   0, F),
    "C13": ( 54.50, 47.50,   0, F),
    "D3":  ( 80.50, 66.50,   0, F, KI + "/Diode_SMD.pretty", "D_SMA"),   # TVS, 9.4 mm from the 42 V entry
    "D5":  ( 72.00, 67.00,   0, F, KI + "/Diode_SMD.pretty", "D_SMA"),   # USB VBUS -> buck input
    # ---- USB on the LEFT LEG. rot 300 so the mouth faces out of the 60 degree bevel; its six through-
    # holes then land at y 52.6..62.2, clear of the bottom edge where the buttons go.
    "J3":  ( 45.38, 57.91, 300, F, KI + "/Connector_USB.pretty", "USB_C_Receptacle_HRO_TYPE-C-31-M-12"),
    "U6":  ( 48.50, 48.50,   0, F, KI + "/Package_TO_SOT_SMD.pretty", "SOT-23-6"),   # ESD, nearest J3
    "R11": ( 39.50, 48.50,   0, F, EZ, "R0402"),
    "R12": ( 43.50, 48.50,   0, F, EZ, "R0402"),
    "U5":  ( 60.00, 68.50,  90, F, KI + "/Package_SO.pretty", "SOIC-16_3.9x9.9mm_P1.27mm"),
    "C22": ( 50.00, 66.00,   0, F, EZ, "C0402"),
    "C27": (100.50, 62.50,  90, F, EZ, "C0402"),
    # ---- bus interface, centre ---------------------------------------------------------------------
    "R1":  ( 85.00, 66.50,  90, F),
    "U3":  ( 88.50, 67.00,  90, F),     # receive buffer
    "U4":  ( 92.50, 67.00, 270, F),     # transmit buffer
    "C18": ( 88.50, 71.00,   0, F),
    "C19": ( 92.50, 63.80,   0, F),     # above U4, whose Vcc faces up (rot 270)
    "R6":  ( 96.50, 66.50,  90, F),
    "R7":  ( 96.50, 69.50,  90, F),
    "D2":  ( 99.50, 67.50,  90, F),
    "C17": ( 99.50, 71.50,  90, F),
    "R10": (102.50, 68.00,  90, F),
    "R16": (102.50, 70.50,  90, F, EZ, "R0402"),
    "R15": ( 85.00, 70.00,   0, F, EZ, "R0402"),
    "TP1": ( 87.00, 73.50,   0, F, KI + "/TestPoint.pretty", "TestPoint_Pad_D1.5mm"),
    "TP2": ( 91.00, 73.50,   0, F, KI + "/TestPoint.pretty", "TestPoint_Pad_D1.5mm"),
    # ---- status LED, reset and auto-reset, bottom right ---------------------------------------------
    "R17": (105.50, 68.00,   0, F, EZ, "R0402"),
    "D4":  (109.00, 68.00,   0, F, KI + "/LED_SMD.pretty", "LED_0603_1608Metric"),
    "Q1":  (113.50, 68.50,   0, F, KI + "/Package_TO_SOT_SMD.pretty", "SOT-23"),
    "R13": (117.80, 68.50,  90, F, EZ, "R0402"),
    "Q2":  (113.50, 72.80,   0, F, KI + "/Package_TO_SOT_SMD.pretty", "SOT-23"),
    "R14": (117.80, 72.80,  90, F, EZ, "R0402"),
    "R8":  (105.50, 70.50,   0, F),
    "C20": (109.00, 70.50,   0, F),
    "C23": (105.50, 73.00,   0, F, EZ, "C0402"),
    "C24": (109.00, 73.00,   0, F, EZ, "C0402"),
    # ---- five user buttons, equispaced along the whole bottom edge ----------------------------------
    # Centres 55.875 to 117.795 on a 15.48 mm pitch, 0.5 mm off each corner, middle one on the board's
    # centreline. Nothing is drilled below y 62.2, so the row clears J3's holes and U1's thermal vias.
    # Descending x: seen from the room this reads bright-, bright+, power, effect, mode.
    "SW5": (117.795, 71.30,  0, B, KI + "/Button_Switch_SMD.pretty", "SW_SPST_PTS645Sx43SMTR92"),
    "SW4": (102.315, 71.30,  0, B, KI + "/Button_Switch_SMD.pretty", "SW_SPST_PTS645Sx43SMTR92"),
    "SW3": ( 86.835, 71.30,  0, B, KI + "/Button_Switch_SMD.pretty", "SW_SPST_PTS645Sx43SMTR92"),
    "SW6": ( 71.355, 71.30,  0, B, KI + "/Button_Switch_SMD.pretty", "SW_SPST_PTS645Sx43SMTR92"),
    "SW7": ( 55.875, 71.30,  0, B, KI + "/Button_Switch_SMD.pretty", "SW_SPST_PTS645Sx43SMTR92"),
    "SW1": (104.00, 64.50,   0, B, KI + "/Button_Switch_SMD.pretty", "SW_Push_1P1T_NO_CK_KMR2"),
    "SW2": (111.00, 64.50,   0, B, KI + "/Button_Switch_SMD.pretty", "SW_Push_1P1T_NO_CK_KMR2"),
}

mm = pcbnew.FromMM
vec = lambda x, y: pcbnew.VECTOR2I(mm(x), mm(y))
LAYER = {F: pcbnew.F_Cu, B: pcbnew.B_Cu}


def sch_nets():
    """{(ref, pad): net name} straight from the schematic, which is the authority."""
    src = NETLIST.read_text()
    toks = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', src)

    def build(i):
        out = []
        while i < len(toks):
            t = toks[i]
            if t == '(':
                sub, i = build(i + 1)
                out.append(sub)
            elif t == ')':
                return out, i + 1
            else:
                out.append(t[1:-1] if t.startswith('"') else t)
                i += 1
        return out, i

    root = build(0)[0][0]
    find = lambda n, k: [x for x in n if isinstance(x, list) and x and x[0] == k]
    out = {}
    for net in find(find(root, "nets")[0], "net"):
        name = find(net, "name")[0][1]
        for node in find(net, "node"):
            out[(find(node, "ref")[0][1], find(node, "pin")[0][1])] = name
    return out


def main():
    backup = PCB.with_name(f"{PCB.stem}-{time.strftime('%Y-%m-%d_%H%M%S')}-pre-place.kicad_pcb")
    shutil.copy2(PCB, backup)
    print(f"backup   {backup.name}")
    want = sch_nets()
    b = pcbnew.LoadBoard(str(PCB))

    # Remove before anything else holds a reference: pcbnew degrades every FOOTPRINT handle on Remove()
    doomed = [f for f in b.GetFootprints() if f.GetReference() in REMOVE]
    for f in doomed:
        b.Remove(f)
    print(f"removed  {', '.join(sorted(REMOVE)) if doomed else '(nothing)'}")
    present = {f.GetReference(): f for f in b.GetFootprints()}

    # Schematic net name -> the board's own net for it, matched on shared members so stale auto-names survive
    board_net_of = {}
    for (ref, pad), name in want.items():
        fp = present.get(ref)
        if not fp:
            continue
        for p in fp.Pads():
            if p.GetNumber() == pad and p.GetNetname():
                board_net_of.setdefault(name, p.GetNetname())
    added_nets = []
    for name in sorted(set(want.values())):
        if name in board_net_of:
            continue
        b.Add(pcbnew.NETINFO_ITEM(b, name))
        board_net_of[name] = name
        added_nets.append(name)
    print(f"nets     {len(added_nets)} new")

    added, moved, refit = [], [], []
    for ref, spec in PLACE.items():
        x, y, rot, side = spec[:4]
        lib_fp = spec[4:6] if len(spec) > 4 else None
        fp = present.get(ref)
        if fp is not None and lib_fp and lib_fp[1] not in fp.GetFPIDAsString():
            b.Remove(fp)                       # the footprint itself is changing
            fp = None
            refit.append(ref)
        if fp is None:
            if not lib_fp:
                sys.exit(f"{ref}: not on the board and no library given")
            fp = pcbnew.FootprintLoad(lib_fp[0], lib_fp[1])
            if fp is None:
                sys.exit(f"{ref}: could not load {lib_fp[1]} from {lib_fp[0]}")
            b.Add(fp)
            fp.SetReference(ref)
            added.append(ref)
        else:
            moved.append(ref)
        if fp.GetLayer() != LAYER[side]:
            fp.Flip(fp.GetPosition(), False)
        fp.SetOrientationDegrees(0)
        fp.SetPosition(vec(x, y))
        fp.SetOrientationDegrees(rot)
        for p in fp.Pads():
            name = want.get((ref, p.GetNumber()))
            if name:
                p.SetNet(b.FindNet(board_net_of[name]))
    print(f"added    {len(added)}: {' '.join(sorted(added))}")
    print(f"refitted {len(refit)}: {' '.join(sorted(refit))}")
    print(f"moved    {len(moved)} existing parts")

    # U1's exposed pad is the buck's heatsink and its quietest ground reference. Thermal spokes starve it --
    # KiCad flags exactly that -- so tie it solidly into the pour instead.
    solid = 0
    for p in next(f for f in b.GetFootprints() if f.GetReference() == "U1").Pads():
        if p.GetNetname() == "GND":
            p.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)   # KiCad 10 name
            solid += 1
    print(f"thermal  {solid} GND pads of U1 tied solidly to the pour")

    # Cut the pour away from the antenna. A rule area would be the obvious way, but KiCad 10's ZONE_FILLER
    # ignores those when driven from Python, so punch an actual hole in the zone's polygon instead.
    ax0, ay0, ax1, ay1 = ANTENNA
    holed = 0
    for z in b.Zones():
        if z.GetIsRuleArea() or z.GetNetname() != "GND":
            continue
        o = z.Outline()
        h = o.NewHole(0)
        for x, y in ((ax0, ay0), (ax1, ay0), (ax1, ay1), (ax0, ay1)):
            o.Append(mm(x), mm(y), 0, h)
        holed += 1
    print(f"antenna  pour cut away from x {ax0}..{ax1}, y {ay0}..{ay1} on {holed} zone(s)")
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())

    # NOTE: U2's 3D model is misplaced by the easyeda2kicad library -- the model is 16 x 24 mm with its
    # origin 4.13 mm off the body centre, the footprint's body is 24 x 16 offset 4.15 mm the other way, and
    # the two are paired with rotate z = 270 and no offset at all. Cosmetic only: no copper, netlist, Gerber
    # or DRC is affected, and the enclosure uses the footprint's courtyard (24.05 x 16.05) and the datasheet
    # height, not this model. Fix it in KiCad: footprint properties -> 3D Models, where offset and rotation
    # preview live. Left at the library default here rather than guessed at from batch renders.
    missing = sorted({r for r, _ in want} - set(PLACE) - REMOVE - {"J1"})
    if missing:
        print(f"MISSING  not placed: {' '.join(missing)}")
    pcbnew.SaveBoard(str(PCB), b)
    print(f"wrote    {PCB.name}")


if __name__ == "__main__":
    main()
