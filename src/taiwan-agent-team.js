import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync, appendFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { compactNumber, toMarkdownTable } from './format.js';

const WORKFLOW_VERSION = '1.4';
const DEFAULT_TICKERS = ['00981A', '00991A', '2330', '4915'];
const DEFAULT_INDICES = ['001', '027', '036', '040', '038'];
const SCREEN_INTENT = /選股|股票篩選|篩選股票|找股票|候選股票|候選名單|全市場掃描|stock\s*screen|find\s+stocks/i;
const EXTERNAL_RESEARCH_INCLUDE = 'tw-company,tw-news,tw-announcements,tw-financials,tw-revenue,tw-valuation,xiaoyu-etf';
const AGENT_LANES = Object.freeze([
  { name: 'planner', responsibility: 'Resolve screen/analyze intent, parameters, stage order, and stop conditions.' },
  { name: 'data-agent', responsibility: 'Inventory repository evidence and prepare point-in-time data in screen mode.' },
  { name: 'strategy-agent', responsibility: 'Run Phase 3 dataset and technical screening only for stock-screening requests.' },
  { name: 'market-agent', responsibility: 'Collect read-only index, ticker, pre-open, sector, and peer context.' },
  { name: 'external-confidence-agent', responsibility: 'Collect company, news, announcement, financial, revenue, valuation, ETF, and Gooaye topic evidence.' },
  { name: 'dom-agent', responsibility: 'Read Shioaji DOM after research and preserve four manual reference prices.' },
  { name: 'verifier', responsibility: 'Audit order, failures, eligibility boundaries, redaction, and read-only safety.' },
]);
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
  mode: { type: 'string', enum: ['auto', 'screen', 'analyze', 'brief', 'full'], description: 'Workflow intent; brief/full remain legacy detail aliases.' },
  detail: { type: 'string', enum: ['brief', 'full'], description: 'Report/tool detail level.' },
  evidenceRoot: { type: 'string', description: 'Point-in-time Phase 3 evidence root used only in screen mode.' },
  offline: { type: 'boolean', description: 'Use only repo artifacts and skip all live/read-only tool calls.' },
  maxTickers: { type: 'number' },
};

