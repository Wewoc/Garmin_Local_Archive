# MCP Call Logger

A standalone diagnostic proxy for GLA's MCP server
(`clients/mcp_server.py`, v1.7.0.1+, streamable-http transport). Sits
between an MCP client (Open WebUI, `mcpo`, or any other Streamable-HTTP
MCP client) and `mcp_server.py`, forwards every request, and logs each
tool call — which tool, which parameters, and what `mcp_server.py`
sent back — so you can see the closest observable record of what data
the MCP server sent to the LLM client, before it wrote its answer.

This exists for one reason: when Ollama/Open WebUI gives a good or a
bad answer about your health data, "why" is otherwise a black box. This
tool makes the actual request/response traffic visible without touching
`mcp_server.py` itself.

## What it is NOT

- **Not part of `mcp_server.py` or the GLA package tree.** `mcp_server.py`
  has no knowledge this tool exists and imports nothing from it. This
  tool is not listed in `build_manifest.py`, is never bundled into T2 or
  T3, and does not share GLA's `sys.path` bootstrap.
- **No MCP protocol logic of its own.** Streamable-HTTP MCP traffic is
  ordinary HTTP with a JSON body — this proxy forwards the request and
  response payload without modifying their JSON content. It never
  changes a tool call's parameters or a response's data. Note this is
  not a byte-transparent transport proxy: the response is fully read
  into memory and re-sent rather than streamed through untouched, and
  framing headers (`Content-Length`, `Transfer-Encoding`, `Connection`)
  are regenerated rather than passed through as-is. Fine for local
  diagnostics; not a drop-in for anything that needs true HTTP-level
  transparency.
