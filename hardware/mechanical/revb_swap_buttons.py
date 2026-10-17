#!/usr/bin/env python3
"""Swaps the three user buttons to the low-profile XKB TS-1187A and re-centres them.

The C&K PTS645 is 4.40 mm tall and sets the whole back half of the case: 6.55 mm of the 12.90 total is
fixed by the linker and the board, so every millimetre saved has to come off the switch. TS-1187A-B-A-B
is the same part family KiCad already carries, 160 gf, height code A = 1.50 mm, brass column -- 2.90 mm
shorter, which takes the case to 10.00 mm.

Pad numbering matches ('1' twice, '2' twice), so the nets carry straight across. Positions are recomputed
from the board rather than copied: the midline between the two edges, the left area either side of the
linker cut-out halved and quartered, the right area halved -- which is where they already sit, and the
script says so. The schematic's footprint field is updated to match.

Traces are left exactly as they are. Some will end up under the new outline; that is expected.

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 revb_swap_buttons.py [--place]
"""
import pathlib
import re
import shutil
import sys
import time

import pcbnew

HERE = pathlib.Path(__file__).resolve().parent
PCB = HERE.parent / "nanoleaf_shapes.kicad_pcb"
SCH = HERE.parent / "nanoleaf_shapes.kicad_sch"
LIB_DIR = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/Button_Switch_SMD.pretty"
LIBNICK = "Button_Switch_SMD"

# ref group -> (old footprint, new footprint, recentre?)
JOBS = {
    "user": (("SW3", "SW4", "SW6"), "SW_SPST_PTS645Sx43SMTR92", "SW_Push_1P1T_XKB_TS-1187A", True),
    "boot": (("SW1", "SW2"), "SW_Push_1P1T_NO_CK_KMR2", "SW_SPST_TS-1088-xR020", False),
}
mm = pcbnew.FromMM
f = lambda v: v / 1e6


def targets(b):
    """Midline, and the quarter points of the area left of the linker cut-out plus the midpoint right of it."""
    pts = []
    for d in b.GetDrawings():
        if d.GetLayer() == pcbnew.Edge_Cuts:
            pts += [(f(d.GetStart().x), f(d.GetStart().y)), (f(d.GetEnd().x), f(d.GetEnd().y))]
    ys = [p[1] for p in pts]
    top, bottom = min(ys), max(ys)
    mid_y = (top + bottom) / 2
    tops = [p[0] for p in pts if abs(p[1] - top) < 1e-6]
    bots = [p[0] for p in pts if abs(p[1] - bottom) < 1e-6]
    t = (mid_y - top) / (bottom - top)
    left = min(tops) + t * (min(bots) - min(tops))
    right = max(tops) + t * (max(bots) - max(tops))

    j1 = next(x for x in b.GetFootprints() if x.GetReference() == "J1")
    sx = [v for g in j1.GraphicalItems() if g.GetLayer() == pcbnew.Edge_Cuts
          for v in (f(g.GetBoundingBox().GetLeft()), f(g.GetBoundingBox().GetRight()))]
    hole_l, hole_r = min(sx), max(sx)

    wl = hole_l - left
    wr = right - hole_r
    print(f"outline  midline y {mid_y:.3f}; at it the board runs x {left:.3f}..{right:.3f}")
    print(f"linker   cut-out x {hole_l:.3f}..{hole_r:.3f}")
    print(f"left     {left:.3f}..{hole_l:.3f} ({wl:.3f} wide) -> quarter points {left + wl/4:.3f}, {left + 3*wl/4:.3f}")
    print(f"right    {hole_r:.3f}..{right:.3f} ({wr:.3f} wide) -> midpoint {hole_r + wr/2:.3f}")
    return mid_y, [left + wl / 4, left + 3 * wl / 4, hole_r + wr / 2]


