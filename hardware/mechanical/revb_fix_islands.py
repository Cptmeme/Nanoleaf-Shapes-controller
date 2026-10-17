"""Stitch the last two GND islands on the replan board and drop one bad grid via.

After the 1.4 mm stitching grid ran, two F.Cu pours were still electrically separate from the
rest of GND, and each one held a ground pin:

  * U6.2  -- GND of the USBLC6-2SC6 USB ESD array, alone in 4.03 mm2
  * U3.3  -- GND of the 74LVC1G125 data buffer, alone in 2.07 mm2

Neither took a grid via: island A's grid points were all inside SW3's pad keepout, and island B
is boxed in so tightly by R1 and U4 that a path search found no escape on F.Cu at all -- not even
a 0.12 mm track at 0.15 mm clearance. Both do fit one standard Ø0.60/0.30 via at the widest point
of the island, so that is what goes in. Island B's spot clears R1.1 by 0.205 mm against the
board's 0.200 mm minimum; it is legal but it is the tightest copper on the board.

The grid also left one via 0.131 mm from Q2 pad 3, under the 0.200 mm minimum. The grid's pad
test compared against GetSize(), which is in the pad's own frame, so Q2's 90 deg rotation made a
1.475 x 0.600 pad look 0.600 x 1.475 and the via passed. revb_stitch.py now uses
GetEffectiveShape().Collide() instead; this script just deletes the via that slipped through.
"""
import datetime, math, os, sys
import pcbnew

BOARD = sys.argv[1] if len(sys.argv) > 1 else "replan/nanoleaf_shapes.kicad_pcb"
VIA_D, VIA_DRILL = 0.60, 0.30
DROP = (42.034999, 48.425317)          # the via that sits 0.131 mm from Q2.3
PLACE = [((100.000, 61.050), "U3.3  74LVC1G125 buffer GND")]   # island B, hand-picked
f = lambda v: v / 1e6
mm = pcbnew.FromMM


def obstacles(board, x0, x1, y0, y1):
    def near(bb):
        return not (f(bb.GetRight()) < x0 - 2 or f(bb.GetLeft()) > x1 + 2
                    or f(bb.GetBottom()) < y0 - 2 or f(bb.GetTop()) > y1 + 2)
    out = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname() == "GND" or not near(p.GetBoundingBox()):
                continue
            for L in (pcbnew.F_Cu, pcbnew.B_Cu):
                if p.IsOnLayer(L):
                    out.append(p.GetEffectiveShape(L))
    for t in board.GetTracks():
        if t.GetNetname() == "GND" or not near(t.GetBoundingBox()):
            continue
        for L in (pcbnew.F_Cu, pcbnew.B_Cu):
            if t.IsOnLayer(L):
                out.append(t.GetEffectiveShape(L))
    return out


def free_radius(x, y, obs, cap=1.5):
    lo, hi = 0.0, cap
    for _ in range(20):
        md = (lo + hi) / 2
        if any(o.Collide(pcbnew.SHAPE_CIRCLE(pcbnew.VECTOR2I(mm(x), mm(y)), mm(md)), 0) for o in obs):
            hi = md
        else:
            lo = md
    return lo


def island_of(board, pad):
    """The one filled F.Cu outline that contains this pad, as its own SHAPE_POLY_SET."""
    for z in board.Zones():
        if z.GetNetname() != "GND" or not z.IsOnLayer(pcbnew.F_Cu):
            continue
        pl = z.GetFilledPolysList(pcbnew.F_Cu)
        for i in range(pl.OutlineCount()):
            sub = pcbnew.SHAPE_POLY_SET()
            sub.AddOutline(pl.Outline(i))
            for h in range(pl.HoleCount(i)):
                sub.AddHole(pl.Hole(i, h), 0)
            if sub.Contains(pad.GetPosition()):
                return sub
    return None


