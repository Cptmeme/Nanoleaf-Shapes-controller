#!/usr/bin/env python3
"""Stitches the two ground pours together with vias on a regular grid.

Candidates come from a grid centred on the board, so what lands stays in straight rows and columns.
A candidate survives only if all of these hold:

  * the whole via pad sits inside the GND pour on BOTH layers -- otherwise the via connects nothing
  * it clears the board outline and the linker slots by the 0.5 mm edge rule
  * it stays out of the module's antenna area AND the board beyond it -- a PCB antenna needs the
    copper cleared in the direction it radiates, not just under its own footprint
  * it clears every pad and every non-GND track by CLEAR, which is deliberately wider than the
    0.1 mm netclass rule so the grid keeps its margin even where the routing is tight
  * it clears every existing hole by the hole-to-hole rule

Routing, footprints and zone outlines are not touched; an assertion holds that. Default is a dry run.

    python3 revb_stitch.py [--place]
"""
import math
import pathlib
import shutil
import sys
import time

import pcbnew

PCB = pathlib.Path(__file__).resolve().parent.parent / "nanoleaf_shapes.kicad_pcb"
PITCH = 3.0             # grid, mm -- 7 rows across the 21.65 mm board, symmetric about the midline
VIA_D, VIA_DRILL = 0.6, 0.3
CLEAR = 0.30            # to other copper; wider than the 0.1 mm netclass rule on purpose
EDGE = 0.50             # board rule
HOLE2HOLE = 0.35
ANT_GAP = 0.80          # past the module's last pad, towards its antenna end
f = lambda v: v / 1e6
mm = pcbnew.FromMM


def pt_seg(p, a, c):
    """Distance from p to segment a-c."""
    qx, qy = c[0] - a[0], c[1] - a[1]
    L2 = qx * qx + qy * qy
    u = 0 if L2 == 0 else max(0, min(1, ((p[0] - a[0]) * qx + (p[1] - a[1]) * qy) / L2))
    return math.hypot(p[0] - (a[0] + u * qx), p[1] - (a[1] + u * qy))


def inside(p, poly):
    """Ray cast, so the outline is taken as drawn rather than assumed to be a trapezoid."""
    x, y = p
    hit = False
    for i in range(len(poly)):
        ax, ay = poly[i]
        cx, cy = poly[(i + 1) % len(poly)]
        if (ay > y) != (cy > y) and x < ax + (y - ay) / (cy - ay) * (cx - ax):
            hit = not hit
    return hit


def ordered_outline(segs, tol=1e-3):
    """Chain the Edge.Cuts segments into one closed ring."""
    todo = list(segs)
    ring = list(todo.pop(0))
    while todo:
        for i, (a, c) in enumerate(todo):
            if math.dist(ring[-1], a) < tol:
                ring.append(c); todo.pop(i); break
            if math.dist(ring[-1], c) < tol:
                ring.append(a); todo.pop(i); break
        else:
            raise SystemExit("Edge.Cuts does not form one closed ring -- check the outline")
    return ring[:-1]


