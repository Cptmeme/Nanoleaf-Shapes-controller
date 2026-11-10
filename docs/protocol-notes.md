# Panel bus notes

Observations of the Nanoleaf Shapes panel bus measured with this board, kept as the raw record. They were
merged into [LeafBus PROTOCOL.md](https://github.com/MyrikLD/LeafBus/blob/main/PROTOCOL.md) in September
2026 and are credited inline there, so that document is now the reference for all of it.

**§ always means a section of PROTOCOL.md**, never of these notes. Its numbering is unchanged by the
merge and every reference below still resolves. Where these notes point at themselves they say "section
N" in words, because both documents now have a section 4, 7 and 8.

**Test setup:**
- **Hardware:** one assembly of 9 Mini Triangles (NL48) with the stock power supply, driven by the rev A
  interface board (ESP32-C5, buffered single-wire bus). Section 9 adds a single Hexagon on the rev B
  board, which is the same bus interface on a board that clips to a panel edge directly.
- **Layouts tested:**
  - a straight chain, with the board at either end;
  - a fork, with the board on a middle panel;
  - a ring of six panels with three more attached.
- **Hexagons (NL42):** one panel driven on hardware on 2026-11-10 -- enumeration, colour and touch all
  confirmed, and section 9 is measured on it. The layout parser had already been checked against a
  published hexagon capture, see section 8.
- **Not tested on hardware:** Triangles (NL47).

## 1. The bulk-pull reply comes in layout order (merged into §5.3)

§5.3 used to say that a panel's index is the same in the bulk push (`E0`) and the bulk pull (`C0`). On
these panels it is not, and §5.3 now carries the corrected table. What was measured here:

| Frame | Order | Index 0 is… |
|---|---|---|
| `E0` bulk push chunks | reverse layout-string order | the panel farthest down the string |
| `C0` bulk pull pairs | **layout-string order** | the panel the controller is plugged into |

**Evidence:**
- **Push order:** lighting layout position 0 lit the panel next to the controller, and the last position lit
  the far end. This matches §5.3.
- **Pull order:** touching the panel next to the controller changed the **first** pair of the `C0` reply, and
  touching the far panel changed the **last** pair.
- **Repeats:** the result held after a full power cycle, and with the controller moved to the other end of the
  chain.
- **Branches:** with the controller on a middle panel (a fork), every panel matched its layout-string
  position. With breadth-first order, positions on the two branches would have swapped. So the pull order is
  exactly the depth-first order of the layout string.

## 2. Status bit `0x20` on the power-supply panel

The first byte of each `C0` pair has more states than §6.3 lists:

| Value | Seen when |
|---|---|
| `00` | idle |
| `10` | first poll after enumeration, **and the first poll after a touch is released** |
| `11`..`1F` | touch. The low nibble is a **magnitude**, not a gesture -- see section 9 |
| `20` | **idle, on the panel the power supply is plugged into** |
| `32`, `37` → `30` → `20` | touch → release → idle on that same panel |

- **`0x20` is a separate bit.** It's ORed with the touch codes rather than replacing them, so test for a touch
  as `(status & 0x10) && (status & 0x0F)`. A check on the whole high nibble misses touches on that panel.
- **It follows the power supply's panel.** With the controller moved, it stayed on that panel (now position
  0). That panel was also where the stock controller used to be plugged in, so "power supply attached" and
  "this particular panel" can't be told apart yet. Moving the supply to another panel would settle it.
- **It isn't always there.** It appeared after the panels powered up, and was absent after the controller
  rebooted and re-enumerated while the panels stayed powered.

## 3. Hot-plug marker after the controller restarts

When the controller restarts while the panels stay powered, the first enumeration afterwards is followed by
`C0` replies with a trailing `CC` (§8), in place of the pair of one panel. A second `00` + `80` clears it. A
controller should therefore re-enumerate whenever `CC` appears, which also covers this case.

## 4. Rings

