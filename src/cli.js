#!/usr/bin/env node
import { loadDotEnv } from './dotenv.js';
loadDotEnv();
import { parseArgs, requireArg, optionalInt } from './args.js';
import { ConfigError, UsageError } from './errors.js';
import { renderToolResult, runTool, tools } from './tools.js';
import { parseTaiwanAgentTeamCliArgs } from './taiwan-agent-team.js';

const HELP = `trade-finance: Codex-friendly finance data CLI

Usage:
  node src/cli.js <command> [options]

US / global commands:
  endpoints                         List Financial Datasets endpoint aliases
  statement --ticker AAPL [--statement income|balance|cash-flow|financials] [--period annual|quarterly] [--limit 5]
  metrics   --ticker AAPL
  price     --ticker AAPL
  news      [--ticker AAPL] [--limit 10]
  filings   --ticker AAPL [--filing-type 10-K|10-Q|8-K] [--limit 5]
  research-pack --ticker AAPL|2330 [--market us|tw] [--include price,metrics,news] [--format markdown|compact-json]
  sector-flow --mode realtime|close [--date YYYY-MM-DD] [--tickers 2330,2327] [--limit 1000] [--format markdown]
  preopen-brief [--date YYYY-MM-DD] [--watchlist 2330,2454] [--format markdown]
  hma-signal    --ticker 2330 [--market tw] [--source finmind|fugle] [--period 20] [--start-date YYYY-MM-DD] [--format markdown]
  signal-study  --ticker 2330 [--market tw] [--period 20] [--volume-window 20] [--institutional-days 5] [--forward-days 3,5,10] [--format markdown]
  daily-decision-study --ticker 2330 [--market tw] [--period 20] [--decision-days 20] [--lookback-bars 60] [--min-average-turnover 20000000] [--format markdown]
  chip-study    --ticker 2330 [--market tw] [--foreign-days 3] [--holder-weeks 3] [--min-holder-lots 1000] [--format markdown]
  market-diagnosis  --ticker TAIEX [--start-date 2026-01-01] [--format markdown]
  judgment-validate --judgment-file j.json --facts-file f.json [--report-file r.md]
  experience-log    --regime trading_range --date 2026-08-11 --ticker TAIEX [--note "..."]
  experience-recall --regime trading_range [--limit 5]
  xiaoyu-etf    [--mode stock|etf|rank|overview] [--ticker 2330] [--etf 00981A] [--scope active|market] [--window d1|d5|d10|d20|d60] [--direction buy|sell] [--limit 10] [--format markdown]
  taiwan-agent-team [--query "盤前+回測+推測"] [--tickers 2330,00981A] [--date YYYY-MM-DD] [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--capital 500000] [--offline] [--format markdown]
  memory-sync   [--memory-dir .omx/memory] [--entry-file entries.json] [--entry "text" --date YYYY-MM-DD --category decision|verified-fix|failure-case|milestone] [--now YYYY-MM-DD] [--format markdown]

Taiwan free-data commands:
  tw-endpoints
  tw-price         --ticker 2330 [--provider auto|finmind|twse|tpex] [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
  tw-company       --ticker 2330 [--provider auto|finmind|twse|tpex]
  tw-revenue       --ticker 2330 [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
  tw-financials    --ticker 2330 [--statement income|balance|cashflow] [--provider finmind|twse|tpex]
  tw-institutional --ticker 2330 [--provider finmind|tpex] [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
  tw-valuation     --ticker 2330 [--provider auto|finmind|twse|tpex]
  tw-announcements --ticker 2330 [--provider auto|twse|tpex] [--limit 10]
  tw-news          --ticker 2330 [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--limit 10]
  tw-raw           --provider finmind --dataset TaiwanStockPrice --ticker 2330 [--start-date YYYY-MM-DD]
  tw-raw           --provider twse|tpex --endpoint /path [--ticker 2330]
  ic-tpex-category --ic D000|5300 [--format markdown]
  ic-tpex-chain    --ticker 2330 [--format markdown]

Fugle realtime commands (requires FUGLE_API_KEY):
  fugle-quote      --ticker 2330 [--type oddlot]
  fugle-ticker     --ticker 2330
  fugle-candles    --ticker 2330 [--scope intraday|historical] [--timeframe 1|D] [--from YYYY-MM-DD] [--to YYYY-MM-DD]
  fugle-trades     --ticker 2330 [--limit 20]
  fugle-volumes    --ticker 2330
  fugle-snapshot   --market TSE [--kind quotes|movers|actives] [--type COMMONSTOCK] [--limit 20]
  fugle-stats      --ticker 2330
  fugle-technical  --ticker 2330 --indicator sma|rsi|kdj|macd|bb [--timeframe D] [--period 5]
  fugle-raw        --endpoint /intraday/quote/2330

Shioaji / Sinotrade read-only commands (requires local shioaji server):
  shioaji-quote     --ticker 2330 [--exchange TSE|OTC]
  shioaji-contract  --ticker 2330 [--security-type STK]
  shioaji-contracts --security-type STK [--page 1] [--page-size 1000]
  shioaji-snapshots --tickers 2330,2317 [--exchange TSE|OTC] [--chunk-size 500]
  shioaji-kbars     --ticker 2330 --start YYYY-MM-DD --end YYYY-MM-DD [--exchange TSE|OTC]
  shioaji-daily-quotes --date YYYY-MM-DD
  shioaji-cache-kbars --tickers 2330,2317 --start YYYY-MM-DD --end YYYY-MM-DD [--cache-dir .omx/cache/shioaji] [--refresh]
  shioaji-cache-daily-quotes --start YYYY-MM-DD --end YYYY-MM-DD [--cache-dir .omx/cache/shioaji] [--refresh]
  shioaji-orderbook --ticker 2330 [--exchange TSE|OTC] [--timeout-ms 3000]
  shioaji-ticks     --ticker 2330 [--exchange TSE|OTC] [--date YYYY-MM-DD] [--last 10|--all]

Options:
  --format json|markdown|compact-json
                                    Output format (default: json; MCP defaults to compact-json)

Cost model:
  LLM reasoning is done by Codex. Taiwan commands default to free/open data sources; Fugle adds realtime market data through your Fugle API key. Shioaji commands are read-only and use your local Shioaji server.
`;

