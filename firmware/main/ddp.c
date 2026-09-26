#include "ddp.h"

#include <string.h>
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/sockets.h"
#include "panelbus.h"

#define DDP_PORT       4048
#define DDP_VER_MASK   0xC0
#define DDP_VER1       0x40
#define DDP_TIMECODE   0x10
#define DDP_PUSH       0x01
#define DDP_TYPE_RGB   1
#define DDP_TYPE_RGBW  3
#define MIN_FRAME_US   25000   // at most 40 colour frames per second on the bus

static const char *TAG = "ddp";
static ddp_stats_t s_stats;

// One pixel per panel in layout order; missing pixels leave a panel unchanged.
static void apply(const uint8_t *px, size_t len, int bpp)
{
    pb_color_t colors[PB_MAX_PANELS];

    pb_lock();
    int n = pb_state()->npanels;
    for (int pos = 0; pos < n; pos++) {
        const uint8_t *p = px + pos * bpp;
        pb_color_t c = { .skip = true };
        if ((size_t)(pos + 1) * bpp <= len) {
            c = (pb_color_t){ .r = p[0], .g = p[1], .b = p[2], .w = bpp == 4 ? p[3] : 0, .t = 1 };
        }
        colors[pb_chunk_index(n, pos)] = c;
    }
    if (n > 0) {
        pb_push(colors, n);
    }
    pb_unlock();
}

static void ddp_task(void *arg)
{
    static uint8_t pkt[1500];
    static uint8_t frame[PB_MAX_PANELS * 4];
    size_t frame_len = 0;
    int bpp = 3;
    bool pending = false;
    int64_t last_push = 0;

    const struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port = htons(DDP_PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    const struct timeval tv = { .tv_sec = 0, .tv_usec = MIN_FRAME_US };
    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock < 0 || bind(sock, (const struct sockaddr *)&addr, sizeof addr) != 0) {
        ESP_LOGE(TAG, "cannot bind UDP %d", DDP_PORT);
        vTaskDelete(NULL);
    }
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);   // wakes up to flush a pending frame

    for (;;) {
        struct sockaddr_in from;
        socklen_t from_len = sizeof from;
        int n = recvfrom(sock, pkt, sizeof pkt, 0, (struct sockaddr *)&from, &from_len);
        if (n >= 10 && (pkt[0] & DDP_VER_MASK) == DDP_VER1) {
            size_t hdr = (pkt[0] & DDP_TIMECODE) ? 14 : 10;
            uint32_t offset = (uint32_t)pkt[4] << 24 | pkt[5] << 16 | pkt[6] << 8 | pkt[7];
            size_t len = pkt[8] << 8 | pkt[9];
            int type = (pkt[2] >> 3) & 7;
            s_stats.packets++;
            s_stats.source = from.sin_addr.s_addr;
            if (hdr + len <= (size_t)n && offset + len <= sizeof frame) {
                if (offset == 0) {
                    frame_len = 0;
                }
                memcpy(frame + offset, pkt + hdr, len);
                if (offset + len > frame_len) {
                    frame_len = offset + len;
                }
                int npanels = pb_state()->npanels;
                bpp = type == DDP_TYPE_RGBW ? 4 : type == DDP_TYPE_RGB ? 3
                    : (npanels > 0 && frame_len >= (size_t)npanels * 4) ? 4 : 3;
                // Senders that never set PUSH still send whole frames at offset 0
                if ((pkt[0] & DDP_PUSH) || (offset == 0 && npanels > 0 && len >= (size_t)npanels * bpp)) {
                    pending = true;
                }
            }
        }
        // Newest frame wins: older ones are dropped rather than played late
        int64_t now = esp_timer_get_time();
        if (pending && now - last_push >= MIN_FRAME_US) {
            apply(frame, frame_len, bpp);
            pending = false;
            last_push = now;
            s_stats.frames++;
            s_stats.last_us = now;
        }
    }
}

void ddp_start(void)
{
    xTaskCreate(ddp_task, "ddp", 6144, NULL, 4, NULL);
}

ddp_stats_t ddp_stats(void)
{
    return s_stats;
}
