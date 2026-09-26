// Bring-up firmware for the Nanoleaf Shapes interface board.
//
// Console on J2 (UART0, 115200 8N1); type `help`. Bring-up order:
//   pinscan  find the bus GPIOs (runs by itself on first boot, saved in NVS)
//   echo     loopback through U4 -> U3; needs no panel
//   listen   receive only; a panel probes an unused edge with C0 every 50 ms
//   enum     00, 80, layout string; starts the C0 poll
//   color / panel / bright
//
// Once `wifi <ssid> <password>` is set, the same console is reachable with
// `nc nanoleaf-bus.local 23`. Wi-Fi is skipped for one boot after a brownout,
// so the serial console stays usable on a weak 3V3 supply.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ddp.h"
#include "driver/gpio.h"
#include "esp_console.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "net.h"
#include "nvs_flash.h"
#include "panelbus.h"
#include "pinscan.h"
#include "soc/lp_aon_reg.h"

#define NVS_NAMESPACE "bus"

static bool pins_load(pb_pins_t *p)
{
    nvs_handle_t h;
    int8_t tx, rx, rc;

    if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &h) != ESP_OK) {
        return false;
    }
    bool ok = nvs_get_i8(h, "tx", &tx) == ESP_OK &&
              nvs_get_i8(h, "rx", &rx) == ESP_OK &&
              nvs_get_i8(h, "rc", &rc) == ESP_OK;
    nvs_close(h);
    if (ok) {
        *p = (pb_pins_t){ tx, rx, rc };
    }
    return ok;
}

static void pins_save(const pb_pins_t *p)
{
    nvs_handle_t h;

    if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h) != ESP_OK) {
        return;
    }
    nvs_set_i8(h, "tx", p->tx);
    nvs_set_i8(h, "rx", p->rx);
    nvs_set_i8(h, "rc", p->rc);
    nvs_commit(h);
    nvs_close(h);
}

static void print_hex(const uint8_t *buf, size_t len)
{
    for (size_t i = 0; i < len; i++) {
        printf("%02X ", buf[i]);
    }
    printf("\n");
}

static bool bus_ready(void)
{
    if (pb_pins()->tx < 0) {
        printf("bus pins unknown: run `pinscan` or `pins <tx> <rx> <rc>`\n");
        return false;
    }
    return true;
}

static bool enumerated(void)
{
    if (pb_state()->npanels == 0) {
        printf("no panels known: run `enum` first\n");
        return false;
    }
    return true;
}

static int arg_byte(int argc, char **argv, int i, int def)
{
    return i < argc ? atoi(argv[i]) & 0xFF : def;
}

// --- commands -----------------------------------------------------------------

static int cmd_pins(int argc, char **argv)
{
    if (argc == 4) {
        pb_pins_t p = { atoi(argv[1]), atoi(argv[2]), atoi(argv[3]) };
        if (!GPIO_IS_VALID_OUTPUT_GPIO(p.tx) || !GPIO_IS_VALID_GPIO(p.rx) ||
            (p.rc != -1 && !GPIO_IS_VALID_GPIO(p.rc)) || pb_init(&p) != ESP_OK) {
            printf("invalid pins\n");
            return 1;
        }
        pins_save(&p);
    } else if (argc != 1) {
        printf("usage: pins [<tx> <rx> <rc>]   (rc -1 = unknown)\n");
        return 1;
    }
    const pb_pins_t *p = pb_pins();
    if (p->tx < 0) {
        printf("bus pins not set\n");
    } else {
        printf("TX=GPIO%d RX=GPIO%d RC=%s%d\n", p->tx, p->rx, p->rc >= 0 ? "GPIO" : "", p->rc);
    }
    return 0;
}

static int cmd_pinscan(int argc, char **argv)
{
    pb_pins_t old = *pb_pins();
    pb_pins_t found;

    if (pinscan_run(&found) != ESP_OK) {
        if (old.tx >= 0) {
            pb_init(&old);
        }
        return 1;
    }
    pins_save(&found);
    pb_init(&found);
    return 0;
}

static int cmd_echo(int argc, char **argv)
{
    static const uint8_t pattern[] = { 0x55, 0xAA, 0x55, 0xAA, 0x0F, 0xF0 };
    int tries = argc > 1 ? atoi(argv[1]) : 20;
    int clean = 0;

    if (!bus_ready()) {
        return 1;
    }
    for (int i = 0; i < tries; i++) {
        bool ok = false;
        pb_xact(pattern, sizeof pattern, NULL, 0, PB_EXPECT_NONE, 0, &ok);
        clean += ok;
    }
    printf("clean echo: %d/%d\n", clean, tries);
    printf("(tests TX -> U4 -> U3 -> RX on the board; says nothing about R1, J1 or the panel)\n");
    return clean == tries ? 0 : 1;
}

