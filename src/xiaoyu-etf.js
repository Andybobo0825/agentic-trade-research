import { compactNumber, toMarkdownTable } from './format.js';

export const XIAOYU_ETF_BASE_URL = 'https://xiaoyu-etf.pages.dev';

function urlFor(path, baseUrl = XIAOYU_ETF_BASE_URL) {
  return new URL(path.replace(/^\//, ''), `${baseUrl.replace(/\/$/, '')}/`);
}

export async function fetchXiaoyuEtfData({ baseUrl = XIAOYU_ETF_BASE_URL } = {}) {
  const url = urlFor('data.js', baseUrl);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`xiaoyu-etf request failed (${res.status}) for ${url}`);
  const text = await res.text();
  const match = text.match(/window\.DATA\s*=\s*(.*?);?\s*$/s);
  if (!match) throw new Error('xiaoyu-etf data.js did not contain window.DATA');
  return JSON.parse(match[1]);
}

export async function fetchXiaoyuEtfJson(path, { baseUrl = XIAOYU_ETF_BASE_URL } = {}) {
  const url = urlFor(path, baseUrl);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`xiaoyu-etf request failed (${res.status}) for ${url}`);
  return res.json();
}

export async function buildXiaoyuEtfLens(args = {}) {
  const data = await fetchXiaoyuEtfData(args);
  const mode = String(args.mode || (args.ticker ? 'stock' : args.etf ? 'etf' : 'rank')).toLowerCase();
  const limit = Number.isFinite(Number(args.limit)) ? Math.max(1, Number(args.limit)) : 10;
  const common = {
    source: 'xiaoyu-etf',
    sourceUrl: XIAOYU_ETF_BASE_URL,
    usage: 'ETF 持股、ETF 推估買賣與三大法人輔助資料；價格/量價/交易判斷仍以 Shioaji 與 Standard Workflow 1.3 為主。',
    meta: data.meta || {},
  };

  if (mode === 'stock') return { ...common, mode, ...stockLens(data, args, limit) };
  if (mode === 'etf') return { ...common, mode, ...await etfLens(data, args, limit) };
  if (mode === 'overview') return { ...common, mode, ...overviewLens(data, limit) };
  return { ...common, mode: 'rank', ...rankLens(data, args, limit) };
}

function stockLens(data, args, limit) {
  const ticker = normalizeCode(args.ticker);
  if (!ticker) throw new Error('xiaoyu-etf stock mode requires ticker');
  const stock = data.stocks?.[ticker];
  if (!stock) return { ticker, found: false, note: '此股票不在 xiaoyu-etf 目前 ETF 持股清單中。' };
  const activeEtfs = new Set((data.etfs || []).filter((e) => e.type === 'active').map((e) => e.code));
  const holders = [...(stock.holders || [])].map((holder) => ({
    ...holder,
    active: activeEtfs.has(holder.etf),
    estimatedNetValueYi: estimateNetValueYi(holder.d1, stock.price),
  }));
  const sortedHolders = holders.sort((a, b) => Math.abs(b.estimatedNetValueYi || 0) - Math.abs(a.estimatedNetValueYi || 0));
  const activeHolders = sortedHolders.filter((holder) => holder.active);
  return {
    ticker,
    found: true,
    stock: {
      code: ticker,
      name: stock.name,
      price: stock.price,
      chg: stock.chg,
      totalLots: stock.tot_lots,
      totalValueYi: stock.tot_value,
      etfCount: stock.etf_count,
      netAmountYi: stock.net_amt,
      streak: stock.streak,
      activeEtfCount: activeHolders.length,
      activeNetLots: sum(activeHolders, 'd1'),
      allNetLots: sum(holders, 'd1'),
      activeEstimatedNetValueYi: round2(sum(activeHolders, 'estimatedNetValueYi')),
      allEstimatedNetValueYi: round2(sum(holders, 'estimatedNetValueYi')),
    },
    topHolders: sortedHolders.slice(0, limit),
    activeHolders: activeHolders.slice(0, limit),
  };
}