const TAIWAN_COMMANDS = new Set(['tw-price', 'tw-company', 'tw-revenue', 'tw-financials', 'tw-institutional', 'tw-valuation', 'tw-announcements', 'tw-news', 'tw-raw', 'ic-tpex-category', 'ic-tpex-chain']);
const FUGLE_COMMANDS = new Set(['fugle-quote', 'fugle-ticker', 'fugle-candles', 'fugle-trades', 'fugle-volumes', 'fugle-snapshot', 'fugle-stats', 'fugle-technical', 'fugle-raw']);
const SHIOAJI_COMMANDS = new Set(['shioaji-quote', 'shioaji-contract', 'shioaji-contracts', 'shioaji-snapshots', 'shioaji-kbars', 'shioaji-daily-quotes', 'shioaji-cache-kbars', 'shioaji-cache-daily-quotes', 'shioaji-orderbook', 'shioaji-ticks']);

export async function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  const command = args._[0];
  if (!command || command === 'help' || args.help) return HELP;
  if (!tools[command]) throw new UsageError(`Unknown command '${command}'. Run: node src/cli.js help`);

  const format = ['markdown', 'compact-json', 'compact'].includes(args.format) ? args.format : 'json';
  const common = { limit: optionalInt(args, 'limit', undefined) };
  let toolArgs = {};

  if (command === 'statement') {
    toolArgs = {
      ticker: requireArg(args, 'ticker').toUpperCase(),
      statement: args.statement ? String(args.statement) : 'income',
      period: args.period ? String(args.period) : 'annual',
      limit: common.limit || 5,
    };
  } else if (command === 'metrics' || command === 'price') {
    toolArgs = { ticker: requireArg(args, 'ticker').toUpperCase() };
  } else if (command === 'news') {
    toolArgs = { ticker: args.ticker ? String(args.ticker).toUpperCase() : undefined, limit: common.limit || 10 };
  } else if (command === 'filings') {
    toolArgs = {
      ticker: requireArg(args, 'ticker').toUpperCase(),
      filingType: args['filing-type'] ? String(args['filing-type']) : undefined,
      limit: common.limit || 5,
    };
  } else if (command === 'research-pack') {
    toolArgs = {
      ticker: requireArg(args, 'ticker').toUpperCase(),
      market: args.market ? String(args.market) : undefined,
      include: args.include ? String(args.include) : undefined,
      limit: common.limit,
      newsLimit: optionalInt(args, 'news-limit', undefined),
      filingLimit: optionalInt(args, 'filing-limit', undefined),
      statementLimit: optionalInt(args, 'statement-limit', undefined),
      announcementLimit: optionalInt(args, 'announcement-limit', undefined),
      hmaLimit: optionalInt(args, 'hma-limit', undefined),
      hmaPeriod: optionalInt(args, 'hma-period', undefined),
      hmaSource: args['hma-source'] ? String(args['hma-source']) : undefined,
      volumeWindow: optionalInt(args, 'volume-window', undefined),
      volumeMultiplier: args['volume-multiplier'] ? Number(args['volume-multiplier']) : undefined,
      institutionalDays: optionalInt(args, 'institutional-days', undefined),
      institutionalProvider: args['institutional-provider'] ? String(args['institutional-provider']) : undefined,
      institutionalLimit: optionalInt(args, 'institutional-limit', undefined),
      holdingLimit: optionalInt(args, 'holding-limit', undefined),
      foreignDays: optionalInt(args, 'foreign-days', undefined),
      holderWeeks: optionalInt(args, 'holder-weeks', undefined),
      minHolderLots: optionalInt(args, 'min-holder-lots', undefined),
      liquidityWindow: optionalInt(args, 'liquidity-window', undefined),
      minAverageVolume: args['min-average-volume'] ? Number(args['min-average-volume']) : undefined,
      minAverageTurnover: args['min-average-turnover'] ? Number(args['min-average-turnover']) : undefined,
      maxPositionPctOfAvgVolume: args['max-position-pct-of-avg-volume'] ? Number(args['max-position-pct-of-avg-volume']) : undefined,
      decisionDays: optionalInt(args, 'decision-days', undefined),
      lookbackBars: optionalInt(args, 'lookback-bars', undefined),
      forwardDays: args['forward-days'] ? String(args['forward-days']) : undefined,
      falseBreakoutDays: optionalInt(args, 'false-breakout-days', undefined),
      falseBreakoutThreshold: args['false-breakout-threshold'] ? Number(args['false-breakout-threshold']) : undefined,
      statement: args.statement ? String(args.statement) : undefined,
      period: args.period ? String(args.period) : undefined,
      provider: args.provider ? String(args.provider) : undefined,
      startDate: args['start-date'] ? String(args['start-date']) : undefined,
      endDate: args['end-date'] ? String(args['end-date']) : undefined,
    };
  } else if (command === 'sector-flow') {
    toolArgs = {
      mode: args.mode ? String(args.mode) : 'realtime',
      date: args.date ? String(args.date) : undefined,
      tickers: args.tickers ? String(args.tickers) : undefined,
      exchange: args.exchange ? String(args.exchange) : undefined,
      securityType: args['security-type'] ? String(args['security-type']) : undefined,
      provider: args.provider ? String(args.provider) : undefined,
      companyProvider: args['company-provider'] ? String(args['company-provider']) : undefined,
      institutionalProvider: args['institutional-provider'] ? String(args['institutional-provider']) : undefined,
      rankBy: args['rank-by'] ? String(args['rank-by']) : undefined,
      chunkSize: optionalInt(args, 'chunk-size', undefined),
      limit: common.limit,
    };
  } else if (command === 'preopen-brief') {
    toolArgs = {
      date: args.date ? String(args.date) : undefined,
      updateTime: args['update-time'] ? String(args['update-time']) : undefined,
      month: optionalInt(args, 'month', undefined),
      watchlist: args.watchlist ? String(args.watchlist) : undefined,
      fxPreviousClose: args['fx-prev-close'] ? Number(args['fx-prev-close']) : undefined,
      fxCurrent: args['fx-current'] ? Number(args['fx-current']) : undefined,
      futureClose: args['future-close'] ? Number(args['future-close']) : undefined,
      futureChange: args['future-change'] ? Number(args['future-change']) : undefined,
      futureVolume: args['future-volume'] ? Number(args['future-volume']) : undefined,
      previousSpotClose: args['previous-spot-close'] ? Number(args['previous-spot-close']) : undefined,
      usMoves: args['us-moves'] ? String(args['us-moves']) : undefined,
      branchData: args['branch-data'] ? String(args['branch-data']) : undefined,
      branchFile: args['branch-file'] ? String(args['branch-file']) : undefined,
      auctionData: args['auction-data'] ? String(args['auction-data']) : undefined,
      auctionFile: args['auction-file'] ? String(args['auction-file']) : undefined,
      auctionThresholdPct: args['auction-threshold-pct'] ? Number(args['auction-threshold-pct']) : undefined,
      noFetch: args['no-fetch'] === true || args['no-fetch'] === 'true',
      spotFrom: args['spot-from'] ? String(args['spot-from']) : undefined,
    };
  } else if (command === 'hma-signal') {
    toolArgs = {
      ticker: requireArg(args, 'ticker').toUpperCase(),
      market: args.market ? String(args.market) : undefined,
      source: args.source ? String(args.source) : undefined,
      provider: args.provider ? String(args.provider) : undefined,
      period: optionalInt(args, 'period', 20),
      limit: common.limit,
      startDate: args['start-date'] ? String(args['start-date']) : undefined,
      endDate: args['end-date'] ? String(args['end-date']) : undefined,
      scope: args.scope ? String(args.scope) : undefined,
      timeframe: args.timeframe ? String(args.timeframe) : undefined,
      from: args.from ? String(args.from) : undefined,
      to: args.to ? String(args.to) : undefined,
      adjusted: args.adjusted ? String(args.adjusted) : undefined,
    };
  } else if (command === 'signal-study') {
    toolArgs = {
      ticker: requireArg(args, 'ticker').toUpperCase(),
      market: args.market ? String(args.market) : undefined,
      provider: args.provider ? String(args.provider) : undefined,
      period: optionalInt(args, 'period', 20),
      limit: common.limit,
      startDate: args['start-date'] ? String(args['start-date']) : undefined,
      endDate: args['end-date'] ? String(args['end-date']) : undefined,
      volumeWindow: optionalInt(args, 'volume-window', undefined),
      volumeMultiplier: args['volume-multiplier'] ? Number(args['volume-multiplier']) : undefined,
      institutionalDays: optionalInt(args, 'institutional-days', undefined),
      institutionalProvider: args['institutional-provider'] ? String(args['institutional-provider']) : undefined,
      institutionalLimit: optionalInt(args, 'institutional-limit', undefined),
      liquidityWindow: optionalInt(args, 'liquidity-window', undefined),
      minAverageVolume: args['min-average-volume'] ? Number(args['min-average-volume']) : undefined,
      minAverageTurnover: args['min-average-turnover'] ? Number(args['min-average-turnover']) : undefined,
      maxPositionPctOfAvgVolume: args['max-position-pct-of-avg-volume'] ? Number(args['max-position-pct-of-avg-volume']) : undefined,
      forwardDays: args['forward-days'] ? String(args['forward-days']) : undefined,
      falseBreakoutDays: optionalInt(args, 'false-breakout-days', undefined),
      falseBreakoutThreshold: args['false-breakout-threshold'] ? Number(args['false-breakout-threshold']) : undefined,
    };
  } else if (command === 'daily-decision-study') {
    toolArgs = {
      ticker: requireArg(args, 'ticker').toUpperCase(),
      market: args.market ? String(args.market) : undefined,
      provider: args.provider ? String(args.provider) : undefined,
      period: optionalInt(args, 'period', 20),
      limit: common.limit,
      startDate: args['start-date'] ? String(args['start-date']) : undefined,
      endDate: args['end-date'] ? String(args['end-date']) : undefined,
      decisionDays: optionalInt(args, 'decision-days', undefined),
      lookbackBars: optionalInt(args, 'lookback-bars', undefined),
      volumeWindow: optionalInt(args, 'volume-window', undefined),
      volumeMultiplier: args['volume-multiplier'] ? Number(args['volume-multiplier']) : undefined,
      liquidityWindow: optionalInt(args, 'liquidity-window', undefined),
      minAverageVolume: args['min-average-volume'] ? Number(args['min-average-volume']) : undefined,
      minAverageTurnover: args['min-average-turnover'] ? Number(args['min-average-turnover']) : undefined,
      maxPositionPctOfAvgVolume: args['max-position-pct-of-avg-volume'] ? Number(args['max-position-pct-of-avg-volume']) : undefined,
      forwardDays: args['forward-days'] ? String(args['forward-days']) : undefined,
    };
  } else if (command === 'chip-study') {
    toolArgs = {
      ticker: requireArg(args, 'ticker').toUpperCase(),
      market: args.market ? String(args.market) : undefined,
      provider: args.provider ? String(args.provider) : undefined,
      period: optionalInt(args, 'period', 20),
      limit: common.limit,
      startDate: args['start-date'] ? String(args['start-date']) : undefined,
      endDate: args['end-date'] ? String(args['end-date']) : undefined,
      foreignDays: optionalInt(args, 'foreign-days', undefined),
      holderWeeks: optionalInt(args, 'holder-weeks', undefined),
      minHolderLots: optionalInt(args, 'min-holder-lots', undefined),
      holdingLimit: optionalInt(args, 'holding-limit', undefined),
      volumeWindow: optionalInt(args, 'volume-window', undefined),
      volumeMultiplier: args['volume-multiplier'] ? Number(args['volume-multiplier']) : undefined,
      institutionalProvider: args['institutional-provider'] ? String(args['institutional-provider']) : undefined,
      institutionalLimit: optionalInt(args, 'institutional-limit', undefined),
      liquidityWindow: optionalInt(args, 'liquidity-window', undefined),
      minAverageVolume: args['min-average-volume'] ? Number(args['min-average-volume']) : undefined,
      minAverageTurnover: args['min-average-turnover'] ? Number(args['min-average-turnover']) : undefined,
      maxPositionPctOfAvgVolume: args['max-position-pct-of-avg-volume'] ? Number(args['max-position-pct-of-avg-volume']) : undefined,
      forwardDays: args['forward-days'] ? String(args['forward-days']) : undefined,
    };
  } else if (command === 'xiaoyu-etf') {
    toolArgs = {
      mode: args.mode ? String(args.mode) : undefined,
      ticker: args.ticker ? String(args.ticker).toUpperCase() : undefined,
      etf: args.etf ? String(args.etf).toUpperCase() : undefined,
      scope: args.scope ? String(args.scope) : undefined,
      window: args.window ? String(args.window) : undefined,
      direction: args.direction ? String(args.direction) : undefined,
      limit: common.limit,
      includeDetail: args['include-detail'] === true || args['include-detail'] === 'true',
      baseUrl: args['base-url'] ? String(args['base-url']) : undefined,
    };
  } else if (command === 'market-diagnosis') {
    toolArgs = {
      ticker: args.ticker ? String(args.ticker).toUpperCase() : undefined,
      provider: args.provider ? String(args.provider) : undefined,
      startDate: args['start-date'] ? String(args['start-date']) : undefined,
      endDate: args['end-date'] ? String(args['end-date']) : undefined,
    };
  } else if (command === 'judgment-validate') {
    toolArgs = {
      judgmentFile: args['judgment-file'] ? String(args['judgment-file']) : undefined,
      factsFile: args['facts-file'] ? String(args['facts-file']) : undefined,
      reportFile: args['report-file'] ? String(args['report-file']) : undefined,
      tickers: args.tickers ? String(args.tickers) : undefined,
    };
  } else if (command === 'experience-log') {
    toolArgs = {
      entryJson: args.entry ? String(args.entry) : undefined,
      regime: args.regime ? String(args.regime) : undefined,
      date: args.date ? String(args.date) : undefined,
      ticker: args.ticker ? String(args.ticker).toUpperCase() : undefined,
      note: args.note ? String(args.note) : undefined,
    };
  } else if (command === 'experience-recall') {
    toolArgs = {
      regime: args.regime ? String(args.regime) : undefined,
      limit: common.limit,
    };
  } else if (command === 'taiwan-agent-team') {
    toolArgs = parseTaiwanAgentTeamCliArgs(args, optionalInt);
  } else if (command === 'memory-sync') {
    toolArgs = {
      memoryDir: args['memory-dir'] ? String(args['memory-dir']) : undefined,
      entryFile: args['entry-file'] ? String(args['entry-file']) : undefined,
      entry: args.entry ? String(args.entry) : undefined,
      date: args.date ? String(args.date) : undefined,
      category: args.category ? String(args.category) : undefined,
      source: args.source ? String(args.source) : undefined,
      reason: args.reason ? String(args.reason) : undefined,
      obsolete: args.obsolete === true || args.obsolete === 'true',
      now: args.now ? String(args.now) : undefined,
      maxHotEntries: optionalInt(args, 'max-hot-entries', undefined),
    };
  } else if (TAIWAN_COMMANDS.has(command)) {
    toolArgs = taiwanArgs(command, args, common.limit);
  } else if (FUGLE_COMMANDS.has(command)) {
    toolArgs = fugleArgs(command, args, common.limit);
  } else if (SHIOAJI_COMMANDS.has(command)) {
    toolArgs = shioajiArgs(command, args, common.limit);
  }

  const result = await runTool(command, toolArgs);
  return renderToolResult(command, result, format);
}

