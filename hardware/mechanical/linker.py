"""Nanoleaf Shapes linker and pad geometry, in mm: the single source for the pocket test piece, the enclosure
and the KiCad pad footprint.

Linker sizes are measured from the community model "Nanoleaf Panel Connector" by thegestalt (Printables 997500,
CC BY-NC; used as a dimensional reference only, see ../README.md). "Joint" is the line where the controller's
edge meets the panel's edge; the rigid linker is centred on it.

The panels have a recess for the linker plate, so a fitted linker sits flush with the panel's back; the enclosure
copies it. Depths below are measured from the recess floor, where the plate's inner face rests.
"""

# Linker plug (one per linker end)
PLUG_W = 11.40          # across the linker
PLUG_L = 12.50          # along the linker
PLUG_H = 2.48           # height above the plate's inner face = depth of the PCB surface below the recess floor
PLUG_R = 3.00           # corner radius
WALL_TO_JOINT = 4.52    # from the joint to the plug's near end (the pocket's near wall)
PAD_CENTRE = WALL_TO_JOINT + PLUG_L / 2   # 10.77 from the joint: the springs sit in the middle of the plug

# Snap hooks: one on each side of the plug
HOOK_Y = (4.90, 7.60)   # band along the linker, measured from the plug's near end
HOOK_IN = 1.50          # hook's inner face, inward from the plug side
BARB_OUT = 0.41         # barb tip, outward from the plug side
HOOK_TIP = 3.63         # depth of the hook tip below the recess floor

# Slots in the PCB beside the pads, one per side. Besides the two snap hooks a real linker has plain posts
# that locate the plug, so the panels' own PCBs carry one slot along the whole plug rather than a short hole
# at each hook. A test print cut only to HOOK_Y fouled those posts, so the slots run the full plug length.
SLOT_Y = (0.00, PLUG_L)  # along the linker, from the plug's near end
SLOT_IN = HOOK_IN        # inner face, inward from the plug side
# Deliberately far outboard, not BARB_OUT: the barb must be free to spring its full travel. The community
# model's 0.41 mm was the only figure for it, and a slot sized to that would block a barb any bigger. The
# extra width costs nothing (it is outboard of the pads) and cannot reduce the latch.
SLOT_OUT = 1.20          # outer face, outward from the plug side

# Linker plate (sits in a recess, flush with the enclosure's back)
PLATE_W = 17.34
PLATE_HALF_L = 20.02    # from the joint to the plate's end
PLATE_T = 2.37          # thickness = recess depth
PLATE_R = 2.00          # corner radius

# Contact pads, as on the panels (Christian Panton: about 10 x 1.5 mm with 1 mm gaps), centred under the springs
PAD_W = 1.50
PAD_L = 10.00
PAD_PITCH = 2.50
