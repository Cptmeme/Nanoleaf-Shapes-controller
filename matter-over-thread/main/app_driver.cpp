/*
   Glue between the Matter data model and the Nanoleaf Shapes panels.

   One extended colour light drives every panel. The colour goes to the panels' RGB and white LEDs,
   and the brightness to their own hardware dimming (FC 04), so a dim colour keeps full colour
   resolution. A second endpoint, an on/off plug-in unit, switches a moving rainbow across the panels
   in place of the colour; the light's on/off and brightness still apply. The panel bus engine (../../firmware/main/panelbus.c) enumerates the panels by itself
   and keeps them polled; whenever it re-enumerates (start-up, hot-plug), the light state is sent again.
*/

#include <esp_log.h>
#include <esp_timer.h>
#include <string.h>

#include <esp_matter.h>
#include <app_priv.h>
#include <common_macros.h>

#include <device.h>
#include <button_gpio.h>
#include <color_format.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "panelbus.h"

using namespace chip::app::Clusters;
using namespace esp_matter;

static const char *TAG = "app_driver";
extern uint16_t light_endpoint_id;
extern uint16_t rainbow_endpoint_id;

#define REFRESH_CHECK_MS 50     // how often to look for a re-enumeration: one bus poll period
#define KELVIN_PER_MIRED 1000000

/* Moving rainbow: how often a frame is pushed, and how far the hue wheel turns each frame.
   2 degrees every 40 ms walks the whole wheel past a panel in about 7 seconds. */
#define RAINBOW_STEP_MS  40
#define RAINBOW_HUE_STEP 2

enum color_mode_t { MODE_HS, MODE_XY, MODE_CT };

/* The light state, in the units the colour helpers use. Written from the Matter task, read by the
   refresh timer, so all access goes through s_lock. */
static SemaphoreHandle_t s_lock;
static bool         s_power  = DEFAULT_POWER;
static uint8_t      s_level  = DEFAULT_BRIGHTNESS;   // Matter 0-254
static color_mode_t s_mode   = MODE_HS;
static HS_color_t   s_hs     = { 180, 100 };          // degrees, percent
static XY_color_t   s_xy     = { 0, 0 };              // Matter units
static uint32_t     s_kelvin = 2700;
static bool         s_rainbow;            // the rainbow runs in place of the colour
static uint16_t     s_phase;              // degrees the rainbow has turned
static uint32_t     s_shown_enumerations;
static bool         s_state_loaded;       // the stored attributes are in; until then show nothing

/* The endpoint wants a non-null private-data pointer; the panel bus is a singleton. */
static uint8_t s_light_token;

/* What the two small buttons step through: a ring of fixed colours with the moving rainbow as the last
   stop, so holding one direction walks the colours, reaches the rainbow and comes back to the first
   colour. Hue and saturation are in Matter's 0..254 units, which is what the attributes take, so these
   are written straight through rather than converted. White is saturation 0, where hue stops mattering. */
static const struct {
    const char *name;
    uint8_t hue;
    uint8_t saturation;
} k_cycle[] = {
    { "red",     0,   254 },
    { "orange",  21,  254 },
    { "yellow",  42,  254 },
    { "green",   85,  254 },
    { "cyan",    127, 254 },
    { "blue",    170, 254 },
    { "purple",  191, 254 },
    { "magenta", 212, 254 },
    { "white",   0,   0   },
};
#define CYCLE_COLOURS (int)(sizeof k_cycle / sizeof k_cycle[0])
#define CYCLE_STEPS   (CYCLE_COLOURS + 1)   /* + the rainbow */

/* Which stop the cycle is on, or -1 when the colour came from somewhere else (a controller, or the
   stored value at boot). From -1, forward starts at the first colour and back starts at the rainbow. */
static int s_cycle_step = -1;

/* Colour of every panel as RGBW. The white share of the colour (the smallest of R, G and B) moves
   to the white LEDs: the panels' RGB-only white is visibly blue, their white LEDs are neutral. */
