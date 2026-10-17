"""Build the JLCPCB and PCBWay BOM and placement files from the board.

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
        mechanical/make_fab_files.py

Run it from `hardware/`. It shells out to kicad-cli for the position export, then writes every file
twice, as .csv and .xlsx, into fab/jlcpcb/ and fab/pcbway/.

Three things here are corrections to JLCPCB's own library rather than to this board, so they go in the
JLCPCB files ONLY. The PCBWay files carry KiCad's values throughout.
"""
import collections
import csv
import pathlib
import re
import subprocess
import sys

import pcbnew

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import xlsx_writer

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
BOARD = ROOT / "nanoleaf_shapes.kicad_pcb"
OUT = ROOT / "fab"
CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"

# Rotation corrections, degrees counterclockwise, added to KiCad's angle. JLCPCB holds these parts at a
# different reference orientation than the footprint does, so a part that is correct on the board
# previews rotated on their side. Read off their placement preview -- U3/U4 are SOT-23-5 and preview
# correctly while Q1/Q2 in SOT-23 do not, so the package family is not uniformly wrong and this cannot
# be inferred from package names. Re-check the preview after any library change.
JLC_ROT = {"Q1": 180, "Q2": 180, "U5": -90, "U6": -90, "U2": 90}

# Placement offsets in mm, added to KiCad's coordinate. J3's KiCad coordinate is correct by the proper
# measure -- its F.Fab body outline runs y 61.180..68.580, centre 64.880, which is the origin exactly --
# but JLCPCB holds C165948 against a different origin and it previews low. +1.460 puts it on the
# centroid of all 22 pads. Do not derive these from geometry; measure them from a preview.
JLC_OFFSET = {"J3": (0.000, +1.460)}

# Footprint names stated JLCPCB's way. Same outline, different naming convention.
JLC_FOOTPRINT = {"U5": "SOP-16"}


def refsort(refs):
    return sorted(refs, key=lambda s: (re.sub(r"\d+$", "", s), int(re.search(r"\d+$", s).group())))


def emit(stem, rows):
    with open(str(stem) + ".csv", "w", newline="") as fh:
        csv.writer(fh).writerows(rows)
    xlsx_writer.write(str(stem) + ".xlsx", rows)


