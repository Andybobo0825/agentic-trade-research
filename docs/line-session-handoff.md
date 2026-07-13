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

1. Primary Taiwan price/volume/replay data: Shioaji local server / repo Shioaji commands.
2. Realtime / intraday fallback quote: Fugle commands when Shioaji does not provide the needed dataset or is externally unavailable after repair attempt.
3. Official Taiwan market snapshots: TWSE / TPEx commands.
4. Historical Taiwan data and studies: FinMind / `tw-price` based tools when Shioaji lacks coverage.
5. Web search: only for missing context, source discovery, product facts, news, or official announcements not already covered by repo tools.

Useful commands:

```sh
node src/cli.js fugle-quote --ticker <TICKER> --format markdown
node src/cli.js tw-price --ticker <TICKER> --provider twse --format markdown
node src/cli.js tw-price --ticker <TICKER> --provider auto --format markdown
```

Notes:

- Use Shioaji first for price/volume/replay evidence; use `fugle-quote` as realtime fallback or supplementary same-day evidence.
- `tw-price --provider twse` may lag to the latest official snapshot and is not the primary realtime source.
- If a ticker is typed without a suffix but the Taiwan listing uses a suffix, normalize only when evidence supports it. Example: `00981` is usually the user's shorthand for `00981A`; state the normalization clearly.

## Required stock / ETF analysis flow

For every Taiwan ticker or ETF the user asks about, run the quote plus both studies before giving entry advice. Use `phase3_stability` as the main strategy lens: 技術候選先成立，再把新聞、法說、財報、股癌等外部資訊作信心加權；外部資訊不得把不合格技術訊號硬推成買進。

```sh
node src/cli.js fugle-quote --ticker <TICKER> --format markdown
node src/cli.js daily-decision-study --ticker <TICKER> --market tw --period 20 --start-date 2026-01-01 --decision-days 20 --lookback-bars 60 --format markdown
node src/cli.js signal-study --ticker <TICKER> --market tw --period 20 --start-date 2026-01-01 --volume-window 20 --institutional-days 5 --forward-days 1,2,3,5 --format markdown
```

When the question is workflow status or candidate generation rather than a single ticker, use the Phase 3 read-only commands:

```sh
node src/cli.js phase3-dataset --evidence-root .omx/evidence/phase3 --format markdown
node src/cli.js phase3-screen --evidence-root .omx/evidence/phase3 --format markdown
```

`phase3-screen` is a deterministic technical filter. It is read-only, does not train a model, and must never trigger real order APIs.

Add the ETF holding lens when the question involves ETF, 投信/主動式 ETF, or whether institutions/ETFs are adding a stock:

```sh
node src/cli.js xiaoyu-etf --mode stock --ticker <TICKER> --format markdown
node src/cli.js xiaoyu-etf --mode etf --etf <ETF_CODE> --format markdown
```

Treat `xiaoyu-etf` as auxiliary ETF-holding / inferred ETF-flow evidence only. It does not replace Shioaji price/volume and is not official 投信買賣超.

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
2. **Phase 3 技術結論** — `daily-decision-study` + `signal-study` interpreted through `phase3_stability`; separate direct tool output from inference.
3. **外部信心加權 / ETF / 籌碼輔助** — Xiaoyu ETF holder / active ETF flow lens when relevant; label as inferred auxiliary data.
4. **進場判斷** — can enter / wait / avoid chasing; include conditions.
5. **部位與風控** — suggest staged sizing, stop or invalidation condition, and what would change the view.
6. **限制** — market-data timing, insufficient rows, ETF-newness caveats, or auxiliary-source caveats.

Preferred wording:

- Use conditional language: 「可分批」、「等回測」、「不追高」、「小部位試單」。
- Avoid guarantee language: 「一定漲」、「保證」、「穩賺」。
- For high-volatility or new ETFs, cap recommendation to small exploratory size unless studies strongly support more.

## Quick examples

Single ticker:

```sh
node src/cli.js fugle-quote --ticker 2330 --format markdown
node src/cli.js daily-decision-study --ticker 2330 --market tw --period 20 --start-date 2026-01-01 --decision-days 20 --lookback-bars 60 --format markdown
node src/cli.js signal-study --ticker 2330 --market tw --period 20 --start-date 2026-01-01 --volume-window 20 --institutional-days 5 --forward-days 1,2,3,5 --format markdown
```

ETF pair such as 0050 and 00981A:

```sh
node src/cli.js fugle-quote --ticker 0050 --format markdown
node src/cli.js daily-decision-study --ticker 0050 --market tw --period 20 --start-date 2026-01-01 --decision-days 20 --lookback-bars 60 --format markdown
node src/cli.js signal-study --ticker 0050 --market tw --period 20 --start-date 2026-01-01 --volume-window 20 --institutional-days 5 --forward-days 1,2,3,5 --format markdown

node src/cli.js fugle-quote --ticker 00981A --format markdown
node src/cli.js daily-decision-study --ticker 00981A --market tw --period 20 --start-date 2026-01-01 --decision-days 20 --lookback-bars 60 --format markdown
node src/cli.js signal-study --ticker 00981A --market tw --period 20 --start-date 2026-01-01 --volume-window 20 --institutional-days 5 --forward-days 1,2,3,5 --format markdown
```