- **No write access to the archive.** Purely observational — it never
  imports `garmin_config`, `maps.mcp_map`, or any other GLA module. The
  only thing it reads from `~/.garmin_mcp_server_config.json` is
  `base_dir`, for its own log location — never the port (see "How the
  ports work" below). It reads that file directly (three lines,
  duplicated from `mcp_server.py`'s own equivalent block), not via a
  GLA import — this tool has no dependency on the GLA `src/` tree being
  present at all.
- **No authentication of its own.** Same trust boundary as
  `mcp_server.py` — binds to `127.0.0.1` only, by default.

## How the ports work

Open WebUI's tool-server URL is something you set **once** and never
touch again — whether logging is active or not.

To make that true, this proxy always listens on the **same port**
`mcp_server.py` normally uses (8756 by default — `logger_config.PROXY_PORT`).
When you want to log, `mcp_server.py` itself moves to a different,
internal port instead (`logger_config.INTERNAL_MCP_PORT`, 8758 by
default) — done entirely through the `GARMIN_MCP_HTTP_PORT` environment
variable, which `garmin_config.py` already reads with its own documented
ENV > file > default precedence. **No code in `mcp_server.py` changes,
no setting in the GUI changes** — only which script you start.

```
Normal (no logging):
  Open WebUI ──────────────► mcp_server.py (port 8756, as always)

With logging (run_mcp_with_logger.bat):
  Open WebUI ──► MCP Call Logger (port 8756) ──► mcp_server.py (port 8758, internal)
                        │
                        └──► writes to garmin_data/log/mcp_proxy/
```

Either way, Open WebUI talks to port 8756 and never knows the
difference. If you delete this whole tool tomorrow, nothing about your
Open WebUI configuration needs to change — you'd just go back to
starting `mcp_server.py` the normal way.

## Setup

```
pip install -r requirements.txt
```

(Only dependency: `requests`, used to forward requests to
`mcp_server.py`. Isolated to this tool — not a GLA project dependency.)

**Before first use:** open `run_mcp_with_logger.bat` in a text editor
and set `MCP_SERVER_PATH` to your actual `mcp_server.exe` location (or
adapt the `start` line to `python clients\mcp_server.py` if you're
running from a T1/dev checkout instead of the T3.3 standalone build).
This tool has no way to guess where your GLA installation lives.

## Usage

**To turn logging on:** run `run_mcp_with_logger.bat`. It opens two
windows — one running `mcp_server.py` on the internal port, one running
this proxy on `mcp_server.py`'s normal port. Open WebUI's tool-server
URL does not need to change.

**To turn logging off:** close both windows, then start `mcp_server.py`
the way you always do (GUI, Start Menu, whatever). Open WebUI's URL
still doesn't need to change — `mcp_server.py` is listening on that
same port again, directly.

**If port 8756 is already in use when the proxy tries to start:**
that almost always means `mcp_server.py` is already running on its
normal port somewhere (not started via `run_mcp_with_logger.bat`).
Stop it first — the proxy needs that port for itself while logging is
active.

## Where logs go

`<base_dir>/garmin_data/log/mcp_proxy/mcp_proxy_<timestamp>.log` —
`base_dir` is read from the same `~/.garmin_mcp_server_config.json`
`mcp_server.py` itself uses. If that file is missing or has no
`base_dir` set, logs fall back to a local `log/` folder next to this
script instead.

One file per proxy run, JSON-lines format (one JSON object per line —
easy to `grep`/parse). Rotates the same way `mcp_server.py`'s own log
does: oldest files beyond `logger_config.LOG_PROXY_MAX` (default 30)
are deleted on each start.

## Log depth

Set in `logger_config.py`:

- **`LOG_DEPTH = "metadata"`** (default) — logs the tool name,
  parameters, response status/size, and for any list-shaped value in
  the response (e.g. an intraday series) its length — but not the
  actual values. Small on disk, enough to judge "too little / too much
  data went in".
- **`LOG_DEPTH = "full"`** — logs the complete response payload,
  including full intraday series. Useful for exact reproduction of what
  the MCP server sent the LLM client; log files grow quickly with heavy
  intraday use.

Example `metadata`-depth entry:

```json
{
  "timestamp": "2026-08-25T17:51:40",
  "tool": "query_health",
  "params": {"field": "heart_rate", "date_from": "2026-08-20", "date_to": "2026-08-25", "resolution": "intraday"},
  "status_code": 200,
  "response_bytes": 979,
  "response_summary": {
    "result": {"type": "dict", "keys": {
      "field": {"type": "str"},
      "values": {"type": "list", "length": 200},
      "unit": {"type": "str"}
    }}
  }
}
```

## Privacy and security

This proxy is intended for local diagnostics only.

With `LOG_DEPTH = "full"`, log files may contain complete Garmin
health/activity data returned by the MCP server, including potentially
sensitive intraday values (heart rate, sleep, stress, body battery,
location-derived context). Treat these logs as sensitive data — the
same care you'd apply to the archive itself, since a full-depth log is
effectively a copy of whatever passed through it.

The proxy adds no authentication of its own. With the default
`PROXY_BIND_HOST = "127.0.0.1"`, it is reachable only from this
machine. If `PROXY_BIND_HOST = "0.0.0.0"` is used for Docker access
(see below), the proxy becomes reachable from other machines on the
local network — same trade-off `mcp_server.py`'s own
`MCP_EXTRA_ALLOWED_HOSTS_ENABLED` setting already accepts.

The proxy never writes to the GLA archive itself (see "What it is
NOT" above) — but that only means it can't corrupt your data. It does
not mean the log files are harmless: they may hold a full copy of
whatever data the archive returned through the MCP server for that
call.

## Docker note (Open WebUI running in a container)

If Open WebUI runs in Docker, it reaches the host via
`host.docker.internal`, not `127.0.0.1` — a proxy bound only to
`127.0.0.1` is physically unreachable from inside the container, no URL
change on Open WebUI's side can work around that.

Set `PROXY_BIND_HOST = "0.0.0.0"` in `logger_config.py` to bind on all
interfaces instead. This makes the proxy reachable from other machines
on your local network too, not just this one — the same trade-off
`mcp_server.py`'s own `MCP_EXTRA_ALLOWED_HOSTS_ENABLED` setting already
accepts for the same Docker scenario.

## Other settings (`logger_config.py`)

- `PROXY_PORT` — the port Open WebUI's tool-server URL points at.
  Should match whatever port `mcp_server.py` would normally use (8756
  unless you changed it in the GUI).
- `INTERNAL_MCP_PORT` — the port `mcp_server.py` runs on while logging
  is active. Must match the `GARMIN_MCP_HTTP_PORT` value set in
  `run_mcp_with_logger.bat` — change both together if you ever need a
  different internal port.
- `LOG_PROXY_MAX` — rolling log-file limit (default 30).
