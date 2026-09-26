/*
   Custom DeviceInstanceInfoProvider, so controllers show this project's names instead of the example
   defaults. Only the names change. The vendor and product IDs stay on the test values the development
   device attestation certificate was issued for: other IDs would fail attestation during commissioning.
*/
#include "device_info.h"

#include <stdio.h>
#include <string.h>
#include <esp_log.h>
#include <esp_mac.h>
#include <esp_matter.h>
#include <esp_matter_providers.h>
#include <lib/support/CodeUtils.h>
#include <lib/support/Span.h>
#include <platform/CHIPDeviceConfig.h>
#include <platform/DeviceInstanceInfoProvider.h>

static const char *TAG = "device_info";

#define DEVICE_VENDOR_NAME  "Cptmeme"
#define DEVICE_PRODUCT_NAME "Shapes Controller"

namespace {

CHIP_ERROR copy_string(char *buf, size_t buf_size, const char *value)
{
    size_t len = strlen(value);
    VerifyOrReturnError(buf != nullptr, CHIP_ERROR_INVALID_ARGUMENT);
    VerifyOrReturnError(buf_size > len, CHIP_ERROR_BUFFER_TOO_SMALL);
    memcpy(buf, value, len + 1);
    return CHIP_NO_ERROR;
}

class ControllerDeviceInfoProvider : public chip::DeviceLayer::DeviceInstanceInfoProvider
{
public:
    CHIP_ERROR GetVendorName(char *buf, size_t buf_size) override
    {
        return copy_string(buf, buf_size, DEVICE_VENDOR_NAME);
    }
    CHIP_ERROR GetProductName(char *buf, size_t buf_size) override
    {
        return copy_string(buf, buf_size, DEVICE_PRODUCT_NAME);
    }
    CHIP_ERROR GetProductLabel(char *buf, size_t buf_size) override
    {
        return copy_string(buf, buf_size, DEVICE_PRODUCT_NAME);
    }
    CHIP_ERROR GetVendorId(uint16_t &vendorId) override
    {
        vendorId = static_cast<uint16_t>(CHIP_DEVICE_CONFIG_DEVICE_VENDOR_ID);
        return CHIP_NO_ERROR;
    }
    CHIP_ERROR GetProductId(uint16_t &productId) override
    {
        productId = static_cast<uint16_t>(CHIP_DEVICE_CONFIG_DEVICE_PRODUCT_ID);
        return CHIP_NO_ERROR;
    }
    CHIP_ERROR GetHardwareVersion(uint16_t &hardwareVersion) override
    {
        hardwareVersion = static_cast<uint16_t>(CHIP_DEVICE_CONFIG_DEFAULT_DEVICE_HARDWARE_VERSION);
        return CHIP_NO_ERROR;
    }
    CHIP_ERROR GetHardwareVersionString(char *buf, size_t buf_size) override
    {
        return copy_string(buf, buf_size, CHIP_DEVICE_CONFIG_DEFAULT_DEVICE_HARDWARE_VERSION_STRING);
    }
    CHIP_ERROR GetPartNumber(char *, size_t) override { return CHIP_ERROR_NOT_IMPLEMENTED; }
    CHIP_ERROR GetProductURL(char *, size_t) override { return CHIP_ERROR_NOT_IMPLEMENTED; }
    /* Fallback for the CHIP cluster code; esp-matter answers from its data model, which is why
       app_main also creates the serial number attribute. */
    CHIP_ERROR GetSerialNumber(char *buf, size_t buf_size) override
    {
        uint8_t mac[6];
        VerifyOrReturnError(esp_read_mac(mac, ESP_MAC_BASE) == ESP_OK, CHIP_ERROR_INTERNAL);
        char serial[13];
        snprintf(serial, sizeof(serial), "%02X%02X%02X%02X%02X%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
        return copy_string(buf, buf_size, serial);
    }
    CHIP_ERROR GetManufacturingDate(uint16_t &, uint8_t &, uint8_t &) override { return CHIP_ERROR_NOT_IMPLEMENTED; }
    CHIP_ERROR GetRotatingDeviceIdUniqueId(chip::MutableByteSpan &) override { return CHIP_ERROR_NOT_IMPLEMENTED; }
};

ControllerDeviceInfoProvider s_provider;

} // namespace

void device_info_register(void)
{
#if CONFIG_CUSTOM_DEVICE_INSTANCE_INFO_PROVIDER
    esp_matter::set_custom_device_instance_info_provider(&s_provider);
    ESP_LOGI(TAG, "reporting as %s / %s", DEVICE_VENDOR_NAME, DEVICE_PRODUCT_NAME);
#else
    ESP_LOGW(TAG, "CONFIG_CUSTOM_DEVICE_INSTANCE_INFO_PROVIDER is off: vendor and product names stay on the defaults");
#endif
}
