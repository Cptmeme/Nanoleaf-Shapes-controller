#include "net.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "ddp.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_ota_ops.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/sockets.h"
#include "mdns.h"
#include "nvs.h"
#include "web.h"

#define NVS_NAMESPACE "wifi"
#define RETRY_US      (5 * 1000 * 1000)
#define PROMPT        "leaf> "

static const char *TAG = "net";

static esp_netif_t *s_netif;
static esp_timer_handle_t s_retry;
static FILE *s_uart_out;
static volatile int s_client = -1;
static bool s_connected;
static bool s_services_started;

static bool load_credentials(char ssid[33], char pass[65])
{
    nvs_handle_t h;
    size_t ssid_len = 33, pass_len = 65;

    if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &h) != ESP_OK) {
        return false;
    }
    bool ok = nvs_get_str(h, "ssid", ssid, &ssid_len) == ESP_OK &&
              nvs_get_str(h, "pass", pass, &pass_len) == ESP_OK;
    nvs_close(h);
    return ok && ssid[0];
}

esp_err_t net_save_credentials(const char *ssid, const char *password)
{
    nvs_handle_t h;

    if (strlen(ssid) > 32 || strlen(password) > 64) {
        return ESP_ERR_INVALID_ARG;
    }
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h);
    if (err != ESP_OK) {
        return err;
    }
    if (ssid[0]) {
        err = nvs_set_str(h, "ssid", ssid);
        if (err == ESP_OK) {
            err = nvs_set_str(h, "pass", password);
        }
    } else {
        err = nvs_erase_all(h);
    }
    if (err == ESP_OK) {
        err = nvs_commit(h);
    }
    nvs_close(h);
    return err;
}

void net_print_status(void)
{
    char ssid[33], pass[65];
    wifi_ap_record_t ap;
    esp_netif_ip_info_t ip;

    if (!s_netif) {
        if (load_credentials(ssid, pass)) {
            printf("Wi-Fi off this boot, configured for \"%s\"\n", ssid);
        } else {
            printf("Wi-Fi not configured\n");
        }
    } else if (s_connected && esp_wifi_sta_get_ap_info(&ap) == ESP_OK &&
               esp_netif_get_ip_info(s_netif, &ip) == ESP_OK) {
        printf("connected to \"%s\", RSSI %d dBm, IP " IPSTR "\n"
               "console: nc %s.local %d\n", (char *)ap.ssid, ap.rssi, IP2STR(&ip.ip),
               NET_HOSTNAME, NET_CONSOLE_PORT);
    } else {
        printf("Wi-Fi not connected\n");
    }
}

// --- network console ------------------------------------------------------------

// Log lines go to the UART and to the connected console client.
static int log_vprintf(const char *fmt, va_list ap)
{
    char buf[256];
    int n = vsnprintf(buf, sizeof buf, fmt, ap);
    if (n <= 0) {
        return n;
    }
    if (n >= (int)sizeof buf) {
        n = sizeof buf - 1;
    }
    fwrite(buf, 1, n, s_uart_out);
    int fd = s_client;
    if (fd >= 0) {
        send(fd, buf, n, MSG_DONTWAIT);
    }
    return n;
}

static ssize_t sock_write(void *cookie, const char *buf, size_t len)
{
    int fd = (int)(intptr_t)cookie;
    size_t done = 0;
    while (done < len) {
        int n = send(fd, buf + done, len - done, 0);
        if (n <= 0) {
            return done ? (ssize_t)done : -1;
        }
        done += n;
    }
    return done;
}

static void serve_client(int fd)
{
    char line[160];
    size_t len = 0;
    int skip = 0;   // telnet negotiation bytes still to drop

    printf("%s console, type help\n" PROMPT, NET_HOSTNAME);
    fflush(stdout);
    for (;;) {
        unsigned char c;
        if (recv(fd, &c, 1, 0) <= 0) {
            return;
        }
        if (skip) {
            skip--;
        } else if (c == 0xFF) {
            skip = 2;   // IAC, command, option
        } else if (c == '\n') {
            line[len] = '\0';
            len = 0;
            console_run(line);
            printf(PROMPT);
            fflush(stdout);
        } else if (c != '\r' && len < sizeof line - 1) {
            line[len++] = c;
        }
    }
}

