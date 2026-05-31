# CLI 快速啟用與使用

這個 repo 的「啟用 CLI」不是啟動一個常駐服務，而是讓本機指令可以讀取 `.env` 裡的 API key，然後呼叫對應資料來源。

目前 `.env` 若已填好，CLI 會自動載入；不要把 `.env` commit 到 git。

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
