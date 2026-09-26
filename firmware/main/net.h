// Wi-Fi station, mDNS name and a network copy of the serial console.
//
//   nc nanoleaf-bus.local 23     console; log output is mirrored there too
//   http://nanoleaf-bus.local/   status page, POST /ota for firmware updates
#pragma once

#include "esp_err.h"

#define NET_HOSTNAME     "nanoleaf-bus"
#define NET_CONSOLE_PORT 23

// Connect with the credentials saved by net_save_credentials().
esp_err_t net_start(void);

// Empty ssid clears the saved credentials.
esp_err_t net_save_credentials(const char *ssid, const char *password);

void net_print_status(void);

// Runs one console command line; output goes to the calling task's stdout.
// Implemented in main.c.
void console_run(char *line);
