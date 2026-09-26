#include "pinscan.h"

#include <stdio.h>
#include "driver/gpio.h"
#include "esp_private/esp_gpio_reserve.h"
#include "esp_rom_sys.h"
#include "soc/soc_caps.h"
#include "soc/uart_pins.h"

#define SETTLE_US  30   // well past the ~3 us the RC node needs to rise
#define ECHO_TRIES 5

static uint64_t candidate_pins(void)
{
    uint64_t mask = 0;
    for (int pin = 0; pin < SOC_GPIO_PIN_COUNT; pin++) {
        if (!GPIO_IS_VALID_OUTPUT_GPIO(pin) || esp_gpio_is_reserved(BIT64(pin))) {
            continue;   // flash pins are reserved at startup
        }
        if (pin == U0TXD_GPIO_NUM || pin == U0RXD_GPIO_NUM) {
            continue;   // console on J2
        }
        mask |= BIT64(pin);
    }
    return mask;
}

static uint64_t read_levels(uint64_t pins)
{
    uint64_t levels = 0;
    for (int pin = 0; pin < SOC_GPIO_PIN_COUNT; pin++) {
        if ((pins & BIT64(pin)) && gpio_get_level(pin)) {
            levels |= BIT64(pin);
        }
    }
    return levels;
}

// Pins that read low while `pin` is driven low and high again once it is driven high.
static uint64_t followers(int pin, uint64_t cand)
{
    uint64_t others = cand & ~BIT64(pin);

    gpio_set_level(pin, 0);
    gpio_set_direction(pin, GPIO_MODE_OUTPUT);
    esp_rom_delay_us(SETTLE_US);
    uint64_t lo = read_levels(others);
    gpio_set_level(pin, 1);
    esp_rom_delay_us(SETTLE_US);
    uint64_t hi = read_levels(others);
    gpio_set_direction(pin, GPIO_MODE_INPUT);   // pull-up stays on
    esp_rom_delay_us(SETTLE_US);

    return ~lo & hi & others;
}

// Same pattern as LeafBus line_check(): 0x55/0xAA toggle every bit.
static bool echo_clean(int tx, int rx)
{
    static const uint8_t pattern[] = { 0x55, 0xAA, 0x55, 0xAA, 0x0F, 0xF0 };
    const pb_pins_t pins = { tx, rx, -1 };
    int clean = 0;

    if (pb_init(&pins) == ESP_OK) {
        for (int i = 0; i < ECHO_TRIES; i++) {
            bool ok = false;
            pb_xact(pattern, sizeof pattern, NULL, 0, PB_EXPECT_NONE, 0, &ok);
            clean += ok;
        }
    }
    pb_deinit();
    return clean == ECHO_TRIES;
}

esp_err_t pinscan_run(pb_pins_t *found)
{
    uint64_t cand = candidate_pins();
    uint64_t follow[SOC_GPIO_PIN_COUNT] = { 0 };
    bool any_follow = false;
    esp_err_t err = ESP_ERR_NOT_FOUND;

    pb_lock();
    pb_deinit();

    printf("pinscan: candidate GPIOs");
    for (int pin = 0; pin < SOC_GPIO_PIN_COUNT; pin++) {
        if (cand & BIT64(pin)) {
            printf(" %d", pin);
        }
    }
    printf("\n");

    const gpio_config_t io = {
        .pin_bit_mask = cand,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    gpio_config(&io);
    esp_rom_delay_us(100);

    for (int pin = 0; pin < SOC_GPIO_PIN_COUNT; pin++) {
        if (!(cand & BIT64(pin))) {
            continue;
        }
        follow[pin] = followers(pin, cand);
        if (follow[pin]) {
            any_follow = true;
            printf("  GPIO%d low pulls low:", pin);
            for (int q = 0; q < SOC_GPIO_PIN_COUNT; q++) {
                if (follow[pin] & BIT64(q)) {
                    printf(" GPIO%d", q);
                }
            }
            printf("\n");
        }
    }

    for (int tx = 0; tx < SOC_GPIO_PIN_COUNT && err != ESP_OK; tx++) {
        for (int rx = 0; rx < SOC_GPIO_PIN_COUNT && err != ESP_OK; rx++) {
            if (!(follow[tx] & BIT64(rx)) || !echo_clean(tx, rx)) {
                continue;
            }
            uint64_t rest = follow[tx] & ~BIT64(rx);
            found->tx = tx;
            found->rx = rx;
            found->rc = __builtin_popcountll(rest) == 1 ? __builtin_ctzll(rest) : -1;
            err = ESP_OK;
        }
    }

    for (int pin = 0; pin < SOC_GPIO_PIN_COUNT; pin++) {
        if (cand & BIT64(pin)) {
            gpio_reset_pin(pin);
        }
    }
    pb_unlock();

    if (err == ESP_OK) {
        printf("pinscan: TX=GPIO%d RX=GPIO%d RC=", found->tx, found->rx);
        if (found->rc >= 0) {
            printf("GPIO%d\n", found->rc);
        } else {
            printf("unknown (left unconfigured, the one-shot still works)\n");
        }
    } else if (!any_follow) {
        printf("pinscan: no pin pulls any other low. U4, D2 or U3 is not working:\n"
               "  check 3V3 on pin 5 of U3/U4, their orientation, and the module's solder joints\n");
    } else {
        printf("pinscan: loopback found but the echo is corrupted.\n"
               "  Unplug the panel and retry; otherwise check R6 and U3.\n");
    }
    return err;
}
