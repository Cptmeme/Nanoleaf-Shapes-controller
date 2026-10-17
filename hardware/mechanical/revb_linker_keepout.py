#!/usr/bin/env python3
"""Puts the case's keepout on J1's footprint, so the board shows where the linker needs clear space.

The enclosure's strength around the linker comes from a band of solid plastic carried from the outer face
up to the board, all the way round the plate recess. Anything standing on the board inside that band
forces the band back down to clear it, and the pocket ends up hanging off a thin web -- which is the
failure the printed case showed.

So the band is published as J1's courtyard. DRC then reports anything inside it as a courtyard overlap,
which turns "where may I put this part" from a judgement call into a check. The outline is also drawn on
F.Fab with a label, because a courtyard alone does not say why.

Every number comes from the same constants the case is built from:

    plate half width   PLATE_W/2 + POCKET_CLEAR          the recess, as cut
    + RECESS_WALL                                        the band that braces the pocket
    + PART_GAP                                           the case cuts to courtyards grown by this

Run it after changing any of those. It writes both the library copy and the board.

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 revb_linker_keepout.py [--place]
"""
import pathlib
import re
import shutil
import sys
import time

import pcbnew

from board import CENTRE_X, JOINT_Y
from linker import PAD_CENTRE, PLATE_HALF_L, PLATE_W
from linker_footprint import POCKET_CLEAR

HERE = pathlib.Path(__file__).resolve().parent
PCB = HERE.parent / "nanoleaf_shapes.kicad_pcb"   # overridden by a path argument
LIB = HERE.parent / "nanoleaf.pretty" / "Nanoleaf_Linker_Pads.kicad_mod"
f = lambda v: v / 1e6


def from_enclosure(name):
    """Read a constant out of enclosure.py's source.

    Importing it would be tidier, but enclosure.py needs numpy and manifold3d and KiCad's Python has
    neither. Reading the text keeps one source of truth without needing both worlds in one interpreter.
    """
    src = (HERE / "enclosure.py").read_text()
    m = re.search(rf"^{name}\s*=\s*([0-9.]+)", src, re.M)
    if not m:
        sys.exit(f"enclosure.py no longer defines {name}")
    return float(m.group(1))


RECESS_WALL = from_enclosure("RECESS_WALL")
PART_GAP = from_enclosure("PART_GAP")

HALF = PLATE_W / 2 + POCKET_CLEAR + RECESS_WALL + PART_GAP     # local x, either side
Y0 = -PAD_CENTRE                                                # the joint; the plate starts here
Y1 = PLATE_HALF_L + POCKET_CLEAR + RECESS_WALL + PART_GAP - PAD_CENTRE
DOC = ('\n\t(fp_rect (start {x0:.3f} {y0:.3f}) (end {x1:.3f} {y1:.3f})'
       ' (stroke (width 0.12) (type dash)) (fill no) (layer "F.Fab"))'
       '\n\t(fp_text user "case needs this clear" (at 0.000 {ty:.3f} 0) (layer "F.Fab")'
       ' (effects (font (size 0.8 0.8) (thickness 0.12))))')


def report():
    print(f"keepout, in J1's own coordinates: x +-{HALF:.3f}, y {Y0:.3f}..{Y1:.3f}")
    print(f"  = plate {PLATE_W/2:.2f} + recess clearance {POCKET_CLEAR:.2f} "
          f"+ brace {RECESS_WALL:.2f} + courtyard gap {PART_GAP:.2f}")
    print(f"  on the board: x {CENTRE_X-HALF:.2f}..{CENTRE_X+HALF:.2f}, "
          f"y {JOINT_Y:.2f}..{JOINT_Y + Y1 + PAD_CENTRE:.2f}")


