#!/usr/bin/env python3
"""Dumps every footprint's footprint-on-the-board and height to parts.json.

The enclosure and the printable board mock both need to know what stands where and how tall it is, but
they are built with manifold3d, which does not live in KiCad's Python, and pcbnew does not live anywhere
else. So this runs under KiCad's interpreter and leaves a plain JSON file for them to read.

Heights are a lookup by footprint name -- KiCad footprints carry no height -- and are deliberately on the
generous side, because a case that is 0.2 mm too deep still closes and one that is 0.2 mm too shallow does
not. The outline is the courtyard unioned with the pads -- see the comment in main(); the courtyard
sweeps.

The table is worth more than the 3D models for most parts and less for a few, so it is the taller of the
two. `board_real.py` exports each part's model and measures it: the models understate badly where
easyeda2kicad ships a generic shape (C1's 1210 came out at 1.25 mm against a real 2.80, C14's at 0.65
against 1.45), and overstate only for the tactile switches, where the model is 4.38 against a datasheet
4.30. Take whichever is taller, part by part.

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 export_parts.py
"""
import json
import math
import pathlib

import pcbnew

PCB = pathlib.Path(__file__).resolve().parent.parent / "nanoleaf_shapes.kicad_pcb"
OUT = pathlib.Path(__file__).resolve().parent / "parts.json"
f = lambda v: v / 1e6

# Package name -> height above the board, mm. Matched as a substring of the footprint id, first hit wins,
# so put the specific ones first.
HEIGHT = {
    "TS-1187A": 1.50,     # XKB TS-1187A-B-A-B: 160 gf, height code A = 1.50 mm, brass column.
                          # Replaced the PTS645 to get the case down; 6.55 mm of the stack is the
                          # linker and the board, so the switch is the only place left to save.
    "PTS645Sx43": 4.40,   # C&K 6x6 tactile, the back buttons. The datasheet says 4.30 and KiCad's model
                          # measures 4.38, so this takes the taller of the two with a little margin --
                          # the lid's button bosses are set off this, and at 4.30 the boss came within
                          # 0.02 mm of the real switch instead of the 0.10 it is meant to leave.
    "TS-1088": 2.00,      # XUNPU TS-1088-AR02016, reset and boot: 3.9 x 3 x 2.0 mm, 2 pads.
                          # Same height as the KMR2 it replaced, so the case did not change -- these
                          # two come off the board once auto-reset is proven, and 2 pads desolder
                          # more easily than 4.
    "KMR2": 2.00,         # C&K KMR2, reset and boot. 2.50 was a guess; KiCad ships a real C&K STEP
                          # model for this one, not a generic shape, and it measures 1.99.
    "USB_C": 3.50,        # HRO TYPE-C-31-M-12, datasheet 3.16 plus margin
    "WT0132C6": 3.20,     # the module
    "IND-SMD": 3.00,      # L1
    "C1210": 2.80,
    "SMA": 2.40,          # D3, the TVS
    "SOIC": 1.75,
    "SOT-23": 1.45, "C0805": 1.45,
    "SOD-123": 1.35,
    "C0603": 0.90, "LED_0603": 0.80, "R0603": 0.60,
    "C0402": 0.55, "R0402": 0.45,
    "TestPoint": 0.00, "Nanoleaf_Linker": 0.00,
}
DEFAULT_H = 2.00

# Fitted for bring-up, desoldered before the board goes in the case. They are on the board and in the BOM,
# so this is not DNP -- it only means the case does not have to make room for them. Without this the
# reset/boot switches, at 2.00 mm against the user buttons' 1.50, would set the whole back of the case.
NOT_IN_CASE = {"SW1", "SW2"}


def fab_bbox(fp):
    """The part's real body, from its F.Fab/B.Fab outline.

    Courtyards carry assembly margin and the plain bounding box carries silkscreen, so both overstate what
    the case has to clear. The fab layer is the one drawn as the component body.
    """
    xs, ys = [], []
    for g in fp.GraphicalItems():
        if g.GetLayer() not in (pcbnew.F_Fab, pcbnew.B_Fab):
            continue
        if g.GetClass() in ("PCB_TEXT", "FP_TEXT", "PCB_TEXTBOX"):
            continue        # the %R reference is on the fab layer too, and is not part of the body
        bb = g.GetBoundingBox()
        xs += [f(bb.GetLeft()), f(bb.GetRight())]
        ys += [f(bb.GetTop()), f(bb.GetBottom())]
    return [min(xs), min(ys), max(xs), max(ys)] if xs else None


def plunger_of(fp):
    """A tactile switch's pressable face, from the circle KiCad draws at the middle of its fab outline.

    The three switches on this board mark it: PTS645 3.50 mm, TS-1187A 2.00, KMR2 1.60. Sizing the lid's
    boss off this instead of a constant matters -- a boss wider than the plunger lands on the switch
    housing and the button never actuates.
    """
    best = 0.0
    for g in fp.GraphicalItems():
        if g.GetLayer() not in (pcbnew.F_Fab, pcbnew.B_Fab):
            continue
        if g.GetClass() != "PCB_SHAPE" or g.GetShape() != pcbnew.SHAPE_T_CIRCLE:
            continue
        cx, cy = f(g.GetCenter().x) - f(fp.GetPosition().x), f(g.GetCenter().y) - f(fp.GetPosition().y)
        if abs(cx) > 0.6 or abs(cy) > 0.6:
            continue
        d = math.hypot(f(g.GetEnd().x) - f(g.GetCenter().x), f(g.GetEnd().y) - f(g.GetCenter().y)) * 2
        best = max(best, d)
    return round(best, 3)