def main(place):
    global PCB, PITCH
    b = pcbnew.LoadBoard(str(PCB))

    board_segs = [((f(d.GetStart().x), f(d.GetStart().y)), (f(d.GetEnd().x), f(d.GetEnd().y)))
                  for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    ring = ordered_outline(board_segs)

    # The linker cut-outs come with J1, so read them off the footprint rather than restating them
    j1 = next(x for x in b.GetFootprints() if x.GetReference() == "J1")
    slots = []
    keepout_segs = list(board_segs)
    for g in j1.GraphicalItems():
        if g.GetLayer() == pcbnew.Edge_Cuts:
            bb = g.GetBoundingBox()
            s = (f(bb.GetLeft()), f(bb.GetTop()), f(bb.GetRight()), f(bb.GetBottom()))
            slots.append(s)
            keepout_segs += [((s[0], s[1]), (s[2], s[1])), ((s[2], s[1]), (s[2], s[3])),
                             ((s[2], s[3]), (s[0], s[3])), ((s[0], s[3]), (s[0], s[1]))]

    # The antenna is the end of the module with no pads on it. Which end that is depends on the
    # footprint's rotation and whether it was flipped, so measure it instead of assuming.
    # The keepout runs from the antenna all the way out to the board edge, over the full height. Stopping
    # it at the module's own outline would leave the corner the antenna fires into full of stitched ground.
    u2 = next(x for x in b.GetFootprints() if x.GetReference() == "U2")
    ub = u2.GetBoundingBox(False, False)
    xs = [f(p.GetPosition().x) for p in u2.Pads()]
    bx0, bx1 = min(p[0] for p in ring) - 1, max(p[0] for p in ring) + 1
    by0, by1 = min(p[1] for p in ring) - 1, max(p[1] for p in ring) + 1
    if f(ub.GetRight()) - max(xs) > min(xs) - f(ub.GetLeft()):
        ant = (max(xs) + ANT_GAP, by0, bx1, by1)
    else:
        ant = (bx0, by0, min(xs) - ANT_GAP, by1)

    print(f"antenna keepout x {ant[0]:.2f}..{ant[2]:.2f}, y {ant[1]:.2f}..{ant[3]:.2f}")

    gnd_polys = {}
    for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
        gnd_polys[lay] = [z.GetFilledPolysList(lay) for z in b.Zones()
                          if z.GetNetname() == "GND" and z.IsOnLayer(lay)]

    pads = [p for fp in b.GetFootprints() for p in fp.Pads()]
    segs = [t for t in b.GetTracks() if t.GetClass() != "PCB_VIA"]   # PCB_ARC too; GetClass() names them separately
    holes = [(f(p.GetPosition().x), f(p.GetPosition().y), f(p.GetDrillSizeX()) / 2)
             for p in pads if p.GetDrillSizeX() > 0]
    holes += [(f(t.GetStart().x), f(t.GetStart().y), f(t.GetDrill()) / 2)
              for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]

    cx = sum(p[0] for p in ring) / len(ring)
    ys = [p[1] for p in ring]
    cy = (min(ys) + max(ys)) / 2
    r = VIA_D / 2
    span = max(math.dist(p, (cx, cy)) for p in ring)
    n = int(span / PITCH) + 2

    inb = 0
    drop = dict(edge=0, slot=0, antenna=0, pour=0, pad=0, track=0, hole=0)
    keep = []
    for j in range(-n, n + 1):
        for i in range(-n, n + 1):
            x, y = cx + i * PITCH, cy + j * PITCH
            if not inside((x, y), ring):
                continue
            inb += 1
            if min(pt_seg((x, y), a, c) for a, c in keepout_segs) < EDGE + r:
                drop["edge"] += 1; continue
            if any(s[0] - r - EDGE < x < s[2] + r + EDGE and s[1] - r - EDGE < y < s[3] + r + EDGE
                   for s in slots):
                drop["slot"] += 1; continue
            if ant[0] - r < x < ant[2] + r and ant[1] - r < y < ant[3] + r:
                drop["antenna"] += 1; continue
            probes = [(x, y), (x + r, y), (x - r, y), (x, y + r), (x, y - r)]
            if not all(any(pl.Contains(pcbnew.VECTOR2I(mm(px), mm(py))) for pl in gnd_polys[lay])
                       for lay in (pcbnew.F_Cu, pcbnew.B_Cu) for px, py in probes):
                drop["pour"] += 1; continue
            # Exact geometry, via KiCad's own collision test. Do NOT compare against
            # GetSize()/GetStart() by hand: GetSize() is in the pad's own frame, so a 90 deg
            # footprint turns a 1.475 x 0.600 pad into something a box test reads as
            # 0.600 x 1.475 and happily drops a via 0.131 mm from it (Q2.3 did exactly that).
            # Collide also covers roundrects, ovals, custom pad shapes and arc tracks, which a
            # point-to-segment distance silently gets wrong.
            disc = {L: pcbnew.SHAPE_CIRCLE(pcbnew.VECTOR2I(mm(x), mm(y)), mm(r))
                    for L in (pcbnew.F_Cu, pcbnew.B_Cu)}
            bad = False
            for p in pads:
                for L in (pcbnew.F_Cu, pcbnew.B_Cu):
                    if p.IsOnLayer(L) and p.GetEffectiveShape(L).Collide(disc[L], mm(CLEAR)):
                        bad = True; break
                if bad:
                    break
            if bad:
                drop["pad"] += 1; continue
            for t in segs:
                if t.GetNetname() == "GND":
                    continue
                for L in (pcbnew.F_Cu, pcbnew.B_Cu):
                    if t.IsOnLayer(L) and t.GetEffectiveShape(L).Collide(disc[L], mm(CLEAR)):
                        bad = True; break
                if bad:
                    break
            if bad:
                drop["track"] += 1; continue
            if any(math.hypot(x - hx, y - hy) < VIA_DRILL / 2 + hr + HOLE2HOLE for hx, hy, hr in holes):
                drop["hole"] += 1; continue
            keep.append((x, y))

    print(f"grid     {PITCH} mm centred on {cx:.3f},{cy:.3f}; {inb} points land on the board")
    print(f"rejected board edge {drop['edge']}, linker slots {drop['slot']}, antenna {drop['antenna']}, "
          f"pour reaches only one layer {drop['pour']}, pads {drop['pad']}, "
          f"non-GND tracks {drop['track']}, holes {drop['hole']}")
    rows = {}
    for x, y in keep:
        rows.setdefault(round(y, 3), []).append(x)
    print(f"kept     {len(keep)} vias in {len(rows)} rows:")
    for y in sorted(rows):
        print(f"           y {y:7.3f}  {len(rows[y]):2d} vias, x {min(rows[y]):.2f}..{max(rows[y]):.2f}")

    if not place:
        print("\ndry run -- nothing written. Re-run with --place to apply.")
        return

    backup = PCB.with_name(f"{PCB.stem}-{time.strftime('%Y-%m-%d_%H%M%S')}-pre-stitch.kicad_pcb")
    shutil.copy2(PCB, backup)
    print(f"\nbackup   {backup.name}")

    before = (len(segs), len(list(b.GetFootprints())), b.GetAreaCount())
    gnd = b.FindNet("GND")
    for x, y in keep:
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        v.SetWidth(mm(VIA_D))
        v.SetDrill(mm(VIA_DRILL))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(gnd)
        b.Add(v)
    after = (len([t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]),
             len(list(b.GetFootprints())), b.GetAreaCount())
    assert before == after, f"existing board objects changed: {before} -> {after}"

    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(str(PCB), b)
    print(f"placed   {len(keep)} GND vias, {VIA_D}/{VIA_DRILL} mm; tracks, footprints and zones untouched")
    print(f"wrote    {PCB.name}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        PCB = pathlib.Path(args[0]).resolve()
        print(f"board    {PCB}")
    if len(args) > 1:
        PITCH = float(args[1])
    main("--place" in sys.argv)