def offenders(b):
    x0, x1 = CENTRE_X - HALF, CENTRE_X + HALF
    y0, y1 = JOINT_Y, JOINT_Y + Y1 + PAD_CENTRE
    out = []
    for fp in b.GetFootprints():
        if fp.GetReference() == "J1" or fp.IsFlipped():
            continue
        # The same envelope export_parts.py uses: the courtyard UNIONED with the pads. Plenty of the
        # easyeda2kicad footprints carry no courtyard at all, and a dozen more draw one around the body
        # with the leads hanging outside it, so neither source alone is trustworthy.
        cy = fp.GetCourtyard(pcbnew.F_CrtYd)
        pb = fp.GetBoundingBox(False, False)
        l, t, r, bo = f(pb.GetLeft()), f(pb.GetTop()), f(pb.GetRight()), f(pb.GetBottom())
        if cy.OutlineCount():
            bb = cy.BBox()
            l, t = min(l, f(bb.GetLeft())), min(t, f(bb.GetTop()))
            r, bo = max(r, f(bb.GetRight())), max(bo, f(bb.GetBottom()))
        if r < x0 or l > x1 or bo < y0 or t > y1:
            continue
        out.append((fp.GetReference(), round(min(r, x1) - max(l, x0), 2), round(min(bo, y1) - max(t, y0), 2),
                    round(min(x1 - l, r - x0), 2), round(min(y1 - t, bo - y0), 2)))
    return out


DOC = DOC.format(x0=-HALF, y0=Y0, x1=HALF, y1=Y1, ty=Y1 - 0.9)


def main(place):
    report()
    b = pcbnew.LoadBoard(str(PCB))
    bad = offenders(b)
    print(f"\n{len(bad)} front part(s) inside it today -- each one pushes the brace down where it sits:")
    for ref, ox, oy, px, py in sorted(bad, key=lambda t: -t[1] * t[2]):
        print(f"   {ref:5s} overlaps {ox:5.2f} x {oy:5.2f} mm; "
              f"clear it by moving {min(px, py):.2f} mm the short way")

    if not place:
        print("\ndry run -- nothing written. Re-run with --place to apply.")
        return

    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    shutil.copy2(LIB, LIB.with_suffix(f".kicad_mod.bak-{stamp}"))
    shutil.copy2(PCB, PCB.with_name(f"{PCB.stem}-{stamp}-pre-keepout.kicad_pcb"))

    n = sum(patch(f) for f in (LIB, PCB))
    print(f"\nwrote    {LIB.name} and {PCB.name}: {n} courtyard(s) replaced by the case keepout")
    print(f"backup   {LIB.name}.bak-{stamp}, {PCB.stem}-{stamp}-pre-keepout.kicad_pcb")


def blocks(txt, head):
    """Every balanced (head ...) s-expression in txt, as (start, end) offsets."""
    out, i = [], 0
    while True:
        i = txt.find(head, i)
        if i == -1:
            return out
        d = 0
        for j in range(i, len(txt)):
            if txt[j] == "(":
                d += 1
            elif txt[j] == ")":
                d -= 1
                if d == 0:
                    break
        out.append((i, j + 1))
        i = j + 1


def patch(path):
    """Swap the pocket-sized courtyard for the keepout, and add the labelled outline once.

    Both files hold the same footprint but print it differently -- the library on one line per element,
    the board pretty-printed over several -- so this matches on balanced parentheses rather than on text.
    """
    txt = path.read_text()
    done = 0
    for a, b in reversed(blocks(txt, "(fp_rect")):
        blk = txt[a:b]
        if "F.CrtYd" not in blk or "-7.5" not in blk:
            continue
        txt = (txt[:a]
               + f'(fp_rect (start {-HALF:.3f} {Y0:.3f}) (end {HALF:.3f} {Y1:.3f})'
                 f' (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))'
               + txt[b:])
        done += 1
    if "case needs this clear" not in txt:
        for a, b in blocks(txt, '(footprint "nanoleaf:Nanoleaf_Linker_Pads"') or blocks(txt, "(footprint "):
            end = txt.rfind(")", a, b)
            txt = txt[:end] + DOC + "\n" + txt[end:]
            break
        else:                                     # the library file: one footprint, whole file
            end = txt.rstrip().rfind(")")
            txt = txt[:end] + DOC + "\n" + txt[end:]
    path.write_text(txt)
    return done


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        PCB = pathlib.Path(args[0]).resolve()
        print(f"board    {PCB}")
    main("--place" in sys.argv)
