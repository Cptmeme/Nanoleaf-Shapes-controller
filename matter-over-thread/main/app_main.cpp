/*
   Matter-over-Thread firmware for the Nanoleaf Shapes controller: every panel together is one
   extended colour light (on/off, brightness, colour wheel, xy colour, white temperature), plus an
   on/off switch for a moving rainbow. Commissioning goes over BLE; the BOOT button toggles the light, holding it resets to factory.
*/

#include <esp_err.h>
#include <esp_log.h>
#include <esp_mac.h>
#include <stdio.h>
#include <string.h>
#include <nvs_flash.h>

#include <esp_matter.h>
#include <esp_matter_console.h>
#include <esp_matter_ota.h>

#include <common_macros.h>

#include <app_priv.h>
#include <app_reset.h>
#include "device_info.h"
#if CHIP_DEVICE_CONFIG_ENABLE_THREAD
#include <platform/ESP32/OpenthreadLauncher.h>
#endif

#include <app/server/CommissioningWindowManager.h>
#include <app/server/Server.h>

static const char *TAG = "app_main";
uint16_t light_endpoint_id = 0;
uint16_t rainbow_endpoint_id = 0;

using namespace esp_matter;
using namespace esp_matter::attribute;
using namespace esp_matter::endpoint;
using namespace chip::app::Clusters;

constexpr auto k_timeout_seconds = 300;

static void app_event_cb(const ChipDeviceEvent *event, intptr_t arg)
{
    switch (event->Type) {
    case chip::DeviceLayer::DeviceEventType::kCommissioningComplete:
        ESP_LOGI(TAG, "Commissioning complete");
        break;

    case chip::DeviceLayer::DeviceEventType::kFailSafeTimerExpired:
        ESP_LOGI(TAG, "Commissioning failed, fail safe timer expired");
        break;

    case chip::DeviceLayer::DeviceEventType::kCommissioningWindowOpened:
        ESP_LOGI(TAG, "Commissioning window opened");
        break;

    case chip::DeviceLayer::DeviceEventType::kCommissioningWindowClosed:
        ESP_LOGI(TAG, "Commissioning window closed");
        break;

    case chip::DeviceLayer::DeviceEventType::kFabricRemoved: {
        ESP_LOGI(TAG, "Fabric removed");
        // After the last fabric is gone, make the device findable again
        if (chip::Server::GetInstance().GetFabricTable().FabricCount() == 0) {
            chip::CommissioningWindowManager &commissionMgr = chip::Server::GetInstance().GetCommissioningWindowManager();
            constexpr auto kTimeoutSeconds = chip::System::Clock::Seconds16(k_timeout_seconds);
            if (!commissionMgr.IsCommissioningWindowOpen()) {
                CHIP_ERROR err = commissionMgr.OpenBasicCommissioningWindow(kTimeoutSeconds,
                                                                            chip::CommissioningWindowAdvertisement::kDnssdOnly);
                if (err != CHIP_NO_ERROR) {
                    ESP_LOGE(TAG, "Failed to open commissioning window, err:%" CHIP_ERROR_FORMAT, err.Format());
                }
            }
        }
        break;
    }

    case chip::DeviceLayer::DeviceEventType::kBLEDeinitialized:
        ESP_LOGI(TAG, "BLE deinitialized and memory reclaimed");
        break;

    default:
        break;
    }
}

static esp_err_t app_identification_cb(identification::callback_type_t type, uint16_t endpoint_id, uint8_t effect_id,
                                       uint8_t effect_variant, void *priv_data)
{
    ESP_LOGI(TAG, "Identification callback: type: %u, effect: %u, variant: %u", type, effect_id, effect_variant);
    return ESP_OK;
}

// Drive the panels before the attribute is stored; attributes that are not ours return ESP_OK.
static esp_err_t app_attribute_update_cb(attribute::callback_type_t type, uint16_t endpoint_id, uint32_t cluster_id,
                                         uint32_t attribute_id, esp_matter_attr_val_t *val, void *priv_data)
{
    if (type == PRE_UPDATE) {
        return app_driver_attribute_update((app_driver_handle_t)priv_data, endpoint_id, cluster_id, attribute_id, val);
    }
    return ESP_OK;
}

