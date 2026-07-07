import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync, appendFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { compactNumber, toMarkdownTable } from './format.js';

const DEFAULT_TICKERS = ['00981A', '00991A', '2330', '4915'];
const DEFAULT_INDICES = ['001', '027', '036', '040', '038'];
const ARTIFACT_ROOTS = [
  '.omx/cache',
  '.omx/backtests',
  '.omx/research',
  '.omx/ultragoal',
  '.omx/line-bridge/responses',
  'docs',
  'workflows',
];

export const TAIWAN_AGENT_TEAM_INPUT_SCHEMA = {
  query: { type: 'string', description: 'Research question or strategy request.' },
  prompt: { type: 'string', description: 'Alias for query.' },
  tickers: { oneOf: [{ type: 'string' }, { type: 'array', items: { type: 'string' } }], description: 'Comma-separated Taiwan tickers or ETF symbols.' },
  ticker: { type: 'string' },
  watchlist: { oneOf: [{ type: 'string' }, { type: 'array', items: { type: 'string' } }] },
  date: { type: 'string' },
  startDate: { type: 'string' },
  endDate: { type: 'string' },
  capital: { type: 'number' },
  mode: { type: 'string', enum: ['brief', 'full'] },
  offline: { type: 'boolean', description: 'Use only repo artifacts and skip live tool calls.' },
  maxTickers: { type: 'number' },
};

export function parseTaiwanAgentTeamCliArgs(args = {}, optionalIntFn = defaultOptionalInt) {
  return {
    query: args.query ? String(args.query) : undefined,
    prompt: args.prompt ? String(args.prompt) : undefined,
    tickers: args.tickers ? String(args.tickers) : undefined,
    ticker: args.ticker ? String(args.ticker) : undefined,
    watchlist: args.watchlist ? String(args.watchlist) : undefined,
    date: args.date ? String(args.date) : undefined,
    startDate: args['start-date'] ? String(args['start-date']) : undefined,
    endDate: args['end-date'] ? String(args['end-date']) : undefined,
    capital: args.capital ? Number(args.capital) : undefined,
    mode: args.mode ? String(args.mode) : undefined,
    offline: args.offline === true || args.offline === 'true',
    maxTickers: optionalIntFn(args, 'max-tickers', undefined),
  };
}

export class TaiwanAgentScratchpad {
  constructor(query, { rootDir = process.cwd(), scratchpadDir } = {}) {
    this.rootDir = rootDir;
    this.dir = scratchpadDir || join(rootDir, '.omx', 'agent-team', 'scratchpad');
    mkdirSync(this.dir, { recursive: true });
    const stamp = new Date().toISOString().slice(0, 19).replace('T', '-').replace(/:/g, '');
    const hash = createHash('md5').update(String(query || '')).digest('hex').slice(0, 12);
    this.filepath = join(this.dir, `${stamp}_${hash}.jsonl`);
    this.append({ type: 'init', content: query || 'taiwan-agent-team', timestamp: new Date().toISOString() });
  }

  append(entry) {
    appendFileSync(this.filepath, `${JSON.stringify(redactSecrets(entry))}\n`);
  }

  thinking(content) {
    this.append({ type: 'thinking', timestamp: new Date().toISOString(), content });
  }

  toolResult(toolName, args, result, status = 'ok') {
    this.append({ type: 'tool_result', timestamp: new Date().toISOString(), toolName, args, status, result: safeJson(result) });
  }
}

