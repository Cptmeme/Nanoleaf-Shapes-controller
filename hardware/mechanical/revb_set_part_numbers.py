"""Fill in the supplier part numbers JLCPCB could not match on its own.

JLCPCB auto-matches a BOM line from its Comment and Footprint when no code is given, and it got 11 of
the 13 blanks right by itself. Two it could not: J3, because "USB_C_Receptacle_USB2.0_16P" names a
generic footprint rather than a part, and SW3/SW4/SW6, because "USER BUTTON" says nothing at all.

Both codes were already known and just never reached the footprint fields:

  * J3        C165948   HRO TYPE-C-31-M-12       -- hardware/rev-b/README.md, where the schematic was written up
  * SW3/4/6   C318884   XKB TS-1187A-B-A-B       -- the easyeda2kicad symbol's own LCSC link

MPN and Manufacturer go in as well, which the JLCPCB BOM ignores but the PCBWay one has columns for.
"""
import datetime
import sys

import pcbnew

BOARD = sys.argv[1] if len(sys.argv) > 1 else "nanoleaf_shapes.kicad_pcb"
# Every line JLCPCB had to guess at is pinned here, so the BOM stops depending on their auto-matcher.
# Leaving a code blank is not neutral: JLCPCB matches on Comment + Footprint, then raises "the comment
# (100k) does not match the one (0402WGF1003TCE) provided in your BOM" on every line it guessed, which
# is what the first upload came back with. The codes below are JLCPCB's own matches from that upload,
# except U5.
PARTS = {
    "J3":  ("C165948",   "TYPE-C-31-M-12", "Korean Hroparts Elec"),
    "SW3": ("C318884",   "TS-1187A-B-A-B", "XKB Enterprise"),
    "SW4": ("C318884",   "TS-1187A-B-A-B", "XKB Enterprise"),
    "SW6": ("C318884",   "TS-1187A-B-A-B", "XKB Enterprise"),
    # pinned from JLCPCB's own matches on the first upload
    "D1":  ("C14996",    "SS210",          "MDD"),
    "D5":  ("C14996",    "SS210",          "MDD"),
    "D3":  ("C41376401", "SMAJ48A",        "LRC"),
    "D4":  ("C2290",     "KT-0603W",       "Hubei KENTO Elec"),
    "Q1":  ("C7420353",  "MMBT3904",       "Jiangsu Changjing"),
    "Q2":  ("C7420353",  "MMBT3904",       "Jiangsu Changjing"),
    "R11": ("C25905",    "0402WGF5101TCE", "UNI-ROYAL"),
    "R12": ("C25905",    "0402WGF5101TCE", "UNI-ROYAL"),
    "R15": ("C25741",    "0402WGF1003TCE", "UNI-ROYAL"),
    "U6":  ("C2827654",  "USBLC6-2SC6",    "Hgsemi"),
    # U5: JLCPCB auto-matched C7464026 and came back "4 shortfall". C84681 is the WCH original, an
    # Extended part JLCPCB stocks in quantity. It was in the project notes all along and simply never
    # reached the footprint field, which is why the matcher was left to pick for itself.
    "U5":  ("C84681",    "CH340C",         "WCH(Jiangsu Qin Heng)"),
    # The board has always been built with a DOIT ESPC5-12 (ESP32-C5) in the WT0132C6-S5 footprint --
    # same 16 x 24 mm ESP-12F pad layout, different module. The BOM said WT0132C6-S5, which JLCPCB
    # matched to C9900241604 and then reported "5 shortfall". C52139916 is the part actually fitted
    # (JLCPCB lists it twice, C52139916 and C52139917 -- confirm the flash size matches the 4 MB the
    # firmware partition table assumes before ordering).
    "U2":  ("C52139916", "ESPC5-12",       "DOIT"),   # C52139917 is the same module, dearer
}

# Footprint Value text to correct at the same time. U2's Value is hidden and lives on F.Fab, so this
# changes no plotted layer -- it only stops the BOM Comment claiming a part that is not fitted.
VALUES = {"U2": "ESPC5-12"}


def main(place):
    board = pcbnew.LoadBoard(BOARD)
    todo = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref not in PARTS:
            continue
        have = {fl.GetName(): fl.GetText().strip() for fl in fp.GetFields()}
        todo.append((fp, have))
        print("%-4s %-24s JLCPCB %r -> %r" % (ref, fp.GetValue()[:24],
                                              have.get("JLCPCB", ""), PARTS[ref][0]))
    missing = set(PARTS) - {fp.GetReference() for fp, _ in todo}
    if missing:
        sys.exit("not on the board: %s" % ", ".join(sorted(missing)))
    if not place:
        print("\ndry run -- nothing written. Re-run with --place to apply.")
        return

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup = BOARD.replace(".kicad_pcb", "-%s-pre-partnos.kicad_pcb" % stamp)
    pcbnew.SaveBoard(backup, board)
    print("\nbackup -> %s" % backup)

    n_tracks, n_fps = len(list(board.GetTracks())), len(board.GetFootprints())
    for fp, _ in todo:
        code, mpn, mfr = PARTS[fp.GetReference()]
        if fp.GetReference() in VALUES:
            fp.SetValue(VALUES[fp.GetReference()])
        for name, value in (("JLCPCB", code), ("MPN", mpn), ("Manufacturer", mfr),
                            ("LCSC Part", code)):
            fp.SetField(name, value)      # creates the field if it is not there yet
            fp.GetField(name).SetVisible(False)
    assert len(list(board.GetTracks())) == n_tracks, "tracks changed"
    assert len(board.GetFootprints()) == n_fps, "footprints changed"
    pcbnew.SaveBoard(BOARD, board)
    print("saved %s -- copper untouched" % BOARD)


main("--place" in sys.argv)