static void current_rgbw(uint8_t *r, uint8_t *g, uint8_t *b, uint8_t *w)
{
    RGB_color_t rgb;
    switch (s_mode) {
    case MODE_XY:
        xy_to_rgb(s_xy, 255, &rgb);
        break;
    case MODE_CT: {
        HS_color_t hs;
        temp_to_hs(s_kelvin, &hs);
        hsv_to_rgb(hs, 100, &rgb);
        break;
    }
    default:
        hsv_to_rgb(s_hs, 100, &rgb);
        break;
    }
    uint8_t white = rgb.red < rgb.green ? rgb.red : rgb.green;
    if (rgb.blue < white) {
        white = rgb.blue;
    }
    *r = rgb.red - white;
    *g = rgb.green - white;
    *b = rgb.blue - white;
    *w = white;
}

/* A full hue wheel spread over the panels in layout order (along the chain), turned by s_phase so
   the colours travel. The bus lock keeps the panel count steady while the frame is built. Lock held. */
static void push_rainbow_locked()
{
    pb_color_t colors[PB_MAX_PANELS];

    pb_lock();
    int n = pb_state()->npanels;
    for (int pos = 0; pos < n; pos++) {
        HS_color_t hs = { (uint16_t)((s_phase + pos * 360 / n) % 360), 100 };
        RGB_color_t rgb;
        hsv_to_rgb(hs, 100, &rgb);
        colors[pb_chunk_index(n, pos)] = { rgb.red, rgb.green, rgb.blue, 0, CONFIG_NANOLEAF_TRANSITION, false };
    }
    if (n > 0) {
        pb_push(colors, n);
    }
    pb_unlock();
}

/* Send the whole state to the panels. Lock held. */
static void render_locked()
{
    const uint8_t t = CONFIG_NANOLEAF_TRANSITION;
    if (!s_state_loaded || pb_state()->npanels == 0) {
        return; // the refresh task catches up once both the stored state and the panels are there
    }
    if (!s_power) {
        pb_fill(0, 0, 0, 0, t);
        return;
    }
    pb_brightness((uint8_t)((s_level * 255 + MATTER_BRIGHTNESS / 2) / MATTER_BRIGHTNESS));
    if (s_rainbow) {
        push_rainbow_locked();
        return;
    }
    uint8_t r, g, b, w;
    current_rgbw(&r, &g, &b, &w);
    pb_fill(r, g, b, w, t);
}

static void render()
{
    if (xSemaphoreTake(s_lock, pdMS_TO_TICKS(100)) != pdTRUE) {
        ESP_LOGW(TAG, "light state busy, frame skipped");
        return;
    }
    render_locked();
    xSemaphoreGive(s_lock);
}

/* Panels power up dark, and a panel plugged in while running joins dark; after every enumeration,
   show all of them the light state again. Its own task rather than a timer: a render builds a frame
   for up to 64 panels on the stack. */
static void refresh_task(void *arg)
{
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(REFRESH_CHECK_MS));
        uint32_t enumerations = pb_state()->enumerations;
        if (enumerations != s_shown_enumerations) {
            s_shown_enumerations = enumerations;
            ESP_LOGI(TAG, "%d panel(s) found, showing the light state", pb_state()->npanels);
            render();
        }
    }
}

/* Turns the rainbow a step at a time while it is on and the light is lit. */
static void rainbow_task(void *arg)
{
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(RAINBOW_STEP_MS));
        if (xSemaphoreTake(s_lock, pdMS_TO_TICKS(100)) != pdTRUE) {
            continue;
        }
        if (s_rainbow && s_power && s_state_loaded) {
            s_phase = (uint16_t)((s_phase + RAINBOW_HUE_STEP) % 360);
            push_rainbow_locked();
        }
        xSemaphoreGive(s_lock);
    }
}

/* Update one field of the state under the lock, then show it. */
#define UPDATE_AND_RENDER(statement)                                        \
    do {                                                                    \
        if (xSemaphoreTake(s_lock, pdMS_TO_TICKS(100)) != pdTRUE) {         \
            return ESP_ERR_TIMEOUT;                                         \
        }                                                                   \
        statement;                                                          \
        render_locked();                                                    \
        xSemaphoreGive(s_lock);                                             \
    } while (0)

