#!/bin/bash
# iMessage Bridge for Poke — MVP installer.
# Sets up a local MCP server + Poke tunnel + menu bar toggle on THIS Mac.
# Each user who runs this gets their own server, their own tunnel, their own
# recipe link. Nobody shares a link — the iMessages live on each person's Mac.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.imsg-bridge"
AGENTS_DIR="$HOME/Library/LaunchAgents"
APP="$HOME/Applications/iMessage Bridge.app"
UID_NUM="$(id -u)"

log()  { printf "\033[1;36m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[!]\033[0m %s\n" "$*"; }
die()  { printf "\033[1;31m[x]\033[0m %s\n" "$*"; exit 1; }

# ---------------------------------------------------------------- dependencies
command -v brew >/dev/null || die "Homebrew is required. Install it from https://brew.sh and re-run."

if ! command -v imsg >/dev/null; then log "Installing imsg (iMessage CLI)…"; brew install imsg; fi
if ! command -v node >/dev/null; then log "Installing Node…"; brew install node; fi
if ! command -v poke >/dev/null; then log "Installing Poke CLI…"; npm i -g poke; fi
if ! command -v uv  >/dev/null; then
  log "Installing uv (Python toolchain)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

NODE_BIN="$(dirname "$(command -v node)")"
POKE_BIN="$(command -v poke)"
UV_BIN="$(command -v uv)"

# ---------------------------------------------------------------- files + venv
log "Installing into $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp "$SCRIPT_DIR/server.py" "$SCRIPT_DIR/menubar.py" "$INSTALL_DIR/"

log "Creating Python environment…"
( cd "$INSTALL_DIR" && "$UV_BIN" venv --quiet && "$UV_BIN" pip install --quiet fastmcp rumps )
PYBIN="$(readlink -f "$INSTALL_DIR/.venv/bin/python")"

# ---------------------------------------------------------------- run wrappers
cat > "$INSTALL_DIR/run-server.sh" <<EOF
#!/bin/bash
cd "$INSTALL_DIR" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
exec "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/server.py"
EOF

cat > "$INSTALL_DIR/run-tunnel.sh" <<EOF
#!/bin/bash
export PATH="$NODE_BIN:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
# wait for the local MCP server to be listening before tunneling
for _ in \$(seq 1 30); do
  if (echo > /dev/tcp/127.0.0.1/8765) >/dev/null 2>&1; then break; fi
  sleep 1
done
# --recipe binds to the same per-user recipe link every launch; capture it.
"$POKE_BIN" tunnel http://localhost:8765/mcp -n "iMessage" --recipe 2>&1 | while IFS= read -r line; do
  echo "\$line"
  case "\$line" in
    *poke.com/r/*) printf '%s' "\$line" | grep -oE 'https://poke.com/r/[A-Za-z0-9]+' > "$INSTALL_DIR/recipe.txt" ;;
  esac
done
EOF
chmod +x "$INSTALL_DIR/run-server.sh" "$INSTALL_DIR/run-tunnel.sh"

# ---------------------------------------------------------------- launchd plists
write_plist() {
  local label="$1" prog="$2" logfile="$3"
  cat > "$AGENTS_DIR/$label.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$label</string>
    <key>ProgramArguments</key><array><string>$prog</string></array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>10</integer>
    <key>StandardOutPath</key><string>$logfile</string>
    <key>StandardErrorPath</key><string>$logfile</string>
</dict>
</plist>
EOF
}
mkdir -p "$AGENTS_DIR"
write_plist "com.imsgbridge.server" "$INSTALL_DIR/run-server.sh" "$INSTALL_DIR/server.log"
write_plist "com.imsgbridge.tunnel" "$INSTALL_DIR/run-tunnel.sh" "$INSTALL_DIR/tunnel.log"

# ---------------------------------------------------------------- poke login
if ! "$POKE_BIN" whoami >/dev/null 2>&1; then
  log "Logging you into Poke (a browser will open; enter the code shown)…"
  "$POKE_BIN" login
fi

# ---------------------------------------------------------------- menu bar app
log "Building menu bar app…"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cat > "$APP/Contents/MacOS/launcher" <<EOF
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
exec "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/menubar.py"
EOF
chmod +x "$APP/Contents/MacOS/launcher"
cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>iMessage Bridge</string>
    <key>CFBundleDisplayName</key><string>iMessage Bridge</string>
    <key>CFBundleIdentifier</key><string>com.imsgbridge.menubar</string>
    <key>CFBundleVersion</key><string>1.0</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>launcher</string>
    <key>LSUIElement</key><true/>
    <key>LSMinimumSystemVersion</key><string>12.0</string>
</dict>
</plist>
EOF

# ---------------------------------------------------------------- load + launch
log "Starting services…"
for label in com.imsgbridge.server com.imsgbridge.tunnel; do
  launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_NUM" "$AGENTS_DIR/$label.plist"
done

# login item (dedupe first) + launch the menu bar app
osascript -e 'tell application "System Events" to delete (every login item whose name is "iMessage Bridge")' 2>/dev/null || true
osascript -e "tell application \"System Events\" to make login item at end with properties {path:\"$APP\", hidden:true}" >/dev/null 2>&1 || true
open "$APP"

# ---------------------------------------------------------------- permissions
open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles" 2>/dev/null || true

printf "\n\033[1;32m✓ iMessage Bridge installed.\033[0m\n"
cat <<EOF

ONE manual step left — macOS requires it and no installer can do it for you:

  1. The Full Disk Access pane just opened. Click +  (or ⌘⇧G to type the path),
     add this binary, and toggle it ON:

        $PYBIN

  2. The first time the bridge sends a text, macOS will ask if it can control
     Messages — click "Allow".

Then click the 💬 in your menu bar → it's ON. Your personal recipe link will
appear under "Copy Recipe Link" once the tunnel is up.

To uninstall later:  $SCRIPT_DIR/uninstall.sh
EOF