export async function buildTaiwanAgentTeam(args = {}, deps = {}) {
  const rootDir = deps.rootDir || process.cwd();
  const query = args.query || args.prompt || '台股深度投資研究';
  const tickers = normalizeTickers(args.tickers || args.ticker || args.watchlist || DEFAULT_TICKERS).slice(0, Number(args.maxTickers || 8));
  const date = args.date || todayTaipei();
  const startDate = args.startDate || args.start || '2026-04-01';
  const endDate = args.endDate || args.end || date;
  const capital = Number(args.capital || 500000);
  const offline = args.offline === true || args.offline === 'true';
  const mode = args.mode || 'full';
  const runTool = deps.runTool;
  const scratchpad = new TaiwanAgentScratchpad(query, { rootDir, scratchpadDir: deps.scratchpadDir });

  const plan = buildResearchPlan({ query, tickers, date, startDate, endDate, capital, offline });
  scratchpad.thinking(`Plan created with ${plan.steps.length} steps; offline=${offline}; tickers=${tickers.join(',') || 'none'}.`);

  const inventory = collectDataInventory(rootDir);
  scratchpad.toolResult('repo_data_inventory', { roots: ARTIFACT_ROOTS }, inventory);

  const backtests = collectBacktestEvidence(rootDir);
  scratchpad.toolResult('backtest_evidence', { roots: ['.omx/backtests', '.omx/research', '.omx/ultragoal'] }, backtests);

  const toolResults = {};
  const errors = {};
  if (!offline && runTool) {
    const toolCalls = buildToolCalls({ tickers, date, startDate, endDate, capital, mode });
    for (const call of toolCalls) {
      try {
        const result = await runTool(call.name, call.args);
        const safeResult = safeJson(result);
        toolResults[call.key] = safeResult;
        scratchpad.toolResult(call.name, call.args, safeResult);
      } catch (error) {
        const message = redactSecrets(error?.message || String(error));
        errors[call.key] = message;
        scratchpad.toolResult(call.name, call.args, { error: message }, 'error');
      }
    }
  } else {
    scratchpad.thinking('Offline/no-runner mode: skipped live tool calls and used repo artifacts only.');
  }

  const synthesis = synthesizeAgentTeam({ query, tickers, date, startDate, endDate, capital, inventory, backtests, toolResults, errors, offline });
  scratchpad.thinking(`Synthesis complete: market=${synthesis.marketRegime.label}; confidence=${synthesis.confidence}.`);

  const result = {
    agent: {
      name: 'taiwan-agent-team',
      inspiredBy: 'virattt/dexter autonomous financial research loop',
      architecture: [
        'planner: decomposes user query into data tasks',
        'data-agent: integrates Shioaji/TWSE/FinMind/Xiaoyu/repo artifacts',
        'backtest-agent: reads reproducible MVP/backtest artifacts',
        'market-agent: evaluates index/sector/volume/liquidity context',
        'scenario-agent: creates bull/base/bear branches from evidence',
        'verifier: records gaps, confidence, and scratchpad audit trail',
      ],
      safety: [
        'No existing Taiwan workflow is deleted or replaced.',
        'Shioaji remains primary for Taiwan price/volume when live calls are enabled.',
        'Predictions are scenario analysis, not guaranteed outcomes.',
      ],
    },
    request: { query, tickers, date, startDate, endDate, capital, mode, offline },
    scratchpad: { path: relative(rootDir, scratchpad.filepath), format: 'jsonl' },
    plan,
    inventory,
    backtests,
    toolResults,
    errors,
    synthesis,
    disclaimer: 'Research automation output only; not guaranteed profit or personalized financial advice.',
  };

  const safeResult = redactSecrets(result);
  persistReport(rootDir, safeResult);
  return safeResult;
}

