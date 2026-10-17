#!/usr/bin/env python3
"""The rev B enclosure: a tray the board drops into, and a lid carrying the three back buttons.

Everything in the thickness direction is forced by the linker, so the stack is built from z = 0 at the
case's WALL-FACING outer face -- the one the linker plate recesses into -- and grows towards the room:

    0.00  outer face, wall-facing                 the plate recess is cut into this
    2.37  plate recess floor                      PLATE_T
    4.95  board's front surface                   + PLUG_H + TOP_GAP, so the plug's top almost touches it
    6.55  board's back surface                    + BOARD_T
   10.85  top of the tallest back part            + the buttons, 4.30
   11.20  lid's inner face                        + BACK_GAP
   12.80  lid's outer face, room-facing           + LID_T

The first three rows are not design choices: pocket_test.py proved them against a real linker, and the
case edge has to fall halfway along the linker or it will not reach the panel. Only the last two are free.

The board's FRONT faces the wall, because that is the side the linker pads are on, so the buttons end up
on the back, facing the room, which is what makes them pressable.

The three button sections are pads raised proud of the lid, each hung on a thin flexure ring and carrying
a boss on its inside that closes most of the gap to the switch. One wide pad on the right, where SW6 sits
alone, and two narrower ones on the left over SW3 and SW4.

Needs parts.json -- run export_parts.py under KiCad's Python first -- and manifold3d:

    pip install manifold3d numpy
    python3 enclosure.py
"""
import json
import math
import pathlib
import struct
import sys

import numpy as np
from manifold3d import CrossSection, JoinType, Manifold

from board import CASE_DEPTH, CASE_W, CENTRE_X, JOINT_Y, SLOPE
from linker import (PLATE_HALF_L, PLATE_R, PLATE_T, PLATE_W, PLUG_H, PLUG_L, PLUG_R, PLUG_W, WALL_TO_JOINT)
from linker_footprint import POCKET_CLEAR, WALL
from pocket_test import TOP_GAP

HERE = pathlib.Path(__file__).resolve().parent

BOARD_T = 1.60          # the fab's finished thickness
FIT = 0.30              # board edge to the case's inner wall
PART_GAP = 0.25         # around every front part
THIN_WALL = 0.50        # walls thinner than twice this are merged away rather than printed
RECESS_WALL = 2.50      # wall put back around the plate recess, so part pockets cannot open into it;
                        # it gives way locally to anything too tall to live under it
FRONT_GAP = 0.35        # over the tallest front part
BACK_GAP = 0.35         # over the tallest back part, before the lid's inner face
PLATE_FLOOR = 0.80      # least material left under the plate recess
GRAZE = 0.05            # overlap with the recess below which a part is not worth relieving
RELIEF_GAP = 0.15       # clearance around a part that has to cut into the recess floor
MIN_FLOOR = 0.60        # thinnest recess floor worth printing; below this it is a hole
LEDGE = 1.20            # rim the board sits on, opened up where a part needs the room
POST_D = 1.80           # support posts out in the open cavity; small, because the free gaps between
                        # parts are a thin web rather than open blobs -- 3.0 mm only fitted in 3 places
LID_T = 1.60
CASE_WALL = 1.60        # perimeter wall
USB_PORT = (9.00, 3.20) # the opening in the outer face: a USB-C plug shell is 8.34 x 2.56
USB_AXIS = 1.72         # the port's centreline above the board's front surface. MEASURED off KiCad's
                        # model, not assumed: slicing the receptacle at y 68.00 shows its cavity at
                        # 8.34 x 2.56 -- the USB-C figure exactly -- centred on z 3.23. Guessing 1.60
                        # put the opening 0.12 mm high, which still passed a plug but left 0.20 mm
                        # clearance on one side against 0.44 on the other.
CORNER_R = 2.00         # plan-view radius on the case's four outer corners
EDGE_R = 1.00           # fillet on the outer perimeter edge, top face and bottom face
EDGE_STEPS = 10         # slabs used to approximate that fillet
# Snap fit. The lid's lip drops into the slot between the board edge and the tray's rim, and that slot
# is where the detent lives: the lip carries four beads that stand proud of its outer face, the tray's
# rim carries four matching grooves. Everything is outboard of the board edge, so none of it touches the
# PCB. Interference is SNAP_H - LIP_FIT, and the beads ramp in from nothing over SNAP_RAMP so closing
# the lid cams them rather than scraping. If the first print is too stiff or too loose, SNAP_H is the
# number to change and nothing else moves.
SNAP_H = 0.30           # bead, proud of the lip's outer face: 0.15 mm interference past LIP_FIT
SNAP_LEN = 14.00        # along the edge, each bead
SNAP_RAMP = 0.40        # lead-in: protrusion grows from 0 to SNAP_H over this height
SNAP_FLAT = 0.45        # full-height part of the bead above the ramp
SNAP_Z0 = 0.25          # bead starts this far above the lip's bottom edge
SNAP_SLACK = 0.20       # extra room in the tray's groove, all round
SNAP_X = (28.0, )       # beads at CENTRE_X +- these, on both long edges
LID_LIP_W = 1.20        # lip width: it locates the lid AND clamps the board onto the tray's ledge
LIP_FIT = 0.15          # lip to tray wall, per side