- **The panels break loops themselves.** A ring of six panels plus three attached ones enumerated as 9
  panels, each listed once, with the same string on four consecutive enumerations. The panel-to-position
  mapping stayed correct.
- **The dropped link was marked once.** On one enumeration, one end of the dropped ring link had `05` instead
  of `04` as its first separator. Bit 0 matches "connector root + 1", using the rule §7.3 gives for
  six-connector panels (bit k−1 ↔ connector root + k). The geometry places that connector exactly on the
  other end's free connector.
- **That mark isn't reliable.** A later enumeration of the same ring showed a plain `04`.

## 5. Geometry lattice

With the §7.6 formulas, every panel centre lies on a lattice of **side/4 × side/(2√3) = 16.75 × 19.341 mm**,
whether it's a mini triangle (either orientation), a large triangle or a hexagon. This holds for layout
rotations in steps of 60°, and it gives exact integer grid coordinates, which are useful for mapping
assemblies onto LED matrices. With square cells the spacing ratio (√3) forces rounding, and neighbours end up
unevenly spaced.

The formulas reproduced the physical ring exactly: the connectors of the two panels joined by the dropped link
land on the same point (0.00 mm apart).

## 6. Electrical and timing

- **Idle level:** the panels hold DATA high when the bus is idle, so no extra pull-up is needed with Shapes
  panels. Without a panel attached, the bus side of the interface floats, so the first frame after an idle
  period can fail the echo check.
- **Unenumerated probing:** an unenumerated panel probes the controller's connector with `C0` every 50.0 ms,
  as §4.3 describes for empty connectors.
- **Reply time:** a `C0` reply for 9 panels starts about 1 ms after the poll.
- **Frame rate:** colour frames at up to 40 per second, with `C0` polling every 50 ms, run without dropouts.

## 7. Recorded layout strings

| Layout | Layout string |
|---|---|
| Chain, controller at one end | `B0 B1 04 B1 B0 B2 04 B0 04 B1 B0 B2 95 04 04 04 04 04 04 40` |
| Same chain, controller at the power-supply end | `B1 B1 04 B2 04 B2 B1 B1 04 B2 04 B0 B1 04 04 04 04 04 95 40` |
| Controller on a middle panel (fork) | `B0 B0 04 B1 B0 B2 95 04 04 04 04 B1 04 B2 04 B0 B1 04 04 40` |
| Ring of six plus three | `B0 B0 B1 04 04 B0 95 04 04 B1 B1 B0 05 04 04 B2 04 B0 04 40` |

## 8. The parser checked against someone else's hexagons

Everything above comes from 9 Mini Triangles, so the layout parser had never seen a 6-connector panel.
Christian Panton's [part 1.5](https://christian.panton.org/posts/nanoleaf-ctrl-pt1-5/) publishes a hexagon
capture with a verified decode, which makes a free test vector:

    e5 00 e1 00 01 00 00 e4 00 01 00 00 01 95 00 e5 00 01 00 95 00 00

He decodes it as **4 hexagons and 2 power supplies**. `parse_node()` in `firmware/main/panelbus.c`, run on
those bytes unchanged, gives the same:

| Panel | Node | Connectors | Parent-facing edge | Parent | Type |
|---|---|---|---|---|---|
| 0 | `E5` | 6 | 5 | root | Hexagon |
| 1 | `E1` | 6 | 1 | 0 | Hexagon |
| 2 | `E4` | 6 | 4 | 1 | Hexagon |
| 3 | `E5` | 6 | 5 | 0 | Hexagon |

All 22 bytes consumed, nothing left over, 2 power supplies found. The four mini-triangle strings in section 7 still
parse to 9 panels and 1 PSU each, so nothing regressed.

Two things worth recording:

