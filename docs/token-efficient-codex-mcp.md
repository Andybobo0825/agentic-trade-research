# Token-efficient Codex MCP setup for investment research

Goal: keep the same research coverage and data quality while lowering the tokens Codex spends reading tool output. The rule is **compress output, not evidence collection**.

## Required MCP stack

Use exactly these default research tools before adding more search providers:

1. `trade-finance` — this repo's structured finance MCP. Use it for prices, statements, metrics, filings, Taiwan open data, FinMind, TWSE/TPEx, and Fugle. Do not use web search for data that this MCP already exposes.
2. `brave-search` — use only the LLM-context/search-summary tool for broad web discovery and source finding.
3. `jina` — use read/search only for token-efficient webpage reading after Brave identifies relevant URLs.

Avoid connecting multiple overlapping search MCPs by default. Extra MCP servers increase tool-schema context and make Codex choose among redundant tools.

## Codex config example

Put this in `~/.codex/config.toml` or merge the relevant blocks into your existing config.

```toml
tool_output_token_limit = 4000

[tools.web_search]
context_size = "low"

[mcp_servers.trade-finance]
command = "node"
args = ["/Users/chentingwei/Desktop/SideProject/trade/src/mcp-server.js"]

[mcp_servers.brave-search]
command = "npx"
args = ["-y", "@brave/brave-search-mcp-server", "--transport", "stdio"]

[mcp_servers.brave-search.env]
BRAVE_API_KEY = "${BRAVE_API_KEY}"
BRAVE_MCP_ENABLED_TOOLS = "brave_llm_context"

[mcp_servers.jina]
command = "npx"
args = [
  "-y",
  "mcp-remote",
  "https://mcp.jina.ai/v1?include_tags=search,read",
  "--header",
  "Authorization: Bearer ${JINA_API_KEY}"
]
```

## Operating policy

### Preserve search/data volume

- Keep requested sources and tool calls intact: price, metrics, statements, filings, news, announcements, valuation, and realtime data when relevant.
- Use provider/API `limit` only when the research question genuinely needs fewer records.
- Use MCP `maxRows` and `outputFields` only as **rendering controls**. They reduce what Codex reads, not what upstream search/data providers are asked to fetch.
- Prefer `research-pack` for one bundled request instead of many raw calls when the same investment memo needs multiple sources.

### Lower token output

- MCP defaults to `format: "compact-json"`; request `format: "markdown"` for memo-ready tables.
- Prefer `outputFields` for row-heavy responses, for example `date,close,volume` for price rows.
- Prefer `maxRows` for display previews while keeping the raw provider limit explicit in the task.
- Use Brave with tight context caps, then Jina to read only the selected URLs.

## Example MCP calls

### US research bundle

```json
{
  "name": "research-pack",
  "arguments": {
    "ticker": "AAPL",
    "market": "us",
    "include": ["price", "metrics", "statement", "news", "filings"],
    "statementLimit": 5,
    "newsLimit": 10,
    "filingLimit": 5,
    "format": "markdown"
  }
}
```

### Taiwan research bundle

```json
{
  "name": "research-pack",
  "arguments": {
    "ticker": "2330",
    "market": "tw",
    "include": ["tw-company", "tw-price", "tw-revenue", "tw-financials", "tw-valuation", "tw-announcements", "tw-news"],
    "provider": "auto",
    "newsLimit": 10,
    "announcementLimit": 10,
    "format": "markdown"
  }
}
```

### Row-heavy output shaping

```json
{
  "name": "tw-price",
  "arguments": {
    "ticker": "2330",
    "provider": "finmind",
    "startDate": "2024-01-01",
    "endDate": "2024-12-31",
    "limit": 250,
    "format": "compact-json",
    "outputFields": "date,stock_id,open,max,min,close,Trading_Volume",
    "maxRows": 20
  }
}
```

Here `limit: 250` preserves the requested provider fetch size; `maxRows: 20` only controls what is rendered back into Codex context.

## Web-search sequence

1. Ask Brave for broad discovery with small caps, e.g. maximum 3-5 URLs and 1500-2500 tokens.
2. Read only the chosen high-signal URLs with Jina `read` so Codex receives cleaned Markdown rather than HTML/DOM noise.
3. Store citations/URLs in the memo; do not paste full articles unless needed.
4. Use `trade-finance` for structured market data and only use web search for missing context, current narratives, official announcements, or source discovery.

## Quality guardrail

Token savings are valid only when the final memo still identifies:

- which sources were fetched;
- which data was direct evidence versus inference;
- any provider/API errors;
- any intentionally omitted rendered rows caused by `maxRows`/`outputFields`.
