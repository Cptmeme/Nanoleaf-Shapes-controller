idf_component_register(SRCS "net.c" "main.c" "panelbus.c" "pinscan.c" "web.c" "ddp.c"
                       INCLUDE_DIRS "."
                       REQUIRES esp_driver_uart esp_driver_gpio console nvs_flash esp_timer
                                esp_wifi esp_netif esp_event esp_http_server app_update lwip)
