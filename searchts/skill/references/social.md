# Social media & communities

Twitter/X, Reddit.

## Primary: read the public URL

For a tweet, profile, subreddit, or Reddit post, the primary path is to read
the public URL directly:

```bash
searchts read "https://x.com/user/status/123"
searchts read "https://www.reddit.com/r/LocalLLaMA/comments/abc/title/"
```

`searchts read` runs the escalating unlocker, so it gets through most bot-walls
keylessly. To find discussions in the first place, use `searchts search`, then
read the URLs it returns. For a video tweet/post, use
`searchts transcribe <url>`.

## Optional: platform CLIs

These are optional enhancements, only useful if you have already installed and
logged into the relevant CLI. They are not required — `searchts read` on the
URL is the default. Run `searchts doctor` to see which (if any) are present.

### Twitter/X (twitter-cli, optional)

```bash
twitter feed -n 20                 # home timeline
twitter tweet URL_OR_ID            # single tweet with replies
twitter user-posts @username -n 20 # user timeline
```

> **Auth**: export cookies via Cookie-Editor and set `TWITTER_AUTH_TOKEN` +
> `TWITTER_CT0`. Prefer `--yaml`/`--json` output for an agent. Avoid frequent
> calls from VPS/datacenter IPs (ban risk).

### Reddit (OpenCLI / rdt-cli, optional, login required)

```bash
opencli reddit search "query" -f yaml     # desktop, reuses browser login
opencli reddit read POST_ID -f yaml
rdt search "query" --limit 10             # legacy/server fallback
```

> Both backends need a logged-in session. The anonymous `.json` endpoints are
> blocked (403). If neither CLI is set up, just `searchts read` the post URL.
