#!/usr/bin/env python3
"""Nudges D3 clear of the linker plate recess.

The plate recess is 2.37 mm deep and the board sits 4.95 mm below the case's outer face, so under the
recess there is 2.58 mm of case and nothing more. D3 is a 2.40 mm SMA, and its body overlapped the recess
by 0.53 mm, which left the enclosure cutting a 5.30 x 1.03 mm relief straight through the recess floor --
a hole, not a floor, mostly but not entirely hidden under the linker plate.

Moving it 0.60 mm further from the joint clears the recess outright. Checked before writing: no courtyard
meets another part, the nearest other-net pad is 4.97 mm away, and both pads stay 1.11 mm from the board
edge against a 0.50 mm rule. The tracks are left where they are -- 0.60 mm of travel on a 1.80 mm pad
keeps them well inside it -- so routing is not disturbed.

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 revb_move_d3.py [--place]
"""
import pathlib
import shutil
import sys
import time

import pcbnew

PCB = pathlib.Path(__file__).resolve().parent.parent / "nanoleaf_shapes.kicad_pcb"
REF = "D3"
DY = 0.60
f = lambda v: v / 1e6


def main(place):
    b = pcbnew.LoadBoard(str(PCB))
    d3 = next(x for x in b.GetFootprints() if x.GetReference() == REF)
    before = (f(d3.GetPosition().x), f(d3.GetPosition().y))
    print(f"{REF} at ({before[0]:.3f}, {before[1]:.3f}) -> ({before[0]:.3f}, {before[1] + DY:.3f})")

    counts = (len([t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]),
              len([t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]),
              len(list(b.GetFootprints())), b.GetAreaCount())
    if not place:
        print("dry run -- nothing written. Re-run with --place to apply.")
        return

    backup = PCB.with_name(f"{PCB.stem}-{time.strftime('%Y-%m-%d_%H%M%S')}-pre-d3.kicad_pcb")
    shutil.copy2(PCB, backup)
    d3.SetPosition(pcbnew.VECTOR2I(d3.GetPosition().x, d3.GetPosition().y + pcbnew.FromMM(DY)))
    after = (len([t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]),
             len([t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]),
             len(list(b.GetFootprints())), b.GetAreaCount())
    assert counts == after, f"something else changed: {counts} -> {after}"
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(str(PCB), b)
    print(f"backup  {backup.name}")
    print(f"wrote   {PCB.name}: {REF} moved {DY:.2f} mm, tracks/vias/footprints/zones untouched")


if __name__ == "__main__":
    main("--place" in sys.argv)
