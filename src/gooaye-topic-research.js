const DEFAULT_RSS_URL = 'https://feeds.soundon.fm/podcasts/954689a5-3096-43a4-a80b-7810b219cef3.xml';
const DEFAULT_RESEARCH_MANIFEST_URL = 'https://gooaye.teamtaiwan.win/content-manifest.json';
const DEFAULT_RESEARCH_BASE_URL = 'https://gooaye.teamtaiwan.win/';
const GENERIC_TAGS = new Set(['股癌', 'gooaye', 'podcast', '台股']);

export async function runGooayeTopicResearch(args = {}, deps = {}) {
  const fetchFn = deps.fetchFn || globalThis.fetch;
  if (typeof fetchFn !== 'function') throw new Error('fetch is unavailable');

  const rssUrl = args.rssUrl || DEFAULT_RSS_URL;
  const manifestUrl = args.manifestUrl || DEFAULT_RESEARCH_MANIFEST_URL;
  const asOfDate = normalizeDate(args.date || args.asOfDate || new Date().toISOString().slice(0, 10));
  const requestedTickers = normalizeTickers(args.tickers || args.ticker);

  const timeoutMs = positiveTimeout(args.timeoutMs, 15_000);
  const rssText = await fetchText(fetchFn, rssUrl, 'Gooaye official RSS', timeoutMs);
  const episodes = parseRssEpisodes(rssText);
  const episode = episodes.find((row) => row.date <= asOfDate);
  if (!episode) {
    return {
      status: 'unavailable',
      asOfDate,
      pointInTime: true,
      readOnly: true,
      requestedTickers,
      episode: null,
      research: null,
      reason: 'No official Gooaye episode was published by the requested as-of date.',
      sourceOrder: ['official_soundon_rss', 'public_research_manifest'],
    };
  }

  const manifest = await fetchJson(fetchFn, manifestUrl, 'Gooaye research manifest', timeoutMs);
  const researchItems = (Array.isArray(manifest?.items) ? manifest.items : [])
    .filter(isGooayeResearch)
    .map(normalizeResearchItem)
    .filter((item) => item.date && item.url && item.date <= asOfDate && item.episodeNumber <= episode.number)
    .sort((a, b) => b.episodeNumber - a.episodeNumber || b.date.localeCompare(a.date));
  const researchItem = researchItems[0] || null;
  const matchingEpisode = researchItem?.episodeNumber === episode.number;

  return {
    status: matchingEpisode ? 'ready' : researchItem ? 'stale' : 'transcript_missing',
    asOfDate,
    pointInTime: true,
    readOnly: true,
    requestedTickers,
    episode: {
      number: episode.number,
      title: episode.title,
      guid: episode.guid,
      pubDate: episode.date,
      officialPubDate: episode.pubDate,
    },
    research: researchItem ? {
      episodeNumber: researchItem.episodeNumber,
      title: researchItem.title,
      description: researchItem.description,
      date: researchItem.date,
      themes: researchItem.tags.filter((tag) => !GENERIC_TAGS.has(tag.toLowerCase())),
      url: new URL(researchItem.url, DEFAULT_RESEARCH_BASE_URL).href,
    } : null,
    reason: matchingEpisode
      ? 'Official episode and public research artifact match.'
      : researchItem
        ? `Latest point-in-time research is EP${researchItem.episodeNumber}, behind official EP${episode.number}.`
        : `No point-in-time research artifact is available for official EP${episode.number}.`,
    fallbackRequired: !matchingEpisode,
    sourceOrder: ['official_soundon_rss', 'public_research_manifest'],
    boundaries: [
      'Gooaye is an external topic-confidence source and cannot change Phase 3 technical eligibility.',
      'This tool performs read-only HTTP retrieval and never invokes an order API.',
    ],
  };
}

export function renderGooayeTopicResearchMarkdown(result) {
  const research = result.research;
  return [
    '# Gooaye topic research',
    '',
    `Status: ${result.status || 'unavailable'}`,
    `As of: ${result.asOfDate || '—'}`,
    `Official episode: ${result.episode ? `EP${result.episode.number} (${result.episode.pubDate})` : '—'}`,
    `Research artifact: ${research?.title || '—'}`,
    `Research date: ${research?.date || '—'}`,
    `Themes: ${(research?.themes || []).join(', ') || '—'}`,
    `Source: ${research?.url || '—'}`,
    `Reason: ${result.reason || '—'}`,
    '',
    ...(result.boundaries || []).map((line) => `- ${line}`),
  ].join('\n');
}

function parseRssEpisodes(xml) {
  const items = String(xml || '').match(/<item>[\s\S]*?<\/item>/gi) || [];
  return items.map((item) => {
    const title = decodeXml(readXmlValue(item, 'title'));
    const pubDate = decodeXml(readXmlValue(item, 'pubDate'));
    return {
      number: episodeNumber(title),
      title,
      guid: decodeXml(readXmlValue(item, 'guid')),
      pubDate,
      date: normalizeDate(pubDate),
    };
  }).filter((item) => Number.isFinite(item.number) && item.date)
    .sort((a, b) => b.date.localeCompare(a.date) || b.number - a.number);
}

function readXmlValue(text, tag) {
  const match = String(text).match(new RegExp(`<${tag}(?:\\s[^>]*)?>([\\s\\S]*?)<\\/${tag}>`, 'i'));
  return match?.[1]?.replace(/^<!\[CDATA\[|\]\]>$/g, '').trim() || '';
}

function decodeXml(value) {
  return String(value || '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'");
}

function isGooayeResearch(item) {
  const text = [item?.id, item?.title, item?.description, ...(item?.tags || [])].join(' ').toLowerCase();
  return text.includes('股癌') || text.includes('gooaye');
}

function normalizeResearchItem(item) {
  return {
    title: String(item?.title || ''),
    description: String(item?.description || ''),
    date: normalizeDate(item?.date),
    tags: Array.isArray(item?.tags) ? item.tags.map(String).filter(Boolean) : [],
    url: String(item?.url || ''),
    episodeNumber: episodeNumber([item?.id, item?.title, item?.description].join(' ')),
  };
}

function episodeNumber(value) {
  const match = String(value || '').match(/\bEP\s*(\d+)\b/i);
  return match ? Number(match[1]) : Number.NEGATIVE_INFINITY;
}

function normalizeDate(value) {
  const text = String(value || '').trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return '';
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Taipei',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(parsed).reduce((acc, part) => ({ ...acc, [part.type]: part.value }), {});
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function normalizeTickers(value) {
  const items = Array.isArray(value) ? value : String(value || '').split(',');
  return [...new Set(items.map((item) => String(item || '').trim().toUpperCase()).filter(Boolean))];
}

async function fetchText(fetchFn, url, label, timeoutMs) {
  const response = await fetchFn(url, {
    headers: { accept: 'application/xml,text/xml,text/plain;q=0.9,*/*;q=0.1' },
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!response?.ok) throw new Error(`${label} failed (${response?.status || 'unknown'})`);
  return response.text();
}

async function fetchJson(fetchFn, url, label, timeoutMs) {
  const response = await fetchFn(url, {
    headers: { accept: 'application/json' },
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!response?.ok) throw new Error(`${label} failed (${response?.status || 'unknown'})`);
  return response.json();
}

function positiveTimeout(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? Math.min(number, 60_000) : fallback;
}