BTN_LARGE = (18.0, 13.0)    # the pad over SW6, alone on its side
BTN_SMALL = (11.0, 9.0)     # the pads over SW3 and SW4
BTN_R = 2.0                 # pad corner radius
BTN_PROUD = 1.00            # how far the pad stands above the lid, so it can be found by feel
BTN_FIT = 0.25              # cap to the lid's opening, per side: it has to slide, not flex
FLANGE_W = 1.20             # how far the retaining ridge stands proud of the cap, per side
FLANGE_T = 0.60             # ridge thickness
CB_DEPTH = 0.80             # counterbore from the lid's inner face, where the ridge lives
TRAVEL = 0.25               # switch travel, worst case; the ridge must stay engaged through it
BOSS_GAP = 0.10             # boss to switch, unpressed
BOSS_MARGIN = 0.40          # boss kept this much inside the plunger, so it cannot sit on the housing

Z_OUT = 0.0
Z_RECESS = PLATE_T
Z_PCB = PLATE_T + PLUG_H + TOP_GAP
Z_PCB_BACK = Z_PCB + BOARD_T
Z_CAV_PLATE = Z_RECESS + PLATE_FLOOR


def rounded(w, l, r, cx=0.0, cy=0.0):
    core = CrossSection.square((max(w - 2 * r, 1e-3), max(l - 2 * r, 1e-3)), center=True)
    return core.offset(r, JoinType.Round, circular_segments=64).translate((cx, cy))


def poly(points):
    cs = CrossSection([list(points)])
    return cs if cs.area() > 0 else CrossSection([list(reversed(points))])


def case_half_width(y):
    return CASE_W / 2 - SLOPE * (y - JOINT_Y)


def case_profile(inset=0.0, sharp=False):
    """The case's trapezoid, corners rounded, optionally shrunk by a perpendicular inset.

    Shrinking and growing by the same radius with round joins rounds every convex corner and leaves
    the straight runs where they were, so the case keeps its 113.00 mm joint edge and its 60 degree
    legs. `sharp` returns the original hard-cornered trapezoid, which the brace band still wants: the
    band is clipped to the case outline only to stop it running off the end, and rounding there would
    pointlessly thin it at the corners.
    """
    p = poly([(CENTRE_X - case_half_width(JOINT_Y), JOINT_Y),
              (CENTRE_X + case_half_width(JOINT_Y), JOINT_Y),
              (CENTRE_X + case_half_width(JOINT_Y + CASE_DEPTH), JOINT_Y + CASE_DEPTH),
              (CENTRE_X - case_half_width(JOINT_Y + CASE_DEPTH), JOINT_Y + CASE_DEPTH)])
    if not sharp and CORNER_R > 0:
        p = (p.offset(-CORNER_R, JoinType.Round, circular_segments=48)
              .offset(CORNER_R, JoinType.Round, circular_segments=48))
    return p.offset(-inset, JoinType.Miter, circular_segments=8) if inset else p


def fillet_face(solid, section, z_face, r, upward, steps=EDGE_STEPS):
    """Round the outer perimeter edge where `solid` meets the plane z_face.

    Manifold has no fillet operator, so the edge is approximated by subtracting a stack of rings: at a
    distance t into the material the profile is inset by r - sqrt(r^2 - (r - t)^2), which is a quarter
    circle. Ten steps over a 1 mm radius is already smoother than the printer can resolve.

    `upward` is True when the material lies above z_face (the tray's wall-facing underside) and False
    when it lies below (the lid's room-facing top).
    """
    if r <= 0:
        return solid
    for i in range(steps):
        t0, t1 = r * i / steps, r * (i + 1) / steps
        d = r - math.sqrt(max(r * r - (r - t0) ** 2, 0.0))      # inset at the shallower end of the band
        ring = section - section.offset(-d, JoinType.Round, circular_segments=32)
        if ring.area() <= 1e-9:
            continue
        lo, hi = (z_face + t0, z_face + t1) if upward else (z_face - t1, z_face - t0)
        solid -= slab(ring, lo, hi)
    return solid


def board_profile(data, grow=0.0):
    ring = chain_edges(data["edges"])
    p = poly(ring)
    return p.offset(grow, JoinType.Miter, circular_segments=8) if grow else p


