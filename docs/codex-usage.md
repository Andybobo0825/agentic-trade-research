# Using this repo with Codex for finance research

This repo intentionally does **not** run a separate LLM agent loop. Codex performs reasoning with your existing Codex/ChatGPT plan; the local tools only fetch and format external finance data.

## Setup

```sh
cp env.example .env
export FINANCIAL_DATASETS_API_KEY=...
```

## CLI examples

```sh
node src/cli.js statement --ticker MSFT --statement income --limit 5 --format markdown
node src/cli.js price --ticker NVDA
node src/cli.js news --ticker TSLA --limit 5
node src/cli.js filings --ticker AAPL --filing-type 10-K --limit 3 --format markdown
```


## Taiwan examples

```sh
node src/cli.js tw-price --ticker 2330 --provider finmind --start-date 2024-01-01 --format markdown
node src/cli.js tw-company --ticker 2330
node src/cli.js tw-revenue --ticker 2330 --start-date 2024-01-01 --format markdown
node src/cli.js tw-financials --ticker 2330 --statement income --provider finmind --start-date 2024-01-01 --format markdown
node src/cli.js tw-valuation --ticker 2330 --provider auto --format markdown
node src/cli.js tw-announcements --ticker 2330 --limit 5
```

Prompt pattern:

```text
Use the Taiwan free-data CLI commands in this repo to research 2330. Fetch price, company profile, monthly revenue, financial statements, valuation, and announcements. Then synthesize an evidence-first Traditional Chinese memo and separate direct data from inference.
```


## Fugle realtime examples

After setting `FUGLE_API_KEY`, use Fugle when a Taiwan-stock memo needs live or intraday evidence:

```sh
node src/cli.js fugle-quote --ticker 2330 --format markdown
node src/cli.js fugle-candles --ticker 2330 --scope intraday --timeframe 1 --format markdown
node src/cli.js fugle-trades --ticker 2330 --limit 20
node src/cli.js fugle-volumes --ticker 2330
```

Prompt pattern:

```text
Use Fugle for realtime quote/intraday data and TWSE/FinMind for fundamentals. Fetch 2330 live quote, intraday 1-minute candles, monthly revenue, valuation, and announcements. Then write a Traditional Chinese market update, clearly labeling realtime data versus fundamental data.
```

## MCP scaffold

For clients that support stdio MCP-like JSON-RPC tool calls:

```sh
node src/mcp-server.js
```

The server exposes `tools/list` and `tools/call` for the same tool names as the CLI.

## Cost boundary

- Codex reasoning: uses your existing Codex/ChatGPT allowance.
- Financial data: still billed/limited by the external data provider you configure.
- This project does not require `OPENAI_API_KEY` and does not call OpenAI API.

## Lowest-token investment research mode

For repeated investment-research service calls, use the required MCP stack and output policy in `docs/token-efficient-codex-mcp.md`:

- this repo's `trade-finance` MCP for structured finance data;
- Brave Search MCP for capped web discovery;
- Jina Reader/Search MCP for cleaned Markdown page reads.

Do not reduce source coverage to save tokens. Use `compact-json`, `markdown`, `outputFields`, and `maxRows` to reduce rendered output only.
