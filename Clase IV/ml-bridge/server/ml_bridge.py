#!/usr/bin/env python3
"""Local MCP + HTTP bridge for the ML Price Bridge browser extension."""

from __future__ import annotations

import json
import os
import queue
import secrets
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = int(os.environ.get("ML_BRIDGE_PORT", "18765"))
STATE_DIR = Path.home() / ".grok" / "ml-bridge"
TOKEN_PATH = STATE_DIR / "token"
JOB_WAIT_SEC = 45

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "ml-bridge"
SERVER_VERSION = "1.0.0"

_jobs: queue.Queue[dict[str, Any]] = queue.Queue()
_waiters: dict[str, "JobWaiter"] = {}
_lock = threading.Lock()
_token = ""
_extension_seen = 0.0
_use_headers = False


class JobWaiter:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.payload: dict[str, Any] | None = None


def log(message: str) -> None:
    sys.stderr.write(f"[ml-bridge] {message}\n")
    sys.stderr.flush()


def load_token() -> str:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text(encoding="utf-8").strip()
    token = secrets.token_urlsafe(24)
    TOKEN_PATH.write_text(token, encoding="utf-8")
    TOKEN_PATH.chmod(0o600)
    return token


def json_bytes(payload: Any, code: int = 200) -> tuple[int, bytes]:
    return code, json.dumps(payload, ensure_ascii=False).encode("utf-8")


class BridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send(self, code: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}

    def _authorized(self) -> bool:
        supplied = self.headers.get("X-Bridge-Token", "")
        return bool(supplied) and secrets.compare_digest(supplied, _token)

    def do_GET(self) -> None:
        global _extension_seen
        parsed = urlparse(self.path)
        if parsed.path == "/v1/status":
            with _lock:
                seen = _extension_seen
            ago = (time.time() - seen) if seen else None
            code, body = json_bytes(
                {
                    "ok": True,
                    "server": SERVER_NAME,
                    "extension_seen_ago_sec": None if ago is None else round(ago, 1),
                    "jobs_waiting": _jobs.qsize(),
                }
            )
            self._send(code, body)
            return
        if parsed.path == "/v1/next":
            if not self._authorized():
                self._send(*json_bytes({"error": "unauthorized"}, 401))
                return
            _extension_seen = time.time()
            wait = 20.0
            qs = parse_qs(parsed.query)
            if qs.get("wait"):
                try:
                    wait = min(25.0, max(0.0, float(qs["wait"][0])))
                except ValueError:
                    wait = 20.0
            try:
                job = _jobs.get(timeout=wait)
            except queue.Empty:
                self._send(204, b"")
                return
            self._send(*json_bytes(job))
            return
        self._send(*json_bytes({"error": "not found"}, 404))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/v1/pair":
            self._send(*json_bytes({"ok": True, "token": _token}))
            return
        if parsed.path == "/v1/result":
            if not self._authorized():
                self._send(*json_bytes({"error": "unauthorized"}, 401))
                return
            payload = self._read_json()
            job_id = str(payload.get("id") or "")
            with _lock:
                waiter = _waiters.get(job_id)
            if waiter:
                waiter.payload = payload
                waiter.event.set()
            self._send(*json_bytes({"ok": True}))
            return
        self._send(*json_bytes({"error": "not found"}, 404))


def start_http() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((HOST, PORT), BridgeHandler)
    thread = threading.Thread(target=server.serve_forever, name="ml-bridge-http", daemon=True)
    thread.start()
    log(f"HTTP bridge on http://{HOST}:{PORT}")
    return server


def submit_job(action: str, args: dict[str, Any], timeout: float = JOB_WAIT_SEC) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    waiter = JobWaiter()
    job = {"id": job_id, "action": action, **args}
    with _lock:
        _waiters[job_id] = waiter
    _jobs.put(job)
    finished = waiter.event.wait(timeout)
    with _lock:
        _waiters.pop(job_id, None)
    if not finished:
        seen = (time.time() - _extension_seen) if _extension_seen else None
        hint = (
            "The Chrome extension did not pick up the job. "
            "Load ML Price Bridge, log into Mercado Libre, open the popup, and click Reconnect to Grok."
        )
        if seen is None:
            hint += " The extension has never connected to this bridge."
        elif seen > 30:
            hint += f" Last extension poll was {int(seen)}s ago."
        return {"ok": False, "error": hint}
    payload = waiter.payload or {}
    if not payload.get("ok", False):
        return {"ok": False, "error": payload.get("error") or "extension job failed"}
    return {"ok": True, "data": payload.get("data")}


