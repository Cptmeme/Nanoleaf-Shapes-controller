#pragma once

#ifdef __cplusplus
extern "C" {
#endif

/** Report the controller with its own vendor and product names. Call before esp_matter::start(). */
void device_info_register(void);

#ifdef __cplusplus
}
#endif