def best_spot(board, pad, pad_standoff=0.20):
    """Widest point *inside this pad's own island* that is not sitting on top of an SMD pad.

    Searching the F.Cu pour at large is not enough: the widest nearby point is usually in the main
    pour a fraction of a millimetre outside the island, and a via there stitches nothing.
    """
    # pad_standoff keeps the via off the pad's copper so reflow cannot wick solder down the barrel.
    # 0.20 mm is the useful setting here: it still lands 0.89 mm from U6.2, close enough to keep the
    # ESD return path short, and leaves 0.352 mm of copper clearance. Pushing it to 0.40 mm buys
    # nothing and forces the via into a 0.203 mm gap instead.
    island = island_of(board, pad)
    if island is None:
        raise SystemExit("no filled F.Cu island contains that pad")
    bb = island.BBox()
    x0, x1 = f(bb.GetLeft()), f(bb.GetRight())
    y0, y1 = f(bb.GetTop()), f(bb.GetBottom())
    obs = obstacles(board, x0, x1, y0, y1)
    zones = [z for z in board.Zones() if z.GetNetname() == "GND"]
    bcu = [z.GetFilledPolysList(pcbnew.B_Cu) for z in zones if z.IsOnLayer(pcbnew.B_Cu)]
    pads = [p for fp in board.GetFootprints() for p in fp.Pads() if p.IsOnLayer(pcbnew.F_Cu)]
    best = (-1, None)
    x = x0
    while x <= x1:
        y = y0
        while y <= y1:
            pt = pcbnew.VECTOR2I(mm(x), mm(y))
            if island.Contains(pt) and any(pl.Contains(pt) for pl in bcu):
                c = pcbnew.SHAPE_CIRCLE(pt, mm(pad_standoff))
                if not any(p.GetEffectiveShape(pcbnew.F_Cu).Collide(c, 0) for p in pads):
                    r = free_radius(x, y, obs)
                    if r > best[0]:
                        best = (r, (x, y))
            y += 0.05
        x += 0.05
    if best[1] is None:
        raise SystemExit("no via spot inside the island clears the pads by %.2f mm" % pad_standoff)
    return best


def main():
    board = pcbnew.LoadBoard(BOARD)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup = BOARD.replace(".kicad_pcb", "-%s-pre-islandfix.kicad_pcb" % stamp)
    pcbnew.SaveBoard(backup, board)
    print("backup -> %s" % backup)

    # Survey before touching anything: board.Remove() leaves GetFootprints() handing back raw
    # SwigPyObjects, so every geometry query has to happen while the board is still untouched.
    u6 = [fp for fp in board.GetFootprints() if fp.GetReference() == "U6"][0]
    r, pt = best_spot(board, [p for p in u6.Pads() if p.GetNumber() == "2"][0])
    spots = [(pt, "U6.2  USBLC6-2SC6 ESD array GND", r)]
    for p, what in PLACE:
        spots.append((p, what, free_radius(p[0], p[1], obstacles(board, p[0] - 2, p[0] + 2,
                                                                 p[1] - 2, p[1] + 2))))

    for v in list(board.GetTracks()):
        if v.GetClass() == "PCB_VIA" and math.hypot(f(v.GetPosition().x) - DROP[0],
                                                    f(v.GetPosition().y) - DROP[1]) < 0.01:
            board.Remove(v)
            print("removed via at %.3f, %.3f (0.131 mm from Q2.3)" % DROP)

    net = board.FindNet("GND")
    for pt, what, rad in spots:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(mm(pt[0]), mm(pt[1])))
        v.SetWidth(mm(VIA_D))
        v.SetDrill(mm(VIA_DRILL))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(net)
        board.Add(v)
        print("via at %.3f, %.3f  clearance %.3f mm  -> rescues %s"
              % (pt[0], pt[1], rad - VIA_D / 2, what))

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(BOARD, board)
    print("refilled zones and saved %s" % BOARD)


main()
