#!/usr/bin/env python3
"""Tents U1's thermal vias, in the library footprint and on the board.

The easyeda2kicad footprint declares each via under the exposed pad as `(layers *.Cu *.Paste *.Mask)`.
Those wildcards are the whole bug: `*` means both sides, so a feature that should only ever have been
copper gets a mask opening and a paste aperture on the back as well.

On the back that is wrong twice over. It leaves bare, solderable GND copper 0.271 mm from SW4's BTN_UP
pad -- the board's solder-mask expansion is 0, so that 0.271 mm is the entire mask dam between them --
and SW4 is a back-side button chosen for hand soldering, where a bridge holds the UP button down for
ever. It also puts B.Paste on four open 0.30 mm holes: U1's vias are the only back-paste features on
this board that are not a switch pad, so a back stencil would drop paste straight onto them.

KiCad's own equivalent, Package_SO:SOIC-8-1EP_..._ThermalVias, gives its thermal vias `(layers "*.Cu")`
and nothing else, and adds the mask opening and paste apertures as separate features. This script makes
the easyeda2kicad footprint agree, then matches the board to it so the two stop differing.

Copper is untouched, so the vias conduct heat and tie the pad to the back pour exactly as before. The
front also behaves exactly as before: the exposed pad is 2.00 x 2.00 mm with its own F.Mask opening and
the vias sit at +-0.5 mm, well inside it, so they stay open on the front through the pad's own window.

It also restores the two things about those vias that live only on the board. They are unnamed pads, so
no schematic pin matches them and nothing in the netlist can give them a net: their GND assignment and
their solid zone connection are set here and nowhere else. An Update PCB from Schematic or Update
Footprints from Library can drop both, which is what left them netless and threw eight DRC errors before.

Run it with no arguments after any such update: it reports what is wrong and changes nothing.

    python3 revb_tent_thermal_vias.py            # check
    python3 revb_tent_thermal_vias.py --place    # fix
"""
import pathlib
import re
import shutil
import sys
import time

import pcbnew

PCB = pathlib.Path(__file__).resolve().parent.parent / "nanoleaf_shapes.kicad_pcb"
LIB = pathlib.Path("/Users/kevinverbeek/Documents/KiCad/easyeda2kicad/easyeda2kicad.pretty/"
                   "SOIC-8_L5.0-W4.0-P1.27-LS6.0-BL-EP2.0.kicad_mod")
OLD = "(layers *.Cu *.Paste *.Mask)"
NEW = "(layers *.Cu)"
f = lambda v: v / 1e6
stamp = time.strftime("%Y-%m-%d_%H%M%S")


def fix_library(place):
    txt = LIB.read_text()
    n = len(re.findall(r"thru_hole.*" + re.escape(OLD), txt))
    print(f"library  {LIB.name}")
    if not n:
        print(f"  no thru-hole pad still carries {OLD} -- already fixed")
        return False
    print(f"  {n} thru-hole pad(s) carry {OLD}")
    if not place:
        return True
    out = re.sub(r"(thru_hole.*?)" + re.escape(OLD), r"\1" + NEW, txt)
    assert out.count(NEW) >= n and "thru_hole" in out
    backup = LIB.with_suffix(f".kicad_mod.bak-{stamp}")   # .bak so KiCad will not load it as a footprint
    shutil.copy2(LIB, backup)
    LIB.write_text(out)
    print(f"  backup  {backup.name}")
    print(f"  wrote   {n} pad(s) -> {NEW}")
    return True


def fix_board(place):
    b = pcbnew.LoadBoard(str(PCB))
    u1 = next(x for x in b.GetFootprints() if x.GetReference() == "U1")
    vias = [p for p in u1.Pads() if p.GetDrillSizeX() > 0]
    drop = ("F.Mask", "B.Mask", "F.Paste", "B.Paste")
    gnd = b.FindNet("GND")
    print(f"\nboard    U1, {len(vias)} drilled pads")
    changed = 0
    for p in vias:
        at = f"({f(p.GetPosition().x):.2f},{f(p.GetPosition().y):.2f})"
        notes = []
        ls = p.GetLayerSet()
        had = [n for n in drop if ls.Contains(b.GetLayerID(n))]
        if had:
            for n in drop:
                ls.RemoveLayer(b.GetLayerID(n))
            p.SetLayerSet(ls)
            notes.append("dropped " + ", ".join(had))
        if p.GetNetname() != "GND":
            notes.append(f"net {p.GetNetname()!r} -> GND")
            p.SetNet(gnd)
        if p.GetLocalZoneConnection() != pcbnew.ZONE_CONNECTION_FULL:
            notes.append("zone connection -> solid")
            p.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
        if notes:
            print(f"  {at} " + "; ".join(notes))
            changed += 1
        else:
            print(f"  {at} copper only, on GND, solid zone connection -- correct")
    if not changed:
        return False
    if not place:
        return True
    backup = PCB.with_name(f"{PCB.stem}-{stamp}-pre-u1fix.kicad_pcb")
    shutil.copy2(PCB, backup)
    before = (len([t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]),
              len(list(b.GetFootprints())), b.GetAreaCount())
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    after = (len([t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]),
             len(list(b.GetFootprints())), b.GetAreaCount())
    assert before == after, f"tracks/footprints/zones changed: {before} -> {after}"
    pcbnew.SaveBoard(str(PCB), b)
    print(f"  backup  {backup.name}")
    print(f"  wrote   {changed} pad(s) corrected")
    return True


if __name__ == "__main__":
    place = "--place" in sys.argv
    a = fix_library(place)
    c = fix_board(place)
    if not place and (a or c):
        print("\ndry run -- nothing written. Re-run with --place to apply.")
