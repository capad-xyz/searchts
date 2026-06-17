# Reddit setup guide

## What it does

Reddit blocks almost all non-browser direct access (including datacenter and ISP proxy IPs), and the JSON API returns 403.

searchts provides Reddit search and reading through **rdt-cli**:
- **Search**: `rdt search "keyword"`
- **Read full post + comments**: `rdt read POST_ID`

Free, no proxy needed, no API key. Requires login authentication (`rdt login`, which automatically extracts the Cookie from the browser).

## Steps the agent can do automatically

1. Check whether rdt-cli is available:
```bash
which rdt && echo "installed" || echo "not installed"
```

2. If not installed, install it automatically (the PyPI version lags behind for now, so install the latest from GitHub):
```bash
pipx install 'git+https://github.com/public-clis/rdt-cli.git'
```

Or one-step install:
```bash
searchts install --env=auto --channels=reddit
```

## Usage examples

Search Reddit content:
```bash
rdt search "python best practices" -n 5
```

Read a full post and comments:
```bash
rdt read POST_ID
```

## Steps the user must do manually

None. rdt-cli is installed automatically by `searchts install --env=auto`.

## Fallback: Exa search

If you have already configured Exa (via mcporter), you can also search Reddit content through Exa:

```bash
mcporter call 'exa.web_search_exa(query: "python best practices", numResults: 5, includeDomains: ["reddit.com"])'
```

rdt-cli is the current recommended option and works with no extra configuration.
