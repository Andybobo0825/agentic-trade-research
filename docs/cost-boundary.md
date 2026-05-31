# Cost boundary: Codex vs external data APIs

## What uses your Codex/ChatGPT allowance

- Reading command outputs.
- Planning the research steps.
- Writing investment memos, DCF assumptions, risk sections, and follow-up questions.
- Any reasoning you ask Codex to do in this repo.

## What does not use your Codex/ChatGPT allowance

- Calls to Financial Datasets through `FINANCIAL_DATASETS_API_KEY`.
- Calls to free/open Taiwan data providers such as FinMind, TWSE OpenAPI, TPEx OpenAPI, and MOPS-backed open datasets; their provider quotas/rate limits still apply.
- Calls to Fugle realtime market data through `FUGLE_API_KEY`; Fugle plan limits and subscription fees are external data costs.
- Any other future data provider API key added to this toolkit.
- Network usage, provider rate limits, or subscription tiers from external data vendors.

## Recommended Codex prompt

```text
Use this repo's finance CLI. Do not call an LLM API. Fetch the needed data with node src/cli.js, then synthesize the answer yourself. Separate evidence from inference and identify any missing data.
```

## Minimal research loop

1. Run `node src/cli.js statement --ticker <TICKER> --statement income --limit 5 --format markdown`.
2. Run `node src/cli.js metrics --ticker <TICKER>`.
3. Run `node src/cli.js price --ticker <TICKER>`.
4. Run `node src/cli.js filings --ticker <TICKER> --filing-type 10-K --limit 3 --format markdown`.
5. Have Codex synthesize a memo using `workflows/research-memo.md` or `workflows/dcf-valuation.md`.
