#!/bin/zsh
# Regenerate app/AppIcon.icns from assets/app-icon.svg (needs Google Chrome for the SVG → PNG step).
set -euo pipefail
KIT=${0:A:h:h}
CHROME=${FORTHMARK_CHROME:-"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"}
TMP=$(mktemp -d)
"$CHROME" --headless=new --disable-gpu --hide-scrollbars --default-background-color=00000000 \
  --window-size=1024,1024 --screenshot="$TMP/icon_1024.png" "file://$KIT/assets/app-icon.svg" >/dev/null 2>&1
SET=$TMP/AppIcon.iconset; mkdir -p "$SET"
for n in 16 32 128 256 512; do
  sips -z $n $n "$TMP/icon_1024.png" --out "$SET/icon_${n}x${n}.png" >/dev/null
  sips -z $((n*2)) $((n*2)) "$TMP/icon_1024.png" --out "$SET/icon_${n}x${n}@2x.png" >/dev/null
done
iconutil -c icns "$SET" -o "$KIT/app/AppIcon.icns"
rm -rf "$TMP"
echo "wrote $KIT/app/AppIcon.icns"