static void console_task(void *arg)
{
    const struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port = htons(NET_CONSOLE_PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    int one = 1;
    int srv = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (srv < 0 || setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one) != 0 ||
        bind(srv, (const struct sockaddr *)&addr, sizeof addr) != 0 || listen(srv, 1) != 0) {
        ESP_LOGE(TAG, "console socket failed");
        vTaskDelete(NULL);
    }

    FILE *uart_stdout = stdout;
    for (;;) {
        int fd = accept(srv, NULL, NULL);
        if (fd < 0) {
            continue;
        }
        setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
        FILE *out = fopencookie((void *)(intptr_t)fd, "w", (cookie_io_functions_t){ .write = sock_write });
        if (out) {
            setvbuf(out, NULL, _IOLBF, 256);
            stdout = out;   // per task in ESP-IDF: command output goes to the client
            s_client = fd;
            serve_client(fd);
            s_client = -1;
            stdout = uart_stdout;
            fclose(out);
        }
        close(fd);
    }
}

// --- Wi-Fi --------------------------------------------------------------------------

static void start_services(void)
{
    if (mdns_init() == ESP_OK) {
        mdns_hostname_set(NET_HOSTNAME);
        mdns_instance_name_set("Nanoleaf Shapes interface board");
        mdns_service_add(NULL, "_telnet", "_tcp", NET_CONSOLE_PORT, NULL, 0);
        mdns_service_add(NULL, "_http", "_tcp", 80, NULL, 0);
    }
    xTaskCreate(console_task, "net_console", 8192, NULL, 3, NULL);
    web_start();
    ddp_start();
}

static void retry_connect(void *arg)
{
    esp_wifi_connect();
}

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *d = data;
        ESP_LOGW(TAG, "Wi-Fi %s (reason %d), retrying in 5 s",
                 s_connected ? "lost" : "connect failed", d->reason);
        s_connected = false;
        esp_timer_start_once(s_retry, RETRY_US);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *e = data;
        s_connected = true;
        ESP_LOGI(TAG, "connected, IP " IPSTR ": nc %s.local %d",
                 IP2STR(&e->ip_info.ip), NET_HOSTNAME, NET_CONSOLE_PORT);
        // An OTA image that reaches the network is good; otherwise the
        // bootloader rolls back to the previous one on the next reset.
        esp_ota_mark_app_valid_cancel_rollback();
        if (!s_services_started) {
            s_services_started = true;
            start_services();
        }
    }
}

esp_err_t net_start(void)
{
    char ssid[33], pass[65];
    wifi_config_t wc = { 0 };

    if (!load_credentials(ssid, pass)) {
        printf("Wi-Fi not configured: wifi <ssid> <password>\n");
        return ESP_ERR_NOT_FOUND;
    }
    memcpy(wc.sta.ssid, ssid, strlen(ssid));
    memcpy(wc.sta.password, pass, strlen(pass));

    s_uart_out = stdout;
    esp_log_set_vprintf(log_vprintf);

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    s_netif = esp_netif_create_default_wifi_sta();
    esp_netif_set_hostname(s_netif, NET_HOSTNAME);
    const wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_event, NULL));
    const esp_timer_create_args_t retry = { .callback = retry_connect, .name = "wifi_retry" };
    ESP_ERROR_CHECK(esp_timer_create(&retry, &s_retry));

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());
    esp_wifi_set_ps(WIFI_PS_NONE);   // console latency over power; the panels supply plenty
    printf("Wi-Fi: connecting to \"%s\"\n", ssid);
    return ESP_OK;
}
