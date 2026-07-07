import { readFile } from 'node:fs/promises';
import { compactNumber, toMarkdownTable } from './format.js';
import { getFugleCandles } from './taiwan-market.js';

const DEFAULT_AUCTION_PULL_THRESHOLD_PCT = 0.5;

function num(value) {
  if (value === null || value === undefined || value === '' || value === true) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function present(value) {
  return value !== undefined && value !== null && value !== '';
}

function pct(value) {
  const n = num(value);
  if (n === undefined) return '—';
  return `${n.toFixed(2)}%`;
}

function signed(value) {
  const n = num(value);
  if (n === undefined) return '—';
  return n > 0 ? `+${compactNumber(n)}` : compactNumber(n);
}

function judgementLabel(value) {
  return ({ bullish: '偏多', bearish: '偏空', neutral: '中性', missing: '資料不足' })[value] || value || '資料不足';
}

function environmentLabel(value) {
  return ({ bullish: '偏多', bearish: '偏空', neutral: '中性', conflict: '訊號矛盾', insufficient: '資料不足' })[value] || value || '資料不足';
}

function actionLabel(value) {
  return ({ observe: '觀察', exclude: '排除/降低優先', insufficient: '資料不足' })[value] || value || '資料不足';
}

export function parseUsMoves(value) {
  if (!value) return {};
  if (typeof value === 'object' && !Array.isArray(value)) return value;
  const text = String(value).trim();
  if (!text) return {};
  if (text.startsWith('{')) {
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('usMoves must be a JSON object or comma-separated key=value list');
    }
    return parsed;
  }
  return Object.fromEntries(text.split(',').map((part) => {
    const [key, raw] = part.split('=').map((s) => s.trim());
    return key ? [key, num(raw)] : null;
  }).filter(Boolean));
}

function parseJsonArray(value, label) {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  try {
    const parsed = JSON.parse(String(value));
    if (!Array.isArray(parsed)) throw new Error(`${label} must be a JSON array`);
    return parsed;
  } catch (error) {
    throw new Error(`${label} JSON parse failed: ${error.message}`);
  }
}