def chain_edges(edges, tol=1e-3):
    todo = [[tuple(a), tuple(c)] for a, c in edges]
    ring = list(todo.pop(0))
    while todo:
        for i, (a, c) in enumerate(todo):
            if math.dist(ring[-1], a) < tol:
                ring.append(c); todo.pop(i); break
            if math.dist(ring[-1], c) < tol:
                ring.append(a); todo.pop(i); break
        else:
            raise SystemExit("Edge.Cuts is not one closed ring")
    return ring[:-1]


def slab(section, z0, z1):
    """Extrude a 2D section between two heights.

    An empty section is normal -- "every part inside the plate recess" is empty once the board is laid out
    properly -- but extruding one yields a manifold with status InvalidConstruction, and subtracting that
    silently takes the whole tray to zero volume rather than raising. So empty in, empty out.
    """
    if section.area() <= 1e-9:
        return Manifold()
    return section.extrude(z1 - z0).translate((0, 0, z0))


def box(x0, y0, x1, y1, z0, z1):
    return Manifold.cube((x1 - x0, y1 - y0, z1 - z0)).translate((x0, y0, z0))


def through_wall(section, y0, y1):
    """Sweep a section drawn in X and height along Y, to cut through a wall.

    CrossSection extrudes along z, so the section is drawn with its height as y and then turned a quarter
    turn about X: x stays x, the section's y becomes z, and the extrusion runs along y.
    """
    return section.extrude(y1 - y0).rotate((90, 0, 0)).translate((0, y1, 0))


def usb_cut(data):
    """The opening for J3 in the far wall: the port's own outline, not a slot.

    Two cuts, because one shape cannot do both jobs. The outer one is the port -- a stadium, fully rounded
    ends, the shape a USB-C plug actually is. The inner one clears the connector's body, which is square in
    section and overhangs the board edge by 0.50 mm, so it sits inside the wall. A stadium wide enough to
    swallow that body as well would have to be about 10.9 mm across, nearly 2 mm wider than the body it is
    hiding, and would look like a slot again -- so the body gets its own clearance behind the port instead,
    where nothing shows.
    """
    j3 = next(p for p in data["parts"] if p["ref"] == "J3")
    bx0, _, bx1, by1 = j3["body"]
    cx, h = (bx0 + bx1) / 2, j3["h"]
    far = JOINT_Y + CASE_DEPTH

    port = rounded(USB_PORT[0], USB_PORT[1], USB_PORT[1] / 2 - 0.01, cx, Z_PCB - USB_AXIS)
    body = rounded(bx1 - bx0 + 2 * PART_GAP, h + 2 * PART_GAP, 0.60, cx, Z_PCB - h / 2)
    return (through_wall(port, by1 - 0.30, far + 1.0)        # through the outer wall, and proud of it
            + through_wall(body, far - CASE_WALL - 1.5, by1 + 0.20))


def plate_section():
    """The recess the plate drops into -- the plate plus its fitting clearance."""
    return rounded(PLATE_W + 2 * POCKET_CLEAR, 2 * (PLATE_HALF_L + POCKET_CLEAR),
                   PLATE_R + POCKET_CLEAR, CENTRE_X, JOINT_Y)


def plate_inner_section():
    """The plate's footprint as the INSIDE of the case sees it: the same outline with the far end squared.

    The recess on the outer face keeps its radius, because the linker plate's own corners are round and it
    has to drop in. Inside the case none of that applies. The boss standing into the cavity is structure,
    and squaring its far end puts material back into the two corners and leaves a flat, full-width end wall
    instead of one that thins away into a radius. It can only add material: the square contains the
    rounded outline, so the recess cut -- still made with the rounded `plate_section()` -- takes nothing
    extra out of the outer face, and the corners it leaves standing sit outboard of the plate's own R2.00
    corners and cannot touch it.

    Only the far (+y) end is squared. The near end straddles the joint, lives outside the case and is
    clipped away by the case profile, so there is nothing there to square.
    """
    r = PLATE_R + POCKET_CLEAR
    w = PLATE_W + 2 * POCKET_CLEAR
    far = JOINT_Y + PLATE_HALF_L + POCKET_CLEAR
    return plate_section() + CrossSection.square((w, r), center=True).translate((CENTRE_X, far - r / 2))


def plate_floor_section():
    """The plate itself, without that clearance.

    Only this area needs a floor kept under it, because only this area has plate resting on it. Using the
    clearanced section instead makes the shallow rule bite 0.20 mm further out than the relief check does,
    and a part landing in the gap between the two -- D3 did -- gets no relief cut and a clash.
    """
    return rounded(PLATE_W, 2 * PLATE_HALF_L, PLATE_R, CENTRE_X, JOINT_Y)


def pocket_section(extra=0.0):
    return rounded(PLUG_W + 2 * (POCKET_CLEAR + extra), PLUG_L + 2 * (POCKET_CLEAR + extra),
                   PLUG_R + POCKET_CLEAR + extra, CENTRE_X, JOINT_Y + WALL_TO_JOINT + PLUG_L / 2)


