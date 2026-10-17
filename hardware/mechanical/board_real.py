#!/usr/bin/env python3
"""The real populated board, from KiCad's own 3D models, placed in the case's coordinates.

board_mock.py draws every part as a block of its bounding box, which is all a fit test needs and prints
without fuss. This is the other thing: `kicad-cli pcb export stl` walks the board and writes the actual
models, so the USB connector is a USB connector rather than a brick. Use it to look at the assembly, and
to check the case against what is really there instead of against the height table in export_parts.py.

KiCad writes the export in page coordinates with y and z pointing the other way: x matches, the board body
sits at z 0..BOARD_T with the front side up, and y comes out negated. Turning it a half turn about X and
lifting it by Z_PCB_BACK lands it exactly where the tray and the lid expect the board. That is a rotation,
not a mirror, so the winding survives it.

The export is ASCII and runs to about 28 MB; this rewrites it as binary, which is the same mesh in a fifth
of the space.

    /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli ...   (found automatically)
    python3 board_real.py
"""
import pathlib
import re
import struct
import subprocess
import sys

import numpy as np

from enclosure import BOARD_T, Z_PCB, Z_PCB_BACK

HERE = pathlib.Path(__file__).resolve().parent
PCB = HERE.parent / "nanoleaf_shapes.kicad_pcb"
OUT = HERE / "board_real.stl"
CLI = pathlib.Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")


def export(tmp, extra=()):
    cmd = [str(CLI), "pcb", "export", "stl", "--no-dnp", "--subst-models", "--force",
           *extra, "-o", str(tmp), str(PCB)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if not tmp.exists():
        sys.exit(f"kicad-cli failed:\n{r.stdout}\n{r.stderr}")
    return tmp


def read_ascii_stl(path):
    txt = path.read_text()
    v = np.array(re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", txt), dtype=np.float64)
    return v.reshape(-1, 3, 3)


def signed_volume(tris):
    """Six times the signed volume, by the divergence theorem. Negative means the normals face inwards."""
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def write_binary_stl(tris, path, header=b"rev B board, from KiCad's 3D models"):
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    rec = np.zeros((len(tris), 50), dtype=np.uint8)
    rec[:, 0:12] = n.astype(np.float32).view(np.uint8).reshape(-1, 12)
    rec[:, 12:48] = tris.astype(np.float32).view(np.uint8).reshape(-1, 36)
    with open(path, "wb") as f:
        f.write(header.ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        f.write(rec.tobytes())


def main():
    tmp = HERE / "_board_real_raw.stl"
    print(f"exporting {PCB.name} with its 3D models ...")
    export(tmp)
    tris = read_ascii_stl(tmp)
    raw = tris.reshape(-1, 3)
    print(f"  {len(tris)} triangles, as exported: "
          f"x {raw[:,0].min():.2f}..{raw[:,0].max():.2f}  "
          f"y {raw[:,1].min():.2f}..{raw[:,1].max():.2f}  z {raw[:,2].min():.2f}..{raw[:,2].max():.2f}")

    # Half a turn about X, then lift: (x, y, z) -> (x, -y, Z_PCB_BACK - z). diag(1, -1, -1) has
    # determinant +1, so this is a rotation and the winding carries through untouched. Reversing it
    # "to put it back" turns every normal inwards -- the volume comes out negative if you do.
    tris = tris * np.array([1.0, -1.0, -1.0]) + np.array([0.0, 0.0, Z_PCB_BACK])
    out = tris.reshape(-1, 3)
    print(f"  in the case's frame:            "
          f"x {out[:,0].min():.2f}..{out[:,0].max():.2f}  "
          f"y {out[:,1].min():.2f}..{out[:,1].max():.2f}  z {out[:,2].min():.2f}..{out[:,2].max():.2f}")
    print(f"  board should sit at z {Z_PCB:.2f}..{Z_PCB_BACK:.2f} ({BOARD_T:.2f} mm); "
           "front parts below it, back parts above")

    vol = signed_volume(tris)
    print(f"  signed volume {vol/1000:+.2f} cm3 -- positive means the normals point outwards")
    if vol < 0:
        sys.exit("normals are inverted; the transform is wrong")

    write_binary_stl(tris, OUT)
    tmp.unlink()
    print(f"\nwrote {OUT.name}: {OUT.stat().st_size/1e6:.1f} MB binary, "
          f"same frame as enclosure_tray.stl and enclosure_lid.stl")


if __name__ == "__main__":
    main()
