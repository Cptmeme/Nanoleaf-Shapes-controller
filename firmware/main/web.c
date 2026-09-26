#include "web.h"

#include <stdarg.h>
#include <stdio.h>
#include "ddp.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "net.h"
#include "panelbus.h"

static const char *TAG = "web";

// Append to a fixed buffer, stopping quietly when it is full.
typedef struct {
    char buf[3072];
    size_t len;
} text_t;

static void add(text_t *t, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(t->buf + t->len, sizeof t->buf - t->len, fmt, ap);
    va_end(ap);
    if (n > 0) {
        t->len += (size_t)n < sizeof t->buf - t->len ? (size_t)n : sizeof t->buf - t->len - 1;
    }
}

static esp_err_t status_get(httpd_req_t *req)
{
    static text_t t;   // one request at a time: httpd runs a single task
    const pb_state_t *st = pb_state();
    const pb_pins_t *p = pb_pins();

    t.len = 0;
    add(&t, "Nanoleaf Shapes interface board\n\nuptime %llu s\n",
        (unsigned long long)(esp_timer_get_time() / 1000000));
    add(&t, "bus pins TX=%d RX=%d RC=%d\n", p->tx, p->rx, p->rc);
    add(&t, "polling %s, polls %lu, missed %lu, echo errors %lu%s\n",
        pb_poll_enabled() ? "on" : "off", (unsigned long)st->polls,
        (unsigned long)st->poll_misses, (unsigned long)st->echo_errors,
        st->hotplug ? ", HOT-PLUG pending" : "");
    const ddp_stats_t d = ddp_stats();
    const uint8_t *ip = (const uint8_t *)&d.source;
    add(&t, "ddp: %lu packets, %lu frames shown", (unsigned long)d.packets, (unsigned long)d.frames);
    if (d.packets) {
        add(&t, ", last from %u.%u.%u.%u", ip[0], ip[1], ip[2], ip[3]);
    }
    add(&t, "\n\nlayout string:");
    for (size_t i = 0; i < st->layout_len; i++) {
        add(&t, " %02X", st->layout[i]);
    }
    add(&t, "\n%d panel(s)\n  pos  chunk  node  type\n", st->npanels);
    for (int i = 0; i < st->npanels; i++) {
        const pb_panel_t *pn = &st->panels[i];
        add(&t, "  %3d  %5d    %02X  %s\n", i, pb_chunk_index(st->npanels, i), pn->node, pn->type);
    }
    add(&t, "\nconsole:  nc %s.local %d\n", NET_HOSTNAME, NET_CONSOLE_PORT);
    add(&t, "WLED:     LED output \"DDP RGBW (network)\", this IP, %d LEDs, pixel 0 = panel 0\n", st->npanels);
    add(&t, "update:   curl --data-binary @build/nanoleaf_bus.bin http://%s.local/ota\n", NET_HOSTNAME);

    httpd_resp_set_type(req, "text/plain");
    return httpd_resp_send(req, t.buf, t.len);
}

static esp_err_t ota_post(httpd_req_t *req)
{
    static char buf[2048];
    const esp_partition_t *part = esp_ota_get_next_update_partition(NULL);
    esp_ota_handle_t ota;

    if (!part || req->content_len == 0 ||
        esp_ota_begin(part, OTA_WITH_SEQUENTIAL_WRITES, &ota) != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "cannot start update\n");
    }
    ESP_LOGI(TAG, "OTA: receiving %u bytes into %s", (unsigned)req->content_len, part->label);

    size_t left = req->content_len;
    while (left > 0) {
        int n = httpd_req_recv(req, buf, left < sizeof buf ? left : sizeof buf);
        if (n == HTTPD_SOCK_ERR_TIMEOUT) {
            continue;
        }
        if (n <= 0 || esp_ota_write(ota, buf, n) != ESP_OK) {
            esp_ota_abort(ota);
            return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "write failed\n");
        }
        left -= n;
    }
    if (esp_ota_end(ota) != ESP_OK || esp_ota_set_boot_partition(part) != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "image rejected\n");
    }

    httpd_resp_sendstr(req, "OK, rebooting\n");
    ESP_LOGI(TAG, "OTA: done, rebooting into %s", part->label);
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
    return ESP_OK;
}

void web_start(void)
{
    httpd_handle_t server;
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.stack_size = 8192;

    if (httpd_start(&server, &cfg) != ESP_OK) {
        ESP_LOGE(TAG, "HTTP server failed to start");
        return;
    }
    const httpd_uri_t status = { .uri = "/", .method = HTTP_GET, .handler = status_get };
    const httpd_uri_t ota = { .uri = "/ota", .method = HTTP_POST, .handler = ota_post };
    httpd_register_uri_handler(server, &status);
    httpd_register_uri_handler(server, &ota);
}