def main():
    board = pcbnew.LoadBoard(str(BOARD))
    meta = {}
    for fp in board.GetFootprints():
        d = {f.GetName(): f.GetText().strip() for f in fp.GetFields()}
        meta[fp.GetReference()] = dict(
            value=fp.GetValue().strip(),
            fpname=fp.GetFPIDAsString().split(":")[-1],
            excl=bool(fp.GetAttributes() & pcbnew.FP_EXCLUDE_FROM_BOM),
            lcsc=(d.get("JLCPCB") or d.get("LCSC Part") or "").strip(),
            mpn=d.get("MPN", "").strip(),
            mfr=d.get("Manufacturer", "").strip(),
            # From the pads, not the footprint's SMD attribute: half the easyeda2kicad footprints leave
            # that flag unset, which labelled every 1210 capacitor as through-hole.
            smd=not any(p.GetDrillSizeX() > 0 and p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH
                        for p in fp.Pads()),
        )

    posfile = OUT / "_pos.csv"
    OUT.mkdir(exist_ok=True)
    subprocess.run([CLI, "pcb", "export", "pos", "-o", str(posfile), "--format", "csv",
                    "--units", "mm", "--side", "both", str(BOARD)],
                   check=True, capture_output=True)
    pos = {r["Ref"]: r for r in csv.DictReader(open(posfile))}
    posfile.unlink()

    inbom = [r for r in sorted(meta) if not meta[r]["excl"]]

    # Group by the supplier code whenever there is one. Grouping on the footprint name split D1 from D5
    # -- the same SS210 drawn from two libraries -- and grouping on the value split SW1 from SW2, whose
    # values are RESET and BOOT. JLCPCB answered both with "multiple lines matched to the same part".
    groups = collections.OrderedDict()
    for r in inbom:
        m = meta[r]
        k = ("lcsc", m["lcsc"]) if m["lcsc"] else ("fp", m["value"], m["fpname"])
        groups.setdefault(k, []).append(r)

    def info(refs):
        m = meta[refs[0]]
        return m["value"], m["fpname"], m["lcsc"], m["mpn"], m["mfr"]

    (OUT / "jlcpcb").mkdir(exist_ok=True)
    (OUT / "pcbway").mkdir(exist_ok=True)

    # --- JLCPCB ---------------------------------------------------------
    # Their template verbatim. The header matters more than anything else: their importer reads the
    # part numbers ONLY when the column is called "JLCPCB Part #". Headed "LCSC Part #" it discarded
    # the whole column silently and auto-matched all 31 lines.
    rows = [["Comment", "Designator", "Footprint", "JLCPCB Part #"]]
    for refs in groups.values():
        val, fpn, lcsc, mpn, mfr = info(refs)
        rows.append([val, ",".join(refsort(refs)), JLC_FOOTPRINT.get(refs[0], fpn), lcsc])
    emit(OUT / "jlcpcb" / "bom_jlcpcb", rows)

    # Fallback for when the importer re-matches a line that already carries a code: no Footprint column
    # and the code repeated in Comment, so there is nothing to match on but the code.
    rows = [["Comment", "Designator", "JLCPCB Part #"]]
    for refs in groups.values():
        val, fpn, lcsc, mpn, mfr = info(refs)
        rows.append([lcsc or val, ",".join(refsort(refs)), lcsc])
    emit(OUT / "jlcpcb" / "bom_jlcpcb_codes_only", rows)

    # Formatted like JLCSMT_Sample_CPL1.xlsx: a literal "mm" suffix and a bare rotation.
    rows = [["Designator", "Mid X", "Mid Y", "Layer", "Rotation"]]
    for r in inbom:
        p = pos.get(r)
        if not p:
            continue
        rot = (float(p["Rot"]) + JLC_ROT.get(r, 0)) % 360
        dx, dy = JLC_OFFSET.get(r, (0.0, 0.0))
        rows.append([r, "%.4fmm" % (float(p["PosX"]) + dx), "%.4fmm" % (float(p["PosY"]) + dy),
                     "Top" if p["Side"] == "top" else "Bottom", "%g" % round(rot, 2)])
    emit(OUT / "jlcpcb" / "cpl_jlcpcb", rows)

    # --- PCBWay ---------------------------------------------------------
    rows = [["Item #", "Designator", "Qty", "Manufacturer Part Number", "Manufacturer",
             "Description / Value", "Package / Footprint", "Type", "Supplier",
             "Supplier Part Number", "Your Instructions / Notes"]]
    for i, refs in enumerate(groups.values(), 1):
        val, fpn, lcsc, mpn, mfr = info(refs)
        rows.append([i, ",".join(refsort(refs)), len(refs), mpn, mfr, val, fpn,
                     "SMD" if any(meta[r]["smd"] for r in refs) else "THT",
                     "LCSC" if lcsc else "", lcsc,
                     "" if (mpn or lcsc) else "NO PART NUMBER - please quote an equivalent"])
    emit(OUT / "pcbway" / "bom_pcbway", rows)

    rows = [["Designator", "Mid X", "Mid Y", "Layer", "Rotation"]]
    for r in inbom:
        p = pos.get(r)
        if not p:
            continue
        rows.append([r, "%.4f" % float(p["PosX"]), "%.4f" % float(p["PosY"]),
                     "Top" if p["Side"] == "top" else "Bottom", "%.2f" % (float(p["Rot"]) % 360)])
    emit(OUT / "pcbway" / "cpl_pcbway", rows)

    missing = [r for r in inbom if not meta[r]["lcsc"]]
    print("BOM lines: %d   placements: %d" % (len(groups), len(inbom)))
    print("excluded (not a component): %s" % ", ".join(r for r in sorted(meta) if meta[r]["excl"]))
    print("no supplier part number (%d): %s" % (len(missing), ", ".join(missing) or "-"))
    for ref, (dx, dy) in sorted(JLC_OFFSET.items()):
        print("JLCPCB offset:   %-3s %+.3f, %+.3f mm" % (ref, dx, dy))
    for ref, corr in sorted(JLC_ROT.items()):
        base = float(pos[ref]["Rot"]) % 360
        print("JLCPCB rotation: %-3s %6.1f -> %6.1f (%+d)" % (ref, base, (base + corr) % 360, corr))
    print("back-side parts: %s" % ", ".join(r for r in inbom if pos.get(r, {}).get("Side") == "bottom"))


main()
