"""
iMessage Bridge — menu bar app to turn the Poke iMessage bridge on/off.

Controls two launchd agents (the MCP server + the Poke tunnel) and shows
live status. Lives in the menu bar only (no dock icon). Fully user-agnostic:
reads the per-user recipe link from the install state dir.
"""

import os
import subprocess

import rumps

UID = str(os.getuid())
HOME = os.path.expanduser("~")
INSTALL_DIR = os.path.join(HOME, ".imsg-bridge")
RECIPE_FILE = os.path.join(INSTALL_DIR, "recipe.txt")
AGENTS = {
    "server": "com.imsgbridge.server",
    "tunnel": "com.imsgbridge.tunnel",
}
PLISTS = {k: f"{HOME}/Library/LaunchAgents/{v}.plist" for k, v in AGENTS.items()}

ICON_ON = "💬"
ICON_OFF = "🌙"
ICON_PARTIAL = "⚠️"


def _launchctl(*args) -> tuple[int, str]:
    p = subprocess.run(["launchctl", *args], capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def _is_loaded(label: str) -> bool:
    rc, _ = _launchctl("print", f"gui/{UID}/{label}")
    return rc == 0


def _server_healthy() -> bool:
    """Cheap TCP check that the MCP server is listening on 8765."""
    import socket

    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=0.4):
            return True
    except OSError:
        return False


def _recipe_url() -> str | None:
    try:
        url = open(RECIPE_FILE).read().strip()
        return url or None
    except OSError:
        return None


def turn_on() -> None:
    for key, label in AGENTS.items():
        if _is_loaded(label):
            _launchctl("kickstart", "-k", f"gui/{UID}/{label}")
        else:
            _launchctl("bootstrap", f"gui/{UID}", PLISTS[key])


def turn_off() -> None:
    for label in AGENTS.values():
        _launchctl("bootout", f"gui/{UID}/{label}")


def status() -> str:
    """Return one of: on, off, partial."""
    s = _is_loaded(AGENTS["server"]) and _server_healthy()
    t = _is_loaded(AGENTS["tunnel"])
    if s and t:
        return "on"
    if not s and not t:
        return "off"
    return "partial"


class BridgeApp(rumps.App):
    def __init__(self):
        super().__init__(ICON_OFF, quit_button=None)
        self.toggle_item = rumps.MenuItem("Turn On", callback=self.on_toggle)
        self.status_item = rumps.MenuItem("Status: …", callback=None)
        self.menu = [
            self.status_item,
            None,
            self.toggle_item,
            None,
            rumps.MenuItem("Copy Recipe Link", callback=self.on_copy),
            rumps.MenuItem("Open Logs Folder", callback=self.on_logs),
            None,
            rumps.MenuItem("Quit (leaves bridge running)", callback=self.on_quit),
        ]
        self.refresh(None)

    @rumps.timer(5)
    def refresh(self, _):
        st = status()
        if st == "on":
            self.title = ICON_ON
            self.status_item.title = "Status: ON — Poke can reach your Mac"
            self.toggle_item.title = "Turn Off"
        elif st == "off":
            self.title = ICON_OFF
            self.status_item.title = "Status: OFF"
            self.toggle_item.title = "Turn On"
        else:
            self.title = ICON_PARTIAL
            self.status_item.title = "Status: starting / partial…"
            self.toggle_item.title = "Restart"

    def on_toggle(self, _):
        if status() == "off":
            turn_on()
        else:
            turn_off()
        self.refresh(None)

    def on_copy(self, _):
        url = _recipe_url()
        if not url:
            rumps.notification(
                "iMessage Bridge", "No recipe link yet",
                "Turn the bridge on once so the tunnel can generate it.",
            )
            return
        p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        p.communicate(url.encode())
        rumps.notification("iMessage Bridge", "Recipe link copied", url)

    def on_logs(self, _):
        subprocess.run(["open", INSTALL_DIR])

    def on_quit(self, _):
        rumps.quit_application()


if __name__ == "__main__":
    BridgeApp().run()
