#!/bin/bash
# Remove the iMessage Bridge: stop services, delete agents, app, and files.
set -uo pipefail
INSTALL_DIR="$HOME/.imsg-bridge"
AGENTS_DIR="$HOME/Library/LaunchAgents"
APP="$HOME/Applications/iMessage Bridge.app"
UID_NUM="$(id -u)"

echo "==> Stopping services…"
for label in com.imsgbridge.server com.imsgbridge.tunnel; do
  launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
  rm -f "$AGENTS_DIR/$label.plist"
done

echo "==> Removing menu bar app + login item…"
pkill -f "$INSTALL_DIR/menubar.py" 2>/dev/null || true
osascript -e 'tell application "System Events" to delete (every login item whose name is "iMessage Bridge")' 2>/dev/null || true
rm -rf "$APP"

echo "==> Removing files…"
rm -rf "$INSTALL_DIR"

echo "✓ Uninstalled. (You may also revoke Full Disk Access manually in System Settings.)"
echo "  Your Poke integration/recipe still exists — remove it at poke.com/settings if you want."
