# Codex Market Narrative / News Workflow

Use Codex reasoning plus local data fetches, not an embedded agent.

1. Fetch recent news:
   `node src/cli.js news --ticker <TICKER> --limit 10`
2. Fetch latest price:
   `node src/cli.js price --ticker <TICKER>`
3. Fetch filing metadata for primary-source follow-up:
   `node src/cli.js filings --ticker <TICKER> --limit 5 --format markdown`
4. Ask Codex to classify each item as: earnings, guidance, regulatory, capital allocation, macro, product, sentiment-only.
5. Prefer primary filings and company releases over social/news summaries when they conflict.
