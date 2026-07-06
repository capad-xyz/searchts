# Minimal image for running the searchts MCP server over stdio — for hosts
# (e.g. Glama) that build and run the server in a container.
#
# It ships the keyless read / search / asset tools. The optional stealth-browser
# tier (patchright) is intentionally omitted to keep the image small, so inside
# this container read_url uses the curl_cffi and Jina Reader tiers.
FROM python:3.12-slim

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir ".[mcp]"

# The MCP server speaks JSON-RPC over stdio; the host spawns it and talks on
# stdin/stdout.
ENTRYPOINT ["searchts", "mcp", "serve"]
