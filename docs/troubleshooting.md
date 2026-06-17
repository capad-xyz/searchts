# Troubleshooting

## Twitter/X: twitter-cli connection fails

**Symptom:** `twitter search` or other commands return an error

**Cause:** twitter-cli needs the AUTH_TOKEN and CT0 environment variables to access the Twitter API. If your network requires a proxy to reach x.com, you must configure a proxy.

**Solutions:**

### Option 1: Set proxy environment variables

```bash
export HTTP_PROXY="http://user:pass@host:port"
export HTTPS_PROXY="http://user:pass@host:port"
twitter search "test" -n 1
```

### Option 2: Use a global proxy tool

Let a proxy tool take over all network traffic so twitter-cli's requests also go through the proxy:

```bash
# macOS - ClashX / Surge with "enhanced mode" enabled
# Linux - proxychains or tun2socks
proxychains twitter search "test" -n 1
```

### Option 3: Skip twitter-cli, use Exa search instead

When twitter-cli is unavailable, you can search Twitter content directly with Exa:

```bash
mcporter call 'exa.web_search_exa(query: "site:x.com your search terms", numResults: 5)'
```

### Option 4: Check authentication

```bash
twitter check
```

> If it returns "Missing credentials", you need to set the AUTH_TOKEN and CT0 environment variables.
>
> **Fallback:** If you have installed the bird CLI (`npm install -g @steipete/bird`), it also works. searchts auto-detects installed tools.