def main(job, place):
    BUTTONS, OLD, NEW, recentre = JOBS[job]
    b = pcbnew.LoadBoard(str(PCB))
    print(f"{job}: {OLD}  ->  {NEW}")
    if recentre:
        mid_y, xs = targets(b)
    print()

    keep = (len([t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]),
            len([t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]),
            b.GetAreaCount(), len(list(b.GetFootprints())))

    olds = []
    for ref in BUTTONS:
        fp = next(x for x in b.GetFootprints() if x.GetReference() == ref)
        if OLD not in fp.GetFPIDAsString():
            sys.exit(f"{ref} is {fp.GetFPIDAsString()}, expected {OLD} -- already swapped?")
        olds.append(fp)
    olds.sort(key=lambda fp: fp.GetPosition().x)

    made = []
    for n, fp in enumerate(olds):
        ref, was = fp.GetReference(), (f(fp.GetPosition().x), f(fp.GetPosition().y))
        # nets by pad number; both footprints number their pads the same way, so this carries straight across
        nets = {p.GetNumber(): p.GetNetCode() for p in fp.Pads()}
        rot, flipped = fp.GetOrientationDegrees(), fp.IsFlipped()
        tx, ty = (xs[n], mid_y) if recentre else was      # boot/reset stay exactly where they are

        new = pcbnew.FootprintLoad(LIB_DIR, NEW)
        if new is None:
            sys.exit(f"could not load {NEW}")
        new.SetReference(ref)
        new.SetValue(fp.GetValue())
        new.SetPath(fp.GetPath())
        new.SetFPID(pcbnew.LIB_ID(LIBNICK, NEW))
        for name in fp.GetFieldsText():
            if not new.HasField(name):
                new.SetField(name, fp.GetFieldText(name))
        b.Add(new)                                        # must be on a board before it can be flipped
        if flipped:
            new.SetLayerAndFlip(pcbnew.B_Cu)
        new.SetOrientationDegrees(rot)
        new.SetPosition(pcbnew.VECTOR2I(mm(tx), mm(ty)))
        missing = [k for k in {p.GetNumber() for p in new.Pads()} if k not in nets]
        if missing:
            sys.exit(f"{ref}: new footprint has pad(s) {missing} the old one does not")
        for p in new.Pads():
            p.SetNetCode(nets[p.GetNumber()])

        bb = new.GetBoundingBox(False, False)
        print(f"  {ref}  ({was[0]:7.2f},{was[1]:6.2f}) -> ({tx:7.2f},{ty:6.2f})  "
              f"{f(bb.GetWidth()):.2f} x {f(bb.GetHeight()):.2f} mm on "
              f"{'B.Cu' if new.IsFlipped() else 'F.Cu'}, nets "
              + ", ".join(sorted({p.GetNetname() for p in new.Pads()})))
        made.append(fp)

    if not place:
        print("\ndry run -- nothing written. Re-run with --place to apply.")
        return

    backup = PCB.with_name(f"{PCB.stem}-{time.strftime('%Y-%m-%d_%H%M%S')}-pre-sw-{job}.kicad_pcb")
    shutil.copy2(PCB, backup)
    for fp in made:
        b.Remove(fp)
    after = (len([t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]),
             len([t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]),
             b.GetAreaCount(), len(list(b.GetFootprints())))
    assert keep == after, f"tracks/vias/zones/footprints changed: {keep} -> {after}"
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(str(PCB), b)
    print(f"\nbackup   {backup.name}")
    print(f"wrote    {PCB.name}: {len(made)} swapped, tracks and vias untouched")

    sch = SCH.read_text()
    n = 0
    for ref in BUTTONS:
        pat = re.compile(r'(\(property "Reference" "' + ref + r'".*?\(property "Footprint" ")[^"]*(")', re.S)
        sch, k = pat.subn(rf"\1{LIBNICK}:{NEW}\2", sch, count=1)
        n += k
    SCH.write_text(sch)
    print(f"wrote    {SCH.name}: {n}/{len(BUTTONS)} footprint fields updated")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else "user", "--place" in sys.argv)