function shioajiArgs(command, args, limit) {
  const base = {
    ticker: args.ticker ? String(args.ticker).trim() : undefined,
    exchange: args.exchange ? String(args.exchange) : 'TSE',
    securityType: args['security-type'] ? String(args['security-type']) : 'STK',
    limit,
  };
  if (!['shioaji-contracts', 'shioaji-snapshots', 'shioaji-daily-quotes', 'shioaji-cache-kbars', 'shioaji-cache-daily-quotes'].includes(command)) base.ticker = requireArg(args, 'ticker');
  if (command === 'shioaji-contracts') {
    base.page = optionalInt(args, 'page', undefined);
    base.pageSize = optionalInt(args, 'page-size', undefined);
  }
  if (command === 'shioaji-snapshots') {
    base.tickers = requireArg(args, 'tickers');
    base.chunkSize = optionalInt(args, 'chunk-size', undefined);
  }
  if (command === 'shioaji-kbars') {
    base.start = requireArg(args, 'start');
    base.end = requireArg(args, 'end');
  }
  if (command === 'shioaji-daily-quotes') {
    base.date = requireArg(args, 'date');
  }
  if (command === 'shioaji-cache-kbars') {
    base.tickers = requireArg(args, 'tickers');
    base.start = requireArg(args, 'start');
    base.end = requireArg(args, 'end');
    base.cacheDir = args['cache-dir'] ? String(args['cache-dir']) : undefined;
    base.refresh = args.refresh === true || args.refresh === 'true';
  }
  if (command === 'shioaji-cache-daily-quotes') {
    base.start = requireArg(args, 'start');
    base.end = requireArg(args, 'end');
    base.cacheDir = args['cache-dir'] ? String(args['cache-dir']) : undefined;
    base.refresh = args.refresh === true || args.refresh === 'true';
  }
  if (command === 'shioaji-orderbook') {
    base.timeoutMs = optionalInt(args, 'timeout-ms', undefined);
    base.intradayOdd = args['intraday-odd'] === true || args['intraday-odd'] === 'true';
  }
  if (command === 'shioaji-ticks') {
    base.date = args.date ? String(args.date) : undefined;
    base.last = optionalInt(args, 'last', undefined);
    base.all = args.all === true || args.all === 'true';
    base.timeStart = args['time-start'] ? String(args['time-start']) : undefined;
    base.timeEnd = args['time-end'] ? String(args['time-end']) : undefined;
  }
  return base;
}

