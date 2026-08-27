#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
support-tools/mcp-call-logger/mcp_call_logger.py

Standalone diagnostic reverse proxy for GLA's MCP server
(clients/mcp_server.py, v1.7.0.1+, streamable-http transport). Sits
between an MCP client (Open WebUI / mcpo / any other Streamable-HTTP
MCP client) and mcp_server.py, forwards every request unchanged, and
logs the tool call (name + parameters) and the response payload
mcp_server.py sent back — so it's visible exactly what data an LLM
saw before it wrote its answer.

NOT part of mcp_server.py or the GLA package tree. mcp_server.py has
no knowledge of this tool's existence, imports nothing from it, and
runs identically whether logging is used or not. This tool imports
nothing from GLA either (no garmin_config, no maps.mcp_map, no
sys.path anchor into src/).

Port model — Open WebUI's tool-server URL never changes:
    This proxy binds to the SAME port Open WebUI is already configured
    for (logger_config.PROXY_PORT, matching mcp_server.py's normal
    port — 8756 by default). mcp_server.py itself moves to a different,
    internal port (logger_config.INTERNAL_MCP_PORT) only while logging
    is active, via the GARMIN_MCP_HTTP_PORT environment variable —
    garmin_config.py's own documented ENV > file > default precedence,
    not a code change to mcp_server.py.

    run_mcp_with_logger.bat does both steps together: sets that ENV var
    and starts mcp_server.py + this proxy in one go. Nothing in
    mcp_server.py's own code, its config file, or Open WebUI's settings
    needs to change to turn logging on or off — only which script you
    double-click.

    The normal, logging-free path — starting mcp_server.py the way you
    always have (GUI, Start Menu, whatever) — is completely unaffected:
    GARMIN_MCP_HTTP_PORT stays unset, mcp_server.py uses its own
    configured port exactly as before, and this proxy is simply not
    running. There is no dependency in either direction.

Usage (with logging):
    Run run_mcp_with_logger.bat. It starts mcp_server.py on
    logger_config.INTERNAL_MCP_PORT and this proxy on
    logger_config.PROXY_PORT, in two separate windows. Open WebUI's
    tool-server URL does not need to change — it already points at
    logger_config.PROXY_PORT. Logs appear under
    <base_dir>/garmin_data/log/mcp_proxy/ (or logger_config.
    LOG_DIR_FALLBACK if base_dir cannot be determined).

    To go back to the normal, logging-free path: close both windows,
    start mcp_server.py the way you normally would. Open WebUI's URL
    still doesn't need to change — mcp_server.py is listening on that
    same port again.

What this does NOT do:
    - No MCP protocol understanding. Streamable-HTTP MCP traffic is
      ordinary HTTP with a JSON body — this proxy forwards the raw
      request/response bytes unchanged and only inspects the JSON body
      for logging. It never modifies a request or a response.
    - No write access to the GLA archive, no import of any GLA write
      path. Purely observational.
    - No authentication of its own — same trust boundary as
      mcp_server.py itself (127.0.0.1 only, see that module's own
      docstring on why the bind host is hardcoded).
