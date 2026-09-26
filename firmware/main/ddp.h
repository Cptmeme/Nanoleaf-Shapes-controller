// DDP receiver: the panels as a network pixel sink.
//
// In WLED add an LED output of type "DDP RGBW (network)" (or "DDP RGB") with
// this board's IP and one LED per panel. LedFx, xLights and Hyperion work the
// same way. UDP port 4048, one pixel per panel in layout order: pixel 0 is the
// panel next to this board, as listed by `enum`.
#pragma once

#include <stdint.h>

typedef struct {
    uint32_t packets, frames;
    uint32_t source;   // IPv4 address of the last sender, network byte order
    int64_t last_us;   // esp_timer time of the last frame, 0 = never
} ddp_stats_t;

void ddp_start(void);
ddp_stats_t ddp_stats(void);
