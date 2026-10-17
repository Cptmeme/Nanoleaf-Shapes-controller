#!/usr/bin/env python3
"""Writes rev B's board outline, linker pads and ground pour into ../nanoleaf_shapes.kicad_pcb.

Grows the board by a clear strip along its top edge so rev A's placement and routing are untouched, and swaps
both connectors for bare pads -- a 2.54 mm header stands 11.6 mm off the board and the linker leaves 4.95 mm.
J1 moves to the joint edge; J2 stays where rev A's header was, its pads landing on the header's own pad
centres so the existing tracks still meet it. Geometry comes from board.py, shared with the enclosure.

Idempotent: re-running replaces the same things and takes a fresh backup first. Needs KiCad's Python:

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 revb_outline.py
"""
import pathlib
import shutil
import sys
import time

import pcbnew

from board import (BOARD_DEPTH, BOARD_W, BOARD_Y, CENTRE_X, FAR_W, JOINT_Y, PAD_ORIGIN, PLATE_KEEPOUT,
                   PLATE_MAX_H, POCKET_KEEPOUT, contains, half_width, outline)
from linker import PAD_L

HERE = pathlib.Path(__file__).resolve().parent
PCB = HERE.parent / "nanoleaf_shapes.kicad_pcb"
LIB = HERE.parent / "nanoleaf.pretty"

# ref -> (footprint in nanoleaf.pretty, where to put it). "joint" takes its place from board.py; "match" lands
# on the pad centres of the footprint it replaces, trying each 90 degree step, so rev A's tracks still arrive.
SWAPS = {"J1": ("Nanoleaf_Linker_Pads", "joint")}   # J2 dropped: the CH340C gives the same UART0
OUTLINE_W = 0.05
ZONE_INSET = 0.50       # ground pour back from the board edge, clear of KiCad's edge-clearance rule
ESCAPE_W = 0.50         # track off each linker pad

mm = pcbnew.FromMM


