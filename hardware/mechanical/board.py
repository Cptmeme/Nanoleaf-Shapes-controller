#!/usr/bin/env python3
"""The rev B outline: the case is a wide isosceles trapezoid, the board is that shape inset.

Imported by revb_outline.py, which writes the board into KiCad, and by enclosure.py, which builds the case, so
the two cannot drift apart. KiCad page coordinates in millimetres, y increasing downwards, so the joint edge --
the long parallel side, the one the linker crosses onto the panel -- is at the top and the board tapers away.

Why this shape. A hexagon's corner is 120 degrees, so each leg of this trapezoid is the panel's own adjacent
edge continued straight through its vertex: the case does not approximate the Shapes lines, it lies on them.
Carried to its end the two legs would close into an equilateral triangle; the trapezoid is that triangle cut
off at CASE_DEPTH, which is the one dimension free to grow for the electronics.

  CASE_W       113.00, just inside a hexagon's 114 mm edge, so the case never overhangs the panel it joins.
  JOINT_Y      the case's joint edge. Every linker dimension is measured from here, NOT from the board edge:
               the linker plate straddles the joint, 20.02 mm onto the panel and 20.02 mm onto the case, so
               this line has to fall halfway along the linker or it will not reach the panel.
  JOINT_INSET  how far the board sits inside that edge, leaving a wall. The pocket's near wall is 2.72 mm in,
               so anything up to that keeps the board under the whole pocket, where it has to be.
  CASE_DEPTH   as shallow as the packed layout allows. The depth is the free dimension -- width is fixed
               by the hexagon's edge -- so it is what sets the board area. The board was reshaped during
               routing, so this is derived from its real far edge rather than chosen.
"""
import math

from linker import PAD_CENTRE, PLATE_HALF_L, PLUG_L, PLUG_W, WALL_TO_JOINT
from linker_footprint import POCKET_CLEAR, WALL

JOINT_Y = 44.00             # the case's joint edge: the long parallel side, against the panel
CASE_W = 113.00             # along it, just inside a hexagon's 114 mm edge
CASE_DEPTH = 25.551         # to the case's far edge: board far edge 67.651 + SIDE_GAP, measured back from JOINT_Y
SIDE_ANGLE = 60.0           # the legs, to the joint edge: a hexagon's corner is 120 degrees
CENTRE_X = 86.835           # the linker, and the whole trapezoid, centre here

JOINT_INSET = 2.00          # board edge inside the case's joint edge
SIDE_GAP = 1.90             # board to case on the legs and the far edge: 1.60 wall + 0.30 clearance

SLOPE = 1.0 / math.tan(math.radians(SIDE_ANGLE))        # width lost per side per mm of depth
LEG_INSET = 1.0 / math.sin(math.radians(SIDE_ANGLE))    # sideways travel per mm of inset from a leg

BOARD_Y = (JOINT_Y + JOINT_INSET, JOINT_Y + CASE_DEPTH - SIDE_GAP)
BOARD_W = CASE_W - 2 * SLOPE * JOINT_INSET - 2 * SIDE_GAP * LEG_INSET    # at the board's own joint edge
BOARD_DEPTH = BOARD_Y[1] - BOARD_Y[0]
FAR_W = BOARD_W - 2 * SLOPE * BOARD_DEPTH

LINKER_X = CENTRE_X
PAD_ORIGIN = (LINKER_X, JOINT_Y + PAD_CENTRE)           # measured from the case edge, not the board edge
BOARD_T = 1.60
BOARD_X = (CENTRE_X - BOARD_W / 2, CENTRE_X + BOARD_W / 2)


def case_half_width(y):
    return CASE_W / 2 - SLOPE * (y - JOINT_Y)


def half_width(y, inset=0.0):
    """Half the board's width at page y, optionally inset from both legs."""
    return BOARD_W / 2 - SLOPE * (y - BOARD_Y[0]) - inset * LEG_INSET