export function renderTaiwanAgentTeamMarkdown(result) {
  const s = result.synthesis || {};
  const lines = [
    '# Taiwan Agent Team Research Report',
    '',
    `Query: ${result.request?.query || '—'}`,
    `Date range: ${result.request?.startDate || '—'} ~ ${result.request?.endDate || '—'}`,
    `Capital base: ${compactNumber(result.request?.capital)}`,
    `Scratchpad: ${result.scratchpad?.path || '—'}`,
    `Report artifact: ${result.reportPath || '—'}`,
    '',
    '## Dexter-style architecture mapped to Taiwan workflow',
    ...(result.agent?.architecture || []).map((item) => `- ${item}`),
    '',
    '## Research plan',
    toMarkdownTable((result.plan?.steps || []).map((step) => ({ step: step.id, owner: step.owner, goal: step.goal })), [
      { label: 'Step', value: (r) => r.step },
      { label: 'Owner', value: (r) => r.owner },
      { label: 'Goal', value: (r) => r.goal },
    ]),
    '',
    '## Data inventory',
    toMarkdownTable(result.inventory?.roots || [], [
      { label: 'Root', value: (r) => r.root },
      { label: 'Files', value: (r) => r.files },
      { label: 'Latest', value: (r) => r.latest || '—' },
    ]),
    '',
    '## Backtest / research evidence',
    `- Artifacts found: ${result.backtests?.files?.length || 0}`,
    ...(result.backtests?.evidenceClasses || []).map((item) => `- ${item.label}: ${item.count} artifact(s) — ${item.boundary}`),
    ...(result.backtests?.highlights || ['No backtest highlights found.']).map((line) => `- ${line}`),
    '',
    '## Evidence boundaries',
    ...(s.evidenceBoundaries || []).map((line) => `- ${line}`),
    '',
    '## Market synthesis',
    `- Regime: ${s.marketRegime?.label || 'unknown'} (${s.marketRegime?.reason || '—'})`,
    `- Confidence: ${s.confidence || 'low'}`,
    `- Data gaps: ${(s.dataGaps || []).join('; ') || 'none'}`,
    '',
    '## Team findings',
    ...(s.findings || []).map((line) => `- ${line}`),
    '',
    '## Scenario analysis',
    toMarkdownTable(s.scenarios || [], [
      { label: 'Case', value: (r) => r.case },
      { label: 'Trigger', value: (r) => r.trigger },
      { label: 'Action', value: (r) => r.action },
    ]),
    '',
    '## Ticker stance',
    toMarkdownTable(s.tickerStance || [], [
      { label: 'Ticker', value: (r) => r.ticker },
      { label: 'Stance', value: (r) => r.stance },
      { label: 'Evidence', value: (r) => r.evidence },
    ]),
    '',
    '## Verification',
    ...(s.verification || []).map((line) => `- ${line}`),
  ];

  const errors = Object.entries(result.errors || {});
  if (errors.length) {
    lines.push('', '## Tool errors / limits');
    for (const [key, message] of errors) lines.push(`- ${key}: ${message}`);
  }
  lines.push('', result.disclaimer || 'Research automation output only.');
  return `${lines.join('\n')}\n`;
}

function buildResearchPlan({ query, tickers, date, startDate, endDate, capital, offline }) {
  return {
    objective: 'Build an evidence-backed Taiwan investment research report using a Dexter-like agent loop.',
    constraints: [
      'preserve existing Taiwan workflows',
      'Shioaji is primary for price/volume when live data is available',
      'use repo artifacts before inventing new assumptions',
      'separate evidence, inference, and scenario forecasts',
    ],
    parameters: { query, tickers, date, startDate, endDate, capital, offline },
    steps: [
      { id: 'S1', owner: 'planner', goal: 'Parse query and choose Taiwan research tasks.' },
      { id: 'S2', owner: 'data-agent', goal: 'Inventory repo caches, backtests, LINE reports, and memory.' },
      { id: 'S3', owner: 'market-agent', goal: 'Fetch Shioaji index/sector/ticker snapshots when online.' },
      { id: 'S4', owner: 'strategy-agent', goal: 'Read MVP/backtest artifacts and current signal studies.' },
      { id: 'S5', owner: 'etf-agent', goal: 'Integrate Xiaoyu ETF active/passive fund-flow lens.' },
      { id: 'S6', owner: 'scenario-agent', goal: 'Generate bull/base/bear scenario triggers and actions.' },
      { id: 'S7', owner: 'verifier', goal: 'Record gaps, confidence, scratchpad path, and reproducibility.' },
    ],
  };
}

function buildToolCalls({ tickers, date, startDate, endDate, capital, mode }) {
  const calls = [
    { key: 'market_indices', name: 'shioaji-snapshots', args: { tickers: DEFAULT_INDICES.join(','), exchange: 'TSE', securityType: 'IND' } },
    { key: 'ticker_snapshots', name: 'shioaji-snapshots', args: { tickers: tickers.join(','), exchange: 'TSE' } },
    { key: 'preopen', name: 'preopen-brief', args: { date, watchlist: tickers.join(','), noFetch: true } },
    { key: 'sector_flow', name: 'sector-flow', args: { mode: 'realtime', date, limit: mode === 'brief' ? 8 : 20 } },
    { key: 'xiaoyu_overview', name: 'xiaoyu-etf', args: { mode: 'overview', limit: mode === 'brief' ? 8 : 20 } },
  ];
  for (const ticker of tickers) {
    if (!ticker) continue;
    calls.push({
      key: `research_${ticker}`,
      name: 'research-pack',
      args: {
        ticker,
        market: 'tw',
        include: 'tw-company,signal-study,daily-decision-study,chip-study,xiaoyu-etf,tw-revenue,tw-valuation',
        startDate,
        endDate,
        decisionDays: 5,
        lookbackBars: 60,
        minAverageTurnover: Math.max(20_000_000, capital * 10),
        forwardDays: '3,5,10',
        limit: mode === 'brief' ? 5 : 20,
      },
    });
  }
  return calls;
}

