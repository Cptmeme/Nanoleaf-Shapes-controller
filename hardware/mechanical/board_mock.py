#!/usr/bin/env python3
"""A printable stand-in for the assembled board, to test the case before the real one is ordered.

The outline, the linker slots and every part's footprint and height come from parts.json, so this is the
board as KiCad has it, not a guess. Parts are printed as plain blocks of their body
and height -- what the case has to clear is the envelope, not the shape. Bodies, not courtyards: a
courtyard is the room an assembly machine wants around a part, and taking it as the part makes J3 1.7 mm
wider than the connector really is, which the USB opening is quite rightly not cut for.

Parts stand on both faces, which cannot print in one piece without supporting one side in mid-air, so it
comes out as two halves split down the middle of the board, each with its own parts facing up. Glue them
back to back and the result is a 1.60 mm board with the right things standing off both sides. The same
split trick the linker pocket test used, and for the same reason.

It also writes the whole thing in one piece, `board_mock_full.stl`, placed in the CASE's own coordinates --
the same frame as enclosure_tray.stl and enclosure_lid.stl -- so loading all three together shows the
assembly. That one needs supports to print, which is exactly why the split pair exists.

The linker slots are cut through both halves, so a real rigid linker can be latched into the printed case
through the printed board, which is the main thing worth proving before the fab order goes out.

    pip install manifold3d numpy
    python3 board_mock.py
"""
import json
import math
import pathlib

from manifold3d import CrossSection, JoinType, Manifold

from enclosure import BOARD_T, Z_PCB, Z_PCB_BACK, chain_edges, poly, write_stl

HERE = pathlib.Path(__file__).resolve().parent
SHRINK = 0.10       # taken off every part all round, so a tight case is the case's fault and not the mock's
                    # (for parts whose library gives no usable body outline, parts.json falls back to the
                    #  courtyard, which overstates -- the safe direction for a fit test)
PIN_D, PIN_CLEAR = 3.0, 0.35      # dowel: a scrap of 3 mm filament
SOCKET_DEPTH = 0.60              # blind, so it never breaks through to the parts side of a 0.80 plate
MIN_BLOCK = 0.60    # parts thinner than this print as nothing useful, so they are floored to it


def part_block(p, half):
    x0, y0, x1, y1 = p["body"]
    h = max(p["h"], MIN_BLOCK)
    w, l = (x1 - x0) - 2 * SHRINK, (y1 - y0) - 2 * SHRINK
    if w <= 0.2 or l <= 0.2:
        return None
    sec = CrossSection.square((w, l), center=True).translate(((x0 + x1) / 2, (y0 + y1) / 2))
    return sec.extrude(h).translate((0, 0, half))