static esp_err_t set_power(bool on)          { UPDATE_AND_RENDER(s_power = on); return ESP_OK; }
static esp_err_t set_level(uint8_t level)    { UPDATE_AND_RENDER(s_level = level); return ESP_OK; }
static esp_err_t set_hue(uint8_t hue)
{
    UPDATE_AND_RENDER(s_hs.hue = (uint16_t)hue * 360 / (MATTER_HUE + 1); s_mode = MODE_HS);
    return ESP_OK;
}
static esp_err_t set_saturation(uint8_t sat)
{
    UPDATE_AND_RENDER(s_hs.saturation = (uint8_t)((uint16_t)sat * 100 / MATTER_SATURATION); s_mode = MODE_HS);
    return ESP_OK;
}
static esp_err_t set_mireds(uint16_t mireds)
{
    if (mireds == 0) {
        return ESP_OK;
    }
    UPDATE_AND_RENDER(s_kelvin = KELVIN_PER_MIRED / mireds; s_mode = MODE_CT);
    return ESP_OK;
}
static esp_err_t set_x(uint16_t x) { UPDATE_AND_RENDER(s_xy.x = x; s_mode = MODE_XY); return ESP_OK; }
static esp_err_t set_y(uint16_t y) { UPDATE_AND_RENDER(s_xy.y = y; s_mode = MODE_XY); return ESP_OK; }
static esp_err_t set_rainbow(bool on)
{
    UPDATE_AND_RENDER(s_rainbow = on); // off puts the light's colour straight back
    ESP_LOGI(TAG, "rainbow %s", on ? "on" : "off");
    return ESP_OK;
}

esp_err_t app_driver_attribute_update(app_driver_handle_t driver_handle, uint16_t endpoint_id, uint32_t cluster_id,
                                      uint32_t attribute_id, esp_matter_attr_val_t *val)
{
    esp_err_t err = ESP_OK;
    if (rainbow_endpoint_id != 0 && endpoint_id == rainbow_endpoint_id) {
        /* Endpoint 0 is the root node, so the id only counts once app_main has created the switch. */
        if (cluster_id == OnOff::Id && attribute_id == OnOff::Attributes::OnOff::Id) {
            err = set_rainbow(val->val.b);
        }
    } else if (endpoint_id != light_endpoint_id) {
        return ESP_OK;
    } else if (cluster_id == OnOff::Id && attribute_id == OnOff::Attributes::OnOff::Id) {
        err = set_power(val->val.b);
    } else if (cluster_id == LevelControl::Id && attribute_id == LevelControl::Attributes::CurrentLevel::Id) {
        err = set_level(val->val.u8);
    } else if (cluster_id == ColorControl::Id) {
        if (attribute_id == ColorControl::Attributes::CurrentHue::Id) {
            err = set_hue(val->val.u8);
        } else if (attribute_id == ColorControl::Attributes::CurrentSaturation::Id) {
            err = set_saturation(val->val.u8);
        } else if (attribute_id == ColorControl::Attributes::ColorTemperatureMireds::Id) {
            err = set_mireds(val->val.u16);
        } else if (attribute_id == ColorControl::Attributes::CurrentX::Id) {
            err = set_x(val->val.u16);
        } else if (attribute_id == ColorControl::Attributes::CurrentY::Id) {
            err = set_y(val->val.u16);
        }
    }
    /* Never fail the attribute write because the bus was busy: esp-matter would reject the update
       and the controller's view would drift from what the panels show. */
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "panel update failed: %s - keeping the attribute anyway", esp_err_to_name(err));
    }
    return ESP_OK;
}

static uint8_t get_u8(uint16_t endpoint_id, uint32_t cluster_id, uint32_t attribute_id)
{
    esp_matter_attr_val_t val = esp_matter_invalid(NULL);
    attribute::get_val(attribute::get(endpoint_id, cluster_id, attribute_id), &val);
    return val.val.u8;
}

static uint16_t get_u16(uint16_t endpoint_id, uint32_t cluster_id, uint32_t attribute_id)
{
    esp_matter_attr_val_t val = esp_matter_invalid(NULL);
    attribute::get_val(attribute::get(endpoint_id, cluster_id, attribute_id), &val);
    return val.val.u16;
}