async function etfLens(data, args, limit) {
  const code = normalizeCode(args.etf || args.ticker);
  if (!code) throw new Error('xiaoyu-etf etf mode requires etf or ticker');
  const etf = (data.etfs || []).find((item) => item.code === code);
  if (!etf) return { etf: code, found: false, note: '此 ETF 不在 xiaoyu-etf 目前清單中。' };
  const holdings = [...(etf.holdings || [])].sort((a, b) => (b.value || 0) - (a.value || 0));
  const changes = [...(etf.holdings || [])]
    .filter((h) => h.d1)
    .sort((a, b) => Math.abs(b.money || 0) - Math.abs(a.money || 0));
  let detail = null;
  if (args.includeDetail === true || args.includeDetail === 'true') {
    detail = await fetchXiaoyuEtfJson(`data/etf/${code}.json`, args).catch((error) => ({ error: error.message || String(error) }));
  }
  return {
    etf: code,
    found: true,
    summary: {
      code,
      name: etf.name,
      type: etf.type || (code.endsWith('A') ? 'active' : 'etf'),
      date: etf.date,
      updated: etf.updated,
      price: etf.price,
      chg: etf.chg,
      scaleYi: etf.scale,
      scaleChangeYi: etf.scale_chg,
      netBuySellYi: etf.net,
      buyAmountYi: etf.buy_amt,
      sellAmountYi: etf.sell_amt,
      addCount: etf.add_n,
      cutCount: etf.cut_n,
      holdingCount: holdings.filter((h) => h.lots > 0).length,
    },
    topHoldings: holdings.slice(0, limit),
    topChanges: changes.slice(0, limit),
    detail,
  };
}

function rankLens(data, args, limit) {
  const scope = ['active', 'market'].includes(String(args.scope)) ? String(args.scope) : 'active';
  const window = ['d1', 'd5', 'd10', 'd20', 'd60'].includes(String(args.window)) ? String(args.window) : 'd1';
  const direction = String(args.direction || 'buy') === 'sell' ? 'sell' : 'buy';
  const rows = data.rank?.[scope]?.[window]?.[direction] || [];
  return {
    scope,
    window,
    direction,
    rows: rows.slice(0, limit),
    note: scope === 'active'
      ? '台股主動式 ETF 持股推估買賣超，不等同官方投信買賣超。'
      : '全市場已更新 ETF 持股推估買賣超，不等同官方投信買賣超。',
  };
}

function overviewLens(data, limit) {
  const etfs = [...(data.etfs || [])];
  const active = etfs.filter((e) => e.type === 'active');
  return {
    counts: {
      etfTotal: data.meta?.etf_total ?? etfs.length,
      activeCount: data.meta?.active_count ?? active.length,
      activeUpdated: data.meta?.active_updated,
      activeTotal: data.meta?.active_total,
      coverLatest: data.meta?.cover_latest,
      coverFull: data.meta?.cover_full,
      incomplete: data.meta?.incomplete,
      laggingEtfs: data.meta?.lagging_etfs,
    },
    activeByNetBuySell: active
      .filter((e) => e.net != null)
      .sort((a, b) => Math.abs(b.net || 0) - Math.abs(a.net || 0))
      .slice(0, limit)
      .map((e) => ({ code: e.code, name: e.name, netBuySellYi: e.net, scaleYi: e.scale, scaleChangeYi: e.scale_chg, addCount: e.add_n, cutCount: e.cut_n })),
  };
}

export function renderXiaoyuEtfMarkdown(result) {
  const lines = [
    `# Xiaoyu ETF lens${result.mode ? `: ${result.mode}` : ''}`,
    '',
    `- Source: ${result.sourceUrl}`,
    `- Data date: ${result.meta?.latest_slash || result.meta?.latest || '—'}`,
    `- Boundary: ${result.usage}`,
    '',
  ];
  if (result.mode === 'stock') return [...lines, renderStockMarkdown(result)].join('\n');
  if (result.mode === 'etf') return [...lines, renderEtfMarkdown(result)].join('\n');
  if (result.mode === 'overview') return [...lines, renderOverviewMarkdown(result)].join('\n');
  return [...lines, renderRankMarkdown(result)].join('\n');
}

function renderStockMarkdown(result) {
  if (!result.found) return `查無 ${result.ticker}：${result.note}`;
  const s = result.stock;
  return [
    `## ${s.code} ${s.name}`,
    '',
    `- Price: ${s.price ?? '—'} (${signedPct(s.chg)})`,
    `- ETF holders: ${s.etfCount ?? 0} / active ETF holders: ${s.activeEtfCount ?? 0}`,
    `- All ETF net lots: ${signed(s.allNetLots)}；active ETF net lots: ${signed(s.activeNetLots)}`,
    `- Estimated ETF net value: all ${signed(s.allEstimatedNetValueYi)} 億；active ${signed(s.activeEstimatedNetValueYi)} 億`,
    '',
    '### Top ETF holders / flows',
    toMarkdownTable(result.topHolders || [], [
      { label: 'ETF', value: (r) => `${r.etf} ${r.etfname || ''}`.trim() },
      { label: 'Active', value: (r) => (r.active ? 'Y' : '') },
      { label: 'Lots', value: (r) => compactNumber(r.lots) },
      { label: 'Weight%', value: (r) => r.weight ?? '—' },
      { label: 'ΔLots', value: (r) => signed(r.d1) },
      { label: 'Est.億', value: (r) => signed(r.estimatedNetValueYi) },
    ]),
  ].join('\n');
}

