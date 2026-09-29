# Docker Test — Containerized MCP Server

A Dockerfile that runs `clients/mcp_server.py` (the MCP server tools,
headless, streamable-http transport) inside a container, against an
archive mounted from the host. Exists for container-based server
verification (e.g. submitting Garmin_Local_Archive to the
[glama.ai](https://glama.ai/mcp/servers) MCP server registry, which
builds and starts a container to check the server responds) and for
quickly trying the MCP tools without a Windows install — e.g. against
the fictional demo archive in `../demo-export/demo_archive.zip`.

## What it is NOT

- **Not part of the GLA package tree.** `mcp_server.py` and
  `garmin_config.py` are used completely unmodified — this folder adds
  files, it does not patch existing ones. Not listed in
  `build_manifest.py`, never bundled into T2 or T3.
- **Not the recommended way to run the MCP server day to day.** The
  Windows app's own "Start MCP Server" button (MCP Server tab) or
  standalone `mcp_server.exe` remain the normal path — see the main
  [README](../../../README.md) and
  [`docs/REFERENCE_MCP.md`](../../docs/REFERENCE_MCP.md). This is a
  container build for verification/testing, not a deployment
  recommendation.

## Why `entrypoint.py` exists

`mcp_server.py` hardcodes `FastMCP(..., host="127.0.0.1", ...)` — a
deliberate security boundary: the normal desktop app is never remotely
reachable. Inside a container, `127.0.0.1` is the container's own
loopback — unreachable from outside even with a published port. Rather
than touch that hardcoded value in production code, `entrypoint.py`
imports `mcp_server` completely unmodified and overrides the
already-constructed `FastMCP` instance's mutable `settings.host`
*after* import but *before* calling `main()` — the `mcp` SDK reads
`self.settings.host` lazily at `.run()`, not at construction (verified
against `mcp==1.30.0`). Opt-in via `GARMIN_MCP_BIND_HOST` (set to
`0.0.0.0` below); unset, behavior is identical to running
`mcp_server.py` directly.

## Building and running

From the repo root (the build needs the whole `src/` tree as context):

```bash
docker build -f src/support-tools/docker-test/Dockerfile -t gla-mcp-server .
```

Against the fictional demo archive (see
[`../demo-export/DEMO_ARCHIVE_README.md`](../demo-export/DEMO_ARCHIVE_README.md)):

```bash
unzip src/support-tools/demo-export/demo_archive.zip -d /tmp/gla-demo
docker run --rm -p 8756:8756 -v /tmp/gla-demo/demo_archive:/data gla-mcp-server
```

The server is then reachable at `http://localhost:8756/mcp` from the
host. Point `-v` at any real GLA archive folder (the one containing
`garmin_data/`) instead of the demo archive to serve real data.

## Known limitation with the demo archive

The demo archive's `quality_log.json` is intentionally empty (see its
own README) — the boot sync that derives `date_min`/`date_max` from it
finds nothing, so `query_health`/`query_context` return `has_data:
false` against the demo archive specifically. This is a demo-data gap,
not a container or `entrypoint.py` issue: `list_available_fields` and
`get_archive_metadata` still work normally, and a real archive (with a
populated `quality_log.json`) queries correctly.
