# Codex DCF / Valuation Workflow

This is a prompt workflow for Codex. It does not call an LLM API.

## Data fetch

```sh
node src/cli.js statement --ticker <TICKER> --statement income --period annual --limit 5 --format markdown
node src/cli.js statement --ticker <TICKER> --statement cash-flow --period annual --limit 5 --format markdown
node src/cli.js metrics --ticker <TICKER>
node src/cli.js price --ticker <TICKER>
node src/cli.js filings --ticker <TICKER> --filing-type 10-K --limit 3 --format markdown
```

## Codex synthesis instructions

1. Build historical revenue, margin, FCF, and share-count baseline from command outputs.
2. State every assumption explicitly: revenue CAGR, operating margin, tax rate, reinvestment, terminal growth, discount rate, net cash/debt, dilution.
3. Produce bear/base/bull scenarios rather than a single point estimate.
4. Separate direct evidence from inference.
5. Flag missing data instead of inventing values.
6. End with a monitoring checklist and what new filing/news would change the thesis.

## Output shape

- Business snapshot
- Historical evidence table
- Key assumptions
- DCF scenario table
- Risks / inversion
- Data gaps
- Monitoring checklist
