#!/usr/bin/env python3
"""A copy of the board with every track and via gone, and nothing else moved.

For re-placing parts. Dragging a footprint in KiCad leaves its tracks where they were, so a board that is
already routed fights you the whole way; this gives the same 63 footprints on the same outline, in exactly
the same places, with the routing cleared out from under them.

It writes a self-contained project in replan/ -- board, schematic, project file, library table and the
local footprint library -- so it opens on its own and cannot be confused with the real one. Nothing in the
original is touched, which matters because KiCad usually has it open.

Zones are kept and refilled. They come back as pours with nothing stitching them, which is correct: the
vias were routing too, and the pours will want re-stitching once the parts settle.

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 revb_strip_routing.py [--place]
"""
import pathlib
import shutil
import sys

import pcbnew

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE.parent
OUT = SRC / "replan"
STEM = "nanoleaf_shapes"
CARRY = [f"{STEM}.kicad_sch", f"{STEM}.kicad_pro", "fp-lib-table"]
f = lambda v: v / 1e6


def main(place):
    b = pcbnew.LoadBoard(str(SRC / f"{STEM}.kicad_pcb"))
    before = {fp.GetReference(): (f(fp.GetPosition().x), f(fp.GetPosition().y),
                                  fp.GetOrientationDegrees(), fp.IsFlipped(), fp.GetFPIDAsString())
              for fp in b.GetFootprints()}
    tracks = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]
    vias = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]
    print(f"source   {len(before)} footprints, {b.GetAreaCount()} zones, "
          f"{len(tracks)} tracks, {len(vias)} vias")
    if not place:
        print(f"would write {OUT}/ with the tracks and vias removed")
        print("\ndry run -- nothing written. Re-run with --place to apply.")
        return

    for t in tracks + vias:
        b.Remove(t)
    left = [t for t in b.GetTracks()]
    assert not left, f"{len(left)} track-like items survived"

    after = {fp.GetReference(): (f(fp.GetPosition().x), f(fp.GetPosition().y),
                                 fp.GetOrientationDegrees(), fp.IsFlipped(), fp.GetFPIDAsString())
             for fp in b.GetFootprints()}
    moved = [r for r in before if before[r] != after.get(r)]
    assert not moved, f"footprints changed: {moved}"
    print(f"removed  {len(tracks)} tracks and {len(vias)} vias; "
          f"all {len(after)} footprints identical in position, rotation, side and footprint")

    OUT.mkdir(exist_ok=True)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(str(OUT / f"{STEM}.kicad_pcb"), b)
    for name in CARRY:
        shutil.copy2(SRC / name, OUT / name)
    lib = SRC / "nanoleaf.pretty"
    if lib.is_dir():
        shutil.rmtree(OUT / "nanoleaf.pretty", ignore_errors=True)
        shutil.copytree(lib, OUT / "nanoleaf.pretty")
    print(f"wrote    {OUT}/  ({', '.join([STEM + '.kicad_pcb'] + CARRY)}, nanoleaf.pretty/)")
    print(f"\nThe original is untouched. Open {OUT.name}/{STEM}.kicad_pro to work in the copy.")


if __name__ == "__main__":
    main("--place" in sys.argv)
