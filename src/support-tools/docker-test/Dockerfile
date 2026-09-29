# Garmin Local Archive — MCP server only, for container-based verification
# (e.g. glama.ai's MCP server registry) and quick local testing.
#
# The full GLA app (GUI, Garmin Connect sync, cloud-LLM chat) stays
# Windows-native. This image runs just clients/mcp_server.py in headless
# mode (GARMIN_MCP_HEADLESS=true, no Tkinter) against an archive mounted
# from the host, via entrypoint.py — a Docker-only wrapper that does not
# modify mcp_server.py or garmin_config.py (see entrypoint.py's own
# docstring for why/how).
#
# Build from the repo root (needs the whole src/ tree in its context):
#   docker build -f src/support-tools/docker-test/Dockerfile -t gla-mcp-server .
# Run against an archive (e.g. the demo archive in
# src/support-tools/demo-export/demo_archive.zip, extracted):
#   docker run -p 8756:8756 -v /path/to/archive:/data gla-mcp-server

FROM python:3.11-slim

WORKDIR /app

COPY src/support-tools/docker-test/requirements-mcp.txt ./requirements-mcp.txt
RUN pip install --no-cache-dir -r requirements-mcp.txt

COPY src/ ./src/
COPY src/support-tools/docker-test/entrypoint.py ./entrypoint.py

ENV GARMIN_MCP_HEADLESS=true
ENV GARMIN_OUTPUT_DIR=/data
ENV GARMIN_MCP_HTTP_PORT=8756
ENV GARMIN_MCP_BIND_HOST=0.0.0.0

EXPOSE 8756
VOLUME ["/data"]

CMD ["python", "entrypoint.py"]