esp_err_t app_driver_light_set_defaults(uint16_t endpoint_id)
{
    /* Seed every colour representation, not only the active one: the driver learns values only
       from change callbacks, so anything not seeded here would keep its start-up default until a
       controller wrote a different value. */
    uint16_t mireds = get_u16(endpoint_id, ColorControl::Id, ColorControl::Attributes::ColorTemperatureMireds::Id);
    uint8_t color_mode = get_u8(endpoint_id, ColorControl::Id, ColorControl::Attributes::ColorMode::Id);
    esp_matter_attr_val_t on = esp_matter_invalid(NULL);
    attribute::get_val(attribute::get(endpoint_id, OnOff::Id, OnOff::Attributes::OnOff::Id), &on);
    esp_matter_attr_val_t rainbow = esp_matter_invalid(NULL);
    if (rainbow_endpoint_id != 0) {
        attribute::get_val(attribute::get(rainbow_endpoint_id, OnOff::Id, OnOff::Attributes::OnOff::Id), &rainbow);
    }

    if (xSemaphoreTake(s_lock, pdMS_TO_TICKS(1000)) != pdTRUE) {
        return ESP_ERR_TIMEOUT;
    }
    s_level = get_u8(endpoint_id, LevelControl::Id, LevelControl::Attributes::CurrentLevel::Id);
    s_hs.hue = (uint16_t)get_u8(endpoint_id, ColorControl::Id, ColorControl::Attributes::CurrentHue::Id) * 360 /
               (MATTER_HUE + 1);
    s_hs.saturation = (uint8_t)((uint16_t)get_u8(endpoint_id, ColorControl::Id,
                                                 ColorControl::Attributes::CurrentSaturation::Id) * 100 /
                                MATTER_SATURATION);
    if (mireds) {
        s_kelvin = KELVIN_PER_MIRED / mireds;
    }
    s_xy.x = get_u16(endpoint_id, ColorControl::Id, ColorControl::Attributes::CurrentX::Id);
    s_xy.y = get_u16(endpoint_id, ColorControl::Id, ColorControl::Attributes::CurrentY::Id);
    s_mode = color_mode == (uint8_t)ColorControl::ColorMode::kColorTemperature ? MODE_CT
           : color_mode == (uint8_t)ColorControl::ColorMode::kCurrentXAndCurrentY ? MODE_XY
           : MODE_HS;
    s_power = on.val.b;
    s_rainbow = rainbow_endpoint_id != 0 && rainbow.val.b;
    s_state_loaded = true;
    render_locked();
    xSemaphoreGive(s_lock);
    return ESP_OK;
}

app_driver_handle_t app_driver_light_init()
{
    const pb_pins_t pins = {
        .tx = CONFIG_NANOLEAF_BUS_TX_GPIO,
        .rx = CONFIG_NANOLEAF_BUS_RX_GPIO,
        .rc = CONFIG_NANOLEAF_BUS_RC_GPIO,
    };
    s_lock = xSemaphoreCreateMutex();
    esp_err_t err = pb_init(&pins);
    if (!s_lock || err != ESP_OK) {
        ESP_LOGE(TAG, "panel bus init failed on TX %d RX %d: %s", pins.tx, pins.rx, esp_err_to_name(err));
        return NULL;
    }
    pb_poll_start(); // polls and enumerates by itself
    xTaskCreate(refresh_task, "panel_refresh", 4096, NULL, 4, NULL);
    xTaskCreate(rainbow_task, "rainbow", 4096, NULL, 4, NULL);
    ESP_LOGI(TAG, "panel bus on TX GPIO%d, RX GPIO%d", pins.tx, pins.rx);
    return (app_driver_handle_t)&s_light_token;
}

/* The BOOT button changes the OnOff attribute rather than the panels directly, so controllers and
   apps stay in step with what somebody did at the wall. */
static void button_toggle_cb(void *arg, void *data)
{
    attribute_t *attribute = attribute::get(light_endpoint_id, OnOff::Id, OnOff::Attributes::OnOff::Id);
    esp_matter_attr_val_t val = esp_matter_invalid(NULL);
    attribute::get_val(attribute, &val);
    val.val.b = !val.val.b;
    attribute::update(light_endpoint_id, OnOff::Id, OnOff::Attributes::OnOff::Id, &val);
}

app_driver_handle_t app_driver_button_init()
{
    button_handle_t handle = NULL;
    const button_config_t btn_cfg = {0};
    const button_gpio_config_t btn_gpio_cfg = button_driver_get_config();

    if (iot_button_new_gpio_device(&btn_cfg, &btn_gpio_cfg, &handle) != ESP_OK) {
        ESP_LOGE(TAG, "failed to create the BOOT button");
        return NULL;
    }
    iot_button_register_cb(handle, BUTTON_SINGLE_CLICK, NULL, button_toggle_cb, NULL);
    return (app_driver_handle_t)handle;
}