def pick_body(fab, court):
    """The fab outline when it really is one, otherwise the courtyard.

    Most of this board comes from easyeda2kicad, whose footprints often put nothing on the fab layer but a
    pin-1 dot. Taking that as the body would say an 0805 is 0.12 mm across, so anything much smaller than
    its own courtyard is rejected and the courtyard -- which overstates, which is the safe direction -- is
    used instead.
    """
    if not fab:
        return court
    area = lambda r: max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])
    return fab if area(fab) >= 0.25 * area(court) else court


def height_of(fpid):
    for key, h in HEIGHT.items():
        if key in fpid:
            return h
    return DEFAULT_H


def main():
    global PCB, OUT
    b = pcbnew.LoadBoard(str(PCB))

    edges = []
    for d in b.GetDrawings():
        if d.GetLayer() == pcbnew.Edge_Cuts:
            edges.append([[f(d.GetStart().x), f(d.GetStart().y)], [f(d.GetEnd().x), f(d.GetEnd().y)]])

    slots = []
    j1 = next(x for x in b.GetFootprints() if x.GetReference() == "J1")
    for g in j1.GraphicalItems():
        if g.GetLayer() == pcbnew.Edge_Cuts:
            bb = g.GetBoundingBox()
            slots.append([f(bb.GetLeft()), f(bb.GetTop()), f(bb.GetRight()), f(bb.GetBottom())])

    parts = []
    unknown = []
    for fp in b.GetFootprints():
        fpid = fp.GetFPIDAsString()
        lay = pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd
        cy = fp.GetCourtyard(lay)
        pads = fp.GetBoundingBox(False, False)
        court = [f(pads.GetLeft()), f(pads.GetTop()), f(pads.GetRight()), f(pads.GetBottom())]
        if cy.OutlineCount():
            # The UNION of the courtyard and the pads, never the courtyard alone. Half the
            # easyeda2kicad footprints draw the courtyard around the component BODY and leave the leads
            # outside it: U1 is SOIC-8_L5.0-W4.0-P1.27-LS6.0, a 6.0 mm lead span inside a 3.95 mm
            # courtyard, and its 3D model is 6.00 mm wide as it should be. Trusting the courtyard there
            # under-reports the part by 1.81 mm, which is how a support post ended up resting on U1's
            # leads. Pads are where the leads land, so the union is the envelope the case must clear.
            bb = cy.BBox()
            court = [min(court[0], f(bb.GetLeft())), min(court[1], f(bb.GetTop())),
                     max(court[2], f(bb.GetRight())), max(court[3], f(bb.GetBottom()))]
        body = pick_body(fab_bbox(fp), court)
        # The clearance envelope must cover whatever the board mock actually draws, which is `body`. For
        # most parts body is inside court, but U2's fab outline is 0.005 mm taller than its courtyard, and
        # that was enough to leave a 0.03 x 0.05 mm corner of the module poking through the cavity wall --
        # a false clash in the fit check with no physical meaning. Keeping court a superset of body
        # removes the whole class of it.
        court = [min(court[0], body[0]), min(court[1], body[1]),
                 max(court[2], body[2]), max(court[3], body[3])]
        if not any(k in fpid for k in HEIGHT):
            unknown.append(f"{fp.GetReference()} ({fpid.split(':')[-1]})")
        parts.append(dict(
            ref=fp.GetReference(), value=fp.GetValue(), fpid=fpid,
            back=bool(fp.IsFlipped()), h=height_of(fpid),
            x=f(fp.GetPosition().x), y=f(fp.GetPosition().y), rot=fp.GetOrientationDegrees(),
            court=court,
            body=body, plunger=plunger_of(fp), in_case=fp.GetReference() not in NOT_IN_CASE,
        ))

    OUT.write_text(json.dumps(dict(edges=edges, linker_slots=slots, parts=parts), indent=1))
    front = [p for p in parts if not p["back"]]
    back = [p for p in parts if p["back"]]
    print(f"{OUT.name}: {len(parts)} parts, {len(front)} front, {len(back)} back")
    print(f"  tallest front {max(p['h'] for p in front):.2f} mm "
          f"({max(front, key=lambda p: p['h'])['ref']})")
    print(f"  tallest back  {max(p['h'] for p in back):.2f} mm "
          f"({max(back, key=lambda p: p['h'])['ref']})")
    cased = [p for p in back if p["in_case"]]
    print(f"  of those, in the case: {len(cased)} of {len(back)}, tallest {max(p['h'] for p in cased):.2f} mm "
          f"({max(cased, key=lambda p: p['h'])['ref']}); "
          f"{', '.join(sorted(NOT_IN_CASE))} come off first")
    if unknown:
        print(f"  !! no height entry, assumed {DEFAULT_H} mm: {', '.join(unknown)}")


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        PCB = pathlib.Path(args[0]).resolve()
        OUT = OUT.with_name(args[1]) if len(args) > 1 else OUT
        print(f"board    {PCB}")
    main()
