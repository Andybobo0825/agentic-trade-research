# Taiwan data sources

This repo now exposes Taiwan stock research tools through free/open data first.

## Free/open providers currently wired

| Provider | CLI coverage | Notes |
| --- | --- | --- |
| FinMind | `tw-price`, `tw-revenue`, `tw-financials`, `tw-institutional`, `tw-valuation`, `tw-news`, `tw-raw` | Free API works without token at a lower quota. Optional `FINMIND_API_TOKEN` can raise quota after registration. |
| TWSE OpenAPI | `tw-price`, `tw-company`, `tw-valuation`, `tw-announcements`, `tw-financials --provider twse`, `tw-raw` | Official listed-company/open-market snapshots. Mostly latest snapshots rather than historical ranges. |
| TPEx OpenAPI | `tw-price`, `tw-company`, `tw-valuation`, `tw-announcements`, `tw-institutional --provider tpex`, `tw-financials --provider tpex`, `tw-raw` | Official OTC/emerging-market snapshots. |
| MOPS-backed open data | `tw-announcements`, `tw-financials --provider twse|tpex` | MOPS company disclosures exposed through TWSE/TPEx OpenAPI datasets. |
| Fugle MarketData | `fugle-quote`, `fugle-candles`, `fugle-trades`, `fugle-volumes`, `fugle-snapshot`, `fugle-technical`, `fugle-raw` | Optional realtime/intraday provider. Requires `FUGLE_API_KEY`; some endpoints require paid Fugle plans. |

## Examples

```sh
node src/cli.js tw-endpoints
node src/cli.js tw-price --ticker 2330 --provider finmind --start-date 2024-01-01 --end-date 2024-01-10 --format markdown
node src/cli.js tw-price --ticker 2330 --provider twse --format markdown
node src/cli.js tw-company --ticker 2330
node src/cli.js tw-revenue --ticker 2330 --start-date 2024-01-01 --format markdown
node src/cli.js tw-financials --ticker 2330 --statement income --provider finmind --start-date 2024-01-01 --format markdown
node src/cli.js tw-financials --ticker 2330 --statement income --provider twse --format markdown
node src/cli.js tw-institutional --ticker 2330 --start-date 2024-01-01
node src/cli.js tw-valuation --ticker 2330 --provider auto --format markdown
node src/cli.js tw-announcements --ticker 2330 --limit 5
node src/cli.js tw-raw --provider finmind --dataset TaiwanStockDividend --ticker 2330 --start-date 2020-01-01
node src/cli.js tw-raw --provider twse --endpoint /exchangeReport/STOCK_DAY_ALL --ticker 2330
```

## Realtime provider

Fugle is now wired for realtime/intraday evidence. See `docs/fugle-marketdata.md`. Keep TWSE/TPEx/FinMind as the free baseline and use Fugle only when live market data matters.

## Paid data worth considering later

Free sources are enough for fundamental research, but a paid source can materially improve the model output if you need:

- clean long-history adjusted prices and corporate-action normalization;
- survivorship-bias-free universes for backtests;
- intraday/tick data with stable SLAs;
- analyst estimates, consensus revisions, ownership, supply-chain, or alternative data;
- unified point-in-time financial statements to avoid restatement leakage.

For Taiwan, a managed API such as TW Market Data or a broker/data-vendor feed may save engineering time once the research workflow proves useful. Keep these optional; they are data costs, not LLM costs.
