# CLI 快速啟用與使用

這個 repo 的「啟用 CLI」不是啟動一個常駐服務，而是讓本機指令可以讀取 `.env` 裡的 API key，然後呼叫對應資料來源。

目前 `.env` 若已填好，CLI 會自動載入；不要把 `.env` commit 到 git。


## 台股 Dexter-style Agent Team

整合既有 Shioaji、盤前流程、MVP 回測、小宇 ETF lens 與 repo artifacts：

```bash
node src/cli.js taiwan-agent-team --query "盤前+回測+推測" --tickers 2330,00981A,00991A --capital 500000 --format markdown
```

離線只看既有 artifacts：

```bash
node src/cli.js taiwan-agent-team --query "整合既有資料" --offline --format markdown
```

輸出會寫入 `.omx/agent-team/scratchpad/` 與 `.omx/agent-team/reports/`，不會覆蓋既有台股 workflow。

## 最基本用法

```sh
npm run help
npm run trade -- help
```

`npm run trade --` 後面可以接任何原本的 CLI 指令：

```sh
npm run trade -- tw-company --ticker 2330 --format markdown
npm run trade -- price --ticker AAPL
npm run trade -- fugle-quote --ticker 2330 --format markdown
```

## 已加好的 npm scripts

### 台股 / 免費或 open data

```sh
npm run tw:endpoints
npm run tw:company -- --ticker 2330 --format markdown
npm run tw:price -- --ticker 2330 --provider twse --format markdown
npm run tw:revenue -- --ticker 2330 --start-date 2024-01-01 --format markdown
npm run tw:financials -- --ticker 2330 --statement income --provider finmind --start-date 2024-01-01 --format markdown
npm run tw:institutional -- --ticker 2330 --provider finmind --start-date 2024-01-01
npm run tw:valuation -- --ticker 2330 --provider auto --format markdown
npm run tw:announcements -- --ticker 2330 --limit 5 --format markdown
npm run tw:news -- --ticker 2330 --limit 5 --format markdown
```

### 台股研究 study

```sh
npm run trade -- chip-study --ticker 2330 --market tw --start-date 2026-01-01 --foreign-days 3 --holder-weeks 3 --min-holder-lots 1000 --format markdown
npm run trade -- sector-flow --mode close --date 2026-06-18 --rank-by foreignNetValue --format markdown
```

`chip-study` 會把外資連買、1000 張以上持股比例連增、量價/HMA 與事件後 3/5/10 日表現包成同一份研究輸出。若 FinMind 股權分級資料沒有權限，輸出會標示 unavailable。

`sector-flow` 有兩種模式：`--mode realtime` 需先啟動 `npm run shioaji:server`，用永豐即時 snapshot 做盤中類股熱度；`--mode close` 用 FinMind 收盤成交與法人買賣超做每日類股資金流 proxy。

### 美股 / Financial Datasets

需要 `.env` 裡有 `FINANCIAL_DATASETS_API_KEY`。

```sh
npm run us:endpoints
npm run us:price -- --ticker AAPL
npm run us:metrics -- --ticker AAPL
npm run us:statement -- --ticker AAPL --statement income --period annual --limit 5 --format markdown
npm run us:news -- --ticker AAPL --limit 5
npm run us:filings -- --ticker AAPL --filing-type 10-K --limit 3 --format markdown
```

### Fugle 台股即時/盤中資料

需要 `.env` 裡有 `FUGLE_API_KEY`。

```sh
npm run fugle:quote -- --ticker 2330 --format markdown
npm run fugle:ticker -- --ticker 2330
npm run fugle:candles -- --ticker 2330 --scope intraday --timeframe 1 --format markdown
npm run fugle:trades -- --ticker 2330 --limit 20
npm run fugle:volumes -- --ticker 2330
npm run fugle:snapshot -- --market TSE --kind quotes --type COMMONSTOCK --limit 20 --format markdown
npm run fugle:stats -- --ticker 2330
npm run fugle:technical -- --ticker 2330 --indicator sma --timeframe D --period 5
```

### 永豐 Shioaji 只讀即時行情

需要 `.env` 裡有 `SJ_API_KEY`、`SJ_SEC_KEY`，並先啟動本機 Shioaji server：

```sh
npm run shioaji:server
```

讀取行情：

```sh
npm run shioaji:quote -- --ticker 2330 --format markdown
npm run shioaji:orderbook -- --ticker 2330 --timeout-ms 3000 --format markdown
npm run shioaji:ticks -- --ticker 2330 --date 2026-06-18 --last 10 --format markdown
```

這三個工具只讀行情，不會下單：

- `shioaji-quote`：即時快照、成交量、委買/委賣、漲停/跌停狀態。
- `shioaji-orderbook`：訂閱一筆 BidAsk SSE，回傳五檔委買委賣。
- `shioaji-ticks`：查詢 tick-by-tick，預設最近 N 筆。

下單保護預設關閉 live order path。未來若新增任何下單工具，必須通過 `TRADE_ORDER_ENABLED=1` 與 `TRADE_ORDER_CONFIRM=I_UNDERSTAND_LIVE_ORDER_RISK` 雙開關。

## 一鍵檢查

```sh
npm run smoke:tw
npm test
```

## 可選：安裝成全域指令

```sh
npm link
trade-finance help
trade-finance tw-company --ticker 2330 --format markdown
```