def reliefs_for(data):
    """Front parts that will not fit under the plate recess, and how deep each has to cut into it.

    Measured against the recess as it is actually cut -- the plate plus its clearance -- not against the
    bare plate. Keying the two to different outlines leaves a 0.20 mm band where a part gets no relief and
    the shallow rule still applies, which is a clash rather than a hole, and worse.
    """
    px0, px1 = CENTRE_X - (PLATE_W / 2 + POCKET_CLEAR), CENTRE_X + (PLATE_W / 2 + POCKET_CLEAR)
    py0, py1 = JOINT_Y, JOINT_Y + PLATE_HALF_L + POCKET_CLEAR
    out = []
    for p in data["parts"]:
        if p["back"] or p["ref"] == "J1":
            continue
        bx0, by0, bx1, by1 = p["body"]
        ov_x = min(bx1, px1) - max(bx0, px0)
        ov_y = min(by1, py1) - max(by0, py0)
        if ov_x < GRAZE or ov_y < GRAZE:
            continue        # a graze at the recess edge, inside the corner radius and the clearance
        z_req = Z_PCB - p["h"] - FRONT_GAP
        if z_req >= Z_CAV_PLATE:
            continue
        # The part's own envelope, capped at the recess edge: growing first and clipping after keeps the
        # relief from eating floor the part never reaches.
        out.append(dict(ref=p["ref"], h=p["h"], z=z_req,
                        rect=(max(bx0 - RELIEF_GAP, px0), max(by0 - RELIEF_GAP, py0),
                              min(bx1 + RELIEF_GAP, px1), min(by1 + RELIEF_GAP, py1)),
                        floor=z_req - Z_RECESS))
    return out


def parts_section(data, taller_than=None):
    """Every front part's courtyard, grown by the clearance the case has to leave around it.

    With taller_than, only the parts that stand higher than that -- used for the recess wall, which only
    has to give way to a part too tall to sit under it.
    """
    out = CrossSection()
    for p in data["parts"]:
        if p["back"] or p["ref"] == "J1" or p["h"] <= 0:
            continue
        if taller_than is not None and p["h"] <= taller_than:
            continue
        x0, y0, x1, y1 = p["court"]
        out += CrossSection.square((x1 - x0 + 2 * PART_GAP, y1 - y0 + 2 * PART_GAP),
                                   center=True).translate(((x0 + x1) / 2, (y0 + y1) / 2))
    # Two parts a hair apart leave a wall a hair thick -- one scan came out at 0.06 mm -- which no nozzle
    # can lay down. Growing the pockets and shrinking them back merges anything that would leave a wall
    # thinner than 2 x THIN_WALL, so what is left is either solid enough to print or not there at all.
    return (out.offset(THIN_WALL, JoinType.Miter, circular_segments=8)
               .offset(-THIN_WALL, JoinType.Miter, circular_segments=8))


def cavity_section(data):
    """Where the tray is hollow under the board: one open space, not a pocket per part.

    Giving each part its own pocket makes a stiff tray, but it also wraps every part in plastic 0.25 mm
    away, and the buck converter has to get rid of its heat somehow. One open cavity leaves the whole front
    of the board in air. What that costs is support and stiffness, which comes back as a ledge round the
    rim, discrete posts inside, and the ring that ties the linker pocket to the floor -- the pocket does not
    need the cavity filled to stop being an island, it needs to be attached.

    The ledge is opened up wherever a front part reaches into it, so it carries the board only where
    nothing else needs the room.
    """
    return (board_profile(data, -LEDGE) + parts_section(data)) ^ board_profile(data, FIT)


def support_posts(data, n=10):
    """A few posts for the board to rest on, out in the open cavity where the rim cannot reach.

    Chosen rather than placed. Everything the post must miss -- parts, the linker pocket and its walls, the
    plate recess and its wall -- is subtracted from the board's interior, then that free area is eroded by
    the post's own radius so what is left is where a post CENTRE may sit. Candidates are taken off a coarse
    grid of that region and picked greedily, each time the one furthest from everything already chosen, so
    they spread out instead of bunching into the largest island.
    """
    keep_out = (parts_section(data)
                + plate_inner_section().offset(RECESS_WALL, JoinType.Miter, circular_segments=8)
                + pocket_section(WALL))
    free = board_profile(data, -LEDGE) - keep_out
    room = free.offset(-(POST_D / 2 + PART_GAP), JoinType.Round, circular_segments=16)
    if room.area() <= 0:
        return []
    x0, y0, x1, y1 = room.bounds()
    probe = CrossSection.square((0.02, 0.02), center=True)
    cands = []
    x = x0
    while x <= x1:
        y = y0
        while y <= y1:
            if (room ^ probe.translate((x, y))).area() > 1e-9:
                cands.append((x, y))
            y += 1.0
        x += 1.0
    chosen = []
    while cands and len(chosen) < n:
        best = max(cands, key=lambda c: min((math.dist(c, k) for k in chosen), default=1e9))
        chosen.append(best)
        cands = [c for c in cands if math.dist(c, best) > 2.5 * POST_D]
    return chosen


