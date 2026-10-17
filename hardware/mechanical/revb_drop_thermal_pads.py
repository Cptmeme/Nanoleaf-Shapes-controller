#!/usr/bin/env python3
"""Takes the thermal vias out of U1's footprint, so they can be ordinary vias on the board instead.

The easyeda2kicad footprint carries four plated holes inside the exposed pad. They are the right idea --
the TPS54360 sheds its heat through that pad, and without a path to the back pour it has nowhere to go --
but expressing them as footprint pads costs more than it buys here:

  * they have no pad number, so no schematic pin can match them. That is four `net_conflict` parity
    warnings, and it is why their GND net had to be set on the board by hand rather than coming from the
    netlist, where an Update PCB from Schematic could drop it again.
  * a plated hole inside an SMD part's courtyard is exactly what `pth_inside_courtyard` looks for: two
    more errors, against SW4 on the other side of the board.

As plain GND vias neither question gets asked, and they behave identically: same four holes, same
0.61/0.30 mm, same net, same places, still inside the exposed pad's mask and paste window, and tented on
the back by default -- which is what we arranged for them anyway.

What it costs: vias do not move with U1. That is precisely why the footprint author put them in the
footprint, and why KiCad's own SOIC-8-1EP_..._ThermalVias does the same. Fine while U1 is placed and
routed; worth remembering if it ever moves, because nothing will warn you.

They come out of the library copy too, or U1 just trades six warnings for one lib_footprint_mismatch.
This script does not place the vias -- that is left to the board.

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 revb_drop_thermal_pads.py [--place]
"""
import pathlib
import re
import shutil
import sys
import time

import pcbnew

HERE = pathlib.Path(__file__).resolve().parent
PCB = HERE.parent / "nanoleaf_shapes.kicad_pcb"
LIB = pathlib.Path("/Users/kevinverbeek/Documents/KiCad/easyeda2kicad/easyeda2kicad.pretty/"
                   "SOIC-8_L5.0-W4.0-P1.27-LS6.0-BL-EP2.0.kicad_mod")
f = lambda v: v / 1e6
stamp = time.strftime("%Y-%m-%d_%H%M%S")


def main(place):
    b = pcbnew.LoadBoard(str(PCB))
    u1 = next(x for x in b.GetFootprints() if x.GetReference() == "U1")
    pads = [p for p in u1.Pads() if p.GetDrillSizeX() > 0]
    ep = max((p for p in u1.Pads() if p.GetDrillSizeX() == 0),
             key=lambda p: f(p.GetSize().x) * f(p.GetSize().y))

    print(f"U1 {u1.GetFPIDAsString()}")
    print(f"  exposed pad {f(ep.GetSize().x):.2f} x {f(ep.GetSize().y):.2f} mm on {ep.GetNetname()}, "
          f"centred ({f(ep.GetPosition().x):.2f}, {f(ep.GetPosition().y):.2f})")
    if not pads:
        print("  no drilled pads left -- already done")
    else:
        print(f"\n  {len(pads)} plated holes to remove. Put vias back at exactly these, {f(pads[0].GetSize().x):.2f} mm "
              f"pad / {f(pads[0].GetDrillSizeX()):.2f} mm drill, net {pads[0].GetNetname()}:")
        for p in sorted(pads, key=lambda p: (f(p.GetPosition().y), f(p.GetPosition().x))):
            print(f"      {f(p.GetPosition().x):7.2f}, {f(p.GetPosition().y):6.2f}")

    lib_txt = LIB.read_text()
    lib_hits = re.findall(r"^\s*\(pad \"\" thru_hole.*$", lib_txt, re.M)
    print(f"\n  library {LIB.name}: {len(lib_hits)} thru_hole pad line(s)")

    if not place:
        print("\ndry run -- nothing written. Re-run with --place to apply.")
        return
    if not pads and not lib_hits:
        return

    keep = (len([t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]),
            len([t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]),
            len(list(b.GetFootprints())), b.GetAreaCount())
    shutil.copy2(PCB, PCB.with_name(f"{PCB.stem}-{stamp}-pre-droppads.kicad_pcb"))
    shutil.copy2(LIB, LIB.with_suffix(f".kicad_mod.bak-{stamp}"))

    for p in pads:
        u1.Remove(p)
    after = (len([t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]),
             len([t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]),
             len(list(b.GetFootprints())), b.GetAreaCount())
    assert keep == after, f"something else changed: {keep} -> {after}"
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())      # the pour has to close over where they were
    pcbnew.SaveBoard(str(PCB), b)
    LIB.write_text(re.sub(r"^\s*\(pad \"\" thru_hole.*$\n?", "", lib_txt, flags=re.M))
    print(f"\nbackups  {PCB.stem}-{stamp}-pre-droppads.kicad_pcb, {LIB.name}.bak-{stamp}")
    print(f"wrote    {PCB.name}: {len(pads)} pads removed, zones refilled, tracks and vias untouched")
    print(f"wrote    {LIB.name}: {len(lib_hits)} pad line(s) removed")


if __name__ == "__main__":
    main("--place" in sys.argv)