static int cmd_listen(int argc, char **argv)
{
    int ms = argc > 1 ? atoi(argv[1]) : 2000;
    uint8_t buf[128];
    int total = 0, probes = 0;

    if (!bus_ready()) {
        return 1;
    }
    printf("listening %d ms without transmitting...\n", ms);
    pb_lock();   // keeps the poller quiet too
    pb_flush();
    int64_t t0 = esp_timer_get_time();
    int64_t last = t0;
    while (esp_timer_get_time() - t0 < (int64_t)ms * 1000) {
        int n = pb_read_raw(buf, sizeof buf, 5);
        if (n <= 0) {
            continue;
        }
        int64_t now = esp_timer_get_time();
        printf("%8.1f ms  +%6.1f  ", (now - t0) / 1000.0, (now - last) / 1000.0);
        print_hex(buf, n);
        last = now;
        total += n;
        for (int i = 0; i < n; i++) {
            probes += buf[i] == PB_BULK_PULL;
        }
    }
    pb_unlock();

    printf("%d bytes, %d x C0\n", total, probes);
    if (total == 0) {
        printf("silent: is the panel powered, and J1 pin 3 on DATA?\n");
    } else if (probes * 2 < total) {
        printf("mostly not C0: the idle level is probably wrong, see the pull-up note\n");
    }
    return 0;
}

static int cmd_enum(int argc, char **argv)
{
    if (!bus_ready()) {
        return 1;
    }
    esp_err_t err = pb_enumerate();
    const pb_state_t *st = pb_state();
    if (st->layout_len == 0) {
        printf("no layout string: bus silent (panel power? J1 wiring? pull-up?)\n");
        return 1;
    }
    printf("layout string (%s): ", st->layout_stable ? "read twice" : "UNSTABLE, did not repeat");
    print_hex(st->layout, st->layout_len);
    if (err != ESP_OK) {
        printf("could not parse it; panel count taken from the node bytes\n");
    }

    printf("%d panel(s)\n  pos  chunk  node  type           parent/connector\n", st->npanels);
    for (int i = 0; i < st->npanels; i++) {
        const pb_panel_t *p = &st->panels[i];
        printf("  %3d  %5d    %02X  %-13s  ", i, pb_chunk_index(st->npanels, i), p->node, p->type);
        if (p->parent < 0) {
            printf("%s\n", err == ESP_OK ? "this board" : "-");
        } else {
            printf("%d/%d\n", p->parent, p->parent_conn);
        }
    }
    if (st->psu_parent >= 0) {
        printf("  power supply on panel %d connector %d\n", st->psu_parent, st->psu_conn);
    }
    pb_poll_enable(true);
    printf("C0 polling on\n");
    return 0;
}

static int cmd_color(int argc, char **argv)
{
    if (argc < 4) {
        printf("usage: color <r> <g> <b> [w] [t]\n");
        return 1;
    }
    if (!bus_ready() || !enumerated()) {
        return 1;
    }
    return pb_fill(arg_byte(argc, argv, 1, 0), arg_byte(argc, argv, 2, 0), arg_byte(argc, argv, 3, 0),
                   arg_byte(argc, argv, 4, 0), arg_byte(argc, argv, 5, 1)) == ESP_OK ? 0 : 1;
}

static int cmd_panel(int argc, char **argv)
{
    if (argc < 5) {
        printf("usage: panel <pos> <r> <g> <b> [w] [t]   (pos as listed by enum)\n");
        return 1;
    }
    if (!bus_ready() || !enumerated()) {
        return 1;
    }
    int n = pb_state()->npanels;
    int pos = atoi(argv[1]);
    if (pos < 0 || pos >= n) {
        printf("pos must be 0..%d\n", n - 1);
        return 1;
    }
    const pb_color_t c = {
        .r = arg_byte(argc, argv, 2, 0), .g = arg_byte(argc, argv, 3, 0), .b = arg_byte(argc, argv, 4, 0),
        .w = arg_byte(argc, argv, 5, 0), .t = arg_byte(argc, argv, 6, 1),
    };
    return pb_set_panel(pos, &c) == ESP_OK ? 0 : 1;
}

// Touch light: a touched panel turns white until released, then gets its
// previous colour back. Proves that touch and colour agree on panel numbers.
static bool s_touchlight;
static pb_color_t s_before_touch[PB_MAX_PANELS];