def snap_bands(data, extra, slack=0.0):
    """The ring between the lip's outer face and `extra` beyond it, cut to the four bead positions.

    Returns a list of (section, z0, z1) with the ramp expressed as a few sub-bands, so the bead is a
    wedge rather than a square shoulder and the lid cams shut instead of jamming.
    """
    base = board_profile(data, FIT - LIP_FIT - slack)
    boxes = CrossSection()
    for dx in SNAP_X:
        for x in (CENTRE_X - dx, CENTRE_X + dx):
            boxes += CrossSection.square((SNAP_LEN + 2 * slack, 400.0), center=True).translate((x, 0))
    out = []
    steps = 4
    for i in range(steps):                                   # the ramp, as a short stack
        h = extra * (i + 1) / steps
        ring = (base.offset(h + slack, JoinType.Round, circular_segments=16) - base) ^ boxes
        z0 = Z_PCB_BACK + SNAP_Z0 + SNAP_RAMP * i / steps
        out.append((ring, z0 - slack, z0 + SNAP_RAMP / steps + slack))
    ring = (base.offset(extra + slack, JoinType.Round, circular_segments=16) - base) ^ boxes
    z0 = Z_PCB_BACK + SNAP_Z0 + SNAP_RAMP
    out.append((ring, z0 - slack, z0 + SNAP_FLAT + slack))
    return out


def build_tray(data, z_seam, z_cav, reliefs):
    tray = slab(case_profile(), Z_OUT, z_seam)
    tray -= slab(board_profile(data, FIT), Z_PCB, z_seam + 1.0)       # board and its back parts

    inner = cavity_section(data)
    plate, keep = plate_section(), pocket_section(WALL)
    solid = plate_inner_section()       # what stands into the cavity; squared far end
    tray -= slab(inner - solid - keep, z_cav, Z_PCB)                  # under the board, general

    # Under the plate only the parts are cut, never a blanket cavity, so the recess keeps a floor and the
    # pocket walls stay embedded rather than standing alone.
    tray -= slab((parts_section(data) ^ solid) - keep, Z_CAV_PLATE, Z_PCB)
    for r in reliefs:
        x0, y0, x1, y1 = r["rect"]
        tray -= box(x0, y0, x1, y1, r["z"], Z_PCB)

    tray -= slab(plate, Z_OUT - 0.5, Z_RECESS)                        # the linker plate's recess

    # Put a wall back around that recess, and carry it up to the recess floor's own level. The cavity is
    # cut from z 1.10, above the recess floor at 2.37, so without this any cavity reaching the plate's edge
    # opens a hole straight into the recess -- C14 and C15 did exactly that. Running the ring from the
    # outer face to Z_CAV_PLATE also makes it the link between two things that would otherwise be islands:
    # it overlaps the 1.10 mm floor below it and the recess floor beside it, so the whole plate region,
    # pocket included, hangs off the tray proper instead of off its root at the joint edge.
    # Width is set by C3, the nearest part too tall to live under a wall, which leaves 1.18 mm.
    # The ring is as thick as the board allows, not one width everywhere. Only a part too tall to sit under
    # it -- over Z_PCB - Z_CAV_PLATE = 1.78 mm -- can push it back, and on this board only C3 and C11 do,
    # at 1.18 and 1.22 mm on the left; everything else stands 6.59 mm clear or more. So the ring is cut
    # wide and then given way to those two, which leaves it thick around most of the recess instead of
    # pinned to the thinnest case anywhere on the board.
    band = ((solid.offset(RECESS_WALL, JoinType.Miter, circular_segments=8) - solid)) ^ case_profile(sharp=True)
    tray += slab(band - parts_section(data, taller_than=Z_PCB - Z_CAV_PLATE), Z_OUT, Z_CAV_PLATE)

    # ...and carry it up to the board wherever nothing is in the way. Without this the ring stops at
    # Z_CAV_PLATE while the pocket wall starts at Z_RECESS, so the two only share 0.81 mm and the whole
    # linker block hangs off the case through that web -- the thin waist you get if you section it
    # sideways. Taking the band to Z_PCB where it can makes the shared height 2.58 mm instead.
    # Each part only pushes the band down as far as it actually needs. Cutting the whole column wherever
    # anything sat over it took a 0.45 mm resistor as seriously as a 2.80 mm capacitor.
    tray += slab(band, Z_CAV_PLATE, Z_PCB)
    for q in data["parts"]:
        if q["back"] or q["ref"] == "J1" or q["h"] <= 0:
            continue
        x0, y0, x1, y1 = q["court"]
        sec = (CrossSection.square((x1 - x0 + 2 * PART_GAP, y1 - y0 + 2 * PART_GAP), center=True)
               .translate(((x0 + x1) / 2, (y0 + y1) / 2))) ^ band
        if sec.area() <= 1e-6:
            continue
        tray -= slab(sec, Z_PCB - q["h"] - FRONT_GAP, Z_PCB + 0.1)

    # Posts for the board to rest on out in the open cavity, where the rim cannot reach.
    for px, py in support_posts(data):
        tray += slab(rounded(POST_D, POST_D, POST_D / 2 - 0.01, px, py), z_cav, Z_PCB)

    tray -= slab(pocket_section(), Z_RECESS, Z_PCB)                   # the plug's pocket
    tray -= usb_cut(data)

    # Last, so nothing puts material back into the rounded edge: the wall-facing face is the one that
    # sits against the panel, and a hard 90 degree arris there is both the first thing to chip and the
    # thing that makes a printed case look printed.
    for sec, z0, z1 in snap_bands(data, SNAP_H, slack=SNAP_SLACK):
        tray -= slab(sec, z0, z1)

    tray = fillet_face(tray, case_profile(), Z_OUT, EDGE_R, upward=True)
    return tray


