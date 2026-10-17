#!/usr/bin/env python3
"""Centres the four user buttons, taking every dimension from the board itself.

Vertically: on the midline between the joint edge and the far edge.
Horizontally: the area left of the linker cut-out is halved and a button centred in each half; likewise
the area to its right. So each button sits at the 1/4 and 3/4 point of its side.

Touches only SW3..SW6. Tracks, vias, zones and every other footprint are left exactly as found -- some
traces will end up under the buttons, which is expected and is being fixed afterwards by hand.
"""
import pathlib
import shutil
import time

import pcbnew

PCB = pathlib.Path(__file__).resolve().parent.parent / "nanoleaf_shapes.kicad_pcb"
BUTTONS = ("SW3", "SW4", "SW5", "SW6")
mm = pcbnew.FromMM
f = lambda v: v / 1e6


def main():
    backup = PCB.with_name(f"{PCB.stem}-{time.strftime('%Y-%m-%d_%H%M%S')}-pre-centre.kicad_pcb")
    shutil.copy2(PCB, backup)
    print(f"backup   {backup.name}")
    b = pcbnew.LoadBoard(str(PCB))
    before = (len(list(b.GetTracks())), b.GetAreaCount(), len(list(b.GetFootprints())))

    # --- board outline, straight from Edge.Cuts -------------------------------------------------
    pts = []
    for d in b.GetDrawings():
        if d.GetLayer() == pcbnew.Edge_Cuts:
            pts += [(f(d.GetStart().x), f(d.GetStart().y)), (f(d.GetEnd().x), f(d.GetEnd().y))]
    ys = [p[1] for p in pts]
    top, bottom = min(ys), max(ys)
    mid_y = (top + bottom) / 2
    tops = [p[0] for p in pts if abs(p[1] - top) < 1e-6]
    bots = [p[0] for p in pts if abs(p[1] - bottom) < 1e-6]
    # the legs are straight, so interpolate the edge x at any y
    t = (mid_y - top) / (bottom - top)
    left = min(tops) + t * (min(bots) - min(tops))
    right = max(tops) + t * (max(bots) - max(tops))
    print(f"outline  y {top:.2f}..{bottom:.2f}  ->  midline y = {mid_y:.3f}")
    print(f"         at the midline the board runs x {left:.3f} .. {right:.3f}")

    # --- the linker cut-out, from J1's own Edge.Cuts slots ----------------------------------------
    j1 = next(x for x in b.GetFootprints() if x.GetReference() == "J1")
    sx = [v for g in j1.GraphicalItems() if g.GetLayer() == pcbnew.Edge_Cuts
          for v in (f(g.GetBoundingBox().GetLeft()), f(g.GetBoundingBox().GetRight()))]
    hole_l, hole_r = min(sx), max(sx)
    print(f"linker   cut-out spans x {hole_l:.3f} .. {hole_r:.3f}")

    # --- quarter points of each side ---------------------------------------------------------------
    targets = {}
    for side, (a, c) in (("left", (left, hole_l)), ("right", (hole_r, right))):
        w = c - a
        q1, q3 = a + w / 4, a + 3 * w / 4
        print(f"{side:8s} {a:7.3f} .. {c:7.3f}  width {w:6.3f}  ->  buttons at {q1:.3f} and {q3:.3f}")
        targets[side] = (q1, q3)
    wanted = sorted([*targets["left"], *targets["right"]])

    # assign in x order, so each button keeps the side it is already on
    order = sorted(BUTTONS, key=lambda r: next(x for x in b.GetFootprints()
                                               if x.GetReference() == r).GetPosition().x)
    print()
    for ref, tx in zip(order, wanted):
        fp = next(x for x in b.GetFootprints() if x.GetReference() == ref)
        bb = fp.GetBoundingBox(False, False)
        ox = f(fp.GetPosition().x) - (f(bb.GetLeft()) + f(bb.GetRight())) / 2
        oy = f(fp.GetPosition().y) - (f(bb.GetTop()) + f(bb.GetBottom())) / 2
        was = (f(fp.GetPosition().x), f(fp.GetPosition().y))
        fp.SetPosition(pcbnew.VECTOR2I(mm(tx + ox), mm(mid_y + oy)))
        print(f"   {ref}  {was[0]:7.2f},{was[1]:6.2f}  ->  {tx + ox:7.3f},{mid_y + oy:6.3f}"
              f"   (body centre lands on {tx:.3f},{mid_y:.3f})")

    after = (len(list(b.GetTracks())), b.GetAreaCount(), len(list(b.GetFootprints())))
    assert before == after, f"something else changed: {before} -> {after}"
    print(f"\nintact   {after[0]} track/via items, {after[1]} zones, {after[2]} footprints")
    pcbnew.SaveBoard(str(PCB), b)
    print(f"wrote    {PCB.name}")


if __name__ == "__main__":
    main()