/* Move the cycle by one stop and show it. Like the BOOT button, this writes the data model rather than
   the panels, so a controller watching the light sees the colour somebody picked at the wall. Selecting
   a colour switches the rainbow off; the rainbow stop switches it on and leaves the colour alone, so
   stepping off the rainbow puts the previous colour straight back. */
static void cycle_step(int delta)
{
    if (light_endpoint_id == 0) {
        return;
    }
    int step = s_cycle_step < 0 ? (delta > 0 ? 0 : CYCLE_STEPS - 1)
                                : ((s_cycle_step + delta) % CYCLE_STEPS + CYCLE_STEPS) % CYCLE_STEPS;
    s_cycle_step = step;

    bool want_rainbow = step == CYCLE_COLOURS;
    if (rainbow_endpoint_id != 0) {
        esp_matter_attr_val_t on = esp_matter_bool(want_rainbow);
        attribute::update(rainbow_endpoint_id, OnOff::Id, OnOff::Attributes::OnOff::Id, &on);
    }
    if (want_rainbow) {
        ESP_LOGI(TAG, "cycle %d/%d: rainbow", step + 1, CYCLE_STEPS);
        return;
    }

    /* Saturation first: at white (saturation 0) the hue is arbitrary, and writing it first would show a
       moment of the old saturation at the new hue. Each write renders, so the order is visible. */
    esp_matter_attr_val_t sat = esp_matter_uint8(k_cycle[step].saturation);
    attribute::update(light_endpoint_id, ColorControl::Id, ColorControl::Attributes::CurrentSaturation::Id, &sat);
    esp_matter_attr_val_t hue = esp_matter_uint8(k_cycle[step].hue);
    attribute::update(light_endpoint_id, ColorControl::Id, ColorControl::Attributes::CurrentHue::Id, &hue);

    /* set_hue and set_saturation already put the driver in HS mode. This is for the controller's sake:
       ColorMode is what tells it to show the hue wheel rather than a colour temperature slider. */
    esp_matter_attr_val_t mode = esp_matter_enum8((uint8_t)ColorControl::ColorMode::kCurrentHueAndCurrentSaturation);
    attribute::update(light_endpoint_id, ColorControl::Id, ColorControl::Attributes::ColorMode::Id, &mode);
    attribute::update(light_endpoint_id, ColorControl::Id, ColorControl::Attributes::EnhancedColorMode::Id, &mode);

    ESP_LOGI(TAG, "cycle %d/%d: %s (hue %u, sat %u)", step + 1, CYCLE_STEPS,
             k_cycle[step].name, k_cycle[step].hue, k_cycle[step].saturation);
}

/* Brightness from the wall. Matter's level is 0..254, so one 10% step is 25.4 and the arithmetic is done
   in percent to keep the steps landing on round numbers wherever the app left the level. */
#define LEVEL_MAX      MATTER_BRIGHTNESS      /* 254 */
#define LEVEL_MIN_PCT  10                     /* a press never leaves the panels below this */
#define LEVEL_STEP_PCT 10                     /* one tap */
#define RAMP_MS        150                    /* how often a held button rewrites the level */
#define RAMP_STEP      10                     /* and by how much: 254/10 * 150 ms is about 3.8 s end to end */
#define RESET_HOLD_MS  10000                  /* power held this long erases the Matter pairing */

static bool s_ramped;        /* a hold ramped, so swallow the click the button may raise on release */

static uint8_t level_get()
{
    return get_u8(light_endpoint_id, LevelControl::Id, LevelControl::Attributes::CurrentLevel::Id);
}

/* Matter's range is 1..254, so no whole level is exactly 10%: the mark for one tenth is 25.4, stored as
   25, which is 9.84%. Truncating that reads back as 9% and makes the log contradict itself one line
   later. Round instead -- this is for display only, the marks themselves are compared as levels. */
static int level_pct(uint8_t level)
{
    return (level * 100 + LEVEL_MAX / 2) / LEVEL_MAX;
}

