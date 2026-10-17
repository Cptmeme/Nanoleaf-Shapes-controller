#!/usr/bin/env python3
"""Printable test piece for the rev B linker pocket.

A block with one pocket that a standard Nanoleaf rigid linker clicks into, with the geometry the enclosure will
use: a recess for the linker plate, like the panels have, and below it the pocket. The pocket floor stands in for
the PCB surface, where the plug's flat top lands, and the snap hooks catch in slots beside it (the real PCB gets
the same slots), under the overhanging pocket wall.

Writes the block in one piece and, again, split at the latch ledge. In one piece that ledge is a cantilever
reaching inward over the slot, so its inner corner -- the only surface the barb can catch on -- is the
droopiest point of an overhang, and no amount of undercut survives that. Split, the same face prints as a first
layer. Both halves print as they come, bottom on the bed, and stack on the registration pins. The pins only
stop the halves sliding; what registers them is their outer faces, the same 26 x 24 block on both, so line
those up by feel and keep the pins loose.

Push one end of a real linker in: it should click in, hold, and sit flush with the top face, with the plug's
top (almost) touching the floor. How hard it grips is BARB_OUT - CLEAR and nothing else -- the slot only has to
stay clear of the barb -- so pass a tighter clearance to print a variant:

    pip install manifold3d numpy
    python pocket_test.py          # pocket_test{,_lower,_upper}.stl at the CLEAR below
    python pocket_test.py 0.10     # the same three as *_c010.stl, gripping 0.10 mm deeper
"""
import pathlib
import struct
import sys

import numpy as np
from manifold3d import CrossSection, JoinType, Manifold

from linker import (BARB_OUT, HOOK_TIP, PLATE_HALF_L, PLATE_R, PLATE_T, PLATE_W, PLUG_H, PLUG_L, PLUG_R, PLUG_W,
                    SLOT_IN, SLOT_OUT, SLOT_Y, WALL_TO_JOINT)

# Print fit
CLEAR = 0.20            # pocket clearance per side
TOP_GAP = 0.10          # plug top to PCB surface: "almost touching"
HOLE_CLEAR = 0.30       # extra room around the hooks and locating posts in the PCB slots

BLOCK = (26.0, 24.0, 8.0)   # test piece size: across, along (y = 0 is the joint edge), height

# Registration pins for the split version, in the solid corners clear of both the plate recess and the slots
PINS = ((10.4, 4.6), (-10.4, 19.4))
PIN_D, PIN_H, PIN_CLEAR = 3.0, 2.6, 0.35   # 0.15 on the radius was too tight to assemble on FDM
PIN_TAPER = 0.35        # tip narrower than the base, so the pin finds the hole


def rounded_box(width, length, radius, height):
    """Rounded rectangle centred on x = y = 0, extruded from z = 0 up."""
    core = CrossSection.square((width - 2 * radius, length - 2 * radius), center=True)
    return core.offset(radius, JoinType.Round, circular_segments=64).extrude(height)


def box(x0, x1, y0, y1, z0, z1):
    return Manifold.cube((x1 - x0, y1 - y0, z1 - z0)).translate((x0, y0, z0))


def build(clear=CLEAR):
    bx, by, bz = BLOCK
    recess = bz - PLATE_T                    # where the plate's inner face rests; the plate's back is then flush
    floor = recess - (PLUG_H + TOP_GAP)      # PCB surface, and the plane the latch ledge lies in
    piece = box(-bx / 2, bx / 2, 0, by, 0, bz)

    # Plate recess, open towards the joint edge (the other half of the plate lies on the panel)
    plate = rounded_box(PLATE_W + 2 * clear, 2 * (PLATE_HALF_L + clear), PLATE_R + clear, PLATE_T + 1)
    piece -= plate.translate((0, 0, recess))

    pocket = rounded_box(PLUG_W + 2 * clear, PLUG_L + 2 * clear, PLUG_R + clear, recess - floor + 1)
    piece -= pocket.translate((0, WALL_TO_JOINT + PLUG_L / 2, floor))

    # The slots in the PCB: along the whole plug, so the plain locating posts drop in as well as the hooks.
    # From inside the hook's inner face to well past the barb, below the PCB surface, so the barb has room to
    # spring its full travel and snap under the pocket wall
    y0, y1 = WALL_TO_JOINT + SLOT_Y[0] - HOLE_CLEAR, WALL_TO_JOINT + SLOT_Y[1] + HOLE_CLEAR
    inner, outer = PLUG_W / 2 - SLOT_IN - HOLE_CLEAR, PLUG_W / 2 + SLOT_OUT + HOLE_CLEAR
    bottom = recess - (HOOK_TIP + 0.40)
    for side in (-1, 1):
        x0, x1 = sorted((side * inner, side * outer))
        piece -= box(x0, x1, y0, y1, bottom, floor + 0.01)

    print(f"plate recess {PLATE_W + 2 * clear:.2f} mm wide, {PLATE_T:.2f} mm deep; pocket {PLUG_W + 2 * clear:.2f} x "
          f"{PLUG_L + 2 * clear:.2f} mm, floor (PCB surface) {bz - floor:.2f} mm below the top, starting "
          f"{WALL_TO_JOINT - clear:.2f} mm from the joint edge")
    print(f"slots {outer - inner:.2f} x {y1 - y0:.2f} mm, {floor - bottom:.2f} mm deep below the floor; "
          f"barb free to x = {outer:.2f} past a pocket wall at {PLUG_W / 2 + clear:.2f}")
    print(f"ledge grip {BARB_OUT - clear:.2f} mm at the modelled BARB_OUT = {BARB_OUT:.2f}")
    return piece, floor


def split(piece, floor):
    """The same block cut at the ledge plane, pinned together, so the ledge prints as a first layer."""
    bx, by, bz = BLOCK
    lower = piece - box(-bx, bx, -1, by + 1, floor, bz + 1)
    upper = piece - box(-bx, bx, -1, by + 1, -1, floor)
    for x, y in PINS:
        pin = Manifold.cylinder(PIN_H, PIN_D / 2, PIN_D / 2 - PIN_TAPER,
                                circular_segments=48).translate((x, y, floor))
        lower += pin
        upper -= Manifold.cylinder(PIN_H + 0.2, PIN_D / 2 + PIN_CLEAR,
                                   circular_segments=48).translate((x, y, floor))
    print(f"split at {floor:.2f}: lower {floor:.2f} mm thick, upper {bz - floor:.2f} mm, on {PIN_D:.1f} mm pins")
    return lower, upper


def write_stl(manifold, path):
    mesh = manifold.to_mesh()
    verts = np.asarray(mesh.vert_properties)[:, :3]
    tris = verts[np.asarray(mesh.tri_verts)]
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12
    with open(path, "wb") as f:
        f.write(b"rev B linker pocket test".ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        for n, t in zip(normals, tris):
            f.write(struct.pack("<12fH", *n, *t.ravel(), 0))
    print(f"{path.name}: {len(tris)} triangles")


if __name__ == "__main__":
    clear = float(sys.argv[1]) if len(sys.argv) > 1 else CLEAR
    tag = "" if clear == CLEAR else f"_c{round(clear * 100):03d}"
    here = pathlib.Path(__file__).parent
    piece, floor = build(clear)
    write_stl(piece, here / f"pocket_test{tag}.stl")
    for part, half in zip(("lower", "upper"), split(piece, floor)):
        write_stl(half, here / f"pocket_test_{part}{tag}.stl")