export function resolveTaiwanAgentTeamMode({ mode, query, prompt } = {}) {
  const normalizedMode = String(mode || 'auto').toLowerCase();
  if (normalizedMode === 'screen' || normalizedMode === 'analyze') {
    return { workflowMode: normalizedMode, modeSource: 'explicit' };
  }
  const text = String(query || prompt || '');
  if (SCREEN_INTENT.test(text)) return { workflowMode: 'screen', modeSource: 'inferred' };
  return { workflowMode: 'analyze', modeSource: 'default' };
}

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
    detail: args.detail ? String(args.detail) : undefined,
    evidenceRoot: args['evidence-root'] ? String(args['evidence-root']) : undefined,
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
  const maxTickers = positiveInteger(args.maxTickers, 8);
  const requestedTickers = normalizeTickers(args.tickers || args.ticker || args.watchlist);
  const date = args.date || todayTaipei();
  const startDate = args.startDate || args.start || '2026-04-01';
  const endDate = args.endDate || args.end || date;
  const capital = Number(args.capital || 500000);
  const evidenceRoot = args.evidenceRoot || join('.omx', 'evidence', 'phase3');
  const offline = args.offline === true || args.offline === 'true';
  const { workflowMode, modeSource } = resolveTaiwanAgentTeamMode(args);
  const detail = args.detail || (['brief', 'full'].includes(args.mode) ? args.mode : 'full');
  const runTool = deps.runTool;
  const scratchpad = new TaiwanAgentScratchpad(query, { rootDir, scratchpadDir: deps.scratchpadDir });

  let targets = workflowMode === 'analyze'
    ? (requestedTickers.length ? requestedTickers : DEFAULT_TICKERS).slice(0, maxTickers)
    : [];
  const plan = buildResearchPlan({
    query,
    requestedTickers,
    workflowMode,
    modeSource,
    targets,
    date,
    startDate,
    endDate,
    capital,
    evidenceRoot,
    offline,
  });
  scratchpad.thinking(`Standard Workflow ${WORKFLOW_VERSION} plan created; workflowMode=${workflowMode}; modeSource=${modeSource}; offline=${offline}.`);

  const inventory = collectDataInventory(rootDir);
  scratchpad.toolResult('repo_data_inventory', { roots: ARTIFACT_ROOTS }, inventory);
  const backtests = collectBacktestEvidence(rootDir);
  scratchpad.toolResult('backtest_evidence', { roots: ['.omx/backtests', '.omx/research', '.omx/ultragoal'] }, backtests);

  const toolResults = {};
  const errors = {};
  const audit = [];
  const phase3 = { dataset: null, screen: null };
  const runRecorded = async ({ key, name, args: toolArgs, stage, agent, ticker }) => {
    const order = audit.length + 1;
    try {
      const result = safeJson(await runTool(name, compactObject(toolArgs)));
      toolResults[key] = result;
      audit.push({ order, stage, agent, key, tool: name, ticker: ticker || null, status: 'ok' });
      scratchpad.toolResult(name, compactObject(toolArgs), result);
      return { ok: true, result };
    } catch (error) {
      const message = redactSecrets(error?.message || String(error));
      errors[key] = message;
      audit.push({ order, stage, agent, key, tool: name, ticker: ticker || null, status: 'error', error: message });
      scratchpad.toolResult(name, compactObject(toolArgs), { error: message }, 'error');
      return { ok: false, error: message };
    }
  };

  if (!offline && runTool) {
    const commonCalls = [
      { key: 'market_indices', name: 'shioaji-snapshots', args: { tickers: DEFAULT_INDICES.join(','), exchange: 'TSE', securityType: 'IND' }, stage: 'market-context', agent: 'market-agent' },
      { key: 'sector_flow', name: 'sector-flow', args: { mode: 'realtime', date, limit: detail === 'brief' ? 8 : 20 }, stage: 'market-context', agent: 'market-agent' },
      { key: 'xiaoyu_overview', name: 'xiaoyu-etf', args: { mode: 'overview', limit: detail === 'brief' ? 8 : 20 }, stage: 'market-context', agent: 'market-agent' },
    ];
    for (const call of commonCalls) await runRecorded(call);

    if (workflowMode === 'screen') {
      const datasetRun = await runRecorded({
        key: 'phase3_dataset',
        name: 'phase3-dataset',
        args: { startDate, endDate, evidenceRoot },
        stage: 'phase3-dataset',
        agent: 'data-agent',
      });
      if (datasetRun.ok) {
        phase3.dataset = datasetRun.result;
        const screenRun = await runRecorded({
          key: 'phase3_screen',
          name: 'phase3-screen',
          // Dataset bounds control evidence collection only. Omitting a screening
          // window makes phase3-screen evaluate the latest complete decision date
          // instead of re-ranking every historical signal in that collection range.
          args: { evidenceRoot, top: maxTickers, includeRejected: true },
          stage: 'phase3-screen',
          agent: 'strategy-agent',
        });
        if (screenRun.ok) {
          phase3.screen = screenRun.result;
          targets = normalizeTickers((screenRun.result?.candidates || []).map((row) => row?.ticker)).slice(0, maxTickers);
        }
      }
    }

    if (targets.length) {
      await runRecorded({
        key: 'ticker_snapshots',
        name: 'shioaji-snapshots',
        args: { tickers: targets.join(','), exchange: 'TSE' },
        stage: 'target-market-context',
        agent: 'market-agent',
      });
      await runRecorded({
        key: 'preopen',
        name: 'preopen-brief',
        args: { date, watchlist: targets.join(','), noFetch: true },
        stage: 'target-market-context',
        agent: 'market-agent',
      });

      for (const ticker of targets) {
        await runRecorded({
          key: `research_${ticker}`,
          name: 'research-pack',
          args: {
            ticker,
            market: 'tw',
            include: EXTERNAL_RESEARCH_INCLUDE,
            startDate,
            endDate,
            minAverageTurnover: Math.max(20_000_000, capital * 10),
            limit: detail === 'brief' ? 5 : 20,
          },
          stage: 'external-confidence',
          agent: 'external-confidence-agent',
          ticker,
        });
        await runRecorded({
          key: `industry_${ticker}`,
          name: 'ic-tpex-chain',
          args: { ticker },
          stage: 'external-confidence',
          agent: 'market-agent',
          ticker,
        });
        await runRecorded({
          key: `xiaoyu_${ticker}`,
          name: 'xiaoyu-etf',
          args: { mode: 'stock', ticker, limit: detail === 'brief' ? 5 : 20 },
          stage: 'external-confidence',
          agent: 'external-confidence-agent',
          ticker,
        });
      }

      await runRecorded({
        key: 'gooaye_market_context',
        name: 'gooaye-topic-research',
        args: { date, tickers: targets.join(',') },
        stage: 'external-confidence',
        agent: 'external-confidence-agent',
      });

      for (const ticker of targets) {
        await runRecorded({
          key: `dom_${ticker}`,
          name: 'phase3-dom-confidence',
          args: { ticker },
          stage: 'dom-confidence',
          agent: 'dom-agent',
          ticker,
        });
      }
    } else if (workflowMode === 'screen' && phase3.screen) {
      scratchpad.thinking('Phase 3 completed with zero eligible candidates; target research and DOM were stopped.');
    }
  } else {
    if (!offline && !runTool) errors.runner = 'no tool runner was provided';
    scratchpad.thinking('Offline/no-runner mode: skipped Phase 3, market, external-confidence, and DOM calls.');
  }

  const tickerAnalysis = buildTickerAnalysis({ targets, workflowMode, toolResults, errors });
  const synthesis = synthesizeAgentTeam({
    inventory,
    backtests,
    toolResults,
    errors,
    offline,
    workflowMode,
    phase3,
    tickerAnalysis,
  });
  scratchpad.thinking(`Synthesis complete: market=${synthesis.marketRegime.label}; confidence=${synthesis.confidence}; targets=${targets.length}.`);

  const result = {
    workflowVersion: WORKFLOW_VERSION,
    workflowMode,
    modeSource,
    agent: {
      name: 'taiwan-agent-team',
      role: 'Official Standard Workflow 1.4 deterministic orchestration entry',
      lanes: AGENT_LANES,
      architecture: AGENT_LANES.map((lane) => `${lane.name}: ${lane.responsibility}`),
      safety: [
        'Phase 3 is the sole technical eligibility mechanism and runs only in screen mode.',
        'External research and DOM cannot change Phase 3 eligibility.',
        'A final actionable shortlist must disclose Gooaye/theme alignment; a mismatch may retire the recommendation without rewriting technical eligibility.',
        'All Shioaji/DOM access is read-only; no order API is called.',
        'Four prices are manual reference data, never executable orders.',
      ],
    },
    request: {
      query,
      requestedTickers,
      date,
      startDate,
      endDate,
      capital,
      requestedMode: args.mode || 'auto',
      detail,
      evidenceRoot,
      workflowMode,
      modeSource,
      offline,
    },
    scratchpad: { path: relative(rootDir, scratchpad.filepath), format: 'jsonl' },
    plan,
    inventory,
    backtests,
    phase3,
    targets,
    tickerAnalysis,
    audit,
    toolResults,
    errors,
    synthesis,
    disclaimer: 'Research automation output only; the user manually decides and places any trade.',
  };

  const safeResult = redactSecrets(result);
  persistReport(rootDir, safeResult);
  return safeResult;
}