def main():
    data = json.loads((HERE / "parts.json").read_text())
    ring = chain_edges(data["edges"])
    board = poly(ring)
    half = BOARD_T / 2

    slots = []
    for sx0, sy0, sx1, sy1 in data["linker_slots"]:
        slots.append(CrossSection.square((sx1 - sx0, sy1 - sy0), center=True)
                     .translate(((sx0 + sx1) / 2, (sy0 + sy1) / 2)))

    # Registration: a blind socket in each glue face, for a scrap of 3 mm filament to dowel the halves.
    # A printed PIN cannot live here. Both halves print glue-face-down, so a pin on that face would have
    # to be printed into the bed; the old code put one on the front half's PARTS face instead, where it
    # stood among the components and could never meet anything. Sockets print fine -- they are just a gap
    # in the first few layers.
    # The two positions are symmetric about the board's centre line, so they map onto each other under the
    # mirror below and line up whichever half gets flipped.
    ys = [p[1] for p in ring]
    xs = [p[0] for p in ring]
    cx = (min(xs) + max(xs)) / 2
    pins = [(min(xs) + 8.0, (min(ys) + max(ys)) / 2),
            (max(xs) - 8.0, (min(ys) + max(ys)) / 2)]

    out = {}
    for side, name in ((False, "front"), (True, "back")):
        plate = board.extrude(half)
        parts = [part_block(p, half) for p in data["parts"]
                 if p["back"] == side and p["ref"] != "J1" and p["h"] > 0 and p.get("in_case", True)]
        solid = plate
        for blk in parts:
            if blk is not None:
                solid += blk
        for s in slots:
            solid -= s.extrude(BOARD_T + 20).translate((0, 0, -10))
        for px, py in pins:
            solid -= Manifold.cylinder(SOCKET_DEPTH + 0.1, PIN_D / 2 + PIN_CLEAR,
                                       circular_segments=48).translate((px, py, -0.1))
        out[name] = solid
        n = len([b for b in parts if b is not None])
        bb = solid.bounding_box()
        print(f"{name:5s}: {n} parts, {bb[5]-bb[2]:.2f} mm tall overall "
              f"({bb[5]-bb[2]-half:.2f} above the board's mid-plane)")

    # Both halves print parts-up with the glue face on the bed, so one of them has to be turned over to
    # mate the two glue faces -- and turning a part over is a 180 degree ROTATION, which mirrors x. So
    # exactly one half must be built pre-mirrored, or the glued board comes out with one side's parts
    # reflected. It has to be the front: the back half's parts already point the way they do in the case,
    # while the front's have to end up pointing the other way, and only the flipped half can do that.
    #
    # The outline is a trapezoid, symmetric left to right but not front to back, so the flip can only be
    # about the long axis -- which is the one that mirrors x -- and the outline itself tells you if you
    # have it the wrong way round.
    #
    # (The old code mirrored the BACK half in z instead. That left it parts-DOWN, needing supports under
    # the whole plate, and fixed nothing about the reflection.)
    out["front"] = out["front"].mirror((1, 0, 0)).translate((2 * cx, 0, 0))

    # and the whole board in one piece, where it sits in the case: front parts hanging towards the wall,
    # back parts standing towards the room
    whole = board.extrude(BOARD_T).translate((0, 0, Z_PCB))
    for p in data["parts"]:
        if p["ref"] == "J1" or p["h"] <= 0 or not p.get("in_case", True):
            continue
        x0, y0, x1, y1 = p["body"]
        w, l = (x1 - x0) - 2 * SHRINK, (y1 - y0) - 2 * SHRINK
        if w <= 0.2 or l <= 0.2:
            continue
        h = max(p["h"], MIN_BLOCK)
        sec = CrossSection.square((w, l), center=True).translate(((x0 + x1) / 2, (y0 + y1) / 2))
        whole += (sec.extrude(h).translate((0, 0, Z_PCB_BACK)) if p["back"]
                  else sec.extrude(h).translate((0, 0, Z_PCB - h)))
    for sl in slots:
        whole -= sl.extrude(BOARD_T + 20).translate((0, 0, Z_PCB - 10))
    out["full"] = whole
    bb = whole.bounding_box()
    print(f"full : every part, one piece, z {bb[2]:.2f}..{bb[5]:.2f} in the case's frame "
          f"(board front face at {Z_PCB:.2f})")

    for name, solid in out.items():
        write_stl(solid, HERE / f"board_mock_{name}.stl")
    print(f"\nPrint both halves as they are: flat face on the bed, parts up, no supports.")
    print(f"To assemble, turn the FRONT half over left-to-right and glue it onto the back half -- "
          f"{half:.2f} + {half:.2f} = {BOARD_T:.2f} mm, the fab's thickness.")
    print(f"The front half is built pre-mirrored so that flip lands its parts in the right place; the "
          f"trapezoid outline shows you if it is round the wrong way.")
    print(f"Sockets are {PIN_D + 2 * PIN_CLEAR:.1f} mm x {SOCKET_DEPTH:.2f} deep in both glue faces -- "
          f"dowel them with a {PIN_D:.0f} mm offcut of filament, or leave them empty and trust the outline.")


if __name__ == "__main__":
    main()
