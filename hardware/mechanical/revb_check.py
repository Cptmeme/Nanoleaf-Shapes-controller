#!/usr/bin/env python3
"""Clears rev A's now-stale routing and checks the new placement. Run with KiCad's Python after revb_place.py.

Keeps only the three escape tracks off the linker pads, which are the one stretch of routing the board
geometry dictates rather than the designer: the tongue is 7.80 mm wide between two slots.
"""
import pathlib
import sys

import pcbnew

from board import BOARD_Y, CENTRE_X, PLATE_KEEPOUT, PLATE_MAX_H, POCKET_KEEPOUT, contains, half_width

PCB = pathlib.Path(__file__).resolve().parent.parent / "nanoleaf_shapes.kicad_pcb"
ESCAPE_X = (84.335, 86.835, 89.335)
HEIGHT = {"C0402": 0.55, "R0402": 0.45, "C0603": 0.9, "R0603": 0.6, "C0805": 1.45, "C1210": 2.8,
          "SMA": 2.4, "SOD-123": 1.35, "SOT-23": 1.45, "SOIC": 1.75, "LED_0603": 0.8,
          "IND-SMD": 3.0, "WT0132C6": 3.2, "SW-SMD": 2.5, "USB_C": 3.5, "TestPoint": 0.0,
          "PTS645Sx43": 4.3,     # C&K 6x6 tactile; the series also comes in 5.0, 7.0 and 9.5 mm
          "Nanoleaf_Linker": 0.0}


def height_of(fpid):
    for key, h in HEIGHT.items():
        if key in fpid:
            return h
    return 2.0


