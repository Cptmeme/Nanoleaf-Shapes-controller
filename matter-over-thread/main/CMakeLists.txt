# The panel bus engine is shared with the standalone firmware in ../../firmware.
#
# No REQUIRES/PRIV_REQUIRES on purpose: ESP-IDF gives the "main" component an implicit dependency on
# every other component in the build, and declaring any requirement replaces that, which loses
# esp_matter, nvs_flash and the device_hal headers.
idf_component_register(SRCS              "app_main.cpp"
                                         "app_driver.cpp"
                                         "device_info.cpp"
                                         "../../firmware/main/panelbus.c"
                       INCLUDE_DIRS      "../../firmware/main"
                       PRIV_INCLUDE_DIRS "." "${ESP_MATTER_PATH}/examples/common/utils")

target_compile_options(${COMPONENT_LIB} PRIVATE "-DCHIP_HAVE_CONFIG_H")