def _trapezoid(top, bottom, width_at, inset=0.0):
    return [(CENTRE_X - width_at(top + inset, inset), top + inset),
            (CENTRE_X + width_at(top + inset, inset), top + inset),
            (CENTRE_X + width_at(bottom - inset, inset), bottom - inset),
            (CENTRE_X - width_at(bottom - inset, inset), bottom - inset)]


def outline(inset=0.0):
    """The board's four corners, clockwise from the joint edge's left end."""
    return _trapezoid(BOARD_Y[0], BOARD_Y[1], half_width, inset)


def case_outline():
    return _trapezoid(JOINT_Y, JOINT_Y + CASE_DEPTH, lambda y, _: case_half_width(y))


def contains(x, y, inset=0.0):
    return (BOARD_Y[0] + inset <= y <= BOARD_Y[1] - inset
            and abs(x - CENTRE_X) <= half_width(y, inset))


# What the linker forbids on the pad side, as (x0, y0, x1, y1) page rectangles, all from the CASE joint edge:
#   pocket   nothing at all -- the printed pocket walls sit on the board here
#   plate    nothing over PLUG_H + TOP_GAP - PLATE_T = 2.58 mm tall, under the linker plate's recess
POCKET_KEEPOUT = (LINKER_X - (PLUG_W / 2 + POCKET_CLEAR + WALL), JOINT_Y + WALL_TO_JOINT - POCKET_CLEAR - WALL,
                  LINKER_X + (PLUG_W / 2 + POCKET_CLEAR + WALL), JOINT_Y + WALL_TO_JOINT + PLUG_L + POCKET_CLEAR + WALL)
PLATE_KEEPOUT = (LINKER_X - 8.87, JOINT_Y, LINKER_X + 8.87, JOINT_Y + PLATE_HALF_L)
PLATE_MAX_H = 2.58

# The module's printed antenna, which overhangs its pads by 8.62 mm. No copper on either layer, and the ground
# pour is cut away from it. Moves with U2, so it is here rather than buried in the placement script.
ANTENNA = (119.0, 48.3, 127.4, 66.4)


if __name__ == "__main__":
    print(f"case    {CASE_W:.2f} mm on the joint edge -> {CASE_W - 2*SLOPE*CASE_DEPTH:.2f} mm, "
          f"{CASE_DEPTH:.2f} mm deep, legs at {SIDE_ANGLE:.0f} deg  (hexagon edge is 114)")
    print(f"board   {BOARD_W:.2f} -> {FAR_W:.2f} mm, {BOARD_DEPTH:.2f} mm deep, y {BOARD_Y[0]:.2f}..{BOARD_Y[1]:.2f}")
    print(f"area    {(BOARD_W + FAR_W) / 2 * BOARD_DEPTH:.0f} mm2")
    print(f"J1      origin {PAD_ORIGIN[0]:.3f}, {PAD_ORIGIN[1]:.2f}; pads {PAD_CENTRE:.2f} mm from the CASE edge, "
          f"{PAD_CENTRE - JOINT_INSET:.2f} from the board's")
    print(f"tongue  {BOARD_Y[0]:.2f} to the slot at {JOINT_Y + 4.22:.2f} leaves {JOINT_Y + 4.22 - BOARD_Y[0]:.2f} mm "
          f"of solid board at the near end")
    print()
    for y, what in ((BOARD_Y[0], "board joint edge"), (62.82, "below the linker"), (63.73, "rev A's top"),
                    (85.18, "rev A's bottom")):
        lo, hi = CENTRE_X - half_width(y), CENTRE_X + half_width(y)
        note = ""
        if y >= 63.73:
            note = f"   rev A 69.05..104.62 -> {min(69.05 - lo, hi - 104.62):.2f} mm spare"
        print(f"  y {y:6.2f}  {what:18s} x {lo:7.2f} ..{hi:8.2f}  ({2*half_width(y):6.2f} mm){note}")
