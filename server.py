"""
imsg-poke-mcp: a local MCP server that wraps the `imsg` CLI so Poke
(poke.com) can read and send iMessages by reaching through to this Mac.

Transport: Streamable HTTP at /mcp
Auth: every request must carry  Authorization: Bearer <IMSG_MCP_TOKEN>
"""

import json
import os
import shutil
import subprocess

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from starlette.requests import Request
from starlette.responses import JSONResponse

# --- config ---------------------------------------------------------------
# Auth is OPTIONAL and depends on how you expose the server:
#   * Public URL (e.g. cloudflared): SET IMSG_MCP_TOKEN. The bearer token is
#     the only thing stopping the internet from texting as you.
#   * Poke native tunnel (`npx poke tunnel`): leave it UNSET. The tunnel only
#     forwards the port and can't carry our header, so a required token would
#     reject Poke. Security then rests on the tunnel being private to your
#     Poke account.
TOKEN = os.environ.get("IMSG_MCP_TOKEN")
if not TOKEN:
    print(
        "[imsg-mcp] WARNING: IMSG_MCP_TOKEN unset — server is UNAUTHENTICATED. "
        "Only expose it via a private tunnel (npx poke tunnel), never a public URL.",
        flush=True,
    )

IMSG = shutil.which("imsg") or "/opt/homebrew/bin/imsg"
if not os.path.exists(IMSG):
    raise SystemExit(f"imsg binary not found at {IMSG}; install with `brew install imsg`.")

mcp = FastMCP(
    name="imsg",
    instructions=(
        "Tools to read and send the user's iMessages/SMS on their Mac. "
        "Use list_chats to find a conversation and its chat_id, read_history "
        "or search_messages to read, and send_message to send. When sending, "
        "prefer an explicit chat_id from list_chats; only use a raw phone "
        "number/email when the user names a contact not yet in a chat. "
        "Always confirm the recipient and message text with the user before "
        "sending anything."
    ),
)


# --- auth ------------------------------------------------------------------
def _check_auth() -> None:
    """Raise if a token is configured and the request doesn't present it.

    No-op when IMSG_MCP_TOKEN is unset (private-tunnel mode)."""
    if not TOKEN:
        return
    headers = get_http_headers(include_all=True)
    auth = headers.get("authorization", "")
    if auth != f"Bearer {TOKEN}":
        raise PermissionError("Unauthorized: missing or invalid bearer token.")


# --- imsg helper -----------------------------------------------------------
def _run(args: list[str]) -> dict:
    """Run `imsg <args> --json` and return parsed JSON (or raw text)."""
    _check_auth()
    cmd = [IMSG, *args, "--json"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, check=False
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "imsg timed out after 60s"}

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()

    if proc.returncode != 0:
        return {
            "ok": False,
            "error": err or out or f"imsg exited {proc.returncode}",
            "cmd": " ".join(args),
        }

    if not out:
        return {"ok": True, "result": None}

    # Try whole-string JSON first (single object/array).
    try:
        return {"ok": True, "result": json.loads(out)}
    except json.JSONDecodeError:
        pass

    # imsg often emits NDJSON (one JSON object per line) — parse line by line.
    rows = []
    all_parsed = True
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            all_parsed = False
            break
    if all_parsed and rows:
        return {"ok": True, "result": rows}

    # Fall back to raw text.
    return {"ok": True, "result": out}


# --- tools -----------------------------------------------------------------
@mcp.tool
def list_chats(limit: int = 20) -> dict:
    """List recent iMessage/SMS conversations with their chat_id and last message.

    Args:
        limit: how many recent conversations to return (default 20).
    """
    return _run(["chats", "--limit", str(limit)])


@mcp.tool
def read_history(chat_id: int, limit: int = 20) -> dict:
    """Read recent messages from a conversation.

    Args:
        chat_id: the chat rowid from list_chats.
        limit: how many recent messages to return (default 20).
    """
    return _run(["history", "--chat-id", str(chat_id), "--limit", str(limit)])


@mcp.tool
def search_messages(query: str, limit: int = 30) -> dict:
    """Full-text search the user's local message history.

    Args:
        query: text to search for (substring match, case-insensitive).
        limit: max results (default 30).
    """
    return _run(["search", "--query", query, "--limit", str(limit)])


@mcp.tool
def whois(address: str) -> dict:
    """Check whether a phone number or email is reachable on iMessage
    (inferred from local history; no network lookup).

    Args:
        address: phone number (e.g. +14155551212) or email.
    """
    return _run(["whois", "--address", address, "--local"])


@mcp.tool
def send_message(
    text: str,
    to: str | None = None,
    chat_id: int | None = None,
) -> dict:
    """Send an iMessage/SMS. Provide EITHER chat_id (preferred) OR a phone/email in `to`.

    Args:
        text: the message body to send.
        to: phone number or email of the recipient (use when no chat_id).
        chat_id: chat rowid from list_chats (preferred for existing chats).
    """
    if not text.strip():
        return {"ok": False, "error": "text is empty"}
    if chat_id is None and not to:
        return {"ok": False, "error": "provide either chat_id or to"}

    args = ["send", "--text", text]
    if chat_id is not None:
        args += ["--chat-id", str(chat_id)]
    else:
        args += ["--to", to]
    return _run(args)


@mcp.tool
def react(chat_id: int, reaction: str = "like") -> dict:
    """Send a tapback reaction to the most recent incoming message in a chat.

    Args:
        chat_id: chat rowid from list_chats.
        reaction: one of love, like, dislike, laugh, emphasis, question.
    """
    valid = {"love", "like", "dislike", "laugh", "emphasis", "question"}
    if reaction not in valid:
        return {"ok": False, "error": f"reaction must be one of {sorted(valid)}"}
    return _run(["react", "--chat-id", str(chat_id), "--reaction", reaction])


# --- health check (no auth) so you can curl the tunnel ---------------------
@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "imsg-poke-mcp"})


import re

# Poke's tunnel forwards requests as /<connection-uuid>/mcp, but our MCP app
# is mounted at /mcp. This middleware strips a single leading path segment in
# front of /mcp so those requests route correctly. /mcp and /health are
# passed through untouched.
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
    # Build the Starlette app (keeps MCP lifespan) and wrap with our rewriter.
    # stateless_http: each request is self-contained — no long-lived SSE
    # session to conflict when Poke's tunnel drops and reconnects (fixes 409).
    app = mcp.http_app(path="/mcp", stateless_http=True)
    app = StripConnectionPrefix(app)
    uvicorn.run(app, host=host, port=port)
