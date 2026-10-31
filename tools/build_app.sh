#!/bin/zsh
# Build the Forthmark menu bar app: app/build/Forthmark.app
#   tools/build_app.sh            build
#   tools/build_app.sh --install  build and copy to ~/Applications (then open it)
set -euo pipefail

KIT=${0:A:h:h}
PYTHON=${FORTHMARK_PYTHON:-$(command -v python3)}
OUT=$KIT/app/build/Forthmark.app
ARCH=$(uname -m)

rm -rf "$OUT"
mkdir -p "$OUT/Contents/MacOS" "$OUT/Contents/Resources"

swiftc -O -swift-version 5 -target "$ARCH-apple-macos13.0" \
  -o "$OUT/Contents/MacOS/Forthmark" "$KIT/app/Forthmark.swift"

cp "$KIT/app/AppIcon.icns" "$OUT/Contents/Resources/AppIcon.icns"   # regenerate with tools/make_icon.sh

cat > "$OUT/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>local.forthmark.menubar</string>
  <key>CFBundleName</key><string>Forthmark</string>
  <key>CFBundleDisplayName</key><string>Forthmark</string>
  <key>CFBundleExecutable</key><string>Forthmark</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>ForthmarkKit</key><string>$KIT</string>
  <key>ForthmarkPython</key><string>$PYTHON</string>
</dict>
</plist>
PLIST

codesign --force --sign - "$OUT" >/dev/null   # ad-hoc signature: enough for local use and notifications
echo "built $OUT"

if [[ ${1:-} == --install ]]; then
  mkdir -p ~/Applications
  pkill -x Forthmark 2>/dev/null || true
  rm -rf ~/Applications/Forthmark.app
  cp -R "$OUT" ~/Applications/
  echo "installed ~/Applications/Forthmark.app"
  open ~/Applications/Forthmark.app
fi