function collectDataInventory(rootDir) {
  const roots = [];
  const latestFiles = [];
  for (const root of ARTIFACT_ROOTS) {
    const abs = join(rootDir, root);
    const files = existsSync(abs) ? walk(abs, 1200) : [];
    const latest = files.map((file) => ({ file, mtimeMs: safeStat(file)?.mtimeMs || 0 }))
      .sort((a, b) => b.mtimeMs - a.mtimeMs)
      .slice(0, 5);
    roots.push({
      root,
      files: files.length,
      latest: latest[0] ? relative(rootDir, latest[0].file) : null,
    });
    latestFiles.push(...latest.map((entry) => relative(rootDir, entry.file)));
  }
  return {
    roots,
    latestFiles: latestFiles.slice(0, 25),
    boundary: 'Inventory only; raw secrets and noisy logs are excluded.',
  };
}

function collectBacktestEvidence(rootDir) {
  const candidates = [...new Set([
    '.omx/backtests',
    '.omx/research',
    '.omx/ultragoal/q2q3-mvp-search',
    '.omx/ultragoal',
  ].flatMap((root) => existsSync(join(rootDir, root)) ? walk(join(rootDir, root), 300) : [])
    .filter((file) => /\.(md|json)$/i.test(file)))];
  const files = candidates.map((file) => relative(rootDir, file));
  const evidenceClasses = summarizeEvidenceClasses(files);
  const highlights = [];
  for (const rel of files) {
    const text = redactSecrets(readText(join(rootDir, rel)));
    const picked = text.split(/\r?\n/).filter((line) => /return|win rate|收益|勝率|MVP|Selected variant|Ending equity|Total return|Max drawdown|Trades|回測/i.test(line)).slice(0, 4);
    for (const line of picked) highlights.push(`${rel}: ${line.replace(/^[-#\s]*/, '').slice(0, 220)}`);
    if (highlights.length >= 16) break;
  }
  return { files, evidenceClasses, highlights: highlights.slice(0, 16) };
}

function synthesizeAgentTeam({ tickers, inventory, backtests, toolResults, errors, offline }) {
  const indexRows = normalizeRows(toolResults.market_indices);
  const tickerRows = normalizeRows(toolResults.ticker_snapshots);
  const sectorRows = normalizeSectorRows(toolResults.sector_flow);
  const index = indexRows.find((row) => String(row.code || row.Code) === '001') || indexRows[0];
  const indexChange = numericChange(index);
  const marketRegime = classifyMarket(indexChange, sectorRows, offline);
  const dataGaps = [];
  if (offline) dataGaps.push('offline mode: live Shioaji/tool calls skipped');
  for (const [key, message] of Object.entries(errors || {})) dataGaps.push(`${key}: ${message}`);
  if (!backtests.files?.length) dataGaps.push('no backtest artifact found');

  const findings = [
    `Repo inventory covers ${inventory.roots?.reduce((sum, r) => sum + Number(r.files || 0), 0) || 0} files across cache/backtest/research/workflow roots.`,
    `Backtest evidence files found: ${backtests.files?.length || 0}.`,
    `Live data mode: ${offline ? 'offline artifact synthesis' : 'tool-backed Shioaji/repo workflow integration'}.`,
  ];
  if (sectorRows.length) findings.push(`Top sector proxy: ${sectorRows[0].industry || sectorRows[0].Industry || 'unknown'} turnover=${sectorRows[0].turnover || sectorRows[0].Turnover || '—'}.`);
  const xiaoyuDate = toolResults.xiaoyu_overview?.date
    || toolResults.xiaoyu_overview?.dataDate
    || toolResults.xiaoyu_overview?.summary?.date
    || toolResults.xiaoyu_overview?.meta?.latest_slash;
  if (xiaoyuDate) findings.push(`Xiaoyu ETF lens included with data date ${xiaoyuDate}.`);

  return {
    marketRegime,
    confidence: dataGaps.length ? 'medium' : 'high',
    dataGaps,
    findings,
    evidenceBoundaries: [
      'Primary price/volume: Shioaji snapshots and existing Shioaji-backed studies when live calls are enabled.',
      'Backtest evidence: .omx/backtests and .omx/research artifacts are cited separately from workflow/policy docs.',
      'Auxiliary flow lens: Xiaoyu ETF data is secondary context, not a replacement for Shioaji price/volume or MVP decision rules.',
      'Scratchpad/report persistence: tool outputs are recursively redacted before writing/returning.',
    ],
    scenarios: buildScenarios(marketRegime),
    tickerStance: buildTickerStance(tickers, tickerRows, toolResults),
    verification: [
      'Scratchpad JSONL persisted every planning/tool/synthesis step.',
      'Existing Taiwan workflows were called/read, not deleted or replaced.',
      'Backtest evidence is linked from repo artifacts; rerun scripts remain separate from the agent harness.',
    ],
  };
}

