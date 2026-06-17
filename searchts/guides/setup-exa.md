# Exa Search setup guide

## What it does
Exa is an AI semantic search engine. It connects via MCP, **free, no API key required**. Once configured it unlocks:
- Web-wide semantic search
- Reddit search (via site:reddit.com)
- Twitter search (via site:x.com)

## Steps the agent can do automatically

`searchts install --env=auto` performs the steps below automatically; you usually do not need to do anything by hand.

### 1. Install mcporter
```bash
npm install -g mcporter
```

### 2. Register the Exa MCP
```bash
mcporter config add exa https://mcp.exa.ai/mcp
```

### 3. Verify
```bash
searchts doctor | grep "Search"
mcporter call 'exa.web_search_exa(query: "test", numResults: 1)'
```

## Steps the user must do manually

**None.** Exa connects via MCP — free, no registration, no API key.

If `searchts install` did not configure Exa automatically because of a network issue, just run the two commands above by hand.

## FAQ

**Q: Is there a limit on the number of searches?**
A: The MCP endpoint is provided by Exa officially (mcp.exa.ai) and is currently free with no limit. If that changes in the future, searchts will adapt in an update.

**Q: What is mcporter?**
A: A command-line bridge for the MCP protocol, used to call an MCP server. searchts uses it to connect to Exa.
