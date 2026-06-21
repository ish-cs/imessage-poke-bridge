#!/bin/bash
# Builds "Install iMessage Bridge.app" — a double-clickable installer that opens
# Terminal and runs install.sh. Unsigned (free): users right-click → Open once.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="$SCRIPT_DIR/dist"
APP="$DIST/Install iMessage Bridge.app"
RAW="https://raw.githubusercontent.com/ish-cs/imessage-poke-bridge/main/install.sh"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

# Launcher: open Terminal and run the installer there (so the user sees output
# and can complete the interactive Poke login + permission steps).
cat > "$APP/Contents/MacOS/launcher" <<EOF
#!/bin/bash
CMD='curl -fsSL $RAW -o /tmp/imsg-bridge-install.sh && bash /tmp/imsg-bridge-install.sh'
osascript <<OSA
tell application "Terminal"
  activate
  do script "\$CMD"
end tell
OSA
EOF
chmod +x "$APP/Contents/MacOS/launcher"

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Install iMessage Bridge</string>
    <key>CFBundleDisplayName</key><string>Install iMessage Bridge</string>
    <key>CFBundleIdentifier</key><string>com.imsgbridge.installer</string>
    <key>CFBundleVersion</key><string>1.0</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>launcher</string>
    <key>LSMinimumSystemVersion</key><string>12.0</string>
</dict>
</plist>
EOF

# ad-hoc codesign (free) so it at least has a stable identity locally
codesign --force --deep -s - "$APP" 2>/dev/null || true

# zip for distribution (preserves the bundle)
( cd "$DIST" && rm -f "Install-iMessage-Bridge.zip" && \
  ditto -c -k --sequesterRsrc --keepParent "Install iMessage Bridge.app" "Install-iMessage-Bridge.zip" )

echo "Built: $APP"
echo "Zip:   $DIST/Install-iMessage-Bridge.zip"
