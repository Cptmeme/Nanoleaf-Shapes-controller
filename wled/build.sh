#!/bin/sh
# Build WLED with the Nanoleaf Shapes output for the interface board.
#
#   wled/build.sh [directory]      default: ./WLED-nanoleaf
#
# Clones WLED at the commit the patch was made against, applies the patch and
# builds the esp32c5_nanoleaf environment. Needs git, Node.js and PlatformIO.
set -e

WLED_COMMIT=961961fdde8c22150a0212243621ee71bc9a7639
PATCHES=$(cd "$(dirname "$0")" && pwd)
DIR=${1:-WLED-nanoleaf}

if [ ! -d "$DIR" ]; then
  git clone https://github.com/wled/WLED.git "$DIR"
  git -C "$DIR" checkout -b nanoleaf-shapes "$WLED_COMMIT"
  git -C "$DIR" am "$PATCHES"/*.patch
fi

cd "$DIR"
npm ci
npm run build
pio run -e esp32c5_nanoleaf

echo
echo "Images in $DIR/.pio/build/esp32c5_nanoleaf/:"
echo "  bootloader.bin @ 0x2000, partitions.bin @ 0x8000, firmware.bin @ 0x10000"
