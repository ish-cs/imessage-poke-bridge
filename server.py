"""
imsg-poke-mcp: a local MCP server that wraps the `imsg` CLI so Poke
(poke.com) can read and send iMessages by reaching through to this Mac.

Transport: Streamable HTTP at /mcp
Auth: optional bearer token (IMSG_MCP_TOKEN). Off for private Poke tunnel.

Extras: contact-name resolution (reads the local AddressBook via Full Disk
Access), a send audit log, rate limiting + optional allowlist, attachments,
a catch-up summary, and a status tool.
"""

import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from starlette.requests import Request
from starlette.responses import JSONResponse

# --- config ---------------------------------------------------------------
HOME = os.path.expanduser("~")
INSTALL_DIR = os.path.join(HOME, ".imsg-bridge")
AUDIT_FILE = os.path.join(INSTALL_DIR, "sends.jsonl")
RECIPE_FILE = os.path.join(INSTALL_DIR, "recipe.txt")

# Optional bearer auth. Unset = private-tunnel mode (no auth).
TOKEN = os.environ.get("IMSG_MCP_TOKEN")
if not TOKEN:
    print(
        "[imsg-mcp] WARNING: IMSG_MCP_TOKEN unset — server is UNAUTHENTICATED. "
        "Only expose it via a private tunnel (npx poke tunnel), never a public URL.",
        flush=True,
    )

# Send guards.
SEND_LIMIT = int(os.environ.get("IMSG_SEND_LIMIT", "30"))      # sends per hour
SEND_WINDOW = 3600
_ALLOW = [h.strip() for h in os.environ.get("IMSG_SEND_ALLOWLIST", "").split(",") if h.strip()]

IMSG = shutil.which("imsg") or "/opt/homebrew/bin/imsg"
if not os.path.exists(IMSG):
    raise SystemExit(f"imsg binary not found at {IMSG}; install with `brew install imsg`.")

mcp = FastMCP(
    name="imsg",
    instructions=(
        "Tools to read and send the user's iMessages/SMS on their Mac. "
        "Find a conversation with list_chats (chats include a resolved contact "
        "name when known) or search_messages, read with read_history, and send "
        "with send_message. To text a person by name, call find_contact first to "
        "get their number. Prefer an explicit chat_id when replying in an existing "
        "chat. ALWAYS confirm the recipient and exact message text with the user "
        "before sending. Use catch_up for a quick 'what did I miss' across chats."
    ),
)


# --- auth ------------------------------------------------------------------
# Lock the bridge to a single Poke account. Poke sends X-Poke-User-Id on every
# request; only the owner's id is accepted. Even if the recipe link leaks,
# another person's Poke (different user id) is rejected.
ALLOWED_POKE_USER = (os.environ.get("IMSG_POKE_USER_ID") or "").strip()
SEEN_USER_FILE = os.path.join(INSTALL_DIR, "seen_poke_user.txt")


def _check_auth() -> None:
    headers = get_http_headers(include_all=True)

    # Optional bearer token (only relevant if you expose a public URL).
    if TOKEN and headers.get("authorization", "") != f"Bearer {TOKEN}":
        raise PermissionError("Unauthorized: missing or invalid bearer token.")

    uid = (headers.get("x-poke-user-id") or "").strip()

    if not ALLOWED_POKE_USER:
        # Setup phase: record the owner's id so install can lock to it.
        if uid:
            try:
                os.makedirs(INSTALL_DIR, exist_ok=True)
                with open(SEEN_USER_FILE, "w") as f:
                    f.write(uid)
            except OSError:
                pass
        return

    # Locked: reject anyone who is not the owner.
    if uid != ALLOWED_POKE_USER:
        raise PermissionError("This bridge is locked to its owner's Poke account.")


