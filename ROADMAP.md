# Roadmap

searchts is *"the free, open-source, keyless web layer for agents"* — won by being reliable and
easy for an agent to reach for, not by having the most features. This roadmap reflects that focus.
It's a direction, not a promise; issues and PRs are welcome (see [CONTRIBUTING.md](CONTRIBUTING.md),
especially [what we merge](CONTRIBUTING.md#what-we-merge-and-what-we-dont)).

## Now

- **Agent legibility** — sharper MCP tool descriptions, an [MCP reference](docs/mcp.md), and
  claiming the Glama listing, so agents (and MCP directories) can find and adopt searchts.
- **Contribution flywheel** — issue/PR templates, this roadmap, and good-first-issues, so the
  project is easy to contribute to.

## Next

- **Public unlocker benchmark** — a reproducible set of bot-walled pages searchts measures itself
  against, published as a scorecard. It doubles as a regression canary (we find out the day an
  anti-bot vendor breaks us) and as a great first contribution: *add a site.*
- **Reliability** — evidence-driven fixes to whatever the benchmark exposes (block-detection gaps,
  timeout tuning).

## Later

- **Persistent stealth profile** — reuse a warmed browser profile across stealth-tier reads.
- **PDF & document reading** — first-class handling for PDF/document URLs.
- **Result caching** — optional content cache for repeat reads of the same URL.
- **Sitemap / small multi-page crawl** — read a handful of related pages in one call.

## Not planned

- Paid-proxy / residential-IP pools, a hosted service, or paid-API backends as defaults — these cut
  against the keyless, own-IP identity that makes searchts different. See
  [what we merge](CONTRIBUTING.md#what-we-merge-and-what-we-dont).