/* CurrentLevel is a NULLABLE uint8, not a plain one -- create_current_level() takes nullable<uint8_t>.
   Writing it with esp_matter_uint8 is rejected with ESP_ERR_INVALID_ARG (258) and the attribute keeps
   its old value, which reads back as though nothing happened. The panels still moved, because the
   driver renders from the value handed to the PRE_UPDATE callback before the store refuses it, so the
   only visible symptom was a brightness that always stepped from the same place. */
static void level_set(int level)
{
    if (level < 1) level = 1;
    if (level > LEVEL_MAX) level = LEVEL_MAX;
    esp_matter_attr_val_t val = esp_matter_nullable_uint8((uint8_t)level);
    esp_err_t err = attribute::update(light_endpoint_id, LevelControl::Id,
                                      LevelControl::Attributes::CurrentLevel::Id, &val);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "level %d rejected: %s", level, esp_err_to_name(err));
    }
}

/* Below about 10% the panels read as off, which makes every button look broken: the colour changes, the
   cycle moves, and nothing on the wall shows it. So a press at the wall always leaves the level visible.
   The app keeps the full range -- this is only on the physical buttons, where there is no slider to see
   what went wrong with. Returns the level now in force. */
static uint8_t level_floor()
{
    uint8_t cur = level_get();
    int floor_level = LEVEL_MIN_PCT * LEVEL_MAX / 100;
    if (cur >= floor_level) {
        return cur;
    }
    ESP_LOGI(TAG, "level %u was below %d%%, lifting to %d", cur, LEVEL_MIN_PCT, floor_level);
    level_set(floor_level);
    return (uint8_t)floor_level;
}

static void colour_cb(void *arg, void *data)
{
    level_floor();
    cycle_step(+1);
}

/* A tap goes to the next 10% mark above where we are, so a level the app left at 37% goes to 40 rather
   than 47, and 100% wraps to the bottom. The marks are searched rather than calculated: going through a
   percentage truncates. 40% stores as 101, 101 * 100 / 254 is 39, which rounds back down to 30 and steps
   to 40 again -- the first version of this sat at 40% forever. Comparing against the marks themselves
   cannot do that, because the level written is always exactly one of them. */
static void bright_click_cb(void *arg, void *data)
{
    if (s_ramped) {           /* this click is the tail of a hold, not a separate press */
        s_ramped = false;
        return;
    }
    uint8_t cur = level_floor();
    int tenth = 0;
    for (int t = 1; t <= 10; t++) {
        if (t * LEVEL_MAX / 10 > cur) {
            tenth = t;
            break;
        }
    }
    if (tenth == 0) {         /* at or above the top mark: wrap round to the floor */
        tenth = LEVEL_MIN_PCT / 10;
    }
    ESP_LOGI(TAG, "brightness tap: %u (%d%%) -> %d (%d%%)", cur, level_pct(cur),
             tenth * LEVEL_MAX / 10, level_pct(tenth * LEVEL_MAX / 10));
    level_set(tenth * LEVEL_MAX / 10);
}

/* Held: ramp up and stop at the top, keeping whatever it reached when released. The event repeats every
   20 ms, which is far too often to rewrite an attribute -- each write renders the panels and reports to
   every subscribed controller -- so it is rate limited to RAMP_MS. */
static void bright_hold_cb(void *arg, void *data)
{
    static int64_t next_write;
    int64_t now = esp_timer_get_time();
    if (!s_ramped) {
        s_ramped = true;
        next_write = 0;       /* first hold event acts at once */
    }
    if (now < next_write) {
        return;
    }
    next_write = now + RAMP_MS * 1000LL;
    uint8_t cur = level_floor();
    if (cur >= LEVEL_MAX) {
        return;               /* at the top: stay there, do not wrap */
    }
    ESP_LOGI(TAG, "brightness ramp: %d%% -> %d%%", level_pct(cur), level_pct(cur + RAMP_STEP));
    level_set(cur + RAMP_STEP);
}

/* A plain GPIO button: the switch shorts the pin to GND and the board carries only a debounce cap on
   each line, so the internal pull-up does the rest. */
