# Social media & communities

Twitter/X, Reddit.

## Twitter/X (twitter-cli)

### Stable commands

```bash
# Home timeline (most stable)
twitter feed -n 20

# Read a single tweet (with replies)
twitter tweet URL_OR_ID

# Read a long post / X Article
twitter article URL_OR_ID

# User timeline
twitter user-posts @username -n 20

# User profile
twitter user @username
```

### Commands that may be unstable

```bash
# Search tweets (Twitter frequently changes its GraphQL endpoints, may 404)
twitter search "query" -n 10

# likes (since 2024 you can only see your own, platform limit)
twitter likes
```

### Retry chain when search fails (run in order, stop on success)

1. Retry once directly (occasional failures are common): `twitter search "query" -n 10`
2. Upgrade and try again: `pipx upgrade twitter-cli && twitter search "query" -n 10`
3. Switch to the OpenCLI fallback (desktop, reuses browser login): `opencli twitter search "query" -f yaml`
4. If none work, route around it with stable commands like `twitter feed` / `twitter user-posts @somebody`

### Important notes

> **Install**: `pipx install twitter-cli` (make sure it is v0.8.5+)
>
> **Auth**: prefer exporting cookies via Cookie-Editor and setting the environment variables `TWITTER_AUTH_TOKEN` + `TWITTER_CT0`. Automatic extraction does not work in SSH/Docker/headless environments.
>
> **IP risk control**: do not call frequently from VPS/datacenter IPs, especially followers/following — there is a ban risk. Use a residential proxy or a local environment.
>
> **OpenCLI fallback**: if OpenCLI is installed on the desktop, the full set `opencli twitter search/article/user-posts -f yaml` is available (browser login, no cookie environment variables needed).
>
> **Output format**: prefer `--yaml` or `--json` for structured output, which is friendlier for an AI agent.

## Reddit (multi-backend, login required)

**Reddit has no zero-config path**: the anonymous `.json` endpoints are blocked (403), and the official API has been essentially impossible to get approved by manual review since 2025-11. Both backends rely on a logged-in session, so run `searchts doctor --json` first to see Reddit's `active_backend`. Access from mainland China needs a proxy.

### Backend A: OpenCLI (desktop preferred, reuses browser login)

```bash
# Search posts
opencli reddit search "query" -f yaml

# Read full post + comments
opencli reddit read POST_ID -f yaml

# Browse subreddit / hot / Popular
opencli reddit subreddit LocalLLaMA -f yaml
opencli reddit hot -f yaml
opencli reddit popular -f yaml

# subreddit metadata (subscriber count, description)
opencli reddit subreddit-info LocalLLaMA -f yaml
```

> Requires Chrome to be open and logged in to reddit.com in the browser.

### Backend B: rdt-cli (legacy/server fallback, upstream frozen since 2026-03)

```bash
rdt search "query" --limit 10   # search posts
rdt read POST_ID                # read full post + comments
rdt sub python --limit 20       # browse subreddit
rdt popular --limit 10          # browse hot
rdt all --limit 10              # browse /r/all
```

> **Install**: `pipx install 'git+https://github.com/public-clis/rdt-cli.git'` (the PyPI version lags behind, install v0.4.2+ from GitHub). Run `rdt login` first to enable search and reading (on a server with no browser, write the Cookie manually — see the doctor hint).
> Prefer `--yaml` output, which is friendlier for an AI agent.

### Advanced option: official API + PRAW (only for users who already have credentials)

Users who registered a Reddit script app before 2025-11 (holding client_id/client_secret) can use PRAW against the official API (100 QPM free). New applications require manual review and personal projects are essentially never approved, so **do not recommend this path to new users**.