export function renderTaiwanAgentTeamMarkdown(result) {
  const s = result.synthesis || {};
  const tickerRows = (result.tickerAnalysis || []).map((row) => ({
    ticker: row.ticker,
    eligibility: row.phase3Eligibility,
    bias: row.bias,
    external: row.externalConfidence?.availableCount ?? 0,
    domScore: row.dom?.score ?? 'unavailable',
    pressure: row.dom?.pressureLabel || 'unavailable',
    reliability: row.dom?.reliability || 'unavailable',
    active: printable(row.prices?.activeEntryLimit),
    patient: printable(row.prices?.patientEntryPrice),
    profit: printable(row.prices?.takeProfitPrice),
    loss: printable(row.prices?.stopLossPrice),
  }));
  const lines = [
    `# Taiwan Agent Team — Standard Workflow ${result.workflowVersion || WORKFLOW_VERSION}`,
    '',
    `Workflow mode: ${result.workflowMode || 'unknown'} (${result.modeSource || 'unknown'})`,
    `Query: ${result.request?.query || '—'}`,
    `Date range: ${result.request?.startDate || '—'} ~ ${result.request?.endDate || '—'}`,
    `Capital base: ${compactNumber(result.request?.capital)}`,
    `Targets: ${(result.targets || []).join(', ') || 'none'}`,
    `Scratchpad: ${result.scratchpad?.path || '—'}`,
    `Report artifact: ${result.reportPath || '—'}`,
    '',
    '## Seven-agent architecture',
    ...(result.agent?.architecture || []).map((item) => `- ${item}`),
    '',
    '## Ordered tool audit',
    toMarkdownTable(result.audit || [], [
      { label: '#', value: (r) => r.order },
      { label: 'Stage', value: (r) => r.stage },
      { label: 'Agent', value: (r) => r.agent },
      { label: 'Tool', value: (r) => r.tool },
      { label: 'Ticker', value: (r) => r.ticker || '—' },
      { label: 'Status', value: (r) => r.status },
    ]),
    '',
    '## Phase 3 screening',
    `- Dataset: ${result.phase3?.dataset ? 'completed' : result.workflowMode === 'screen' ? 'unavailable' : 'not requested'}`,
    `- Screen: ${result.phase3?.screen ? 'completed' : result.workflowMode === 'screen' ? 'unavailable' : 'not requested'}`,
    `- Eligible: ${result.phase3?.screen?.eligibleCount ?? (result.workflowMode === 'screen' ? 0 : 'not_evaluated')}`,
    `- Rejected: ${result.phase3?.screen?.rejectedCount ?? (result.workflowMode === 'screen' ? 0 : 'not_evaluated')}`,
    '',
    '## Gooaye topic context',
    `- Status: ${result.toolResults?.gooaye_market_context?.status || 'unavailable'}`,
    `- Episode: ${result.toolResults?.gooaye_market_context?.episode?.title || '—'}`,
    `- Research: ${result.toolResults?.gooaye_market_context?.research?.title || '—'}`,
    `- Themes: ${(result.toolResults?.gooaye_market_context?.research?.themes || []).join(', ') || '—'}`,
    '',
    '## Ticker confidence and four prices',
    toMarkdownTable(tickerRows, [
      { label: 'Ticker', value: (r) => r.ticker },
      { label: 'Phase 3', value: (r) => r.eligibility },
      { label: 'Bias', value: (r) => r.bias },
      { label: 'External sources', value: (r) => r.external },
      { label: 'DOM score', value: (r) => r.domScore },
      { label: 'Pressure', value: (r) => r.pressure },
      { label: 'Reliability', value: (r) => r.reliability },
      { label: 'Active entry limit', value: (r) => r.active },
      { label: 'Patient entry', value: (r) => r.patient },
      { label: 'Take-profit', value: (r) => r.profit },
      { label: 'Stop-loss', value: (r) => r.loss },
    ]),
    ...(result.tickerAnalysis || []).flatMap((row) => [
      '',
      `### ${row.ticker} price references`,
      `- Active entry limit: ${printable(row.prices?.activeEntryLimit)}`,
      `- Patient entry price: ${printable(row.prices?.patientEntryPrice)}`,
      `- Take-profit price: ${printable(row.prices?.takeProfitPrice)}`,
      `- Stop-loss price: ${printable(row.prices?.stopLossPrice)}`,
      ...(row.dom?.reliability === 'unavailable'
        ? ['- DOM gap: no valid sample; all four price fields are null']
        : []),
    ]),
    '',
    '## Market synthesis',
    `- Regime: ${s.marketRegime?.label || 'unknown'} (${s.marketRegime?.reason || '—'})`,
    `- Confidence: ${s.confidence || 'low'}`,
    `- Data gaps: ${(s.dataGaps || []).join('; ') || 'none'}`,
    '',
    '## Evidence boundaries',
    ...(s.evidenceBoundaries || []).map((line) => `- ${line}`),
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

function buildResearchPlan(parameters) {
  const screen = parameters.workflowMode === 'screen';
  return {
    objective: 'Run the official Taiwan Standard Workflow 1.4 with auditable eligibility and confidence boundaries.',
    constraints: [
      'Phase 3 screens only when stock-screening intent is resolved',
      'only eligible screen candidates may enter downstream research',
      'external research, including Gooaye topic context, precedes DOM and cannot alter eligibility',
      'final recommendations disclose trend alignment and may demote unrelated candidates after Phase 3',
      'DOM is read-only and always returns four manual reference fields or explicit nulls',
    ],
    parameters,
    steps: [
      { id: 'S1', owner: 'planner', goal: 'Resolve screen/analyze intent and stop conditions.' },
      { id: 'S2', owner: 'data-agent', goal: screen ? 'Inventory evidence and prepare point-in-time Phase 3 data.' : 'Inventory repo evidence without Phase 3.' },
      { id: 'S3', owner: 'strategy-agent', goal: screen ? 'Run Phase 3 and emit eligible candidates only.' : 'Mark named tickers not_evaluated by Phase 3.' },
      { id: 'S4', owner: 'market-agent', goal: 'Collect index, target, pre-open, sector, and peer context.' },
      { id: 'S5', owner: 'external-confidence-agent', goal: 'Collect point-in-time company, industry, ETF, and Gooaye topic evidence before DOM.' },
      { id: 'S6', owner: 'dom-agent', goal: 'Read DOM after research and derive four manual reference prices.' },
      { id: 'S7', owner: 'verifier', goal: 'Audit stage order, failures, eligibility isolation, and read-only safety.' },
    ],
  };
}

function buildTickerAnalysis({ targets, workflowMode, toolResults, errors }) {
  return targets.map((ticker) => {
    const sourceKeys = [`research_${ticker}`, `industry_${ticker}`, `xiaoyu_${ticker}`, 'gooaye_market_context'];
    const available = sourceKeys.filter((key) => key === 'gooaye_market_context'
      ? Boolean(toolResults[key]?.research)
      : toolResults[key] !== undefined);
    const unavailable = sourceKeys.filter((key) => errors[key] !== undefined
      || (key === 'gooaye_market_context' && toolResults[key] !== undefined && !toolResults[key]?.research));
    const rawDom = toolResults[`dom_${ticker}`];
    const referencePrices = rawDom?.referencePrices || {};
    const prices = {
      activeEntryLimit: referencePrices.activeEntryLimit ?? null,
      patientEntryPrice: referencePrices.patientEntryPrice ?? null,
      takeProfitPrice: referencePrices.takeProfitPrice ?? null,
      stopLossPrice: referencePrices.stopLossPrice ?? null,
    };
    const score = rawDom?.domConfidenceScore ?? null;
    return {
      ticker,
      phase3Eligibility: workflowMode === 'screen' ? 'eligible' : 'not_evaluated',
      externalConfidence: {
        availableCount: available.length,
        requestedCount: sourceKeys.length,
        available,
        unavailable,
      },
      dom: {
        available: Boolean(rawDom),
        executionMode: rawDom?.executionMode || 'read_only',
        readOnly: rawDom?.readOnly ?? true,
        validSampleCount: rawDom?.validSampleCount ?? 0,
        requestedSampleCount: rawDom?.requestedSampleCount ?? 0,
        score,
        meanPressure: rawDom?.meanPressure ?? null,
        pressureLabel: rawDom?.pressureLabel || 'unavailable',
        reliability: rawDom?.reliability || 'unavailable',
        interpretation: rawDom?.interpretation || 'unavailable',
        risks: rawDom?.risks || [errors[`dom_${ticker}`] ? 'dom_tool_error' : 'no_valid_dom_sample'],
      },
      prices,
      bias: score === null ? 'insufficient_dom_data' : score >= 58 ? '偏多' : score <= 42 ? '偏空' : '中性',
    };
  });
}

function synthesizeAgentTeam({ inventory, backtests, toolResults, errors, offline, workflowMode, phase3, tickerAnalysis }) {
  const indexRows = normalizeRows(toolResults.market_indices);
  const sectorRows = normalizeSectorRows(toolResults.sector_flow);
  const index = indexRows.find((row) => String(row.code || row.Code) === '001') || indexRows[0];
  const marketRegime = classifyMarket(numericChange(index), sectorRows, offline);
  const dataGaps = [];
  if (offline) dataGaps.push('offline mode: all tool calls skipped');
  for (const [key, message] of Object.entries(errors || {})) dataGaps.push(`${key}: ${message}`);
  if (!backtests.files?.length) dataGaps.push('no backtest artifact found');
  if (workflowMode === 'screen' && phase3.screen && tickerAnalysis.length === 0) {
    dataGaps.push('zero eligible Phase 3 candidates; downstream target research stopped');
  }
  for (const row of tickerAnalysis) {
    if (row.dom.reliability === 'unavailable') dataGaps.push(`${row.ticker}: DOM unavailable; four prices are null`);
  }
  return {
    marketRegime,
    confidence: dataGaps.length ? 'medium' : 'high',
    dataGaps,
    findings: [
      `Repo inventory covers ${inventory.roots?.reduce((sum, row) => sum + Number(row.files || 0), 0) || 0} files.`,
      `Targets completed: ${tickerAnalysis.length}.`,
      `Phase 3 mode: ${workflowMode === 'screen' ? 'technical screening requested' : 'not evaluated for direct analysis'}.`,
    ],
    evidenceBoundaries: [
      'Phase 3 is the sole technical eligibility path and runs only in screen mode.',
      'External company/news/financial/Gooaye evidence is a post-screen confidence layer, not an eligibility gate.',
      'Gooaye/theme mismatch may remove a ticker from the actionable shortlist while preserving its historical Phase 3 result.',
      'DOM is sampled only after external research and does not enter Phase 3 features or eligibility.',
      'Four prices are visible-book references for manual decisions, not guaranteed fills or orders.',
      'Backtest artifacts are auditable historical evidence, not a second active strategy.',
    ],
    verification: [
      'Seven logical agent lanes and every tool call are recorded in deterministic order.',
      'Rejected or zero-candidate screen results cannot enter target research or DOM.',
      'Analyze-mode tickers are explicitly marked not_evaluated by Phase 3.',
      'No order API is part of this workflow; Shioaji/DOM access remains read-only.',
    ],
  };
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
    roots.push({ root, files: files.length, latest: latest[0] ? relative(rootDir, latest[0].file) : null });
    latestFiles.push(...latest.map((entry) => relative(rootDir, entry.file)));
  }
  return { roots, latestFiles: latestFiles.slice(0, 25), boundary: 'Inventory only; raw secrets and noisy logs are excluded.' };
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
    const picked = text.split(/\r?\n/).filter((line) => /return|win rate|收益|勝率|MVP|Ending equity|Total return|Max drawdown|Trades|回測/i.test(line)).slice(0, 4);
    for (const line of picked) highlights.push(`${rel}: ${line.replace(/^[-#\s]*/, '').slice(0, 220)}`);
    if (highlights.length >= 16) break;
  }
  return { files, evidenceClasses, highlights: highlights.slice(0, 16) };
}

