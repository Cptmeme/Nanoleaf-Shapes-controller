#pragma once

#include <esp_err.h>
#include <esp_matter.h>

#if CHIP_DEVICE_CONFIG_ENABLE_THREAD
#include "esp_openthread_types.h"
#endif

/** Matter ranges */
#define MATTER_BRIGHTNESS 254
#define MATTER_HUE 254
#define MATTER_SATURATION 254

/** Default attribute values on first boot */
#define DEFAULT_POWER true
#define DEFAULT_BRIGHTNESS 128
#define DEFAULT_HUE 128
#define DEFAULT_SATURATION 254

typedef void *app_driver_handle_t;

/** Start the panel bus. Returns a handle for the light endpoint, NULL on failure. */
app_driver_handle_t app_driver_light_init();

/** Register the BOOT button: a tap toggles the light. Returns the button handle for app_reset. */
app_driver_handle_t app_driver_button_init();

/** Apply one attribute change to the panels. Called from the Matter attribute callback. */
esp_err_t app_driver_attribute_update(app_driver_handle_t driver_handle, uint16_t endpoint_id, uint32_t cluster_id,
                                      uint32_t attribute_id, esp_matter_attr_val_t *val);

/** Load every light attribute, and the rainbow switch, from the data model into the driver and show
    the result. */
esp_err_t app_driver_light_set_defaults(uint16_t endpoint_id);

#if CHIP_DEVICE_CONFIG_ENABLE_THREAD
#define ESP_OPENTHREAD_DEFAULT_RADIO_CONFIG()                                           \
    {                                                                                   \
        .radio_mode = RADIO_MODE_NATIVE,                                                \
    }

#define ESP_OPENTHREAD_DEFAULT_HOST_CONFIG()                                            \
    {                                                                                   \
        .host_connection_mode = HOST_CONNECTION_MODE_NONE,                              \
    }

#define ESP_OPENTHREAD_DEFAULT_PORT_CONFIG()                                            \
    {                                                                                   \
        .storage_partition_name = "nvs", .netif_queue_size = 10, .task_queue_size = 10, \
    }
#endif
