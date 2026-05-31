# Fugle realtime market data

Fugle is wired as an optional realtime/intraday Taiwan market-data provider. It is separate from the free TWSE/TPEx/FinMind commands and requires a Fugle API key.

## Apply for a key

1. Register or log in at Fugle Developer: <https://developer.fugle.tw/>
2. Open the key-management page from the docs navigation: <https://developer.fugle.tw/docs/key/>
3. Create/copy your market-data API key.
4. Add it to `.env`:

```env
FUGLE_API_KEY=your-fugle-marketdata-api-key
FUGLE_MARKETDATA_BASE_URL=https://api.fugle.tw/marketdata/v1.0/stock
```

The Fugle REST API authenticates requests with this HTTP header:

```http
X-API-KEY: <YOUR_API_KEY>
```

## Commands

```sh
node src/cli.js fugle-quote --ticker 2330 --format markdown
node src/cli.js fugle-ticker --ticker 2330
node src/cli.js fugle-candles --ticker 2330 --scope intraday --timeframe 1 --format markdown
node src/cli.js fugle-candles --ticker 2330 --scope historical --timeframe D --from 2024-01-01 --to 2024-01-31 --format markdown
node src/cli.js fugle-trades --ticker 2330 --limit 20
node src/cli.js fugle-volumes --ticker 2330
node src/cli.js fugle-snapshot --market TSE --kind quotes --type COMMONSTOCK --limit 20 --format markdown
node src/cli.js fugle-stats --ticker 2330
node src/cli.js fugle-technical --ticker 2330 --indicator sma --timeframe D --period 5
node src/cli.js fugle-raw --endpoint /intraday/quote/2330
```

## Plan / pricing caveats

Fugle's docs say the base registered user tier can use Taiwan intraday API and limited WebSocket subscriptions. Snapshot, technical indicators, corporate events, and higher limits require Developer or Advanced plans. Treat this as data-provider cost, not LLM cost.

Use the free/open commands for non-realtime research, and use Fugle when the research question needs live bid/ask, latest trade, intraday candles/trades/volumes, or reliable realtime snapshots.