"""

import datetime
import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

import logger_config as lcfg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


# ── Shared config file — read-only, same file mcp_server.py reads ────────
def _read_mcp_server_config() -> dict:
    """Best-effort read of ~/.garmin_mcp_server_config.json. Returns {}
    on any failure — every caller below has its own fallback default,
    matching mcp_server.py's own "never a startup blocker" approach for
    this file."""
    try:
        return json.loads(lcfg.MCP_SERVER_CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _resolve_log_dir():
    cfg = _read_mcp_server_config()
    base_dir = cfg.get("base_dir")
    if base_dir:
        from pathlib import Path
        return Path(base_dir) / "garmin_data" / "log" / "mcp_proxy"
    return lcfg.LOG_DIR_FALLBACK


# ── Log file setup — same rotation shape as mcp_server.py's own log ──────
def _start_log_file():
    log_dir = _resolve_log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Could not create log directory %s (%s) — "
                        "falling back to %s", log_dir, exc, lcfg.LOG_DIR_FALLBACK)
        log_dir = lcfg.LOG_DIR_FALLBACK
        log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = log_dir / f"mcp_proxy_{timestamp}.log"

    # Prune — oldest first, same pattern as mcp_server.py / daily_update.py.
    logs = sorted(log_dir.glob("mcp_proxy_*.log"), key=lambda f: f.stat().st_mtime)
    for old in logs[:-lcfg.LOG_PROXY_MAX] if len(logs) > lcfg.LOG_PROXY_MAX else []:
        try:
            old.unlink()
        except OSError:
            pass

    logger.info("Call log: %s", log_path)
    return log_path


def _extract_json_payload(response_body: bytes):
    """Returns the parsed JSON object from a response body, handling
    both response shapes the MCP spec allows for a POST to the /mcp
    endpoint (see mcp_call_logger.py's own docstring, "Port model" is
    unrelated — this is about response *framing*, not ports):

    - Content-Type: application/json — response_body IS the JSON-RPC
      message directly. json.loads() on the raw bytes works as-is.
    - Content-Type: text/event-stream — response_body is SSE-framed,
      one or more "data: <json>\\n\\n" blocks even for a single,
      immediate response (this is what mcp_server.py's underlying SDK
      actually sends — confirmed against the real traffic that broke
      this the first time, see NOTES on this proxy's port/SSE fixes).
      The actual JSON-RPC message is the last "data:" line's payload —
      earlier ones, if any, are intermediate progress events, not the
      final result this proxy cares about for logging.

    Raises json.JSONDecodeError / UnicodeDecodeError on genuine
    failure — callers already catch both, matching this function's
    predecessor (a bare json.loads() call) so no caller needed to
    change its except clause."""
    text = response_body.decode("utf-8")
    if text.lstrip().startswith("data:") or "\ndata:" in text:
        data_lines = [
            line[len("data:"):].strip()
            for line in text.splitlines()
            if line.startswith("data:")
        ]
        if not data_lines:
            raise json.JSONDecodeError("no data: line in SSE body", text, 0)
        # Last data: line is the final JSON-RPC response — see docstring.
        return json.loads(data_lines[-1])
    return json.loads(text)


def _log_call(log_path, tool_name: str, params: dict, response_body: bytes,
              status_code: int) -> None:
    """Appends one JSON-line entry per call. Depth controlled by
    logger_config.LOG_DEPTH — "full" keeps the complete response
    payload, "metadata" reduces it to shape/size only (see that
    setting's docstring in logger_config.py)."""
    entry = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "tool": tool_name,
        "params": params,
        "status_code": status_code,
        "response_bytes": len(response_body),
    }

    if lcfg.LOG_DEPTH == "full":
        try:
            entry["response"] = _extract_json_payload(response_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            entry["response"] = "<non-JSON response body, not logged>"
    else:
        entry["response_summary"] = _summarize_response(response_body)

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("Could not write call log entry: %s", exc)


def _summarize_response(response_body: bytes) -> dict:
    """metadata-depth summary: field names present, and — for any
    value that is itself a list (the shape mcp_map.py's daily/intraday
    series come back as) — its length, without keeping the values
    themselves."""
    try:
        parsed = _extract_json_payload(response_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"note": "<non-JSON response body>"}

    def _shape(value):
        if isinstance(value, list):
            return {"type": "list", "length": len(value)}
        if isinstance(value, dict):
            return {"type": "dict", "keys": {k: _shape(v) for k, v in value.items()}}
        return {"type": type(value).__name__}

    if isinstance(parsed, dict):
        return {k: _shape(v) for k, v in parsed.items()}
    return _shape(parsed)


def _extract_tool_call(body: bytes):
    """Best-effort extraction of tool name + params from an MCP
    tools/call JSON-RPC request body, for readable log entries. Returns
    (tool_name, params) with safe fallbacks — never raises. This proxy
    forwards the raw body unchanged regardless of whether this parse
    succeeds; it is used for logging only."""
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "<unparseable request>", {}

    if payload.get("method") == "tools/call":
        params = payload.get("params", {})
        return params.get("name", "<unnamed tool>"), params.get("arguments", {})
    return payload.get("method", "<non tools/call request>"), {}


class _ProxyHandler(BaseHTTPRequestHandler):
    target_port = None
    log_path = None

    def log_message(self, fmt, *args):
        # Route the base class's own per-request line through our logger
        # instead of stderr directly — keeps output consistent with the
        # rest of this script's logging.
        logger.debug(fmt, *args)

    def _forward(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""

        target_url = f"http://{lcfg.TARGET_HOST}:{self.target_port}{self.path}"
        forward_headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in ("host", "content-length")
        }

        try:
            resp = requests.request(
                method=self.command,
                url=target_url,
                headers=forward_headers,
                data=body,
                timeout=60,
            )
        except requests.RequestException as exc:
            logger.error("Could not reach mcp_server.py at %s (%s)",
                         target_url, exc)
            self.send_response(502)
            self.end_headers()
            self.wfile.write(b"Bad Gateway: could not reach mcp_server.py")
            return

        tool_name, params = _extract_tool_call(body)
        if tool_name not in ("<non tools/call request>",):
            _log_call(self.log_path, tool_name, params, resp.content,
                      resp.status_code)

        self.send_response(resp.status_code)
        for k, v in resp.headers.items():
            if k.lower() not in ("content-length", "transfer-encoding",
                                  "connection"):
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(resp.content)))
        self.end_headers()
        self.wfile.write(resp.content)

    def do_GET(self):
        self._forward()

    def do_POST(self):
        self._forward()

    def do_DELETE(self):
        self._forward()


def main() -> None:
    log_path = _start_log_file()

    _ProxyHandler.target_port = lcfg.INTERNAL_MCP_PORT
    _ProxyHandler.log_path = log_path

    logger.info("MCP Call Logger listening on http://%s:%d",
                lcfg.PROXY_BIND_HOST, lcfg.PROXY_PORT)
    logger.info("Forwarding to mcp_server.py at http://%s:%d "
                "(mcp_server.py must be started with GARMIN_MCP_HTTP_PORT=%d "
                "— see run_mcp_with_logger.bat)",
                lcfg.TARGET_HOST, lcfg.INTERNAL_MCP_PORT, lcfg.INTERNAL_MCP_PORT)
    logger.info("Log depth: %s", lcfg.LOG_DEPTH)
    if lcfg.PROXY_BIND_HOST == "0.0.0.0":
        logger.warning(
            "PROXY_BIND_HOST is 0.0.0.0 — this proxy is reachable from "
            "other machines on the local network, not just this one "
            "(needed for Open WebUI running in Docker via "
            "host.docker.internal). Same trade-off mcp_server.py's own "
            "MCP_EXTRA_ALLOWED_HOSTS_ENABLED setting already accepts.")

    server = ThreadingHTTPServer((lcfg.PROXY_BIND_HOST, lcfg.PROXY_PORT),
                                  _ProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopped.")
    except OSError as exc:
        logger.error(
            "Could not start on %s:%d — port already in use. If "
            "mcp_server.py is already running on its normal port (not "
            "started via run_mcp_with_logger.bat), stop it first — this "
            "proxy needs port %d for itself: %s",
            lcfg.PROXY_BIND_HOST, lcfg.PROXY_PORT, lcfg.PROXY_PORT, exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