function renderEtfMarkdown(result) {
  if (!result.found) return `查無 ${result.etf}：${result.note}`;
  const s = result.summary;
  return [
    `## ${s.code} ${s.name}`,
    '',
    `- Type: ${s.type}；updated: ${s.updated ? 'yes' : 'no'}；date: ${s.date || '—'}`,
    `- Price: ${s.price ?? '—'} (${signedPct(s.chg)})；scale: ${compactNumber(s.scaleYi)} 億`,
    `- Net buy/sell: ${signed(s.netBuySellYi)} 億；adds/cuts: ${s.addCount ?? 0}/${s.cutCount ?? 0}`,
    '',
    '### Top holdings',
    toMarkdownTable(result.topHoldings || [], [
      { label: 'Code', value: (r) => `${r.code} ${r.name || ''}`.trim() },
      { label: 'Weight%', value: (r) => r.weight ?? '—' },
      { label: 'Lots', value: (r) => compactNumber(r.lots) },
      { label: 'Value億', value: (r) => compactNumber(r.value) },
      { label: 'ΔLots', value: (r) => signed(r.d1) },
      { label: 'Δ億', value: (r) => signed(r.money) },
    ]),
    '',
    '### Top daily changes',
    toMarkdownTable(result.topChanges || [], [
      { label: 'Code', value: (r) => `${r.code} ${r.name || ''}`.trim() },
      { label: 'ΔLots', value: (r) => signed(r.d1) },
      { label: 'Δ億', value: (r) => signed(r.money) },
      { label: 'Chg%', value: (r) => signedPct(r.chg) },
      { label: 'New/Clear', value: (r) => (r.new ? 'new' : r.clear ? 'clear' : '') },
    ]),
  ].join('\n');
}

function renderRankMarkdown(result) {
  return [
    `## ETF inferred ${result.direction} rank`,
    '',
    `- Scope: ${result.scope}；window: ${result.window}`,
    `- Note: ${result.note}`,
    '',
    toMarkdownTable(result.rows || [], [
      { label: 'Code', value: (r) => `${r.code} ${r.name || ''}`.trim() },
      { label: 'Lots', value: (r) => signed(r.lots) },
      { label: 'Money億', value: (r) => signed(r.money) },
      { label: 'ETF count', value: (r) => r.etf_count ?? '—' },
      { label: 'Chg%', value: (r) => signedPct(r.chg) },
      { label: 'Main ETFs', value: (r) => (r.etfs || []).slice(0, 3).map((e) => `${e.etf}:${signed(e.d1)}`).join(', ') },
    ]),
  ].join('\n');
}

function renderOverviewMarkdown(result) {
  return [
    '## Coverage',
    '',
    `- ETFs: ${result.counts.etfTotal ?? '—'}；active: ${result.counts.activeCount ?? '—'}；active updated: ${result.counts.activeUpdated ?? '—'}/${result.counts.activeTotal ?? '—'}`,
    `- Latest coverage: ${result.counts.coverLatest ?? '—'}；full coverage: ${result.counts.coverFull ?? '—'}；incomplete: ${result.counts.incomplete ? 'yes' : 'no'}`,
    '',
    '### Active ETFs by absolute net buy/sell',
    toMarkdownTable(result.activeByNetBuySell || [], [
      { label: 'ETF', value: (r) => `${r.code} ${r.name || ''}`.trim() },
      { label: 'Net億', value: (r) => signed(r.netBuySellYi) },
      { label: 'Scale億', value: (r) => compactNumber(r.scaleYi) },
      { label: 'ScaleΔ億', value: (r) => signed(r.scaleChangeYi) },
      { label: 'Adds/Cuts', value: (r) => `${r.addCount ?? 0}/${r.cutCount ?? 0}` },
    ]),
  ].join('\n');
}

function normalizeCode(value) {
  return String(value || '').trim().toUpperCase();
}

function estimateNetValueYi(lots, price) {
  if (!Number.isFinite(Number(lots)) || !Number.isFinite(Number(price))) return null;
  return round2((Number(lots) * Number(price) * 1000) / 100000000);
}

function sum(rows, key) {
  return rows.reduce((total, row) => total + (Number(row?.[key]) || 0), 0);
}

function round2(value) {
  if (!Number.isFinite(Number(value))) return value == null ? null : value;
  return Math.round(Number(value) * 100) / 100;
}

function signed(value) {
  if (value == null || value === '') return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return `${n > 0 ? '+' : ''}${compactNumber(round2(n))}`;
}

function signedPct(value) {
  if (value == null || value === '') return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return `${n > 0 ? '+' : ''}${round2(n)}%`;
}