def vec(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def overlaps(box, rect):
    x0, y0, x1, y1 = rect
    return (box.GetLeft() < mm(x1) and box.GetRight() > mm(x0)
            and box.GetTop() < mm(y1) and box.GetBottom() > mm(y0))


def set_outline(b):
    dropped = [d for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    for d in dropped:
        b.Remove(d)
    corners = outline()
    for a, c in zip(corners, corners[1:] + corners[:1]):
        seg = pcbnew.PCB_SHAPE(b)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(vec(*a))
        seg.SetEnd(vec(*c))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(mm(OUTLINE_W))
        b.Add(seg)
    print(f"outline  {len(dropped)} segments replaced -> trapezoid {BOARD_W:.2f} mm at the joint edge "
          f"(y {BOARD_Y[0]:.2f}) tapering to {FAR_W:.2f} mm over {BOARD_DEPTH:.2f} mm")


def pad_centres(fp):
    return {p.GetNumber(): (p.GetPosition().x / 1e6, p.GetPosition().y / 1e6) for p in fp.Pads()}


def match_pads(fp, want):
    """Rotate and place fp so its pads sit on `want` ({number: (x, y)}). Returns (worst error mm, rotation)."""
    best = None
    for rot in (0, 90, 180, 270):
        fp.SetOrientationDegrees(rot)
        fp.SetPosition(vec(0, 0))
        local = pad_centres(fp)
        shared = [n for n in want if n in local]
        dx = sum(want[n][0] - local[n][0] for n in shared) / len(shared)
        dy = sum(want[n][1] - local[n][1] for n in shared) / len(shared)
        err = max(((want[n][0] - local[n][0] - dx) ** 2 + (want[n][1] - local[n][1] - dy) ** 2) ** 0.5
                  for n in shared)
        if best is None or err < best[0]:
            best = (err, rot, dx, dy)
    err, rot, dx, dy = best
    fp.SetOrientationDegrees(rot)
    fp.SetPosition(vec(dx, dy))
    return err, rot


def read_old(b, refs):
    """Everything to carry over, read before anything is removed: FindFootprintByReference stops returning a
    cast FOOTPRINT once a footprint has been added to the board."""
    found = {}
    for fp in b.GetFootprints():
        ref = fp.GetReference()
        if ref in refs:
            found[ref] = dict(nets={p.GetNumber(): p.GetNetname() for p in fp.Pads()}, want=pad_centres(fp),
                              path=fp.GetPath(), value=fp.GetValue(), layer=fp.GetLayer(), fp=fp)
    missing = set(refs) - set(found)
    if missing:
        sys.exit(f"not on the board: {', '.join(sorted(missing))}")
    return found


def swap(b, ref, name, how, old):
    nets, want = old["nets"], old["want"]
    path, value, layer = old["path"], old["value"], old["layer"]
    b.Remove(old["fp"])

    fp = pcbnew.FootprintLoad(str(LIB), name)
    if fp is None:
        sys.exit(f"could not load {name} from {LIB}")
    b.Add(fp)
    fp.SetReference(ref)
    fp.SetValue(value)
    fp.SetPath(path)
    fp.SetLayerAndFlip(layer)
    fp.SetExcludedFromBOM(True)
    fp.SetExcludedFromPosFiles(True)
    if how == "joint":
        fp.SetOrientationDegrees(0)
        fp.SetPosition(vec(*PAD_ORIGIN))
        note = f"at {PAD_ORIGIN[0]:.3f}, {PAD_ORIGIN[1]:.2f} on the joint edge"
    else:
        err, rot = match_pads(fp, want)
        note = f"on rev A's pad centres, rotated {rot} deg, worst pad off by {err*1000:.0f} um"
    for p in fp.Pads():
        netname = nets.get(p.GetNumber())
        net = b.FindNet(netname) if netname else None
        if net is None:
            sys.exit(f"{ref}: no net for pad {p.GetNumber()} (wanted {netname!r})")
        p.SetNet(net)
    print(f"{ref:8s} {name} {note}  [" + " ".join(f"{n}={nets[n]}" for n in sorted(nets)) + "]")


def extend_zone(b):
    """Rev A poured ground to its own edge; the new strip would otherwise have none, leaving J1's GND pad dry.

    The pour is clipped around the linker rather than kept out by a rule area, because KiCad 10's ZONE_FILLER
    ignores rule areas when driven from Python -- DRC then flags the fill it just made. Clipping the outline is
    the same result and provable from the polygon. The linker corner has to stay clear on both layers: poured,
    ground sits a fraction of a millimetre from 42 V between pads 2.50 mm apart, merges its mask openings with
    theirs, and on the back breaks edge clearance against the slots, which the filler does not read as cutouts
    because they are Edge.Cuts shapes inside the J1 footprint."""
    # Pour over the whole board but notched around the linker: the board is 106 mm across the joint edge and
    # the linker claims only the middle 15, so there is plenty either side worth pouring.
    top, bottom = BOARD_Y[0] + ZONE_INSET, BOARD_Y[1] - ZONE_INSET
    tl, tr = CENTRE_X - half_width(top, ZONE_INSET), CENTRE_X + half_width(top, ZONE_INSET)
    bl, br = CENTRE_X - half_width(bottom, ZONE_INSET), CENTRE_X + half_width(bottom, ZONE_INSET)
    nx0, nx1 = POCKET_KEEPOUT[0] - ZONE_INSET, POCKET_KEEPOUT[2] + ZONE_INSET
    notch = POCKET_KEEPOUT[3] + 0.18        # just under the escape tracks' end, so GND's lands in the pour
    corners = [(tl, top), (nx0, top), (nx0, notch), (nx1, notch), (nx1, top), (tr, top), (br, bottom), (bl, bottom)]
    done = []
    for z in b.Zones():
        if z.GetNetname() != "GND" or z.GetIsRuleArea():
            continue
        o = z.Outline()
        o.RemoveAllContours()
        o.NewOutline()
        for x, y in corners:
            o.Append(mm(x), mm(y))
        done.append(z.GetNetname())
    filler = pcbnew.ZONE_FILLER(b)
    filler.Fill(b.Zones())
    print(f"zone     {len(done)} ground pour(s) refilled, inset {ZONE_INSET} mm, notched round the linker "
          f"(x {nx0:.2f}..{nx1:.2f} down to y {notch:.2f})")


def escape_tongue(b):
    """Bring J1's three nets off the contact tongue. The tongue is the one constrained stretch -- 7.80 mm wide
    between the slots -- so the tracks run straight down it to clear ground, where there is open board. GND
    lands in the pour and is done; 42V and COM end as stubs for the rest of the routing."""
    j1 = next(fp for fp in b.GetFootprints() if fp.GetReference() == "J1")
    y_end = POCKET_KEEPOUT[3] + 0.50
    for pad in j1.Pads():
        x = pad.GetPosition().x / 1e6
        y_start = pad.GetPosition().y / 1e6 + PAD_L / 2 - ESCAPE_W / 2
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(vec(x, y_start))
        t.SetEnd(vec(x, y_end))
        t.SetWidth(mm(ESCAPE_W))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(pad.GetNet())
        b.Add(t)
    print(f"escape   3 tracks {ESCAPE_W} mm wide down the tongue to y {y_end:.2f}, "
          f"clear of the slots and the pour")


def check_inside(b):
    """Every bit of copper has to be inside the trapezoid, which is not a superset of the rectangle rev A was
    laid out in: it tapers, so a part that fits near the joint may not fit at the far edge."""
    worst, outside = None, []
    for fp in b.GetFootprints():
        for pad in fp.Pads():
            c = pad.GetPosition()
            r = max(pad.GetSize().x, pad.GetSize().y) / 2e6
            x, y = c.x / 1e6, c.y / 1e6
            margin = min(half_width(y) - abs(x - CENTRE_X) - r, y - BOARD_Y[0], BOARD_Y[1] - y)
            if margin < 0:
                outside.append(f"{fp.GetReference()}.{pad.GetNumber()}")
            if worst is None or margin < worst[0]:
                worst = (margin, f"{fp.GetReference()}.{pad.GetNumber()}")
    for t in b.GetTracks():
        for pt in (t.GetStart(), t.GetEnd()):
            x, y = pt.x / 1e6, pt.y / 1e6
            if not contains(x, y):
                outside.append(f"track at {x:.1f},{y:.1f}")
    if outside:
        print(f"inside   {len(outside)} items OUTSIDE the board: {', '.join(sorted(set(outside))[:6])}")
    else:
        print(f"inside   all pads and tracks fit; tightest is {worst[1]} with {worst[0]:.2f} mm to the edge")


def check_keepouts(b):
    clashes = []
    for fp in b.GetFootprints():
        if fp.GetReference() in SWAPS:
            continue
        box = fp.GetBoundingBox(False, False)
        if overlaps(box, POCKET_KEEPOUT):
            clashes.append(f"{fp.GetReference()} in the pocket")
        elif overlaps(box, PLATE_KEEPOUT):
            clashes.append(f"{fp.GetReference()} under the plate (needs to be under {PLATE_MAX_H} mm tall)")
    print("keepout  " + ("; ".join(clashes) if clashes else "clear: nothing in the pocket or under the plate"))


def main():
    backup = PCB.with_name(f"{PCB.stem}-{time.strftime('%Y-%m-%d_%H%M%S')}-pre-outline.kicad_pcb")
    shutil.copy2(PCB, backup)
    print(f"backup   {backup.name}")
    b = pcbnew.LoadBoard(str(PCB))
    # Drop any previous escape tracks first: a re-run would otherwise stack a second set on the first,
    # and pcbnew degrades every handle once the board has been mutated, so this cannot wait until later.
    stale = [t for t in b.GetTracks()
             if t.GetClass() == "PCB_TRACK"
             and any(abs(t.GetStart().x / 1e6 - x) < 0.01 and abs(t.GetEnd().x / 1e6 - x) < 0.01
                     for x in (PAD_ORIGIN[0] - 2.5, PAD_ORIGIN[0], PAD_ORIGIN[0] + 2.5))]
    for t in stale:
        b.Remove(t)
    print(f"escapes  {len(stale)} old ones cleared")
    b = pcbnew.LoadBoard(str(PCB)) if False else b
    set_outline(b)
    old = read_old(b, SWAPS)
    for ref, (name, how) in SWAPS.items():
        swap(b, ref, name, how, old[ref])
    escape_tongue(b)
    extend_zone(b)
    check_inside(b)
    check_keepouts(b)
    pcbnew.SaveBoard(str(PCB), b)
    print(f"wrote    {PCB.name}")


if __name__ == "__main__":
    main()