def build_lid(data, z_seam, buttons):
    """The lid, with a stepped opening per button. The buttons themselves are separate parts."""
    lid = slab(case_profile(), z_seam, z_seam + LID_T)

    # The lip reaches all the way down to the board's back face, so closing the lid traps the board against
    # the tray's ledge. Stopping it short would leave the board loose by the whole height of the back parts.
    outer = board_profile(data, FIT - LIP_FIT)
    lid += slab(outer - outer.offset(-LID_LIP_W, JoinType.Miter, circular_segments=8),
                Z_PCB_BACK, z_seam)

    # Two diameters, not one. The cap passes through the outer part; the ridge cannot, and bears on the
    # step between them. Both are cut from the lid -- there is only 0.35 mm between the switch and the
    # lid's inner face, nothing like enough to hang a ridge in, so it lives inside the lid's own thickness.
    for b in buttons:
        shaft = rounded(b["w"] + 2 * BTN_FIT, b["l"] + 2 * BTN_FIT, BTN_R + BTN_FIT, b["x"], b["y"])
        bore = rounded(b["w"] + 2 * (FLANGE_W + BTN_FIT), b["l"] + 2 * (FLANGE_W + BTN_FIT),
                       BTN_R + FLANGE_W + BTN_FIT, b["x"], b["y"])
        lid -= slab(shaft, z_seam + CB_DEPTH, z_seam + LID_T + 1.0)
        lid -= slab(bore, z_seam - 1.0, z_seam + CB_DEPTH)

    # The room-facing face: this is the one anybody looking at the thing actually sees.
    for sec, z0, z1 in snap_bands(data, SNAP_H):
        lid += slab(sec, z0, z1)

    lid = fillet_face(lid, case_profile(), z_seam + LID_T, EDGE_R, upward=False)
    return lid


def build_buttons(z_seam, buttons):
    """The caps, printed separately and dropped into the lid from the inside before the board goes in.

    Each is a cap that stands proud of the lid, a ridge under it that cannot pass back out through the
    opening, and a boss sized to the switch's own plunger. The switch's spring holds the ridge up against
    the step; the board stops it falling the other way once assembled.
    """
    out = {}
    for b in buttons:
        cap = rounded(b["w"], b["l"], BTN_R, b["x"], b["y"])
        flange = rounded(b["w"] + 2 * FLANGE_W, b["l"] + 2 * FLANGE_W, BTN_R + FLANGE_W, b["x"], b["y"])
        bd = b["plunger"] - BOSS_MARGIN         # a boss wider than the plunger lands on the housing
        boss = rounded(bd, bd, bd / 2 - 0.01, b["x"], b["y"])
        top = z_seam + CB_DEPTH                 # the ridge sits against the step, pushed there by the switch
        part = (slab(cap, top, z_seam + LID_T + BTN_PROUD)
                + slab(flange, top - FLANGE_T, top)
                + slab(boss, b["top"] + BOSS_GAP, top - FLANGE_T))
        out[b["ref"]] = part
    return out


