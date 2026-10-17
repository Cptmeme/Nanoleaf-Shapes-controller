"""Give SW3/SW4/SW6 a 3D model, because KiCad ships the TS-1187A footprint without one.

`Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A` points its model at
`${KICAD10_3DMODEL_DIR}/Button_Switch_SMD.3dshapes/SW_Push_1P1T_XKB_TS-1187A.step`, and that file does not
exist in this KiCad install -- only the .kicad_mod does. So the three user buttons were simply absent from
`board_real.stl`: a fit check against the real models had nothing to check at the one place it matters
most, under the three button caps.

easyeda2kicad has the part as C318884 (`SW-SMD_4P-L5.1-W5.1-P3.70-LS6.5-TL_H1.5`, 5.1 x 5.1 x 1.5 mm, which
agrees with the 1.50 mm in export_parts.py's height table), so this borrows that model and leaves the
footprint alone. No pad, net or track is touched.

The two footprints share an origin -- the easyeda2kicad pads sit at (+-3.00, +-1.85) against KiCad's
(+-3.000, +-1.875) -- so the model needs no offset or rotation. The 0.025 mm disagreement in y is the
footprints', not the model's, and is below anything that matters here.

Note: this lives on the BOARD, not in the library, since the library is KiCad's own. "Update footprints
from symbols" will drop it again -- re-run this script if that happens.
"""
import datetime
import sys

import pcbnew

BOARD = sys.argv[1] if len(sys.argv) > 1 else "../nanoleaf_shapes.kicad_pcb"
REFS = ("SW3", "SW4", "SW6")
MODEL = "${EASYEDA2KICAD}/easyeda2kicad.3dshapes/SW-SMD_4P-L5.1-W5.1-P3.70-LS6.5-TL_H1.5.wrl"


def main(place):
    board = pcbnew.LoadBoard(BOARD)
    todo = []
    for fp in board.GetFootprints():
        if fp.GetReference() not in REFS:
            continue
        have = [m.m_Filename for m in fp.Models()]
        todo.append((fp, have))
        print("%-4s %-44s current model(s): %s" % (fp.GetReference(), fp.GetFPIDAsString(),
                                                   ", ".join(have) or "none"))
    if len(todo) != len(REFS):
        sys.exit("expected %d footprints, found %d" % (len(REFS), len(todo)))
    if not place:
        print("\ndry run -- nothing written. Re-run with --place to apply.")
        return

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup = BOARD.replace(".kicad_pcb", "-%s-pre-swmodel.kicad_pcb" % stamp)
    pcbnew.SaveBoard(backup, board)
    print("\nbackup -> %s" % backup)

    n_tracks = len(list(board.GetTracks()))
    n_fps = len(board.GetFootprints())
    for fp, _ in todo:
        fp.Models().clear()
        m = pcbnew.FP_3DMODEL()
        m.m_Filename = MODEL
        m.m_Show = True
        m.m_Opacity = 1.0
        fp.Models().push_back(m)
        print("%-4s -> %s" % (fp.GetReference(), MODEL.rsplit("/", 1)[-1]))
    assert len(list(board.GetTracks())) == n_tracks, "tracks changed"
    assert len(board.GetFootprints()) == n_fps, "footprints changed"
    pcbnew.SaveBoard(BOARD, board)
    print("saved %s" % BOARD)


main("--place" in sys.argv)
