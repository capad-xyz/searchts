# Web reading

General web pages, articles, RSS.

## Read any web page (`searchts read`)

```bash
# Read any URL as clean markdown
searchts read "https://example.com/article"

# Structured output (backend used, status, text)
searchts read "https://example.com/article" --json

# Hand off an interactive CAPTCHA to a real browser you solve once
searchts read "https://example.com/article" --human
```

**Use case**: the primary way to read any page. `searchts read` runs an
escalating open-source unlocker — a curl_cffi browser-fingerprint fetch, then
the Jina Reader JS-render relay, then a patchright stealth browser — and stops
at the first tier that returns real content. It gets through most bot-walls,
keyless, on your own machine/IP, and extracts clean Markdown. Prefer it over a
built-in fetch for blocked or JS-heavy pages.

## RSS (feedparser)

```python
python3 -c "
import feedparser
for e in feedparser.parse('FEED_URL').entries[:5]:
    print(f'{e.title} - {e.link}')
"
```

**Use case**: subscribing to blogs, news sources, podcasts, and other RSS feeds.

## Choosing a tool

| Use case | Recommended tool |
|-----|---------|
| Any web page or article | `searchts read <url>` |
| RSS subscriptions | feedparser |