function parseTickerList(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  return String(value)
    .split(/[,，\s]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

async function readJsonArrayFile(path, label) {
  if (!path) return [];
  const text = await readFile(path, 'utf8');
  return parseJsonArray(text, label);
}

function normalizeNetLots(values) {
  if (!Array.isArray(values)) return [];
  return values.map(num).filter((value) => value !== undefined);
}

function analyzeFx(fx = {}) {
  const previousClose = num(fx.previousClose);
  const current = num(fx.current);
  if (previousClose === undefined || current === undefined) {
    return {
      previousClose,
      current,
      change: undefined,
      judgement: 'missing',
      basis: '缺前一交易日下午收盤或今日早盤報價，不補造匯率方向。',
    };
  }
  const change = current - previousClose;
  if (change <= -0.1) {
    return { previousClose, current, change, judgement: 'bullish', basis: '新台幣兌美元明顯升值約 0.1 元以上，權值股環境相對有利。' };
  }
  if (change >= 0.1) {
    return { previousClose, current, change, judgement: 'bearish', basis: '新台幣兌美元明顯貶值，操作態度應保守。' };
  }
  return { previousClose, current, change, judgement: 'neutral', basis: '匯率接近平盤，需回到個股籌碼、期貨與試撮判斷。' };
}

function analyzeFutures(futures = {}, month = new Date().getMonth() + 1) {
  const nightClose = num(futures.nightClose);
  const change = num(futures.change);
  const volume = num(futures.volume);
  const previousSpotClose = num(futures.previousSpotClose);
  const basis = nightClose !== undefined && previousSpotClose !== undefined ? nightClose - previousSpotClose : undefined;
  const exDividendCaveat = [6, 7, 8].includes(Number(month)) && basis !== undefined && basis <= -100 && basis >= -300;
  if (nightClose === undefined || previousSpotClose === undefined) {
    return {
      nightClose,
      change,
      volume,
      previousSpotClose,
      basis,
      exDividendCaveat: false,
      judgement: 'missing',
      basisText: '缺台指期夜盤或前一日現貨收盤，無法計算期現貨價差。',
    };
  }
  if (basis > 100) {
    return { nightClose, change, volume, previousSpotClose, basis, exDividendCaveat: false, judgement: 'bullish', basisText: '台指期夜盤明顯正價差超過 100 點，台股開高機率提高。' };
  }
  if (basis < -100) {
    if (exDividendCaveat) {
      return { nightClose, change, volume, previousSpotClose, basis, exDividendCaveat, judgement: 'neutral', basisText: '6～8 月除息旺季，逆價差 100～300 點可能受除息影響，不能單獨判定明顯偏空。' };
    }
    return { nightClose, change, volume, previousSpotClose, basis, exDividendCaveat: false, judgement: 'bearish', basisText: '台指期夜盤明顯逆價差超過 100 點，台股開低機率提高。' };
  }
  return { nightClose, change, volume, previousSpotClose, basis, exDividendCaveat: false, judgement: 'neutral', basisText: '期現貨價差未達 ±100 點，期貨結構未提供明確方向。' };
}

function analyzeRelativeStrength(usMarket = {}, futuresResult = {}) {
  const moves = Object.values(usMarket).map(num).filter((value) => value !== undefined);
  if (!moves.length || futuresResult.judgement === 'missing') {
    return { state: 'missing', chaseAllowed: false, basis: '缺美股主要指數或台指期夜盤反應，無法判斷相對強弱。' };
  }
  const avg = moves.reduce((sum, value) => sum + value, 0) / moves.length;
  const max = Math.max(...moves);
  if (max >= 1 && futuresResult.judgement !== 'bullish') {
    return { state: 'taiwan_weaker_than_us', chaseAllowed: false, basis: '美股明顯上漲但台指期未同步偏強，台股相對弱於美股，禁止開盤直接追高。' };
  }
  if (avg <= -1 && futuresResult.judgement !== 'bearish') {
    return { state: 'taiwan_resilient', chaseAllowed: false, basis: '美股明顯下跌但台指期未明顯偏空，可標記相對抗跌，但不得直接推導為買入訊號。' };
  }
  return { state: 'aligned', chaseAllowed: false, basis: '美股與台指期反應大致一致；仍需等待正式開盤確認，不開放無條件追價。' };
}

function analyzeBranch(row = {}) {
  const recentDailyNetLots = normalizeNetLots(row.dailyNetLots ?? row.netLots ?? row.recentNetLots).slice(-5);
  const dailyNetLots = recentDailyNetLots;
  const observationDays = dailyNetLots.length;
  if (observationDays < 5) {
    return { ...row, dailyNetLots, observationDays, cumulativeNetLots: dailyNetLots.reduce((a, b) => a + b, 0), consecutiveBuy: false, increasing: false, turnedSell: false, action: 'insufficient', basis: '分點資料不足 5 個交易日。' };
  }
  const consecutiveBuy = dailyNetLots.every((value) => value > 0);
  const consecutiveSell = dailyNetLots.every((value) => value < 0);
  const increasing = dailyNetLots.every((value, index) => index === 0 || value > dailyNetLots[index - 1]);
  const turnedSell = dailyNetLots.slice(-2).some((value) => value < 0) && dailyNetLots.slice(0, 3).some((value) => value > 0);
  const cumulativeNetLots = dailyNetLots.reduce((a, b) => a + b, 0);
  let action = 'insufficient';
  let basis = '分點訊號不完整，降低權重。';
  if (consecutiveBuy && increasing && !turnedSell) {
    action = 'observe';
    basis = '最近 5 日連續買超、買超量逐日增加，且尚未轉賣。';
  } else if (turnedSell || consecutiveSell || (dailyNetLots.at(-1) ?? 0) < 0) {
    action = 'exclude';
    basis = '原本買超分點開始轉賣或最近賣超，排除或降低優先順序。';
  }
  return { ...row, dailyNetLots, observationDays, cumulativeNetLots, consecutiveBuy, consecutiveSell, increasing, turnedSell, action, basis };
}

function analyzeAuction(row = {}, thresholdPct = DEFAULT_AUCTION_PULL_THRESHOLD_PCT) {
  const price858 = num(row.price858);
  const price859 = num(row.price859);
  const open = num(row.open);
  if (price858 === undefined || price859 === undefined || open === undefined) {
    return { ...row, price858, price859, open, lastMinuteChange: undefined, lastMinuteChangePct: undefined, state: 'insufficient', basis: '缺 8:58、8:59 或正式開盤價，試撮資料不足。' };
  }
  const lastMinuteChange = price859 - price858;
  const lastMinuteChangePct = price858 ? (lastMinuteChange / price858) * 100 : undefined;
  if (lastMinuteChangePct !== undefined && lastMinuteChangePct >= thresholdPct) {
    return { ...row, price858, price859, open, lastMinuteChange, lastMinuteChangePct, state: 'last_minute_pull_up', basis: '最後一分鐘突然拉高，存在開高回落風險，禁止追開盤第一波。' };
  }
  if (lastMinuteChangePct !== undefined && lastMinuteChangePct <= -thresholdPct) {
    const held = open >= price859;
    return { ...row, price858, price859, open, lastMinuteChange, lastMinuteChangePct, state: held ? 'last_minute_press_down_held' : 'last_minute_press_down_failed', basis: held ? '最後一分鐘壓低但開盤後未延續下跌，下方可能有承接跡象。' : '最後一分鐘壓低且開盤延續偏弱，等待正式盤確認。' };
  }
  return { ...row, price858, price859, open, lastMinuteChange, lastMinuteChangePct, state: 'stable', basis: '最後一分鐘未出現明顯拉高或壓低。' };
}

function countJudgements(values, target) {
  return values.filter((value) => value === target).length;
}

function summarize({ fx, futures, relativeStrength, branches, auctions, completeness, watchlist = [] }) {
  const requiredJudgements = [fx.judgement, futures.judgement];
  const bullish = countJudgements(requiredJudgements, 'bullish');
  const bearish = countJudgements(requiredJudgements, 'bearish');
  const hasMissing = completeness.status !== 'complete';
  const branchObserve = branches.filter((row) => row.action === 'observe').map((row) => row.ticker).filter(Boolean);
  const branchExclude = branches.filter((row) => row.action === 'exclude').map((row) => row.ticker).filter(Boolean);
  const auctionPullUp = auctions.some((row) => row.state === 'last_minute_pull_up');
  const relativeWeak = relativeStrength.state === 'taiwan_weaker_than_us';
  const branchBearish = branchExclude.length > 0;

  let marketEnvironment = 'neutral';
  if (hasMissing) marketEnvironment = 'insufficient';
  if (!hasMissing && bullish >= 2 && !relativeWeak && !auctionPullUp && !branchBearish) marketEnvironment = 'bullish';
  if (!hasMissing && bearish >= 2) marketEnvironment = 'bearish';
  if (!hasMissing && ((bullish > 0 && bearish > 0) || relativeWeak || auctionPullUp || branchBearish)) marketEnvironment = 'conflict';

  const cancelConditions = [
    '正式開盤後無法延續盤前方向，跌破開盤價且量能放大。',
  ];
  if (relativeWeak) cancelConditions.push('美股強但台指期反應弱，禁止開盤追高。');
  if (auctionPullUp) cancelConditions.push('試撮最後一分鐘拉高，禁止追開盤第一波。');
  if (branchBearish) cancelConditions.push('候選股關鍵分點轉賣或連續賣超，排除或降低優先。');

  const researchAdvice = marketEnvironment === 'bullish'
    ? '環境偏多，但本流程仍只允許觀察與等待正式開盤確認；若開太高不追第一波。'
    : marketEnvironment === 'bearish'
      ? '環境偏空，降低追價與持倉積極度，先看風控與減碼。'
      : marketEnvironment === 'conflict'
        ? '訊號矛盾，不追價，等待 9:00 後價格與量能確認。'
        : marketEnvironment === 'insufficient'
          ? '資料不足，不補造結論；只能產出部分盤前雷達。'
          : '環境中性，回到個股籌碼、期貨與正式開盤結構判斷。';

  return {
    marketEnvironment,
    riskLevel: marketEnvironment === 'bullish' ? 'medium' : marketEnvironment === 'bearish' ? 'high' : 'medium_high',
    weightStockEnvironment: fx.judgement === 'bullish' && futures.judgement === 'bullish' ? '相對有利' : fx.judgement === 'bearish' || futures.judgement === 'bearish' ? '保守' : '中性/待確認',
    allowOpenChase: false,
    chaseRestriction: '禁止無條件開盤追價；需等待正式開盤延續與量價確認。',
    observeTickers: [...new Set([...branchObserve, ...watchlist])],
    excludeTickers: [...new Set(branchExclude)],
    cancelConditions,
    researchAdvice,
  };
}

function completenessOf({ fx, futures, usMarket, branches, auctions }) {
  const missing = [];
  if (fx.judgement === 'missing') missing.push('新台幣匯率');
  if (futures.judgement === 'missing') missing.push('台指期夜盤/期現貨價差');
  if (!Object.values(usMarket || {}).map(num).some((value) => value !== undefined)) missing.push('美股主要指數');
  if (!branches.length || branches.some((row) => row.action === 'insufficient')) missing.push('候選股最近 5 日分點');
  if (!auctions.length || auctions.some((row) => row.state === 'insufficient')) missing.push('8:58～9:00 集合競價');
  return { status: missing.length ? 'partial' : 'complete', missing: [...new Set(missing)] };
}

export function analyzePreopenWorkflow(input = {}) {
  const date = input.date || new Date().toISOString().slice(0, 10);
  const month = Number(input.month || String(date).slice(5, 7) || new Date().getMonth() + 1);
  const watchlist = parseTickerList(input.watchlist);
  const fx = analyzeFx(input.fx || {});
  const futures = analyzeFutures(input.futures || {}, month);
  const usMarket = parseUsMoves(input.usMarket);
  const relativeStrength = analyzeRelativeStrength(usMarket, futures);
  const branches = (input.branches || []).map(analyzeBranch);
  const auctions = (input.auctions || []).map((row) => analyzeAuction(row, input.auctionThresholdPct));
  const completeness = completenessOf({ fx, futures, usMarket, branches, auctions });
  const summary = summarize({ fx, futures, relativeStrength, branches, auctions, completeness, watchlist });
  return {
    workflow: 'taiwan-preopen-30min',
    prompt: '盤前流程',
    date,
    updateTime: input.updateTime || new Date().toISOString(),
    watchlist,
    completeness,
    fx,
    futures,
    usMarket,
    relativeStrength,
    branches,
    auctions,
    summary,
    boundaries: [
      '依使用者提供的台股盤前 30 分鐘拆解流程輸出觀察報告。',
      '不得因單一匯率、期貨價差、分點或試撮訊號生成無條件下單指令。',
      '資料不足時必須標示，不得補造。',
    ],
  };
}

export async function tryFetchPreviousSpotClose(args, effectiveDate, fetchCandles = getFugleCandles) {
  if (args.noFetch || args['no-fetch']) return undefined;
  if (args.previousSpotClose !== undefined) return num(args.previousSpotClose);
  try {
    const result = await fetchCandles({ ticker: 'IX0001', scope: 'historical', timeframe: 'D', from: args.spotFrom, to: effectiveDate, limit: 5 });
    const rows = Array.isArray(result.data) ? result.data : [];
    const sorted = [...rows].sort((a, b) => String(b.date).localeCompare(String(a.date)));
    const previous = sorted.find((row) => row.date !== effectiveDate) || sorted[1];
    return num(previous?.close);
  } catch {
    return undefined;
  }
}

export async function buildPreopenBrief(args = {}) {
  const effectiveDate = args.date || new Date().toISOString().slice(0, 10);
  const branches = [
    ...parseJsonArray(args.branchData, 'branchData'),
    ...await readJsonArrayFile(args.branchFile, 'branchFile'),
  ];
  const auctions = [
    ...parseJsonArray(args.auctionData, 'auctionData'),
    ...await readJsonArrayFile(args.auctionFile, 'auctionFile'),
  ];
  const previousSpotClose = num(args.previousSpotClose) ?? await tryFetchPreviousSpotClose(args, effectiveDate);
  return analyzePreopenWorkflow({
    date: effectiveDate,
    updateTime: args.updateTime,
    month: args.month,
    watchlist: args.watchlist,
    fx: { previousClose: args.fxPreviousClose, current: args.fxCurrent },
    futures: {
      nightClose: args.futureClose,
      change: args.futureChange,
      volume: args.futureVolume,
      previousSpotClose,
    },
    usMarket: parseUsMoves(args.usMoves),
    branches,
    auctions,
    auctionThresholdPct: args.auctionThresholdPct,
  });
}

function renderDataCompleteness(completeness) {
  if (completeness.status === 'complete') return '完整';
  return `部分缺失（${completeness.missing.join('、') || '未明'}）`;
}

export function renderPreopenBriefMarkdown(result) {
  const branchRows = result.branches.map((row) => ({
    stock: `${row.ticker || '—'} ${row.name || ''}`.trim(),
    branch: row.branch || '—',
    daily: row.dailyNetLots?.join(', ') || '—',
    consecutiveBuy: row.consecutiveBuy ? '是' : '否',
    increasing: row.increasing ? '是' : '否',
    turnedSell: row.turnedSell ? '是' : '否',
    action: actionLabel(row.action),
  }));
  const auctionLines = result.auctions.length ? result.auctions.map((row) => [
    `- ${row.ticker || '—'}：8:58=${row.price858 ?? '—'}，8:59=${row.price859 ?? '—'}，開盤=${row.open ?? '—'}，最後一分鐘=${signed(row.lastMinuteChange)} / ${pct(row.lastMinuteChangePct)}，判斷=${row.basis}`,
  ].join('')) : ['- 資料不足：未提供 8:58、8:59、開盤價。'];

  return [
    '# 今日台股盤前報告',
    '',
    '## 基本資料',
    '',
    `- 日期：${result.date}`,
    `- 資料更新時間：${result.updateTime}`,
    `- 資料完整性：${renderDataCompleteness(result.completeness)}`,
    '',
    '## 一、新台幣匯率',
    '',
    `- 前一交易日下午收盤：${result.fx.previousClose ?? '—'}`,
    `- 今日早盤報價：${result.fx.current ?? '—'}`,
    `- 升貶幅：${signed(result.fx.change)}`,
    `- 判斷：${judgementLabel(result.fx.judgement)}`,
    `- 依據：${result.fx.basis}`,
    '',
    '## 二、台指期夜盤',
    '',
    `- 夜盤收盤：${result.futures.nightClose ?? '—'}`,
    `- 漲跌點數：${signed(result.futures.change)}`,
    `- 成交量：${compactNumber(result.futures.volume)}`,
    `- 與現貨價差：${signed(result.futures.basis)}`,
    `- 是否處於 6～8 月除息期間：${result.futures.exDividendCaveat ? '是，逆價差可能受除息影響' : '否或未觸發例外'}`,
    `- 判斷：${judgementLabel(result.futures.judgement)}`,
    `- 依據：${result.futures.basisText}`,
    '',
    '## 三、美股與台股相對強弱',
    '',
    `- 美股主要指數表現：${Object.entries(result.usMarket || {}).map(([key, value]) => `${key} ${signed(value)}%`).join('、') || '—'}`,
    `- 台指期夜盤反應：${judgementLabel(result.futures.judgement)}`,
    `- 相對強弱：${result.relativeStrength.basis}`,
    `- 是否適合追高：否`,
    `- 依據：${result.relativeStrength.basis}`,
    '',
    '## 四、個股分點觀察',
    '',
    branchRows.length ? toMarkdownTable(branchRows, [
      { label: '股票', value: (r) => r.stock },
      { label: '分點', value: (r) => r.branch },
      { label: '最近 5 日買賣超', value: (r) => r.daily },
      { label: '是否連續買超', value: (r) => r.consecutiveBuy },
      { label: '是否增加', value: (r) => r.increasing },
      { label: '是否轉賣', value: (r) => r.turnedSell },
      { label: '處理', value: (r) => r.action },
    ]) : '_資料不足：未提供候選股票最近 5 日分點買賣超。_',
    '',
    '## 五、集合競價',
    '',
    ...auctionLines,
    '',
    '## 六、綜合結論',
    '',
    `- 市場環境：${environmentLabel(result.summary.marketEnvironment)}`,
    `- 權值股環境：${result.summary.weightStockEnvironment}`,
    `- 追價限制：${result.summary.chaseRestriction}`,
    `- 今日觀察股票：${result.summary.observeTickers.join(', ') || '—'}`,
    `- 今日排除股票：${result.summary.excludeTickers.join(', ') || '—'}`,
    `- 主要風險：${result.summary.cancelConditions.join('；')}`,
    `- 尚缺資料：${result.completeness.missing.join('、') || '—'}`,
    `- Research 建議：${result.summary.researchAdvice}`,
    '',
    '## 七、執行原則',
    '',
    `- 是否允許開盤追價：${result.summary.allowOpenChase ? '是' : '否'}`,
    '- 是否需要等待開盤確認：是，正式開盤後必須確認價格是否延續。',
    `- 觸發取消交易的條件：${result.summary.cancelConditions.join('；')}`,
    '',
    '資料邊界：本報告只依「台股盤前 30 分鐘拆解流程」產生觀察與風險分類；不因單一資料點給出無條件下單指令，資料不足時不補造。',
  ].join('\n');
}
