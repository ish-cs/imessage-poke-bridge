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
Click **`iMSG ●`** in the menu bar (`○` = off). Then text Poke naturally:
- *"what did mom text me?"*
- *"tell Sarah I'm running 10 min late"*

Works whenever your Mac is awake. (We deliberately don't keep it awake — your
battery thanks us.) Closed lid / asleep = bridge is dark until you wake it.

## Menu bar app
- **Turn On / Off** — start/stop the bridge
- **Copy Recipe Link** — your personal Poke link
- **Open Logs Folder** — `~/.imsg-bridge`

## Tools exposed to Poke
| Tool | What it does |
|------|--------------|
| `list_chats` | recent conversations + chat_id + resolved contact name |
| `read_history` | messages in a chat (group senders resolved to names) |
| `search_messages` | full-text search your history |
| `find_contact` | name → phone/email, so "text Mom" works |
| `whois` | is a handle reachable on iMessage |
| `catch_up` | "what did I miss" across recent chats in one call |
| `send_message` | send a text |
| `send_attachment` | send an image/file (+ optional text) |
| `react` | tapback the latest message |
| `bridge_status` | self-diagnose: health, contacts, send count, recipe link |

Contact names are resolved by reading your local AddressBook (covered by the
Full Disk Access grant — no extra Contacts permission).

## Safety
Every send is appended to `~/.imsg-bridge/sends.jsonl` (an audit log you can
review). Two optional env vars guard the send tools:
- `IMSG_SEND_LIMIT` — max sends per hour (default `30`)
- `IMSG_SEND_ALLOWLIST` — comma-separated handles; if set, only those can be
  texted

Set them in the launchd plist or your environment.

> ⚠️ Anything in your messages — secrets, 2FA codes — becomes readable by Poke
> (an LLM). Don't text yourself API keys, and rotate any that are already there.

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
