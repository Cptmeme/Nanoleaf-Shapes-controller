# Case v1 — the known-good enclosure, kept as a fallback

Snapshot taken 2026-10-13, before adding rounded outer edges and a snap fit to the lid.

This is the version that was fully verified against the board:

- **10.00 mm** total thickness, 11.00 mm across a button pad
- **0 reliefs** under the plate recess and **0.00 mm²** of front-part intrusion into the 150.55 mm²
  brace band, so the linker pocket is solid the whole way round
- Fit check clear on tray, lid and all three caps, and clear again against `board_real.stl`, which is
  built from the actual KiCad 3D models; the only intersection left is SW1/SW2, desoldered before the
  case goes on
- Tray a single solid, genus 2

`parts.json` is included because the geometry is derived from it — the same `enclosure.py` against a
different board gives a different case. To go back to this version, copy the `.py` files and
`parts.json` up one level and re-run `enclosure.py`.
