# iMessage Bridge for Poke

Text [Poke](https://poke.com) to read and send your iMessages. A tiny local
server runs on your Mac, Poke reaches it over a private tunnel, and a menu bar
switch turns it on/off.

> Your messages never leave your Mac except when *you* ask Poke to act on them.
> Each person runs their own copy — **recipe links are not shareable** (a shared
> link would point at *your* Mac and *your* texts).

## Install

```bash
git clone https://github.com/ish-cs/imessage-poke-bridge.git
cd imessage-poke-bridge
./install.sh
```

The installer:
- installs deps it needs (`imsg`, Node, `poke` CLI, `uv`) via Homebrew,
- sets up a local MCP server + Poke tunnel as background services (launchd),
- logs you into Poke and mints **your** recipe link,
- installs the **iMessage Bridge** menu bar app (auto-starts at login),
- opens the Full Disk Access pane for the one permission it can't grant for you.

### Two permissions you must grant (macOS requires it)
1. **Full Disk Access** for the Python binary the installer prints — lets it read
   your Messages database.
2. **Automation → Messages** — pops up the first time it sends a text. Click Allow.

## Use it
Click **💬** in the menu bar (🌙 = off). Then text Poke naturally:
- *"what did mom text me?"*
- *"tell Sarah I'm running 10 min late"*

Works whenever your Mac is awake. (We deliberately don't keep it awake — your
battery thanks us.) Closed lid / asleep = bridge is dark until you wake it.

## Menu bar app
- **Turn On / Off** — start/stop the bridge
- **Copy Recipe Link** — your personal Poke link
- **Open Logs Folder** — `~/.imsg-bridge`

## Tools exposed to Poke
`list_chats`, `read_history`, `search_messages`, `whois`, `send_message`, `react`

## Uninstall
```bash
./uninstall.sh
```

## Architecture
```
Poke  →  Poke tunnel  →  localhost:8765 (FastMCP server)  →  imsg CLI  →  Messages.app
```
- `server.py` — FastMCP server wrapping the `imsg` CLI (stateless HTTP, path-prefix
  shim for Poke's `/<id>/mcp` routing, optional bearer auth for public exposure).
- `menubar.py` — rumps menu bar controller for the launchd services.
- `install.sh` / `uninstall.sh` — per-user setup/teardown.

## Limitations (honest)
- **Mac must be awake.** iMessage only exists on your Mac; no cloud option that
  isn't a paid cloud-Mac.
- **SIP-on features only.** Typing indicators, read receipts, edit/unsend, polls,
  rich effects need SIP disabled and are intentionally not exposed.
- **Not notarized yet.** MVP installs from source. A signed `.dmg` is the next step.
