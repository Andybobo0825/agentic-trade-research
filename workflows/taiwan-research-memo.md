# Codex Taiwan Stock Research Memo Workflow

Use Codex reasoning plus the local free-data CLI. Do not call a second LLM API.

## Data fetch

```sh
node src/cli.js tw-company --ticker <TICKER>
# Optional realtime layer if FUGLE_API_KEY is configured
node src/cli.js fugle-quote --ticker <TICKER> --format markdown
node src/cli.js fugle-candles --ticker <TICKER> --scope intraday --timeframe 1 --format markdown
node src/cli.js tw-price --ticker <TICKER> --provider finmind --start-date <YYYY-MM-DD> --format markdown
node src/cli.js hma-signal --ticker <TICKER> --market tw --source finmind --period 20 --start-date <YYYY-MM-DD> --format markdown
node src/cli.js signal-study --ticker <TICKER> --market tw --period 20 --start-date <YYYY-MM-DD> --volume-window 20 --institutional-days 5 --forward-days 3,5,10 --format markdown
node src/cli.js tw-revenue --ticker <TICKER> --start-date <YYYY-MM-DD> --format markdown
node src/cli.js tw-financials --ticker <TICKER> --statement income --provider finmind --start-date <YYYY-MM-DD> --format markdown
node src/cli.js tw-financials --ticker <TICKER> --statement balance --provider finmind --start-date <YYYY-MM-DD> --format markdown
node src/cli.js tw-institutional --ticker <TICKER> --start-date <YYYY-MM-DD>
node src/cli.js tw-valuation --ticker <TICKER> --provider auto --format markdown
node src/cli.js tw-announcements --ticker <TICKER> --limit 10
```

## Codex synthesis instructions

1. Identify listing venue and business profile.
2. Build realtime quote/intraday trend if Fugle data is available, then price trend, HMA trend signal, monthly revenue trend, margin/profitability trend, balance-sheet risk, valuation, and institutional-flow sections.
3. Separate official-source evidence from FinMind-derived historical data.
4. Flag data gaps and provider limitations; do not invent missing fields.
5. Write in Traditional Chinese unless the user requests another language.

## Taiwan-specific stability / potential checks

- When judging whether a Taiwan stock is relatively stable or has potential, verify whether the company is currently included in 00981A（主動式 ETF）using the latest available ETF holdings / issuer disclosure before citing it. Treat inclusion as one supporting data point for institutional recognition or portfolio-fit, not as proof of safety or upside by itself; if holdings data is unavailable or outdated, explicitly mark it as a data gap.
- When discussing current price volatility, pull recent institutional-flow data (`tw-institutional`, and Fugle/other realtime data if configured) to check whether foreign investors, investment trusts, dealers, or other major players are net buying or selling. Use this to explain whether the move is supported by main-force accumulation, rotation into specific names/themes, or short-term speculative flow.

## Output shape

- 一句話結論
- 公司與產業定位
- 價格與估值
- HMA 趨勢、成交量/法人確認與訊號研究
- 00981A / 主動 ETF 納入狀態與意義
- 月營收與財報趨勢
- 籌碼 / 三大法人
- 重大訊息與風險
- 需要補資料的地方
- 觀察清單