function fugleArgs(command, args, limit) {
  const base = {
    ticker: args.ticker ? String(args.ticker).trim() : undefined,
    type: args.type ? String(args.type) : undefined,
    timeframe: args.timeframe ? String(args.timeframe) : undefined,
    sort: args.sort ? String(args.sort) : undefined,
    from: args.from ? String(args.from) : undefined,
    to: args.to ? String(args.to) : undefined,
    adjusted: args.adjusted ? String(args.adjusted) : undefined,
    fields: args.fields ? String(args.fields) : undefined,
    limit,
  };
  if (!['fugle-snapshot', 'fugle-raw'].includes(command)) base.ticker = requireArg(args, 'ticker');
  if (command === 'fugle-candles') base.scope = args.scope ? String(args.scope) : 'intraday';
  if (command === 'fugle-snapshot') {
    base.market = args.market ? String(args.market) : 'TSE';
    base.kind = args.kind ? String(args.kind) : 'quotes';
  }
  if (command === 'fugle-technical') {
    base.indicator = args.indicator ? String(args.indicator) : 'sma';
    base.period = args.period ? String(args.period) : undefined;
    base.fastPeriod = args['fast-period'] ? String(args['fast-period']) : undefined;
    base.slowPeriod = args['slow-period'] ? String(args['slow-period']) : undefined;
    base.signalPeriod = args['signal-period'] ? String(args['signal-period']) : undefined;
  }
  if (command === 'fugle-raw') {
    base.endpoint = requireArg(args, 'endpoint');
    base.market = args.market ? String(args.market) : undefined;
  }
  return base;
}

