// HTTP server: GET / shows bus status, POST /ota takes a new firmware image.
//
//   curl --data-binary @build/nanoleaf_bus.bin http://nanoleaf-bus.local/ota
#pragma once

void web_start(void);