- **The node byte is `0x80 | (connectors << 4) | parent_edge`.** Our `(b >> 4) & 7` and `b & 7` already
  implement this. The post describes the upper nibble as "the number of edges", which cannot be read
  literally -- hexagons are `0xE_`, not `0x6_` -- and our mini triangles at `0xB0..0xB2` are the second data
  point that pins the form down. He had only hexagons and says the other shapes are unconfirmed.
- **The shape byte is confirmed on the wire.** He reads `01` hexagon / `02` large triangle / `03` Apex
  hexagon out of the firmware but says he could not confirm it from captures. `panel_type()` already keys on
  `sep[1] & 7` with `1 = Hexagon, 2 = Triangle, 3 = Elements`, and on his capture that returns Hexagon for
  all four, which is right. Only the name for `3` is in question -- "Elements" here against his "Apex
  hexagon", and neither is verified.

**The first step byte differs by panel type and both work.** His hexagons use `00` where our mini triangles
use `04`. The parser does not interpret that byte except through the shape test, and the 3-connector branch
keys on `(sep[0] >> 2) & 7 <= 1`, which accepts both. The section 4 theory that the low bits mark a non-child
neighbour is still unconfirmed, and the one `05` that supported it did not reappear.

**Still unimplemented: stable panel identity.** Panel indices are depth-first positions, so removing a panel
renumbers every panel found after it -- he measured panel 4's removal shifting panels 5 to 29 down by one.
He gives the UID query as `0xF8 ... 0x82`. `PB_NODE_CMD` (`0xF8`) is defined in `panelbus.h` and used
nowhere; the exact framing and reply layout are not in the post, so it needs probing with the `raw` console
command before anything is written against it.

## 9. The low nibble of a touch is a magnitude, not a gesture

Section 2 listed the touch codes as a set whose low nibble "varies with the gesture". It does not. The low
nibble is a **magnitude from 0 to 15**, and what moves it is how much of your hand is on the panel.

Measured on 2026-11-10 with one Hexagon on the rev B board, pressing the centre of the front diffuser,
five attempts per condition, `C0` polled every 50 ms:

| Contact | Touches that reached the wire | Peak magnitude |
|---|---|---|
| One fingertip, light | **2 of 5** | 1 |
| One fingertip, firm | **1 of 5** | 2 |
| Whole hand, flat | **5 of 5** | 15 |

- **It follows contact area, not force.** Pressing the same fingertip harder moved the peak from 1 to 2.
  Laying a whole hand on moved it to 15. A capacitive sensor measures the contact patch, and pressing
  harder barely changes that.
- **`15` saturates the nibble**, so a palm is clipped and there is no way to tell how much headroom is left
  above one.
- **It rises, then decays while the touch is held.** Two profiles, as value@ms from the start of the touch:

      1@0   2@204  3@308  4@308  7@414  15@414  2@927
      3@0   7@0    15@103  14@409  12@512  8@512

  That is a baseline tracker re-learning a stationary finger. A held touch therefore ends because the
  reading decayed to zero, not because the finger left, and that is the `10` "released" status of section 2.
- **A fingertip sits on the detection floor.** 1 or 2 out of 15, in the most sensitive spot on the panel.
  Seven of ten single-finger attempts produced **no bus traffic at all** -- every `C0` during them answered
  `00 00`, so the panel never reported them and no controller could have acted on them.

Whether that floor is normal or this particular hexagon is a weak one is **not established**: one panel,
one session. A second panel would separate the two. Note also that the panel's ground was tied to an
earthed laptop through the board's USB port throughout, which changes the reference a capacitive sensor
works against.

**What this rules out on the controller side.** The same session traced 14 touches that did reach the wire,
and the firmware acted on all 14, including one lasting 100 ms. The once-a-second layout re-read (`00` +
`80`) takes about 105 ms and a `C0` poll resumes on the very next frame, so it does not blind the bus to
touch -- an open question since September, now closed. Treating any non-zero low nibble as a touch, as
`(status & 0x10) && (status & 0x0F)` does, is already the most sensitive reading the protocol allows.
