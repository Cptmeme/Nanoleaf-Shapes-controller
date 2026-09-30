#!/bin/sh
# Build WLED with the Nanoleaf Shapes output for the interface board.
#
#   wled/core-patch/build.sh [directory] [environment]
#
#   directory    WLED checkout to create or reuse (default: ./WLED-nanoleaf)
#   environment  esp32c5_nanoleaf (ESPC5-12, tested; default)
#                esp32c6_nanoleaf (WT0132C6-S5, untested)
#
# Clones WLED at the commit the patches were made against, applies them and
# builds. Needs git, Node.js and PlatformIO.
set -e

WLED_COMMIT=961961fdde8c22150a0212243621ee71bc9a7639
PATCHES=$(cd "$(dirname "$0")" && pwd)
DIR=${1:-WLED-nanoleaf}
ENV=${2:-esp32c5_nanoleaf}

if [ ! -d "$DIR" ]; then
  git clone https://github.com/wled/WLED.git "$DIR"
  git -C "$DIR" checkout -b nanoleaf-shapes "$WLED_COMMIT"
  git -C "$DIR" am "$PATCHES"/*.patch
fi

cd "$DIR"
npm ci
npm run build
pio run -e "$ENV"

case "$ENV" in
  esp32c5*) BOOT=0x2000 ;;   # the ESP32-C5 bootloader lives at 0x2000
  *)        BOOT=0x0 ;;      # ESP32-C3, -C6 and -S3 at 0x0
esac
echo
echo "Images in $DIR/.pio/build/$ENV/:"
echo "  bootloader.bin @ $BOOT, partitions.bin @ 0x8000, firmware.bin @ 0x10000"