def assembled_board(data):
    """The populated board where it will sit in the case: front parts hanging down, back parts standing up.

    Bodies, not courtyards. A courtyard is the room an assembly machine wants around a part, not the space
    the part occupies, so checking the case against courtyards reports clashes that do not exist. The
    cavity is still cut to the courtyard, so the case gives away more room than it is checked against.
    """
    asm = slab(board_profile(data), Z_PCB, Z_PCB_BACK)
    for p in data["parts"]:
        if p["ref"] == "J1" or p["h"] <= 0 or not p.get("in_case", True):
            continue
        x0, y0, x1, y1 = p["body"]
        sec = CrossSection.square((x1 - x0, y1 - y0), center=True).translate(((x0 + x1) / 2, (y0 + y1) / 2))
        # Clipped to the board, because these envelopes are axis-aligned bounding boxes and a box corner
        # is not a part. U2's pads run along two edges of the module, so the corner of their bbox is
        # 0.317 mm past the sloped board edge in empty space -- the nearest real U2 pad is 1.013 mm
        # inside it. Unclipped, that phantom corner reads as a 0.0026 mm3 clash against the tray wall,
        # which the cavity cannot avoid because the cavity is itself clipped to the board outline.
        sec = sec ^ board_profile(data, FIT)
        asm += (slab(sec, Z_PCB_BACK, Z_PCB_BACK + p["h"]) if p["back"]
                else slab(sec, Z_PCB - p["h"], Z_PCB))
    return asm


def fit_check(data, tray, lid, caps=None, buttons=None, z_seam=None):
    """Nothing in the case may occupy the same space as anything on the board."""
    asm = assembled_board(data)
    print("\nFIT CHECK, case against the populated board")
    bad = False
    for part, name in ((tray, "tray"), (lid, "lid")):
        clash = part ^ asm
        v = clash.volume()
        if v < 1e-3:
            print(f"  {name:4s} clear")
            continue
        bad = True
        bb = clash.bounding_box()
        print(f"  {name:4s} CLASHES: {v:.2f} mm3 at x {bb[0]:.1f}..{bb[3]:.1f} "
              f"y {bb[1]:.1f}..{bb[4]:.1f} z {bb[2]:.2f}..{bb[5]:.2f}")
        for p in data["parts"]:
            if p["ref"] == "J1" or p["h"] <= 0 or not p.get("in_case", True):
                continue
            x0, y0, x1, y1 = p["body"]
            if x1 < bb[0] or x0 > bb[3] or y1 < bb[1] or y0 > bb[4]:
                continue
            sec = CrossSection.square((x1 - x0, y1 - y0), center=True).translate(((x0 + x1) / 2, (y0 + y1) / 2))
            one = slab(sec, Z_PCB_BACK, Z_PCB_BACK + p["h"]) if p["back"] else slab(sec, Z_PCB - p["h"], Z_PCB)
            if (part ^ one).volume() > 1e-3:
                print(f"         {p['ref']} ({p['value'][:20]}, {p['h']:.2f} mm): {(part ^ one).volume():.2f} mm3")

    # the caps have to be free of the lid, free of the board at rest, and still captive
    if caps:
        for b in buttons:
            cap = caps[b["ref"]]
            jam = (cap ^ lid).volume()
            hit = (cap ^ asm).volume()
            # Captivity is about engagement, not interference: the fit is a sliding one, so the cap never
            # intersects the lid at all. What matters is how much ridge is still under the step at full
            # press, and how far the ridge overhangs the opening it must not pass back through.
            engaged = CB_DEPTH - (BOSS_GAP + TRAVEL)
            overhang = FLANGE_W - BTN_FIT
            ok = jam < 1e-3 and hit < 1e-3 and engaged > 0.15
            print(f"  {b['ref']:4s} cap {'slides free' if jam < 1e-3 else f'JAMS in the lid ({jam:.2f} mm3)'}"
                  f"{'' if hit < 1e-3 else f', FOULS the board ({hit:.2f} mm3)'}"
                  f"; ridge overhangs the opening by {overhang:.2f} mm, still {engaged:.2f} mm "
                  f"into the step at full press")
            bad = bad or not ok
    return not bad


def write_stl(manifold, path):
    mesh = manifold.to_mesh()
    verts = np.asarray(mesh.vert_properties)[:, :3]
    tris = verts[np.asarray(mesh.tri_verts)]
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    with open(path, "wb") as fh:
        fh.write(b"Nanoleaf Shapes controller rev B".ljust(80, b" "))
        fh.write(struct.pack("<I", len(tris)))
        for a, t in zip(n, tris):
            fh.write(struct.pack("<12fH", *a, *t.ravel(), 0))
    print(f"  {path.name}: {len(tris)} triangles")


