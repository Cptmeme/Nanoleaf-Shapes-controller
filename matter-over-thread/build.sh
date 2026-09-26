#!/bin/sh
# Run idf.py for the Matter firmware with the ESP-IDF and esp-matter environments set up.
#
#   matter-over-thread/build.sh set-target esp32c5      # once; esp32c6 for the WT0132C6-S5
#   matter-over-thread/build.sh build
#   matter-over-thread/build.sh -p /dev/cu.usbserial-XXXX flash monitor
#
# If `source $IDF_PATH/export.sh && source $ESP_MATTER_PATH/export.sh` works on your machine, you can
# use plain idf.py instead. This wrapper exists for installs where export.sh does not work (an ESP-IDF
# Installation Manager setup with the VS Code extension's Python environment): it pulls the tool
# environment straight out of idf_tools.py. Override the paths below through the environment.
set -e

: "${IDF_PATH:=$HOME/.espressif/v5.5.4/esp-idf}"
: "${IDF_TOOLS_PATH:=$HOME/.espressif}"
: "${ESP_MATTER_PATH:=$HOME/.espressif/esp-matter}"
: "${IDF_PYTHON_ENV_PATH:=$HOME/.espressif/tools/python/v5.5.4/venv}"
export IDF_PATH IDF_TOOLS_PATH ESP_MATTER_PATH IDF_PYTHON_ENV_PATH
# Such installs have no espidf.constraints file and idf.py refuses to start without it; the packages
# are present, so skip the check.
export IDF_PYTHON_CHECK_CONSTRAINTS=no
IDF_PY="$IDF_PYTHON_ENV_PATH/bin/python"

eval "$("$IDF_PY" "$IDF_PATH/tools/idf_tools.py" export --format key-value 2>/dev/null \
        | grep -E '^[A-Za-z_]+=' | sed 's/^/export /')"

# What esp-matter's export.sh adds: gn (the CHIP component builds with it), the host tools and zap.
CHIP=$ESP_MATTER_PATH/connectedhomeip/connectedhomeip
export PATH="$PATH:$CHIP/.environment/cipd/packages/pigweed/:$CHIP/out/host"
export ZAP_INSTALL_PATH="$CHIP/.environment/cipd/packages/zap"
export _PW_ACTUAL_ENVIRONMENT_ROOT="$CHIP/.environment"

cd "$(cd "$(dirname "$0")" && pwd)"
exec "$IDF_PY" "$IDF_PATH/tools/idf.py" "$@"