# --- imsg helper -----------------------------------------------------------
def _run(args: list[str]) -> dict:
    """Run `imsg <args> --json` and return parsed JSON (NDJSON-aware)."""
    _check_auth()
    cmd = [IMSG, *args, "--json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "imsg timed out after 60s"}

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return {"ok": False, "error": err or out or f"imsg exited {proc.returncode}", "cmd": " ".join(args)}
    if not out:
        return {"ok": True, "result": None}

    try:
        return {"ok": True, "result": json.loads(out)}
    except json.JSONDecodeError:
        pass
    rows, ok = [], True
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            ok = False
            break
    if ok and rows:
        return {"ok": True, "result": rows}
    return {"ok": True, "result": out}


# --- contacts (read local AddressBook via Full Disk Access) ----------------
_contacts = {"by_phone": {}, "by_email": {}, "name_index": [], "ts": 0.0}
_CONTACTS_TTL = 300  # seconds


def _norm_phone(s: str) -> str:
    digits = re.sub(r"\D", "", s or "")
    return digits[-10:] if len(digits) >= 10 else digits


def _addressbook_dbs() -> list[str]:
    paths = glob.glob(f"{HOME}/Library/Application Support/AddressBook/Sources/*/AddressBook-v22.abcddb")
    paths.append(f"{HOME}/Library/Application Support/AddressBook/AddressBook-v22.abcddb")
    return [p for p in paths if os.path.exists(p)]


def _load_contacts() -> None:
    """(Re)build name<->handle maps from the AddressBook. Cached for TTL."""
    if time.time() - _contacts["ts"] < _CONTACTS_TTL and _contacts["name_index"]:
        return
    by_phone, by_email, name_index = {}, {}, []
    for db in _addressbook_dbs():
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            recs = {}
            for r in con.execute(
                "SELECT Z_PK, ZFIRSTNAME, ZLASTNAME, ZORGANIZATION FROM ZABCDRECORD"
            ):
                name = " ".join(x for x in (r["ZFIRSTNAME"], r["ZLASTNAME"]) if x).strip()
                name = name or (r["ZORGANIZATION"] or "")
                if name:
                    recs[r["Z_PK"]] = name
            for r in con.execute("SELECT ZOWNER, ZFULLNUMBER FROM ZABCDPHONENUMBER"):
                name = recs.get(r["ZOWNER"])
                if name and r["ZFULLNUMBER"]:
                    key = _norm_phone(r["ZFULLNUMBER"])
                    if key:
                        by_phone.setdefault(key, name)
                        name_index.append((name, r["ZFULLNUMBER"]))
            try:
                for r in con.execute("SELECT ZOWNER, ZADDRESS FROM ZABCDEMAILADDRESS"):
                    name = recs.get(r["ZOWNER"])
                    if name and r["ZADDRESS"]:
                        by_email.setdefault(r["ZADDRESS"].lower(), name)
                        name_index.append((name, r["ZADDRESS"]))
            except sqlite3.Error:
                pass
            con.close()
        except sqlite3.Error:
            continue
    _contacts.update(by_phone=by_phone, by_email=by_email, name_index=name_index, ts=time.time())


def _name_for(handle: str | None) -> str | None:
    if not handle:
        return None
    _load_contacts()
    if "@" in handle:
        return _contacts["by_email"].get(handle.lower())
    return _contacts["by_phone"].get(_norm_phone(handle))


def _enrich_chat(c: dict) -> dict:
    if isinstance(c, dict) and not c.get("display_name") and not c.get("name"):
        parts = c.get("participants") or []
        names = [n for n in (_name_for(p) for p in parts) if n]
        if names:
            c["contact_name"] = ", ".join(names)
    return c


# --- send guards -----------------------------------------------------------
_send_times: list[float] = []


def _rate_ok() -> bool:
    now = time.time()
    _send_times[:] = [t for t in _send_times if now - t < SEND_WINDOW]
    return len(_send_times) < SEND_LIMIT


def _allowed(recipient: str | None) -> bool:
    if not _ALLOW or not recipient:
        return True
    rp = _norm_phone(recipient) if "@" not in recipient else recipient.lower()
    for a in _ALLOW:
        ap = _norm_phone(a) if "@" not in a else a.lower()
        if rp == ap:
            return True
    return False


def _audit(action: str, recipient, text: str, result: dict) -> None:
    try:
        os.makedirs(INSTALL_DIR, exist_ok=True)
        with open(AUDIT_FILE, "a") as f:
            f.write(json.dumps({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "action": action,
                "recipient": recipient,
                "text": (text or "")[:500],
                "ok": result.get("ok"),
            }) + "\n")
    except OSError:
        pass


# --- read tools ------------------------------------------------------------
@mcp.tool
def list_chats(limit: int = 20) -> dict:
    """List recent conversations with chat_id, last message, and (when known) a
    resolved contact name.

    Args:
        limit: how many recent conversations to return (default 20).
    """
    res = _run(["chats", "--limit", str(limit)])
    if res.get("ok") and isinstance(res.get("result"), list):
        res["result"] = [_enrich_chat(c) for c in res["result"]]
    return res


@mcp.tool
def read_history(chat_id: int, limit: int = 20) -> dict:
    """Read recent messages from a conversation, with each sender's contact name
    resolved when known (useful for group chats).

    Args:
        chat_id: the chat rowid from list_chats.
        limit: how many recent messages to return (default 20).
    """
    res = _run(["history", "--chat-id", str(chat_id), "--limit", str(limit)])
    if res.get("ok") and isinstance(res.get("result"), list):
        for m in res["result"]:
            if isinstance(m, dict) and not m.get("is_from_me"):
                nm = _name_for(m.get("sender") or m.get("handle"))
                if nm:
                    m["sender_name"] = nm
    return res


@mcp.tool
def search_messages(query: str, limit: int = 30) -> dict:
    """Full-text search the user's local message history.

    Args:
        query: text to search for (substring, case-insensitive).
        limit: max results (default 30).
    """
    return _run(["search", "--query", query, "--limit", str(limit)])


@mcp.tool
def find_contact(name: str, limit: int = 10) -> dict:
    """Look up a person's phone numbers / emails by name from the address book.
    Use this to turn "text Mom" into an actual handle for send_message.

    Args:
        name: full or partial contact name (case-insensitive).
        limit: max matches (default 10).
    """
    _check_auth()
    _load_contacts()
    q = name.strip().lower()
    if not q:
        return {"ok": False, "error": "name is empty"}
    seen, matches = set(), []
    for nm, handle in _contacts["name_index"]:
        if q in nm.lower():
            key = (nm, handle)
            if key not in seen:
                seen.add(key)
                matches.append({"name": nm, "handle": handle})
        if len(matches) >= limit:
            break
    return {"ok": True, "result": matches, "count": len(matches)}


@mcp.tool
def whois(address: str) -> dict:
    """Check whether a phone/email is reachable on iMessage (from local history).

    Args:
        address: phone number (e.g. +14155551212) or email.
    """
    return _run(["whois", "--address", address, "--local"])


@mcp.tool
def catch_up(chats: int = 8, per_chat: int = 6) -> dict:
    """Quick 'what did I miss': the latest messages across your most recent
    conversations, with contact names resolved.

    Args:
        chats: how many recent conversations to scan (default 8).
        per_chat: messages to pull from each (default 6).
    """
    res = _run(["chats", "--limit", str(chats)])
    if not res.get("ok") or not isinstance(res.get("result"), list):
        return res
    out = []
    for c in res["result"]:
        cid = c.get("id")
        if cid is None:
            continue
        label = c.get("display_name") or c.get("name") or _enrich_chat(c).get("contact_name") \
            or (c.get("participants") or ["?"])[0]
        h = _run(["history", "--chat-id", str(cid), "--limit", str(per_chat)])
        msgs = []
        if h.get("ok") and isinstance(h.get("result"), list):
            for m in h["result"]:
                who = "me" if m.get("is_from_me") else (
                    _name_for(m.get("sender") or m.get("handle")) or m.get("sender") or "them")
                msgs.append({"from": who, "text": (m.get("text") or "")[:200]})
        out.append({"chat_id": cid, "chat": label, "messages": msgs})
    return {"ok": True, "result": out}


# --- write tools -----------------------------------------------------------
@mcp.tool
def send_message(text: str, to: str | None = None, chat_id: int | None = None) -> dict:
    """Send an iMessage/SMS. Provide EITHER chat_id (preferred) OR a phone/email in `to`.
    Always confirm recipient + text with the user first.

    Args:
        text: the message body to send.
        to: phone number or email of the recipient (use when no chat_id).
        chat_id: chat rowid from list_chats (preferred for existing chats).
    """
    if not text.strip():
        return {"ok": False, "error": "text is empty"}
    if chat_id is None and not to:
        return {"ok": False, "error": "provide either chat_id or to"}
    if not _rate_ok():
        r = {"ok": False, "error": f"rate limit: max {SEND_LIMIT} sends/hour reached"}
        _audit("send_blocked", to or f"chat:{chat_id}", text, r)
        return r
    if to is not None and not _allowed(to):
        r = {"ok": False, "error": f"recipient {to} not in IMSG_SEND_ALLOWLIST"}
        _audit("send_blocked", to, text, r)
        return r

    args = ["send", "--text", text]
    if chat_id is not None:
        args += ["--chat-id", str(chat_id)]
    else:
        args += ["--to", to]
    res = _run(args)
    if res.get("ok"):
        _send_times.append(time.time())
    _audit("send", to or f"chat:{chat_id}", text, res)
    return res


@mcp.tool
def send_attachment(file: str, to: str | None = None, chat_id: int | None = None,
                    text: str | None = None) -> dict:
    """Send a file (image/document) as an attachment, optionally with text.
    Provide EITHER chat_id OR a phone/email in `to`. Confirm with the user first.

    Args:
        file: absolute path to the file to send.
        to: recipient phone/email (use when no chat_id).
        chat_id: chat rowid from list_chats.
        text: optional message body to send alongside the file.
    """
    path = os.path.expanduser(file)
    if not os.path.isfile(path):
        return {"ok": False, "error": f"file not found: {path}"}
    if chat_id is None and not to:
        return {"ok": False, "error": "provide either chat_id or to"}
    if not _rate_ok():
        return {"ok": False, "error": f"rate limit: max {SEND_LIMIT} sends/hour reached"}
    if to is not None and not _allowed(to):
        return {"ok": False, "error": f"recipient {to} not in IMSG_SEND_ALLOWLIST"}

    args = ["send", "--file", path]
    if text:
        args += ["--text", text]
    if chat_id is not None:
        args += ["--chat-id", str(chat_id)]
    else:
        args += ["--to", to]
    res = _run(args)
    if res.get("ok"):
        _send_times.append(time.time())
    _audit("send_attachment", to or f"chat:{chat_id}", f"[file:{os.path.basename(path)}] {text or ''}", res)
    return res


@mcp.tool
def react(chat_id: int, reaction: str = "like") -> dict:
    """Send a tapback to the most recent incoming message in a chat.

    Args:
        chat_id: chat rowid from list_chats.
        reaction: love, like, dislike, laugh, emphasis, or question.
    """
    valid = {"love", "like", "dislike", "laugh", "emphasis", "question"}
    if reaction not in valid:
        return {"ok": False, "error": f"reaction must be one of {sorted(valid)}"}
    return _run(["react", "--chat-id", str(chat_id), "--reaction", reaction])


@mcp.tool
def bridge_status() -> dict:
    """Report bridge health: imsg feature availability, contacts loaded, recent
    send count, and the recipe link. Use to self-diagnose connectivity."""
    _check_auth()
    _load_contacts()
    now = time.time()
    recent = len([t for t in _send_times if now - t < SEND_WINDOW])
    recipe = None
    try:
        recipe = open(RECIPE_FILE).read().strip() or None
    except OSError:
        pass
    return {
        "ok": True,
        "result": {
            "imsg_basic": _run(["status"]).get("ok", False),
            "contacts_loaded": len(_contacts["by_phone"]) + len(_contacts["by_email"]),
            "sends_last_hour": recent,
            "send_limit_per_hour": SEND_LIMIT,
            "allowlist_active": bool(_ALLOW),
            "recipe_link": recipe,
        },
    }


# --- health check (no auth) ------------------------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "imsg-poke-mcp"})


# --- path shim: Poke routes as /<connection-uuid>/mcp ----------------------
_PREFIXED_MCP = re.compile(r"^/[^/]+/mcp(/.*)?$")


class StripConnectionPrefix:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if not path.startswith("/mcp") and not path.startswith("/health"):
                m = _PREFIXED_MCP.match(path)
                if m:
                    new_path = "/mcp" + (m.group(1) or "")
                    scope = dict(scope)
                    scope["path"] = new_path
                    scope["raw_path"] = new_path.encode()
        await self.app(scope, receive, send)


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("IMSG_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("IMSG_MCP_PORT", "8765"))
    app = mcp.http_app(path="/mcp", stateless_http=True)
    app = StripConnectionPrefix(app)
    uvicorn.run(app, host=host, port=port)