def main():
    data = json.loads((HERE / "parts.json").read_text())
    front = [p for p in data["parts"] if not p["back"]]
    back = [p for p in data["parts"] if p["back"] and p.get("in_case", True)]
    front_max = max(p["h"] for p in front)
    back_max = max(p["h"] for p in back)

    z_cav = Z_PCB - front_max - FRONT_GAP
    z_back_top = Z_PCB_BACK + back_max
    z_seam = z_back_top + BACK_GAP
    total = z_seam + LID_T

    users = [p for p in back if p["ref"] in ("SW3", "SW4", "SW6")]
    left = [p for p in users if p["x"] < CENTRE_X]
    right = [p for p in users if p["x"] >= CENTRE_X]
    buttons = []
    for group in (left, right):
        w, l = BTN_LARGE if len(group) == 1 else BTN_SMALL
        for p in group:
            buttons.append(dict(ref=p["ref"], x=p["x"], y=p["y"], w=w, l=l,
                                top=Z_PCB_BACK + p["h"], plunger=p["plunger"]))

    reliefs = reliefs_for(data)

    print("THICKNESS, from the wall-facing outer face")
    for z, what in ((Z_OUT, "outer face, wall-facing -- the plate recesses into this"),
                    (Z_RECESS, f"plate recess floor            PLATE_T {PLATE_T}"),
                    (z_cav, f"component cavity ceiling      {Z_PCB - z_cav:.2f} mm clear for a {front_max:.2f} mm part"),
                    (Z_PCB, f"board, front surface          + PLUG_H {PLUG_H} + TOP_GAP {TOP_GAP}"),
                    (Z_PCB_BACK, f"board, back surface           + BOARD_T {BOARD_T}"),
                    (z_back_top, f"tallest back part             + {back_max:.2f} ({max(back, key=lambda p: p['h'])['ref']})"),
                    (z_seam, f"lid inner face / seam         + BACK_GAP {BACK_GAP}"),
                    (total, f"lid outer face, room-facing   + LID_T {LID_T}")):
        print(f"  {z:6.2f}  {what}")
    print(f"  lid lip {LID_LIP_W:.2f} mm wide reaches down to {Z_PCB_BACK:.2f}, "
          f"clamping the board over {z_seam - Z_PCB_BACK:.2f} mm")
    print(f"\n  TOTAL CASE THICKNESS  {total:.2f} mm"
          f"   (+{BTN_PROUD:.2f} at the button pads, so {total + BTN_PROUD:.2f} over those)")
    print(f"  front floor is {z_cav:.2f} mm thick over the tall parts, {PLATE_FLOOR:.2f} under the plate recess")

    print(f"\nBUTTONS, printed separately and dropped into the lid from the inside")
    print(f"  cap stands {BTN_PROUD:.2f} mm proud; ridge {FLANGE_W:.2f} mm wide x {FLANGE_T:.2f} thick in a "
          f"{CB_DEPTH:.2f} mm counterbore, so {LID_T - CB_DEPTH:.2f} mm of lid is left to retain it")
    print(f"  travel: {BOSS_GAP:.2f} mm of free play, then the switch")
    for b in buttons:
        print(f"  {b['ref']}  cap {b['w']:.0f} x {b['l']:.0f} mm at ({b['x']:.2f}, {b['y']:.2f}), "
              f"opening {b['w'] + 2*BTN_FIT:.1f} x {b['l'] + 2*BTN_FIT:.1f}, "
              f"ridge {b['w'] + 2*FLANGE_W:.1f} x {b['l'] + 2*FLANGE_W:.1f}; "
              f"boss {b['plunger'] - BOSS_MARGIN:.2f} on a {b['plunger']:.2f} plunger")

    thin = [r for r in reliefs if r["floor"] < MIN_FLOOR]
    if reliefs:
        print(f"\nRELIEFS under the plate recess ({len(reliefs)} part(s) need the floor cut back):")
        for r in sorted(reliefs, key=lambda r: r["floor"]):
            note = "A HOLE, not a floor" if r["floor"] < MIN_FLOOR else "still a floor"
            print(f"     {r['ref']:4s} {r['h']:.2f} mm tall -> floor {r['floor']:5.2f} mm   {note}")
    if thin:
        print(f"   !! {', '.join(r['ref'] for r in thin)} break through. "
              f"Anything under {MIN_FLOOR:.2f} mm cannot be printed as a floor.")

    print("\nBUILDING")
    tray = build_tray(data, z_seam, z_cav, reliefs)
    lid = build_lid(data, z_seam, buttons)
    caps = build_buttons(z_seam, buttons)
    fit_check(data, tray, lid, caps, buttons, z_seam)
    print()
    for ref, part in caps.items():
        bb = part.bounding_box()
        print(f"  button_{ref}: {bb[3]-bb[0]:.1f} x {bb[4]-bb[1]:.1f} x {bb[5]-bb[2]:.2f} mm, "
              f"{len(part.decompose())} solid(s)")
        write_stl(part, HERE / f"button_{ref}.stl")

    for part, name in ((tray, "enclosure_tray"), (lid, "enclosure_lid")):
        bb = part.bounding_box()
        print(f"  {name}: {part.volume()/1000:.1f} cm3, "
              f"{bb[3]-bb[0]:.1f} x {bb[4]-bb[1]:.1f} x {bb[5]-bb[2]:.2f} mm, genus {part.genus()}")
        write_stl(part, HERE / f"{name}.stl")


if __name__ == "__main__":
    main()
