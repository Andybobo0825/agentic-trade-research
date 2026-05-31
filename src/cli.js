#!/usr/bin/env node
import { loadDotEnv } from './dotenv.js';
loadDotEnv();
import { parseArgs, requireArg, optionalInt } from './args.js';
import { ConfigError, UsageError } from './errors.js';
import { renderToolResult, runTool, tools } from './tools.js';

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

Options:
  --format json|markdown|compact-json
                                    Output format (default: json; MCP defaults to compact-json)

Cost model:
  LLM reasoning is done by Codex. Taiwan commands default to free/open data sources; Fugle adds realtime market data through your Fugle API key.
`;

const TAIWAN_COMMANDS = new Set(['tw-price', 'tw-company', 'tw-revenue', 'tw-financials', 'tw-institutional', 'tw-valuation', 'tw-announcements', 'tw-news', 'tw-raw']);
const FUGLE_COMMANDS = new Set(['fugle-quote', 'fugle-ticker', 'fugle-candles', 'fugle-trades', 'fugle-volumes', 'fugle-snapshot', 'fugle-stats', 'fugle-technical', 'fugle-raw']);

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
      statement: args.statement ? String(args.statement) : undefined,
      period: args.period ? String(args.period) : undefined,
      provider: args.provider ? String(args.provider) : undefined,
      startDate: args['start-date'] ? String(args['start-date']) : undefined,
      endDate: args['end-date'] ? String(args['end-date']) : undefined,
    };
  } else if (TAIWAN_COMMANDS.has(command)) {
    toolArgs = taiwanArgs(command, args, common.limit);
  } else if (FUGLE_COMMANDS.has(command)) {
    toolArgs = fugleArgs(command, args, common.limit);
  }

  const result = await runTool(command, toolArgs);
  return renderToolResult(command, result, format);
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
  if (command !== 'tw-raw' && command !== 'tw-endpoints') base.ticker = requireArg(args, 'ticker');
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