static button_handle_t user_button(int gpio, const char *what, uint16_t long_press_ms = 0)
{
    if (gpio < 0) {
        return NULL;
    }
    button_handle_t handle = NULL;
    /* 0 means the component's own default, which is a full second before a hold registers. The
       brightness button passes something shorter, because a second of nothing feels broken. */
    const button_config_t btn_cfg = { .long_press_time = long_press_ms, .short_press_time = 0 };
    const button_gpio_config_t gpio_cfg = {
        .gpio_num = gpio,
        .active_level = 0,
        .enable_power_save = false,
        .disable_pull = false,
    };
    if (iot_button_new_gpio_device(&btn_cfg, &gpio_cfg, &handle) != ESP_OK) {
        ESP_LOGE(TAG, "failed to create the %s button on GPIO%d", what, gpio);
        return NULL;
    }
    ESP_LOGI(TAG, "%s button on GPIO%d", what, gpio);
    return handle;
}

/* Two red flashes to confirm the pairing has gone. The device reboots immediately afterwards, so without
   this there is nothing at all to see and no way to tell a reset from a crash.

   Driven straight at the panels rather than through the data model: those attributes are about to be
   erased, so writing them would only persist state that is being thrown away, and a controller would be
   told about a colour the device is not going to keep. The rainbow is stopped first, or rainbow_task
   overwrites the flashes every 40 ms. Brightness goes to full because the whole point is to be visible
   whatever the level happened to be. */
static void blink_red(int times)
{
    if (xSemaphoreTake(s_lock, pdMS_TO_TICKS(200)) == pdTRUE) {
        s_rainbow = false;
        xSemaphoreGive(s_lock);
    }
    pb_brightness(255);
    for (int i = 0; i < times; i++) {
        pb_fill(255, 0, 0, 0, 0);
        vTaskDelay(pdMS_TO_TICKS(250));
        pb_fill(0, 0, 0, 0, 0);
        vTaskDelay(pdMS_TO_TICKS(250));
    }
}

/* Held for RESET_HOLD_MS, the power button erases the Matter pairing. SW1 and SW2 are not fitted on this
   board, so the usual hold-BOOT route does not exist and this is the only way to re-commission without a
   serial cable. The button component fires BUTTON_LONG_PRESS_START once, at the press_time registered
   with it, so this cannot repeat while the button stays down. */
static void power_reset_cb(void *arg, void *data)
{
    ESP_LOGW(TAG, "power held %d s: erasing the Matter pairing", RESET_HOLD_MS / 1000);
    blink_red(2);
    esp_matter::factory_reset();   /* wipes the fabrics and reboots */
}

/* The power button lifts the level too, so switching the light on at the wall can never produce a panel
   that is on but too dim to see. Switching it off leaves the level alone. */
static void power_cb(void *arg, void *data)
{
    attribute_t *attribute = attribute::get(light_endpoint_id, OnOff::Id, OnOff::Attributes::OnOff::Id);
    esp_matter_attr_val_t val = esp_matter_invalid(NULL);
    attribute::get_val(attribute, &val);
    if (!val.val.b) {
        level_floor();
    }
    val.val.b = !val.val.b;
    attribute::update(light_endpoint_id, OnOff::Id, OnOff::Attributes::OnOff::Id, &val);
}

void app_driver_user_buttons_init()
{
    button_handle_t power = user_button(CONFIG_NANOLEAF_BTN_POWER_GPIO, "power");
    if (power) {
        iot_button_register_cb(power, BUTTON_SINGLE_CLICK, NULL, power_cb, NULL);
        button_event_args_t reset_args = {};
        reset_args.long_press.press_time = RESET_HOLD_MS;
        iot_button_register_cb(power, BUTTON_LONG_PRESS_START, &reset_args, power_reset_cb, NULL);
        ESP_LOGI(TAG, "hold power %d s to erase the Matter pairing", RESET_HOLD_MS / 1000);
    }
    button_handle_t colour = user_button(CONFIG_NANOLEAF_BTN_COLOUR_GPIO, "colour cycle");
    if (colour) {
        iot_button_register_cb(colour, BUTTON_SINGLE_CLICK, NULL, colour_cb, NULL);
    }
    button_handle_t bright = user_button(CONFIG_NANOLEAF_BTN_BRIGHT_GPIO, "brightness", 400);
    if (bright) {
        iot_button_register_cb(bright, BUTTON_SINGLE_CLICK, NULL, bright_click_cb, NULL);
        iot_button_register_cb(bright, BUTTON_LONG_PRESS_HOLD, NULL, bright_hold_cb, NULL);
    }
}