function classifyMarket(indexChange, sectorRows, offline) {
  if (offline || Number.isNaN(indexChange)) return { label: 'artifact-only', reason: 'No live index change available.' };
  const weakSectors = sectorRows.filter((row) => Number(row.changePct ?? row.change_percent ?? row.change ?? 0) < -2).length;
  if (indexChange <= -2) return { label: 'risk-off', reason: `Index change ${indexChange}% with ${weakSectors} weak sectors.` };
  if (indexChange >= 1) return { label: 'risk-on', reason: `Index change ${indexChange}% supports pro-risk context.` };
  return { label: 'rotation', reason: `Index change ${indexChange}% implies selective/rotational conditions.` };
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
  return raw.map((item) => typeof item === 'object' ? item?.ticker : item)
    .map((item) => String(item || '').trim().toUpperCase())
    .filter(Boolean);
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
    { key: 'canonical-backtests', label: 'Canonical/reproducible backtests', boundary: 'performance evidence only; does not rewrite the active Phase 3 strategy', match: (file) => file.startsWith('.omx/backtests/') },
    { key: 'research-artifacts', label: 'Research artifacts', boundary: 'research-only variants; promoted only by explicit user instruction', match: (file) => file.startsWith('.omx/research/') },
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

function compactObject(value) {
  return Object.fromEntries(Object.entries(value || {}).filter(([, item]) => item !== undefined));
}

function positiveInteger(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ''), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
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

function printable(value) {
  return value === null || value === undefined ? 'null' : value;
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
      if (/token|secret|password|api[_-]?key/i.test(key)) output[key] = '[REDACTED]';
      else output[key] = redactSecrets(nested);
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