/* A colour command on the light switches the rainbow off, so picking a colour shows that colour. Runs
   before the command itself, so it also catches a colour the light already has: that changes no attribute
   and never reaches the attribute callback. Switching the rainbow endpoint keeps controllers in step. */
static esp_err_t colour_command_cb(const chip::app::ConcreteCommandPath &path, chip::TLV::TLVReader &tlv, void *opaque)
{
    if (rainbow_endpoint_id == 0 || path.mEndpointId != light_endpoint_id) {
        return ESP_OK;
    }
    esp_matter_attr_val_t val = esp_matter_invalid(NULL);
    attribute::get_val(attribute::get(rainbow_endpoint_id, OnOff::Id, OnOff::Attributes::OnOff::Id), &val);
    if (val.val.b) {
        ESP_LOGI(TAG, "colour command: rainbow off");
        val = esp_matter_bool(false);
        attribute::update(rainbow_endpoint_id, OnOff::Id, OnOff::Attributes::OnOff::Id, &val);
    }
    return ESP_OK; // anything else would stop the colour command
}

extern "C" void app_main()
{
    esp_err_t err = ESP_OK;

    nvs_flash_init();

    app_driver_handle_t light_handle = app_driver_light_init();
    app_driver_handle_t button_handle = app_driver_button_init();
    app_reset_button_register(button_handle); // hold BOOT for a factory reset

    node::config_t node_config;
    node_t *node = node::create(&node_config, app_attribute_update_cb, app_identification_cb);
    ABORT_APP_ON_FAILURE(node != nullptr, ESP_LOGE(TAG, "Failed to create Matter node"));

    /* esp-matter's Basic Information cluster has no serial number attribute unless it is created;
       controllers that ask for it get a failed read otherwise. The MAC is unique and stable. */
    static char serial_number[13] = {0};
    uint8_t mac[6];
    if (esp_read_mac(mac, ESP_MAC_BASE) == ESP_OK) {
        snprintf(serial_number, sizeof(serial_number), "%02X%02X%02X%02X%02X%02X",
                 mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
        endpoint_t *root_endpoint = endpoint::get(node, 0);
        cluster_t *basic_info_cluster = root_endpoint ? cluster::get(root_endpoint, BasicInformation::Id) : nullptr;
        if (!basic_info_cluster ||
            !cluster::basic_information::attribute::create_serial_number(basic_info_cluster, serial_number,
                                                                         strlen(serial_number))) {
            ESP_LOGW(TAG, "Could not add the serial number attribute");
        }
    }

    extended_color_light::config_t light_config;
    light_config.on_off.on_off = DEFAULT_POWER;
    light_config.on_off_lighting.start_up_on_off = nullptr;
    light_config.level_control.current_level = DEFAULT_BRIGHTNESS; // first boot only; then restored from flash
    /* Null means "the previous level": for OnLevel on every On command, for StartUpCurrentLevel after a
       power cut. A value here would send every On to that brightness (the example's 128 = 50 %). */
    light_config.level_control.on_level = nullptr;
    light_config.level_control_lighting.start_up_current_level = nullptr;
    light_config.color_control.color_mode = (uint8_t)ColorControl::ColorMode::kCurrentHueAndCurrentSaturation;
    light_config.color_control.enhanced_color_mode = (uint8_t)ColorControl::ColorMode::kCurrentHueAndCurrentSaturation;
    light_config.color_control_color_temperature.start_up_color_temperature_mireds = nullptr;

    endpoint_t *endpoint = extended_color_light::create(node, &light_config, ENDPOINT_FLAG_NONE, light_handle);
    ABORT_APP_ON_FAILURE(endpoint != nullptr, ESP_LOGE(TAG, "Failed to create extended color light endpoint"));
    light_endpoint_id = endpoint::get_id(endpoint);
    ESP_LOGI(TAG, "Light created with endpoint_id %d", light_endpoint_id);

    /* extended_color_light only installs the colour temperature and xy features. Without the
       hue/saturation feature, Apple Home shows a white-temperature slider and no colour wheel. */
    cluster_t *color_control_cluster = cluster::get(endpoint, ColorControl::Id);
    ABORT_APP_ON_FAILURE(color_control_cluster != nullptr, ESP_LOGE(TAG, "Failed to find the color control cluster"));
    cluster::color_control::feature::hue_saturation::config_t hue_saturation_config;
    hue_saturation_config.current_hue = DEFAULT_HUE;
    hue_saturation_config.current_saturation = DEFAULT_SATURATION;
    err = cluster::color_control::feature::hue_saturation::add(color_control_cluster, &hue_saturation_config);
    ABORT_APP_ON_FAILURE(err == ESP_OK, ESP_LOGE(TAG, "Failed to add hue/saturation, err:%d", err));

    /* These change rapidly during fades; persist them after the fact, not on every step. */
    attribute::set_deferred_persistence(attribute::get(light_endpoint_id, LevelControl::Id,
                                                       LevelControl::Attributes::CurrentLevel::Id));
    attribute::set_deferred_persistence(attribute::get(light_endpoint_id, ColorControl::Id,
                                                       ColorControl::Attributes::CurrentX::Id));
    attribute::set_deferred_persistence(attribute::get(light_endpoint_id, ColorControl::Id,
                                                       ColorControl::Attributes::CurrentY::Id));
    attribute::set_deferred_persistence(attribute::get(light_endpoint_id, ColorControl::Id,
                                                       ColorControl::Attributes::ColorTemperatureMireds::Id));

    /* A second endpoint that shows up as a plain on/off switch and runs a moving rainbow across the
       panels. The light's own on/off and brightness still apply while it runs. Like the light, it
       comes back in its previous state after a power cut (StartUpOnOff null). */
    on_off_plug_in_unit::config_t rainbow_config;
    rainbow_config.on_off.on_off = false;
    rainbow_config.on_off_lighting.start_up_on_off = nullptr;
    endpoint_t *rainbow_endpoint = on_off_plug_in_unit::create(node, &rainbow_config, ENDPOINT_FLAG_NONE, light_handle);
    ABORT_APP_ON_FAILURE(rainbow_endpoint != nullptr, ESP_LOGE(TAG, "Failed to create the rainbow endpoint"));
    rainbow_endpoint_id = endpoint::get_id(rainbow_endpoint);
    ESP_LOGI(TAG, "Rainbow switch created with endpoint_id %d", rainbow_endpoint_id);

    /* Every colour command (hue, saturation, xy, white temperature) stops the rainbow; StopMoveStep only
       halts a running fade. */
    for (command_t *cmd = command::get_first(color_control_cluster); cmd; cmd = command::get_next(cmd)) {
        if (command::get_id(cmd) != ColorControl::Commands::StopMoveStep::Id) {
            command::set_user_callback(cmd, colour_command_cb);
        }
    }

#if CHIP_DEVICE_CONFIG_ENABLE_THREAD
    esp_openthread_platform_config_t config = {
        .radio_config = ESP_OPENTHREAD_DEFAULT_RADIO_CONFIG(),
        .host_config = ESP_OPENTHREAD_DEFAULT_HOST_CONFIG(),
        .port_config = ESP_OPENTHREAD_DEFAULT_PORT_CONFIG(),
    };
    set_openthread_platform_config(&config);
#endif

    device_info_register(); // before esp_matter::start()

    err = esp_matter::start(app_event_cb);
    ABORT_APP_ON_FAILURE(err == ESP_OK, ESP_LOGE(TAG, "Failed to start Matter, err:%d", err));

    app_driver_light_set_defaults(light_endpoint_id);

#if CONFIG_ENABLE_CHIP_SHELL
    esp_matter::console::diagnostics_register_commands();
    esp_matter::console::factoryreset_register_commands();
    esp_matter::console::attribute_register_commands();
#if CONFIG_OPENTHREAD_CLI
    esp_matter::console::otcli_register_commands();
#endif
    esp_matter::console::init();
#endif
}
