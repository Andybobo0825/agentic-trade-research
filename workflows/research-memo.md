# Codex Finance Research Memo Workflow

Use this with Codex, not with a second LLM API-backed agent.

1. Define the research question and ticker universe.
2. Fetch primary data with `node src/cli.js` commands.
3. Ask Codex to synthesize evidence, cite command outputs, and separate evidence from inference.
4. If valuation is required, fetch 3-5 years of statements and build assumptions in the memo.
5. Produce a concise memo: thesis, evidence, risks, valuation/monitoring checklist, open questions.

Suggested commands:

```sh
node src/cli.js statement --ticker AAPL --statement income --period annual --limit 5 --format markdown
node src/cli.js metrics --ticker AAPL
node src/cli.js price --ticker AAPL
node src/cli.js filings --ticker AAPL --filing-type 10-K --limit 3 --format markdown
```