function taiwanArgs(command, args, limit) {
  const base = {
    ticker: args.ticker ? String(args.ticker).trim() : undefined,
    provider: args.provider ? String(args.provider) : undefined,
    startDate: args['start-date'] ? String(args['start-date']) : undefined,
    endDate: args['end-date'] ? String(args['end-date']) : undefined,
    limit,
  };
  if (command === 'ic-tpex-category') {
    base.ic = args.ic ? String(args.ic) : undefined;
    delete base.ticker;
  } else if (command === 'ic-tpex-chain') {
    base.ticker = requireArg(args, 'ticker');
  } else if (command !== 'tw-raw' && command !== 'tw-endpoints') base.ticker = requireArg(args, 'ticker');
  if (command === 'tw-financials') base.statement = args.statement ? String(args.statement) : 'income';
  if (command === 'tw-raw') {
    base.provider = requireArg(args, 'provider');
    base.dataset = args.dataset ? String(args.dataset) : undefined;
    base.endpoint = args.endpoint ? String(args.endpoint) : undefined;
  }
  return base;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().then((text) => process.stdout.write(text)).catch((err) => {
    if (err instanceof ConfigError || err instanceof UsageError) {
      console.error(`${err.name}: ${err.message}`);
      process.exit(2);
    }
    console.error(err?.stack || String(err));
    process.exit(1);
  });
}