def main():
    b = pcbnew.LoadBoard(str(PCB))
    all_tracks = list(b.GetTracks())
    doomed = []
    for t in all_tracks:
        s, e = t.GetStart(), t.GetEnd()
        keep = (t.GetClass() == "PCB_TRACK"
                and any(abs(s.x / 1e6 - x) < 0.01 and abs(e.x / 1e6 - x) < 0.01 for x in ESCAPE_X))
        if not keep:
            doomed.append(t)
    for t in doomed:
        b.Remove(t)          # GetTracks() stops being iterable once the list has been mutated
    print(f"tracks   removed {len(doomed)} stale, kept {len(all_tracks) - len(doomed)} escape tracks")
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(str(PCB), b)

    fps = {f.GetReference(): f for f in b.GetFootprints()}
    box = lambda f: f.GetBoundingBox(False, False)
    mmf = lambda v: v / 1e6

    # J1 is excluded from the three geometric checks below: its bounding box is the FAB DRAWING of the linker
    # plate, 17.34 x 40 mm, which deliberately crosses the joint edge onto the panel. Its real copper is three
    # pads and two Edge.Cuts slots, and the pocket/plate keepout checks cover the linker properly.
    DRAWN_ONLY = {"J1"}

    # Checked on pads, not bounding boxes: a part rotated off a 90 degree step has bbox corners outside its
    # own outline, so J3 at 300 degrees on the left leg would read as off-board when its copper is fine.
    # Copper-to-edge proper is DRC's job; this is the coarse "did something fall off" check.
    bad, worst = [], None
    for ref, f in fps.items():
        if ref in DRAWN_ONLY:
            continue
        for pad in f.Pads():
            c = pad.GetPosition()
            r = max(pad.GetSize().x, pad.GetSize().y) / 2e6
            x, y = c.x / 1e6, c.y / 1e6
            margin = min(half_width(y) - abs(x - CENTRE_X) - r, y - BOARD_Y[0], BOARD_Y[1] - y)
            if margin < 0:
                bad.append(f"{ref} ({x:.1f},{y:.1f})")
            if worst is None or margin < worst[0]:
                worst = (margin, f"{ref}.{pad.GetNumber()}")
    print("inside   " + (f"OFF BOARD: {', '.join(sorted(set(bad)))}" if bad
                         else f"every pad fits the trapezoid; tightest {worst[1]} at {worst[0]:.2f} mm"))

    overlaps = []
    items = sorted((r, f) for r, f in fps.items() if r not in DRAWN_ONLY)
    for i, (r1, f1) in enumerate(items):
        for r2, f2 in items[i + 1:]:
            if f1.GetLayer() != f2.GetLayer():
                continue
            a, c = box(f1), box(f2)
            ox = min(a.GetRight(), c.GetRight()) - max(a.GetLeft(), c.GetLeft())
            oy = min(a.GetBottom(), c.GetBottom()) - max(a.GetTop(), c.GetTop())
            if ox > 0 and oy > 0:
                overlaps.append(f"{r1}/{r2} ({mmf(min(ox, oy)):.2f} mm)")
    print("courtyd  " + (f"{len(overlaps)} OVERLAP: {', '.join(overlaps)}" if overlaps else "no courtyard overlaps"))

    def hits(bb, rect):
        x0, y0, x1, y1 = rect
        return (bb.GetLeft() < pcbnew.FromMM(x1) and bb.GetRight() > pcbnew.FromMM(x0)
                and bb.GetTop() < pcbnew.FromMM(y1) and bb.GetBottom() > pcbnew.FromMM(y0))

    from board import ANTENNA                # the module's printed antenna: no copper on either layer
    in_antenna = sorted(r for r, f in fps.items()
                        if r not in DRAWN_ONLY | {"U2"} and hits(box(f), ANTENNA))
    print("antenna  " + (f"IN THE ANTENNA ZONE: {', '.join(in_antenna)}" if in_antenna
                         else f"clear (x {ANTENNA[0]}..{ANTENNA[2]}, y {ANTENNA[1]}..{ANTENNA[3]})"))

    pocket, tall = [], []
    for ref, f in fps.items():
        if ref in ("J1",) or f.GetLayer() != pcbnew.F_Cu:
            continue
        bb = box(f)
        if hits(bb, POCKET_KEEPOUT):
            pocket.append(ref)
        elif hits(bb, PLATE_KEEPOUT) and height_of(f.GetFPIDAsString()) > PLATE_MAX_H:
            tall.append(f"{ref} {height_of(f.GetFPIDAsString())}mm")
    print("pocket   " + (f"IN THE POCKET: {', '.join(pocket)}" if pocket else "clear"))
    print("plate    " + (f"TOO TALL under the plate: {', '.join(tall)}" if tall else f"clear (limit {PLATE_MAX_H} mm)"))

    tallest = max((height_of(f.GetFPIDAsString()), f.GetReference(), f.GetLayerName()) for f in fps.values()
                  if f.GetLayer() == pcbnew.F_Cu)
    back = [(height_of(f.GetFPIDAsString()), f.GetReference()) for f in fps.values()
            if f.GetLayer() == pcbnew.B_Cu]
    print(f"height   front {tallest[0]:.2f} mm ({tallest[1]}) against the linker's 4.95 mm")
    if back:
        print(f"sides    {len(back)} on the back ({', '.join(r for _, r in sorted(back))}), "
              f"tallest {max(h for h, _ in back):.2f} mm; the other {len(fps)-len(back)} are front-side")
    else:
        print("sides    one-sided: every part on the front, so the whole board is assemblable")

    import math
    d = lambda a, c: math.dist(a, c)
    pos = lambda ref, net: next((((p.GetPosition().x) / 1e6, (p.GetPosition().y) / 1e6)
                                 for p in fps[ref].Pads() if p.GetNetname() == net), None)
    print("\nwhat rev A got wrong, now:")
    u2_3v3 = pos("U2", "3V3")
    near = sorted((d(u2_3v3, pos(c, "3V3")), c) for c in ("C4", "C5", "C6", "C7", "C8", "C9") if pos(c, "3V3"))
    print(f"  module 3V3 -> nearest 100nF   {near[0][0]:5.2f} mm ({near[0][1]})   was 8.17")
    print(f"               three nearest    " + ", ".join(f"{c} {v:.2f}" for v, c in near[:3]))
    vin = pos("U1", "42V")
    for c in ("C1", "C2", "C3", "C11"):
        print(f"  U1 VIN -> {c:4s}                {d(vin, pos(c, '42V')):5.2f} mm")
    sw = next(p.GetNetname() for p in fps["U1"].Pads() if p.GetNumber() == "8")
    print(f"  U1 SW  -> D1 (catch)          {d(pos('U1', sw), pos('D1', sw)):5.2f} mm   was n/a")
    print(f"  D1 GND -> U1 GND              {d(pos('D1','GND'), pos('U1','GND')):5.2f} mm   was 17.89")
    print(f"  U1 SW  -> L1                  {d(pos('U1', sw), pos('L1', sw)):5.2f} mm")
    for u in ("U3", "U4"):
        caps = [(d(pos(u, "3V3"), pos(c, "3V3")), c) for c in ("C18", "C19") if pos(c, "3V3")]
        v, c = min(caps)
        print(f"  {u} Vcc -> {c}                 {v:5.2f} mm")


if __name__ == "__main__":
    main()
