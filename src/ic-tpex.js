export const IC_TPEX_BASE_URL = 'https://ic.tpex.org.tw';

function stripTags(html = '') {
  return decodeHtml(String(html)
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim());
}

function decodeHtml(text = '') {
  return String(text)
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}

function normalizeCode(value) {
  return String(value || '').trim().toUpperCase();
}

async function fetchText(url) {
  const response = await fetch(url, { headers: { 'User-Agent': 'codex-finance-tools/0.1' } });
  if (!response.ok) throw new Error(`ic.tpex request failed: ${response.status} ${url}`);
  return response.text();
}

function parseTitle(html) {
  const h3 = String(html).match(/<h3[^>]*>([\s\S]*?)<\/h3>/i)?.[1];
  if (h3) return stripTags(h3);
  return stripTags(String(html).match(/###\s*([^<\n]+)/)?.[1] || '');
}

function parseCompanies(html) {
  const companies = [];
  const seen = new Set();
  const re = /<a\b[^>]*href=["'][^"']*stk_code=([0-9A-Za-z]+)[^"']*["'][^>]*>([\s\S]*?)<\/a>/gi;
  for (const match of String(html).matchAll(re)) {
    const code = normalizeCode(match[1]);
    const name = stripTags(match[2]);
    if (!/^\d{4,6}$/.test(code) || !name || seen.has(code)) continue;
    seen.add(code);
    companies.push({ code, name });
  }
  return companies;
}

function parseIcFromCompanyChain(html) {
  return String(html).match(/introduce\.php\?ic=([0-9A-Za-z]+)&stk_code=/i)?.[1]?.toUpperCase()
    || String(html).match(/introduce\.php\?ic=([0-9A-Za-z]+)/i)?.[1]?.toUpperCase()
    || undefined;
}

export async function getIcTpexCategory({ ic = 'D000' } = {}) {
  const code = normalizeCode(ic || 'D000');
  const url = `${IC_TPEX_BASE_URL}/introduce.php?ic=${encodeURIComponent(code)}`;
  const html = await fetchText(url);
  return {
    source: 'ic.tpex',
    url,
    ic: code,
    title: parseTitle(html),
    companies: parseCompanies(html),
    text: stripTags(html).slice(0, 4000),
    disclaimer: 'Official TPEx/TWSE industry-value-chain classification only; not realtime price, not actual supplier-chain proof, and company-level data may be self-reported.',
  };
}

export async function getIcTpexCompanyChain({ ticker } = {}) {
  const code = normalizeCode(ticker);
  if (!code) throw new Error('getIcTpexCompanyChain requires ticker');
  const url = `${IC_TPEX_BASE_URL}/company_chain.php?stk_code=${encodeURIComponent(code)}`;
  const html = await fetchText(url);
  return {
    source: 'ic.tpex',
    url,
    ticker: code,
    ic: parseIcFromCompanyChain(html),
    title: parseTitle(html),
    companies: parseCompanies(html),
    text: stripTags(html).slice(0, 4000),
    disclaimer: 'Official TPEx/TWSE industry-value-chain classification only; use Shioaji for prices, volume, and K-bars.',
  };
}
