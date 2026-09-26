// Bus master for Nanoleaf Shapes panels.
//
// Frame formats and timing follow LeafBus PROTOCOL.md
// (https://github.com/MyrikLD/LeafBus); section numbers below refer to it.
//
// The board drives the bus through two 74LVC1G125 buffers: U4 transmits and
// is enabled by the D2/R7/C17 one-shot while TX is active, U3 always
// receives. The master therefore hears its own echo, which is stripped here.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define PB_MAX_PANELS 64
#define PB_MAX_LAYOUT 256

// frame types (§4.1)
#define PB_ROOT_DETECT   0x00
#define PB_LAYOUT_DETECT 0x80
#define PB_BULK_PULL     0xC0
#define PB_BULK_PUSH     0xE0
#define PB_NODE_CMD      0xF8
#define PB_GLOBAL_CMD    0xFC

#define PB_TERMINATOR 0x40   // ends the layout string
#define PB_HOTPLUG    0xCC   // trailing byte of a bulk pull reply (§8)

// global commands (§6.1)
#define PB_CMD_BRIGHTNESS   0x04
#define PB_CMD_TOUCH_ENABLE 0x07

// expect argument of pb_xact()
#define PB_EXPECT_NONE       0
#define PB_EXPECT_TERMINATOR (-1)

typedef struct {
    int tx;   // UART TX -> U4 input and D2
    int rx;   // UART RX <- U3 output through R6
    int rc;   // one-shot node through R10, -1 if unknown; kept high impedance
} pb_pins_t;

typedef struct {
    uint8_t node;         // node byte from the layout string
    uint8_t connectors;
    uint8_t root;         // connector facing the master
    int8_t parent;        // layout position of the parent, -1 = attached to this board
    int8_t parent_conn;   // parent connector this panel hangs on
    const char *type;
} pb_panel_t;

typedef struct {
    uint8_t layout[PB_MAX_LAYOUT];   // raw layout string including the terminator
    size_t layout_len;
    bool layout_stable;              // the same string was read twice (§9.2)
    int npanels;                     // 0 = not enumerated
    pb_panel_t panels[PB_MAX_PANELS];   // in layout-string order
    int psu_parent, psu_conn;        // where the power supply node sits, -1 if absent
    bool hotplug;                    // a bulk pull saw panels added or removed; re-enumeration pending
    uint32_t polls, poll_misses, echo_errors;
    uint32_t enumerations;           // successful enumerations since pb_init(); lets users re-apply state
} pb_state_t;

typedef struct {
    uint8_t r, g, b, w;
    uint8_t t;      // transition time
    bool skip;      // leave this panel unchanged
} pb_color_t;

esp_err_t pb_init(const pb_pins_t *pins);
void pb_deinit(void);
const pb_pins_t *pb_pins(void);
const pb_state_t *pb_state(void);

// Held across multi-frame sequences so the poller does not interleave.
void pb_lock(void);
void pb_unlock(void);

// Send one frame, check and strip its echo, read the reply.
// expect: reply length, PB_EXPECT_NONE or PB_EXPECT_TERMINATOR.
// Returns the number of reply bytes, or -1 if the bus is not initialised.
int pb_xact(const uint8_t *frame, size_t len, uint8_t *reply, size_t reply_max,
            int expect, int wait_ms, bool *echo_ok);

// Receive without transmitting.
void pb_flush(void);
int pb_read_raw(uint8_t *buf, size_t max, int timeout_ms);

esp_err_t pb_enumerate(void);
int pb_bulk_pull(void);
esp_err_t pb_push(const pb_color_t *colors, int n);   // colors in chunk order
esp_err_t pb_fill(uint8_t r, uint8_t g, uint8_t b, uint8_t w, uint8_t t);
esp_err_t pb_set_panel(int layout_pos, const pb_color_t *color);   // others unchanged
pb_color_t pb_panel_color(int layout_pos);   // last colour pushed, black if never set
esp_err_t pb_brightness(uint8_t value);

// Called from the poll task, bus lock held, when a panel is touched or released.
typedef void (*pb_touch_cb_t)(int layout_pos, bool touched, uint8_t status);
void pb_on_touch(pb_touch_cb_t cb);

// Bulk push chunk index of the panel at a layout position (§5.3). Bulk pull
// replies are NOT reversed: their pairs come in layout order.
static inline int pb_chunk_index(int npanels, int layout_pos)
{
    return npanels - 1 - layout_pos;
}

// Keep the panels polled with C0 every 50 ms; without it only the first
// colour frame is applied (§4.2).
void pb_poll_start(void);
void pb_poll_enable(bool on);
bool pb_poll_enabled(void);

// Log every frame sent and every reply received, in hex.
void pb_trace(bool on);
bool pb_tracing(void);

#ifdef __cplusplus
}
#endif
