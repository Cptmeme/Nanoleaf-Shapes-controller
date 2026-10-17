#!/usr/bin/env python3
"""Writes the KiCad footprint for the linker contact pads: ../nanoleaf.pretty/Nanoleaf_Linker_Pads.kicad_mod.

Seen from the pad side with the joint (the board edge that meets the panel) at the top, the pads are DATA, GND,
42 V from left to right. That matches the panels: seen from their back with the joint at the bottom, 42 V is on
the left, and the linker crosses the two outer contacts over.

The footprint origin is the centre of the pads; the joint is at y = -PAD_CENTRE. It also cuts the two holes
for the linker's snap hooks (Edge.Cuts), as the panels' own PCBs have them. The courtyard covers the pocket plus
the printed pocket walls that rest on the board, so nothing else goes there on the pad side.

    python linker_footprint.py
"""
import pathlib
import uuid

from linker import (PAD_CENTRE, PAD_L, PAD_PITCH, PAD_W, PLATE_HALF_L, PLATE_W, PLUG_L, PLUG_W, SLOT_IN,
                    SLOT_OUT, SLOT_Y, WALL_TO_JOINT)

HOLE_CLEAR = 0.30       # room around the hooks and locating posts in the milled slots
POCKET_CLEAR = 0.20     # enclosure pocket clearance per side (as in pocket_test.py)
WALL = 1.60             # printed pocket wall resting on the board, around the pocket

JOINT_Y = -PAD_CENTRE


def y_from_joint(distance):
    return JOINT_Y + distance


def uid():
    return f'(uuid "{uuid.uuid4()}")'


def rect(x0, y0, x1, y1, layer, width):
    return (f'\t(fp_rect (start {x0:.3f} {y0:.3f}) (end {x1:.3f} {y1:.3f}) '
            f'(stroke (width {width}) (type solid)) (fill no) (layer "{layer}") {uid()})')


def line(x0, y0, x1, y1, layer, width):
    return (f'\t(fp_line (start {x0:.3f} {y0:.3f}) (end {x1:.3f} {y1:.3f}) '
            f'(stroke (width {width}) (type solid)) (layer "{layer}") {uid()})')


def text(kind, value, x, y, layer, size=1.0, hide=False):
    head = f'(property "{kind}" "{value}"' if kind in ("Reference", "Value") else f'(fp_text user "{value}"'
    return (f'\t{head} (at {x:.3f} {y:.3f} 0) (layer "{layer}"){" (hide yes)" if hide else ""} {uid()} '
            f'(effects (font (size {size} {size}) (thickness {size * 0.15:.3f}))))')


def build():
    out = [
        '(footprint "Nanoleaf_Linker_Pads"',
        '\t(version 20260206)',
        '\t(generator "linker_footprint.py")',
        '\t(layer "F.Cu")',
        '\t(descr "Contact pads for a Nanoleaf Shapes linker. 1 = 42 V, 2 = GND, 3 = DATA. From the pad side with the '
        'joint at the top, 42 V is on the right. Includes the linker slots. ENIG finish, no paste")',
        '\t(tags "nanoleaf shapes linker edge connector")',
        text("Reference", "J1", 0, PAD_L / 2 + 2.0, "F.SilkS", size=0.8),
        text("Value", "Nanoleaf_Linker_Pads", 0, y_from_joint(PLATE_HALF_L) + 1.2, "F.Fab"),
        '\t(attr smd)',
    ]

    # Pads: no paste layer, so no solder ends up on the contact surface
    for number, x in (("1", PAD_PITCH), ("2", 0.0), ("3", -PAD_PITCH)):
        out.append(f'\t(pad "{number}" smd rect (at {x:.3f} 0) (size {PAD_W:.3f} {PAD_L:.3f}) '
                   f'(layers "F.Cu" "F.Mask") {uid()})')
    for label, x in (("42V", PAD_PITCH), ("GND", 0.0), ("DATA", -PAD_PITCH)):
        out.append(text("user", label, x, PAD_L / 2 + 0.9, "F.SilkS", size=0.6))

    # Slots beside the pads: they clear the snap hooks and the plain locating posts, so they run the plug's
    # whole length, as on the panels' own PCBs
    y0 = y_from_joint(WALL_TO_JOINT + SLOT_Y[0] - HOLE_CLEAR)
    y1 = y_from_joint(WALL_TO_JOINT + SLOT_Y[1] + HOLE_CLEAR)
    inner, outer = PLUG_W / 2 - SLOT_IN - HOLE_CLEAR, PLUG_W / 2 + SLOT_OUT + HOLE_CLEAR
    for side in (-1, 1):
        out.append(rect(side * inner, y0, side * outer, y1, "Edge.Cuts", 0.05))

    # Fabrication drawing: plug, linker plate, joint
    out.append(rect(-PLUG_W / 2, y_from_joint(WALL_TO_JOINT), PLUG_W / 2, y_from_joint(WALL_TO_JOINT + PLUG_L),
                    "F.Fab", 0.1))
    out.append(rect(-PLATE_W / 2, JOINT_Y, PLATE_W / 2, y_from_joint(PLATE_HALF_L), "F.Fab", 0.1))
    out.append(line(-PLATE_W / 2 - 2, JOINT_Y, PLATE_W / 2 + 2, JOINT_Y, "F.Fab", 0.15))
    out.append(text("user", "joint (panel side)", 0, JOINT_Y - 0.6, "F.Fab", size=0.6))

    # Courtyard: pocket with clearance, plus the printed walls
    reach = PLUG_W / 2 + POCKET_CLEAR + WALL
    out.append(rect(-reach, y_from_joint(WALL_TO_JOINT - POCKET_CLEAR - WALL), reach,
                    y_from_joint(WALL_TO_JOINT + PLUG_L + POCKET_CLEAR + WALL), "F.CrtYd", 0.05))
    out.append(')')
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    lib = pathlib.Path(__file__).resolve().parent.parent / "nanoleaf.pretty"
    lib.mkdir(exist_ok=True)
    path = lib / "Nanoleaf_Linker_Pads.kicad_mod"
    path.write_text(build())
    print(f"wrote {path}")
