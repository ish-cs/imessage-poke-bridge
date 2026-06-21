"""
iMessage Bridge — menu bar app to turn the Poke iMessage bridge on/off.

Controls two launchd agents (the MCP server + the Poke tunnel) and shows
live status. Menu-bar only (no dock icon). Built on raw pyobjc — rumps does
not render a status item on macOS 26+.
"""

import os
import socket
import subprocess

from AppKit import (
    NSApplication,
    NSMenu,
    NSMenuItem,
    NSPasteboard,
    NSPasteboardTypeString,
    NSStatusBar,
    NSTimer,
    NSVariableStatusItemLength,
)
from Foundation import NSObject
from PyObjCTools import AppHelper

UID = str(os.getuid())
HOME = os.path.expanduser("~")
INSTALL_DIR = os.path.join(HOME, ".imsg-bridge")
RECIPE_FILE = os.path.join(INSTALL_DIR, "recipe.txt")
AGENTS = {
    "server": "com.imsgbridge.server",
    "tunnel": "com.imsgbridge.tunnel",
}
PLISTS = {k: f"{HOME}/Library/LaunchAgents/{v}.plist" for k, v in AGENTS.items()}

ICON_ON = "iMSG ●"
ICON_OFF = "iMSG ○"
ICON_PARTIAL = "iMSG ◐"


# ----------------------------------------------------------------- bridge logic
def _launchctl(*args) -> tuple[int, str]:
    p = subprocess.run(["launchctl", *args], capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def _is_loaded(label: str) -> bool:
    rc, _ = _launchctl("print", f"gui/{UID}/{label}")
    return rc == 0


def _server_healthy() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=0.4):
            return True
    except OSError:
        return False


def _recipe_url() -> str | None:
    try:
        return open(RECIPE_FILE).read().strip() or None
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
    s = _is_loaded(AGENTS["server"]) and _server_healthy()
    t = _is_loaded(AGENTS["tunnel"])
    if s and t:
        return "on"
    if not s and not t:
        return "off"
    return "partial"


def _notify(title: str, text: str) -> None:
    subprocess.run(
        ["osascript", "-e", f'display notification "{text}" with title "{title}"'],
        check=False,
    )


def _make_item(target, title, action):
    """Build an NSMenuItem. Module-level so pyobjc doesn't treat it as a
    selector on the delegate class."""
    mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
    if action is not None:
        mi.setTarget_(target)
    return mi


# ----------------------------------------------------------------- menu bar app
class BridgeDelegate(NSObject):
    def applicationDidFinishLaunching_(self, _notification):
        bar = NSStatusBar.systemStatusBar()
        self.item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        self.item.button().setTitle_(ICON_OFF)

        menu = NSMenu.alloc().init()
        self.status_mi = _make_item(self, "Status: …", None)
        self.toggle_mi = _make_item(self, "Turn On", b"toggle:")
        menu.addItem_(self.status_mi)
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(self.toggle_mi)
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(_make_item(self, "Copy Recipe Link", b"copyRecipe:"))
        menu.addItem_(_make_item(self, "Open Logs Folder", b"openLogs:"))
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(_make_item(self, "Quit (leaves bridge running)", b"quitApp:"))
        self.item.setMenu_(menu)

        self.refresh_(None)
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            5.0, self, b"refresh:", None, True
        )

    def refresh_(self, _timer):
        st = status()
        if st == "on":
            self.item.button().setTitle_(ICON_ON)
            self.status_mi.setTitle_("Status: ON — Poke can reach your Mac")
            self.toggle_mi.setTitle_("Turn Off")
        elif st == "off":
            self.item.button().setTitle_(ICON_OFF)
            self.status_mi.setTitle_("Status: OFF")
            self.toggle_mi.setTitle_("Turn On")
        else:
            self.item.button().setTitle_(ICON_PARTIAL)
            self.status_mi.setTitle_("Status: starting / partial…")
            self.toggle_mi.setTitle_("Restart")

    def toggle_(self, _sender):
        if status() == "off":
            turn_on()
        else:
            turn_off()
        self.refresh_(None)

    def copyRecipe_(self, _sender):
        url = _recipe_url()
        if not url:
            _notify("iMessage Bridge", "No recipe link yet — turn the bridge on first.")
            return
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(url, NSPasteboardTypeString)
        _notify("iMessage Bridge", "Recipe link copied")

    def openLogs_(self, _sender):
        subprocess.run(["open", INSTALL_DIR], check=False)

    def quitApp_(self, _sender):
        NSApplication.sharedApplication().terminate_(None)


if __name__ == "__main__":
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(1)  # accessory: menu bar only, no dock icon
    delegate = BridgeDelegate.alloc().init()
    app.setDelegate_(delegate)
    AppHelper.runEventLoop()
