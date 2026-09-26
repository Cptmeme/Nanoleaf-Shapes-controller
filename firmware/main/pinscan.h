// Find which module GPIOs are wired to the bus TX, RX and RC nets.
//
// The board has a loopback that needs no panel: TX low pulls U4's OE low
// through D2, U4 drives U3, and U3 drives RX through R6. A candidate pin that
// is driven low therefore pulls two others low: RX and the RC node. Of those
// two, only RX carries a clean UART echo.
#pragma once

#include "esp_err.h"
#include "panelbus.h"

// Leaves the bus deinitialised. found->rc is -1 if RC could not be told apart.
esp_err_t pinscan_run(pb_pins_t *found);