function classifyMarket(indexChange, sectorRows, offline) {
  if (offline || Number.isNaN(indexChange)) return { label: 'artifact-only', reason: 'No live index change available.' };
  const weakSectors = sectorRows.filter((row) => Number(row.changePct ?? row.change_percent ?? row.change ?? 0) < -2).length;
  if (indexChange <= -2) return { label: 'risk-off', reason: `Index change ${indexChange}% with ${weakSectors} weak sectors.` };
  if (indexChange >= 1) return { label: 'risk-on', reason: `Index change ${indexChange}% supports pro-risk stance.` };
  return { label: 'rotation', reason: `Index change ${indexChange}% implies selective/rotational market.` };
}

function buildScenarios(marketRegime) {
  return [
    {
      case: 'Bull',
      trigger: 'Index reclaims key intraday level; Shioaji breadth/sector-flow improves; ETF lens stops net selling high-beta holdings.',
      action: 'Use existing MVP/decision-study entries; avoid chasing without volume/liquidity confirmation.',
    },
    {
      case: 'Base',
      trigger: `Market stays ${marketRegime.label}; sector leadership rotates instead of broad advance.`,
      action: 'Prioritize liquid leaders, reduce weak high-beta exposure, keep position sizing tied to turnover.',
    },
    {
      case: 'Bear',
      trigger: 'Index breaks support with electronics/ETF sell pressure and failed rebounds.',
      action: 'No averaging down; wait for failed-breakout/WR3 or new decision-study confirmation before entries.',
    },
  ];
}

function buildTickerStance(tickers, snapshotRows, toolResults) {
  return tickers.map((ticker) => {
    const row = snapshotRows.find((entry) => String(entry.code || entry.Code) === String(ticker));
    const change = numericChange(row);
    const research = toolResults[`research_${ticker}`];
    const hasBackedStudy = Boolean(research?.results?.['signal-study'] || research?.results?.['daily-decision-study'] || research?.results?.['chip-study']);
    let stance = 'observe';
    if (!Number.isNaN(change)) {
      if (change <= -4) stance = 'avoid-catch-falling-knife';
      else if (change >= 2) stance = 'momentum-watch';
      else stance = 'neutral-confirmation';
    }
    return {
      ticker,
      stance,
      evidence: row ? `snapshot change=${Number.isNaN(change) ? '—' : `${change}%`}; researchPack=${hasBackedStudy ? 'yes' : 'no'}` : `snapshot unavailable; researchPack=${hasBackedStudy ? 'yes' : 'no'}`,
    };
  });
}

function persistReport(rootDir, result) {
  const dir = join(rootDir, '.omx', 'agent-team', 'reports');
  mkdirSync(dir, { recursive: true });
  const stamp = new Date().toISOString().slice(0, 19).replace('T', '-').replace(/:/g, '');
  const file = join(dir, `${stamp}-taiwan-agent-team.md`);
  result.reportPath = relative(rootDir, file);
  writeFileSync(file, renderTaiwanAgentTeamMarkdown(result));
  return file;
}

function normalizeTickers(value) {
  const raw = Array.isArray(value) ? value : String(value || '').split(',');
  return raw.map((item) => String(item).trim().toUpperCase()).filter(Boolean);
}