TOOLS = [
    {
        "name": "ml_status",
        "description": (
            "Check whether the ML Price Bridge Chrome extension is connected "
            "and whether the user appears logged into Mercado Libre."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "site": {
                    "type": "string",
                    "description": "MLA, MLM, MLB, MLC, MCO, or MLU. Default MLA.",
                }
            },
        },
    },
    {
        "name": "ml_search",
        "description": (
            "Search Mercado Libre listings through the user's logged-in Chrome session. "
            "Use for live prices. Prefer sort=price_asc when estimating a build."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query, e.g. ASUS Dual RTX 5060"},
                "site": {"type": "string", "description": "Site ID. Default MLA (Argentina)."},
                "limit": {"type": "integer", "description": "1-50 results. Default 12."},
                "condition": {
                    "type": "string",
                    "enum": ["new", "used", "any"],
                    "description": "Default new.",
                },
                "sort": {
                    "type": "string",
                    "enum": ["relevance", "price_asc", "price_desc"],
                    "description": "Default relevance.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "ml_search_many",
        "description": (
            "Run several Mercado Libre searches in one round trip. "
            "Use this to price a parts list."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "query": {"type": "string"},
                            "limit": {"type": "integer"},
                            "condition": {"type": "string"},
                            "sort": {"type": "string"},
                        },
                        "required": ["query"],
                    },
                },
                "site": {"type": "string"},
            },
            "required": ["queries"],
        },
    },
    {
        "name": "ml_item",
        "description": "Fetch one Mercado Libre item by id, e.g. MLA123456789.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Item id such as MLA73120310"}
            },
            "required": ["id"],
        },
    },
]


def handle_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "ml_status":
        return submit_job("status", {"site": arguments.get("site") or "MLA"}, timeout=12)
    if name == "ml_search":
        return submit_job(
            "search",
            {
                "query": arguments.get("query"),
                "site": arguments.get("site") or "MLA",
                "limit": arguments.get("limit") or 12,
                "condition": arguments.get("condition") or "new",
                "sort": arguments.get("sort") or "price_asc",
            },
        )
    if name == "ml_search_many":
        return submit_job(
            "search_many",
            {
                "queries": arguments.get("queries") or [],
                "site": arguments.get("site") or "MLA",
                "limit": arguments.get("limit") or 8,
                "condition": arguments.get("condition") or "new",
                "sort": arguments.get("sort") or "price_asc",
            },
            timeout=90,
        )
    if name == "ml_item":
        return submit_job("item", {"id": arguments.get("id")})
    return {"ok": False, "error": f"unknown tool {name}"}


def read_message() -> dict[str, Any] | None:
    global _use_headers
    first = sys.stdin.buffer.readline()
    if not first:
        return None
    if first.lstrip().startswith(b"{"):
        _use_headers = False
        return json.loads(first.decode("utf-8"))
    _use_headers = True
    headers: dict[str, str] = {}
    line = first
    while line not in (b"\r\n", b"\n", b""):
        decoded = line.decode("utf-8")
        if ":" in decoded:
            key, value = decoded.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        line = sys.stdin.buffer.readline()
        if not line:
            return None
    length = int(headers.get("content-length", "0"))
    body = sys.stdin.buffer.read(length) if length else b""
    return json.loads(body.decode("utf-8")) if body else {}


def write_message(payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if _use_headers:
        sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii"))
        sys.stdout.buffer.write(raw)
    else:
        sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()


def result_ok(req_id: Any, result: Any) -> None:
    write_message({"jsonrpc": "2.0", "id": req_id, "result": result})


def result_error(req_id: Any, message: str, code: int = -32000) -> None:
    write_message({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def tool_text(payload: Any) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    is_error = isinstance(payload, dict) and payload.get("ok") is False
    return {
        "content": [{"type": "text", "text": text}],
        "isError": bool(is_error),
    }


def main() -> None:
    global _token
    _token = load_token()
    start_http()
    log("MCP stdio ready")
    while True:
        try:
            msg = read_message()
        except Exception as exc:  # noqa: BLE001
            log(f"bad message: {exc}")
            continue
        if msg is None:
            break
        if not isinstance(msg, dict):
            continue
        method = msg.get("method")
        req_id = msg.get("id")
        if method == "initialize":
            params = msg.get("params") or {}
            version = params.get("protocolVersion") or PROTOCOL_VERSION
            result_ok(
                req_id,
                {
                    "protocolVersion": version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            )
            continue
        if method == "notifications/initialized" or method == "initialized":
            continue
        if method == "ping":
            if req_id is not None:
                result_ok(req_id, {})
            continue
        if method == "tools/list":
            result_ok(req_id, {"tools": TOOLS})
            continue
        if method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}
            try:
                payload = handle_tool(str(name), arguments if isinstance(arguments, dict) else {})
                result_ok(req_id, tool_text(payload))
            except Exception as exc:  # noqa: BLE001
                result_ok(req_id, tool_text({"ok": False, "error": str(exc)}))
            continue
        if method == "shutdown":
            if req_id is not None:
                result_ok(req_id, {})
            break
        if req_id is not None:
            result_error(req_id, f"unknown method {method}", -32601)


if __name__ == "__main__":
    main()
