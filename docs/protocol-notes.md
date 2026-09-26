# Panel bus notes

Observations of the Nanoleaf Shapes panel bus measured with this board. They add to, and in one place
correct, [LeafBus PROTOCOL.md](https://github.com/MyrikLD/LeafBus/blob/main/PROTOCOL.md), which remains the
reference for everything not mentioned here. Section numbers (§) refer to that document.

**Test setup:**
- **Hardware:** one assembly of 9 Mini Triangles (NL48) with the stock power supply, driven by the rev A
  interface board (ESP32-C5, buffered single-wire bus).
- **Layouts tested:**
  - a straight chain, with the board at either end;
  - a fork, with the board on a middle panel;
  - a ring of six panels with three more attached.
- **Not tested:** Triangles (NL47) and Hexagons (NL42).

## 1. The bulk-pull reply comes in layout order (correction to §5.3)

§5.3 says a panel's index is the same in the bulk push (`E0`) and the bulk pull (`C0`). On these panels it
isn't:

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
| `11`, `12`, `13`, `15`, `16`, `17` | touch (the low nibble varies with the gesture) |
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
