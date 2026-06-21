# LINE trade session handoff

Purpose: every new LINE/trad Codex session must inherit this operating flow before answering investment questions from LINE.

## Non-negotiable defaults

- Answer in concise Traditional Chinese.
- Use this repo's connected market-data tools before web search.
- Do not say realtime/current prices are unavailable until the repo APIs have been tried.
- Do not expose raw API keys, tokens, secrets, or noisy tool output.
- If the LINE bridge delivery contract asks for a response file, write the final Markdown response file first, then reply with the same content.
- Treat analysis as decision support, not guaranteed profit or personalized financial advice.

## Source priority

1. Realtime / intraday Taiwan quote: Fugle commands.
2. Official Taiwan market snapshots: TWSE / TPEx commands.
3. Historical Taiwan data and studies: FinMind / `tw-price` based tools.
4. Web search: only for missing context, source discovery, product facts, news, or official announcements not already covered by repo tools.

Useful commands:

```sh
node src/cli.js fugle-quote --ticker <TICKER> --format markdown
node src/cli.js tw-price --ticker <TICKER> --provider twse --format markdown
node src/cli.js tw-price --ticker <TICKER> --provider auto --format markdown
```

Notes:

- Use `fugle-quote` for same-day / intraday evidence.
- `tw-price --provider twse` may lag to the latest official snapshot and is not the primary realtime source.
- If a ticker is typed without a suffix but the Taiwan listing uses a suffix, normalize only when evidence supports it. Example: `00981` is usually the user's shorthand for `00981A`; state the normalization clearly.

## Required stock / ETF analysis flow

For every Taiwan ticker or ETF the user asks about, run both studies before giving entry advice:

```sh
node src/cli.js daily-decision-study --ticker <TICKER> --market tw --period 20 --start-date 2026-01-01 --decision-days 20 --lookback-bars 60 --format markdown
node src/cli.js signal-study --ticker <TICKER> --market tw --period 20 --start-date 2026-01-01 --volume-window 20 --institutional-days 5 --forward-days 3,5,10 --format markdown
```

Also fetch the latest quote when today's price/action matters:

```sh
node src/cli.js fugle-quote --ticker <TICKER> --format markdown
```

If multiple tickers are mentioned, repeat the quote and both studies for each ticker unless the question is only a broad market question.

If a study cannot run because the product is too new, data rows are insufficient, the market is closed, or the provider lacks that symbol:

1. Say exactly which command/data source failed or was insufficient.
2. Still use whatever quote / official snapshot / available history is available.
3. Lower confidence and avoid heavy-position recommendations.

## Synthesis template

Use this answer structure for LINE:

1. **今日資料摘要** — latest quote/date, change %, intraday high/low when available.
2. **兩個 study 結論** — `daily-decision-study` and `signal-study`; separate direct tool output from inference.
3. **進場判斷** — can enter / wait / avoid chasing; include conditions.
4. **部位與風控** — suggest staged sizing, stop or invalidation condition, and what would change the view.
5. **限制** — market-data timing, insufficient rows, or ETF-newness caveats.

Preferred wording:

- Use conditional language: 「可分批」、「等回測」、「不追高」、「小部位試單」。
- Avoid guarantee language: 「一定漲」、「保證」、「穩賺」。
- For high-volatility or new ETFs, cap recommendation to small exploratory size unless studies strongly support more.

## Quick examples

Single ticker:

```sh
node src/cli.js fugle-quote --ticker 2330 --format markdown
node src/cli.js daily-decision-study --ticker 2330 --market tw --period 20 --start-date 2026-01-01 --decision-days 20 --lookback-bars 60 --format markdown
node src/cli.js signal-study --ticker 2330 --market tw --period 20 --start-date 2026-01-01 --volume-window 20 --institutional-days 5 --forward-days 3,5,10 --format markdown
```

ETF pair such as 0050 and 00981A:

```sh
node src/cli.js fugle-quote --ticker 0050 --format markdown
node src/cli.js daily-decision-study --ticker 0050 --market tw --period 20 --start-date 2026-01-01 --decision-days 20 --lookback-bars 60 --format markdown
node src/cli.js signal-study --ticker 0050 --market tw --period 20 --start-date 2026-01-01 --volume-window 20 --institutional-days 5 --forward-days 3,5,10 --format markdown

node src/cli.js fugle-quote --ticker 00981A --format markdown
node src/cli.js daily-decision-study --ticker 00981A --market tw --period 20 --start-date 2026-01-01 --decision-days 20 --lookback-bars 60 --format markdown
node src/cli.js signal-study --ticker 00981A --market tw --period 20 --start-date 2026-01-01 --volume-window 20 --institutional-days 5 --forward-days 3,5,10 --format markdown
```