static void touchlight(int pos, bool touched, uint8_t status)
{
    static const pb_color_t white = { .r = 255, .g = 255, .b = 255, .w = 255, .t = 1 };

    if (!s_touchlight) {
        return;
    }
    if (touched) {
        s_before_touch[pos] = pb_panel_color(pos);
        pb_set_panel(pos, &white);
    } else {
        pb_set_panel(pos, &s_before_touch[pos]);
    }
}

static int cmd_touchlight(int argc, char **argv)
{
    if (argc == 2) {
        s_touchlight = strcmp(argv[1], "on") == 0;
    }
    printf("touch light %s\n", s_touchlight ? "on" : "off");
    return 0;
}

static int cmd_bright(int argc, char **argv)
{
    if (argc != 2) {
        printf("usage: bright <0-255>\n");
        return 1;
    }
    if (!bus_ready()) {
        return 1;
    }
    return pb_brightness(atoi(argv[1]) & 0xFF) == ESP_OK ? 0 : 1;
}

static int cmd_poll(int argc, char **argv)
{
    if (argc == 2) {
        pb_poll_enable(strcmp(argv[1], "on") == 0);
    }
    printf("C0 polling %s\n", pb_poll_enabled() ? "on" : "off");
    return 0;
}

static int cmd_raw(int argc, char **argv)
{
    uint8_t frame[64];
    uint8_t reply[512];
    size_t len = 0;

    if (argc < 3) {
        printf("usage: raw <read_ms> <hex byte>...   e.g. raw 50 C0\n");
        return 1;
    }
    if (!bus_ready()) {
        return 1;
    }
    int read_ms = atoi(argv[1]);
    for (int i = 2; i < argc && len < sizeof frame; i++) {
        frame[len++] = strtol(argv[i], NULL, 16);
    }
    bool echo_ok = false;
    int n = pb_xact(frame, len, reply, sizeof reply,
                    read_ms > 0 ? (int)sizeof reply : PB_EXPECT_NONE, read_ms, &echo_ok);
    printf("echo %s, %d reply byte(s)%s", echo_ok ? "ok" : "BAD", n, n > 0 ? ": " : "\n");
    if (n > 0) {
        print_hex(reply, n);
    }
    return 0;
}

static int cmd_stats(int argc, char **argv)
{
    const pb_state_t *st = pb_state();
    const ddp_stats_t d = ddp_stats();
    printf("panels %d, polling %s, polls %lu, missed %lu, echo errors %lu%s\n",
           st->npanels, pb_poll_enabled() ? "on" : "off",
           (unsigned long)st->polls, (unsigned long)st->poll_misses, (unsigned long)st->echo_errors,
           st->hotplug ? ", HOT-PLUG pending" : "");
    if (d.packets) {
        const uint8_t *ip = (const uint8_t *)&d.source;
        printf("ddp: %lu packets, %lu frames shown, last from %u.%u.%u.%u %.1f s ago\n",
               (unsigned long)d.packets, (unsigned long)d.frames, ip[0], ip[1], ip[2], ip[3],
               d.last_us ? (esp_timer_get_time() - d.last_us) / 1e6 : 0.0);
    }
    return 0;
}

static int cmd_trace(int argc, char **argv)
{
    if (argc == 2) {
        pb_trace(strcmp(argv[1], "on") == 0);
    }
    printf("bus trace %s\n", pb_tracing() ? "on" : "off");
    return 0;
}

static int cmd_wifi(int argc, char **argv)
{
    if (argc == 3) {
        if (net_save_credentials(argv[1], argv[2]) != ESP_OK) {
            printf("could not save (SSID max 32, password max 64 characters)\n");
            return 1;
        }
        printf("saved; Wi-Fi starts at the next power-up or `restart`\n");
    } else if (argc == 2 && strcmp(argv[1], "clear") == 0) {
        net_save_credentials("", "");
        printf("cleared\n");
    } else if (argc != 1) {
        printf("usage: wifi [<ssid> <password> | clear]   (quote names with spaces)\n");
        return 1;
    }
    net_print_status();
    return 0;
}

static int cmd_restart(int argc, char **argv)
{
    esp_restart();
    return 0;
}

// The BOOT strap is unreliable on this board: download mode also needs GPIO27
// (bus RX) high at reset, and that follows the floating bus.
static int cmd_download(int argc, char **argv)
{
    printf("rebooting into UART download mode\n");
    fflush(stdout);
    REG_SET_FIELD(LP_AON_SYS_CFG_REG, LP_AON_FORCE_DOWNLOAD_BOOT, 1);
    esp_restart();
    return 0;
}