function normalizeRows(result) {
  if (!result) return [];
  if (Array.isArray(result)) return result;
  if (Array.isArray(result.data)) return result.data;
  if (Array.isArray(result.data?.rows)) return result.data.rows;
  if (Array.isArray(result.rows)) return result.rows;
  return [];
}

function normalizeSectorRows(result) {
  if (!result) return [];
  if (Array.isArray(result.industries)) return result.industries;
  if (Array.isArray(result.data?.industries)) return result.data.industries;
  return normalizeRows(result);
}

function summarizeEvidenceClasses(files) {
  const classes = [
    { key: 'canonical-backtests', label: 'Canonical/reproducible backtests', boundary: 'performance evidence only; does not rewrite the active MVP strategy', match: (file) => file.startsWith('.omx/backtests/') },
    { key: 'research-artifacts', label: 'Research artifacts', boundary: 'research-only variants or baseline studies; promoted only by explicit user instruction', match: (file) => file.startsWith('.omx/research/') },
    { key: 'goal-audit', label: 'Goal/audit artifacts', boundary: 'execution audit trail and quality-gate evidence, not market data', match: (file) => file.startsWith('.omx/ultragoal/') },
  ];
  return classes.map((entry) => ({
    key: entry.key,
    label: entry.label,
    count: files.filter(entry.match).length,
    boundary: entry.boundary,
  })).filter((entry) => entry.count > 0);
}

function todayTaipei() {
  const date = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Taipei' }));
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function walk(root, maxFiles = 1000, acc = []) {
  if (acc.length >= maxFiles) return acc;
  let entries = [];
  try { entries = readdirSync(root, { withFileTypes: true }); } catch { return acc; }
  for (const entry of entries) {
    if (acc.length >= maxFiles) break;
    if (entry.name === 'node_modules' || entry.name === '.git' || entry.name.includes('secret')) continue;
    const file = join(root, entry.name);
    if (entry.isDirectory()) walk(file, maxFiles, acc);
    else acc.push(file);
  }
  return acc;
}

function safeStat(file) {
  try { return statSync(file); } catch { return null; }
}

function defaultOptionalInt(args, key, defaultValue) {
  const value = args?.[key];
  if (value === undefined || value === null || value === '') return defaultValue;
  const parsed = Number.parseInt(String(value), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : defaultValue;
}

function readText(file) {
  try {
    const stat = statSync(file);
    if (stat.size > 500_000) return '';
    return readFileSync(file, 'utf8');
  } catch {
    return '';
  }
}

function numericChange(row) {
  return Number(row?.changeRate ?? row?.change_rate ?? row?.change_percent ?? row?.changePct ?? row?.changePercent ?? row?.['Change %']);
}

function safeJson(value) {
  if (value === undefined) return null;
  try {
    return redactSecrets(JSON.parse(JSON.stringify(value)));
  } catch {
    return redactSecrets(String(value));
  }
}

function redactSecrets(value) {
  if (Array.isArray(value)) return value.map((item) => redactSecrets(item));
  if (value && typeof value === 'object') {
    const output = {};
    for (const [key, nested] of Object.entries(value)) {
      if (/token|secret|password|api[_-]?key/i.test(key)) {
        output[key] = '[REDACTED]';
      } else {
        output[key] = redactSecrets(nested);
      }
    }
    return output;
  }
  if (typeof value === 'string') {
    return value
      .replace(/(\\?["'][^\\"']*(?:token|secret|password|api[_-]?key|apikey)[^\\"']*\\?["']\s*:\s*\\?["'])[^\\"']+(\\?["'])/gi, '$1[REDACTED]$2')
      .replace(/([?&](?:token|api_key|apikey|key)=)[^&\s"']+/gi, '$1[REDACTED]')
      .replace(/\b((?:[A-Z0-9_]*)(?:TOKEN|SECRET|PASSWORD|API[_-]?KEY|APIKEY|SJ_API_KEY)(?:[A-Z0-9_]*))\s*[:=]\s*[^,\s"'}]+/gi, '$1=[REDACTED]')
      .replace(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g, '[REDACTED_JWT]')
      .replace(/\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+/gi, '$1 [REDACTED]')
      .replace(/\bU[a-f0-9]{30,}\b/gi, '[REDACTED_LINE_USER]');
  }
  return value;
}
