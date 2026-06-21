<div align="center">

# 💬 iMessage Bridge for Poke

**Text [Poke](https://poke.com) to read and send your iMessages.**

A tiny local server runs on your Mac, Poke reaches it over a private tunnel, and
a menu bar switch turns it on and off. Your messages never leave your Mac unless
*you* ask Poke to act on them.

![platform](https://img.shields.io/badge/platform-macOS%2012%2B-black)
![license](https://img.shields.io/badge/license-MIT-blue)
![built for Poke](https://img.shields.io/badge/built%20for-Poke-7c3aed)
![MCP](https://img.shields.io/badge/protocol-MCP-success)

</div>

---

## What it feels like

> **You:** what did the last person text me?
> **Poke:** Sarah said "running 10 late, order me a flat white" — want me to reply?
> **You:** yeah tell her got it 👍
> **Poke:** Sent ✅

You're texting an assistant that can actually reach into your real iMessages —
from your phone, from anywhere, as long as your Mac is awake.

## How it works

```
 your phone           Poke cloud            your Mac (awake)
┌──────────┐         ┌──────────┐    private tunnel   ┌────────────────────────────┐
│  text    │ ──────▶ │   Poke   │ ─────────────────▶ │ FastMCP server :8765        │
│  "Poke…" │         │  (LLM)   │ ◀───────────────── │   └▶ imsg CLI ▶ Messages.app │
└──────────┘         └──────────┘                     └────────────────────────────┘
```

Poke is an MCP **host**: it discovers the tools your server exposes and calls
them mid-conversation. The server wraps [`imsg`](https://github.com/steipete/imsg),
a CLI that reads your local `chat.db` and drives Messages.app.

> **Each person runs their own copy.** Recipe links are **not shareable** — a
> shared link would point Poke at *your* Mac and *your* texts. Share the repo,
> not your link.

## Quick start

**Prerequisites:** macOS 12+, [Homebrew](https://brew.sh), and a
[Poke](https://poke.com) account.

### Option A — download the app (easiest)

1. **[⬇️ Download the latest release](https://github.com/ish-cs/imessage-poke-bridge/releases/latest)** and unzip it.
2. **Right-click** `Install iMessage Bridge.app` → **Open** → **Open**.
   *(Needed once — the app is unsigned, so macOS asks you to confirm.)*
3. A Terminal window runs the setup and walks you through the rest.

### Option B — one command

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ish-cs/imessage-poke-bridge/main/install.sh)
```

<details>
<summary>Option C — clone the repo</summary>

```bash
git clone https://github.com/ish-cs/imessage-poke-bridge.git
cd imessage-poke-bridge
./install.sh
```
</details>

However you install, it sets everything up **for your account**: deps (`imsg`,
Node, `poke` CLI, `uv`), the server + tunnel as background services, logs **you**
into **your** Poke, mints **your** recipe link, and adds the menu bar app. Every
install is fully self-contained — your Poke talks to your Mac, nobody else's.

### Two permissions you must grant

macOS requires these and no installer can do them for you:

| Permission | Why | How |
|------------|-----|-----|
| **Full Disk Access** | read your Messages database | The installer prints a Python path and opens the pane — add it with `+` (or `⌘⇧G` to paste the path) and toggle it **on** |
| **Automation → Messages** | send texts | A dialog pops up the first time it sends — click **Allow** |

Then click **`iMSG ●`** in your menu bar (`○` = off) and start texting Poke.

## Using it

Text Poke naturally:

- *"what did mom text me?"*
- *"tell Sarah I'm running 10 min late"*
- *"what did I miss today?"*
- *"send the photo at ~/Desktop/ticket.png to the group"*

Works whenever your Mac is awake. Lid closed / asleep = the bridge is dark until
you wake it. (We deliberately **don't** keep your Mac awake — your battery thanks us.)

## Tools

| Tool | What it does |
|------|--------------|
| `list_chats` | recent conversations + `chat_id` + resolved contact name |
| `read_history` | messages in a chat (group senders resolved to names) |
| `search_messages` | full-text search your history |
| `find_contact` | name → phone/email, so *"text Mom"* works |
| `whois` | is a handle reachable on iMessage |
| `catch_up` | *"what did I miss"* across recent chats in one call |
| `send_message` | send a text |
| `send_attachment` | send an image/file (+ optional text) |
| `react` | tapback the latest message |
| `bridge_status` | self-diagnose: health, contacts, send count, recipe link |

Contact names come from your local AddressBook — covered by the Full Disk Access
grant, so no extra Contacts permission.

## Menu bar app

| Item | Action |
|------|--------|
| **Turn On / Off** | start/stop the bridge (`iMSG ●` on, `iMSG ○` off) |
| **Copy Recipe Link** | your personal Poke link |
| **Open Logs Folder** | `~/.imsg-bridge` |

Auto-starts at login and self-restarts if it crashes.

## Configuration

Set in the launchd plist or environment:

| Variable | Default | Purpose |
|----------|---------|---------|
| `IMSG_SEND_LIMIT` | `30` | max sends per hour |
| `IMSG_SEND_ALLOWLIST` | *(unset)* | comma-separated handles; if set, only those can be texted |
| `IMSG_MCP_TOKEN` | *(unset)* | bearer token — **set this only if you expose the server on a public URL**; leave unset for the private Poke tunnel |

## Safety & privacy

- **Audit log** — every send is appended to `~/.imsg-bridge/sends.jsonl`. Review
  exactly what Poke did in your name.
- **Rate limit + allowlist** — guard rails on the send tools (see Configuration).
- **Local-first** — messages stay on your Mac; only what Poke acts on is sent to it.

> ⚠️ Anything in your messages — secrets, 2FA codes, private notes — becomes
> readable by Poke (an LLM). Don't text yourself API keys, and rotate any that
> are already in your history.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| **Menu bar icon missing** | It runs as a LaunchAgent; check `launchctl list \| grep imsgbridge`. Re-run `./install.sh` if absent. |
| **Poke says "offline / no available upstreams"** | The tunnel isn't running. Click the menu bar item → **Turn On**, or check `~/.imsg-bridge/tunnel.log`. |
| **"can't read messages"** | Full Disk Access isn't granted to the Python binary the installer printed. |
| **Sends fail silently** | Grant **Automation → Messages** (System Settings → Privacy & Security → Automation). |
| **Poke can't reach it** | Your Mac is asleep. Wake it. |
| **Duplicate integrations in Poke** | Delete extras at `poke.com/settings`; keep one. |

Logs live in `~/.imsg-bridge/` (`server.log`, `tunnel.log`, `menubar.log`).

## Uninstall

```bash
./uninstall.sh
```

Removes the services, menu bar app, and files. Revoke Full Disk Access manually
in System Settings, and remove the integration at `poke.com/settings` if you want.

## Limitations

- **Your Mac must be awake.** iMessage only exists on your Mac; there's no free
  cloud option (a cloud Mac costs $100+/mo).
- **SIP-on features only.** Typing indicators, read receipts, edit/unsend, polls,
  and rich effects need SIP disabled and are intentionally not exposed.
- **Not notarized yet.** MVP installs from source.
- **Contact matching** is by last-10-digits, so some international numbers may
  mismatch.

## Roadmap

- [ ] [Signed + notarized `.dmg` installer](https://github.com/ish-cs/imessage-poke-bridge/issues/1)
- [ ] [Dependency-free Swift/Go rewrite](https://github.com/ish-cs/imessage-poke-bridge/issues/2)

## Architecture

```
server.py     FastMCP server wrapping imsg — 10 tools, stateless HTTP,
              path-prefix shim for Poke's /<id>/mcp routing, optional bearer auth,
              AddressBook contact resolution, send audit + rate limit.
menubar.py    pyobjc menu bar controller for the launchd services.
install.sh    per-user setup: deps, services, recipe capture, menu bar agent.
uninstall.sh  teardown.
```

## License

[MIT](LICENSE) © Ishaan Pandey

---

<div align="center">
<sub>Built on <a href="https://github.com/steipete/imsg">imsg</a> ·
<a href="https://gofastmcp.com">FastMCP</a> ·
<a href="https://modelcontextprotocol.io">MCP</a>. Not affiliated with Apple or Poke.</sub>
</div>