static const esp_console_cmd_t s_cmds[] = {
    { .command = "pins", .hint = "[<tx> <rx> <rc>]", .help = "Show or set the bus GPIOs", .func = cmd_pins },
    { .command = "pinscan", .help = "Find the bus GPIOs through the on-board loopback", .func = cmd_pinscan },
    { .command = "echo", .hint = "[tries]", .help = "Loopback test through U4 and U3", .func = cmd_echo },
    { .command = "listen", .hint = "[ms]", .help = "Print bus traffic without transmitting", .func = cmd_listen },
    { .command = "enum", .help = "Send 00 and 80, print the layout, start polling", .func = cmd_enum },
    { .command = "color", .hint = "<r> <g> <b> [w] [t]", .help = "Set every panel", .func = cmd_color },
    { .command = "panel", .hint = "<pos> <r> <g> <b> [w] [t]", .help = "Set one panel, leave the rest", .func = cmd_panel },
    { .command = "bright", .hint = "<0-255>", .help = "Global brightness (FC 04)", .func = cmd_bright },
    { .command = "touchlight", .hint = "[on|off]", .help = "Touched panel lights white until released", .func = cmd_touchlight },
    { .command = "poll", .hint = "[on|off]", .help = "C0 poll every 50 ms and auto-enum (off = quiet bus)", .func = cmd_poll },
    { .command = "raw", .hint = "<read_ms> <hex>...", .help = "Send a raw frame and print the reply", .func = cmd_raw },
    { .command = "stats", .help = "Bus counters", .func = cmd_stats },
    { .command = "trace", .hint = "[on|off]", .help = "Log frames and replies in hex, repeats counted", .func = cmd_trace },
    { .command = "wifi", .hint = "[<ssid> <password> | clear]", .help = "Show or set Wi-Fi", .func = cmd_wifi },
    { .command = "restart", .help = "Reboot", .func = cmd_restart },
    { .command = "download", .help = "Reboot into download mode for serial flashing", .func = cmd_download },
};

#define NCMDS (sizeof s_cmds / sizeof s_cmds[0])

void console_run(char *line)
{
    char *argv[12];
    size_t argc = esp_console_split_argv(line, argv, sizeof argv / sizeof argv[0]);

    if (argc == 0) {
        return;
    }
    if (strcmp(argv[0], "help") == 0) {
        for (size_t i = 0; i < NCMDS; i++) {
            printf("  %-10s %-28s %s\n", s_cmds[i].command, s_cmds[i].hint ? s_cmds[i].hint : "",
                   s_cmds[i].help);
        }
        return;
    }
    for (size_t i = 0; i < NCMDS; i++) {
        if (strcmp(argv[0], s_cmds[i].command) == 0) {
            s_cmds[i].func(argc, argv);
            return;
        }
    }
    printf("unknown command %s, try help\n", argv[0]);
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }

    printf("\nNanoleaf Shapes interface board: bus bring-up\n");
    esp_reset_reason_t why = esp_reset_reason();
    bool weak_supply = why == ESP_RST_BROWNOUT || why == ESP_RST_PWR_GLITCH;
    if (weak_supply) {
        printf("WARNING: last reset was a %s, 3V3 sagged; Wi-Fi skipped this boot\n",
               why == ESP_RST_BROWNOUT ? "brownout" : "power glitch");
    }

    pb_pins_t pins;
    if (pins_load(&pins)) {
        printf("bus pins from NVS: TX=GPIO%d RX=GPIO%d RC=%d\n", pins.tx, pins.rx, pins.rc);
    } else {
        printf("no saved bus pins, running pinscan\n");
        if (pinscan_run(&pins) == ESP_OK) {
            pins_save(&pins);
        } else {
            pins.tx = -1;
        }
    }
    if (pins.tx >= 0 && pb_init(&pins) != ESP_OK) {
        printf("bus init failed on those pins\n");
    }
    pb_on_touch(touchlight);
    pb_poll_start();
    if (!weak_supply) {
        net_start();
    }

    esp_console_repl_t *repl;
    esp_console_repl_config_t repl_cfg = ESP_CONSOLE_REPL_CONFIG_DEFAULT();
    repl_cfg.prompt = "leaf>";
    repl_cfg.task_stack_size = 8192;
    esp_console_dev_uart_config_t uart_cfg = ESP_CONSOLE_DEV_UART_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_console_new_repl_uart(&uart_cfg, &repl_cfg, &repl));
    for (size_t i = 0; i < sizeof s_cmds / sizeof s_cmds[0]; i++) {
        ESP_ERROR_CHECK(esp_console_cmd_register(&s_cmds[i]));
    }
    ESP_ERROR_CHECK(esp_console_start_repl(repl));
}
