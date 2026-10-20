#!/usr/bin/env node
/** Standalone public newsletter collector. No external packages or sibling skills. */
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const SOURCES = [
  { id: 'rundown', name: 'The Rundown AI', entry: 'https://rss.beehiiv.com/feeds/2R3C6Bt5wj.xml', strategy: 'rss_full_content' },
  { id: 'tldr', name: 'TLDR AI', entry: 'https://tldr.tech/ai/archives', strategy: 'official_archive' },
  { id: 'superhuman', name: 'Superhuman AI', entry: 'https://www.superhuman.ai/', strategy: 'official_home' },
];

// A supplied date selects source material, rather than merely relabelling today.
// Keep this shared policy in the package so both independent branches agree.
export function resolveSelection({ date, timezone = 'Asia/Shanghai', mode = date ? 'as-of' : 'latest', now = new Date() } = {}) {
  if (!['latest', 'as-of'].includes(mode)) throw new Error('mode must be latest or as-of');
  const formatter = new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' });
  if (mode === 'as-of' && !date) throw new Error('as-of mode requires --date YYYY-MM-DD');
  date ||= formatter.format(now);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || Number.isNaN(Date.parse(`${date}T00:00:00Z`)) || new Date(`${date}T00:00:00Z`).toISOString().slice(0, 10) !== date)
    throw new Error('date must be a real YYYY-MM-DD calendar date');
  const nextDate = new Date(Date.parse(`${date}T00:00:00Z`) + 86400000).toISOString().slice(0, 10);
  return { mode, date, timezone, cutoff_exclusive: mode === 'as-of' ? new Date(zonedMidnight(nextDate, timezone)).toISOString() : null, ...(mode === 'latest' ? { checked_at: now.toISOString() } : {}) };
}
function zonedMidnight(date, timezone) {
  const nominal = Date.parse(`${date}T00:00:00Z`);
  const fmt = new Intl.DateTimeFormat('en-US', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
  let time = nominal;
  for (let n = 0; n < 4; n++) {
    const parts = Object.fromEntries(fmt.formatToParts(new Date(time)).map(p => [p.type, p.value]));
    const local = Date.parse(`${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}Z`);
    const adjusted = time + nominal - local;
    if (adjusted === time) return time;
    time = adjusted;
  }
  throw new Error('Cannot resolve local midnight for timezone');
}
export function publicationTime(value, selection) {
  if (typeof value !== 'string' || !value.trim()) return NaN;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    try { resolveSelection({ date: value }); return zonedMidnight(value, selection.timezone); } catch { return NaN; }
  }
  // ISO datetimes without a timezone must never depend on the execution host.
  if (/^\d{4}-\d{2}-\d{2}T/.test(value) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(value)) return NaN;
  return Date.parse(value);
}
export function selectIssue(candidates, selection) {
  const eligible = candidates.filter(c => Number.isFinite(publicationTime(c.published_at, selection)) &&
    (selection.mode === 'as-of' ? publicationTime(c.published_at, selection) < Date.parse(selection.cutoff_exclusive)
      : publicationTime(c.published_at, selection) <= Date.parse(selection.checked_at)));
  eligible.sort((a, b) => publicationTime(b.published_at, selection) - publicationTime(a.published_at, selection));
  return eligible[0] || null;
}
const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', ndash: '–', mdash: '—', rsquo: '’', lsquo: '‘', rdquo: '”', ldquo: '“', hellip: '…', bull: '•' };
function decode(s = '') {
  return String(s).replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (whole, e) => {
    if (e[0] !== '#') return ENTITIES[e.toLowerCase()] ?? whole;
    const n = e[1].toLowerCase() === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
    return Number.isFinite(n) && n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : whole;
  });
}
function attrs(tag) {
  const out = {};
  for (const m of tag.matchAll(/([:\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/g)) out[m[1].toLowerCase()] = decode(m[2] ?? m[3] ?? m[4]);
  return out;
}
function absolute(value, base) {
  try { const u = new URL(value, base); return /^https?:$/.test(u.protocol) ? u.href : null; } catch { return null; }
}
function textOf(html) {
  return decode(html.replace(/<script\b[^>]*>[\s\S]*?<\/script\s*>/gi, '').replace(/<style\b[^>]*>[\s\S]*?<\/style\s*>/gi, '').replace(/<noscript\b[^>]*>[\s\S]*?<\/noscript\s*>/gi, '').replace(/<!--[\s\S]*?-->/g, '').replace(/<\/(?:p|div|li|h[1-6]|section|article|tr|main)>|<br\b[^>]*>/gi, '\n').replace(/<[^>]+>/g, ' ')).replace(/[\t\r ]+/g, ' ').replace(/ *\n */g, '\n').replace(/\n{3,}/g, '\n\n').trim();
}
function metadata(html, base) {
  const meta = {};
  for (const m of html.matchAll(/<meta\b[^>]*>/gi)) { const a = attrs(m[0]); if (a.content && (a.property || a.name)) meta[a.property || a.name] = a.content; }
  const title = meta['og:title'] || textOf(html.match(/<title\b[^>]*>([\s\S]*?)<\/title>/i)?.[1] || '');
  const links = [];
  for (const m of html.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a\s*>/gi)) { const a = attrs(m[1]); const url = absolute(a.href, base); if (url) links.push({ url, text: textOf(m[2]), title: a.title || null }); }
  const images = [];
  for (const m of html.matchAll(/<img\b[^>]*>/gi)) {
    const a = attrs(m[0]); const url = absolute(a.src || a['data-src'], base);
    if (url) images.push({ url, alt: a.alt || '', width: a.width || null, height: a.height || null, srcset: a.srcset || null, source_page: base, downloaded: false, visual_verified: false });
  }
  if (meta['og:image']) { const url = absolute(meta['og:image'], base); if (url && !images.some(x => x.url === url)) images.push({ url, alt: 'Open Graph image; content requires visual verification', source_page: base, downloaded: false, visual_verified: false }); }
  const headings = [...html.matchAll(/<h[1-6]\b[^>]*>([\s\S]*?)<\/h[1-6]>/gi)].map(m => textOf(m[1])).filter(Boolean);
  const published = meta['article:published_time'] || html.match(/"datePublished"\s*:\s*"([^"]+)"/)?.[1] || null;
  return { title, published_at: published, links, image_candidates: images, headings, meta };
}
function field(xml, key) {
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const value = xml.match(new RegExp(`<${escaped}\\b[^>]*>([\\s\\S]*?)<\\/${escaped}\\s*>`, 'i'))?.[1] || '';
  return value.replace(/^\s*<!\[CDATA\[([\s\S]*)\]\]>\s*$/, '$1');
}
function jsonAfter(html, marker) {
  const at = html.indexOf(marker); if (at < 0) return null;
  const start = html.indexOf('{', at + marker.length); if (start < 0) return null;
  let depth = 0, inString = false, escape = false;
  for (let i = start; i < html.length; i++) {
    const c = html[i];
    if (inString) { if (escape) escape = false; else if (c === '\\') escape = true; else if (c === '"') inString = false; }
    else if (c === '"') inString = true;
    else if (c === '{') depth++;
    else if (c === '}' && --depth === 0) { try { return JSON.parse(html.slice(start, i + 1)); } catch { return null; } }
  }
  return null;
}
function postObjects(value, found = [], depth = 0) {
  if (!value || typeof value !== 'object' || depth > 30) return found;
  if (!Array.isArray(value) && typeof value.slug === 'string' && (value.scheduled_at || value.override_scheduled_at || value.published_at)) found.push(value);
  for (const v of Object.values(value)) if (v && typeof v === 'object') postObjects(v, found, depth + 1);
  return found;
}
function regionById(html, id) {
  const open = new RegExp(`<([a-z][\\w:-]*)\\b[^>]*\\bid=["']${id}["'][^>]*>`, 'i').exec(html);
  if (!open) return null;
  const tag = open[1], token = new RegExp(`<\\/?${tag}\\b[^>]*>`, 'gi');
  token.lastIndex = open.index + open[0].length; let depth = 1, m;
  while ((m = token.exec(html))) { depth += /^<\//.test(m[0]) ? -1 : /\/\s*>$/.test(m[0]) ? 0 : 1; if (!depth) return html.slice(open.index, token.lastIndex); }
  return null;
}
async function request(url, attempts, fetchImpl = globalThis.fetch) {
  let last;
  for (let n = 1; n <= 3; n++) {
    const at = new Date().toISOString();
    try {
      const res = await fetchImpl(url, { signal: AbortSignal.timeout(25000), redirect: 'follow', headers: { 'user-agent': 'DailyNewsSite/1.0 public-newsletter-reader', accept: 'text/html,application/rss+xml,application/xml;q=0.9,*/*;q=0.5' } });
      const body = await res.text();
      attempts.push({ url, resolved_url: res.url, attempt: n, fetched_at: at, http_status: res.status, bytes: Buffer.byteLength(body) });
      if (body.length > 12 * 1024 * 1024) throw new Error('Response exceeds 12 MiB text limit');
      if (!res.ok) { const error = new Error(`HTTP ${res.status}`); error.retryable = res.status === 429 || res.status >= 500; error.responseBody = body; error.responseUrl = res.url; throw error; }
      return { body, url: res.url, fetched_at: at };
    } catch (e) {
      last = e; attempts.push({ url, attempt: n, failed_at: new Date().toISOString(), error: e.message, cause: e.cause?.message || null });
      if (e.retryable === false || n === 3) break;
      await new Promise(r => setTimeout(r, n * 700));
    }
  }
  throw last;
}
async function writeJson(path, value) { await writeFile(path, JSON.stringify(value, null, 2) + '\n'); }
function publishedPosts(html, url) {
  const data = jsonAfter(html, 'window.__remixContext =');
  const posts = postObjects(data).filter(p => !p.hide_from_feed).map(p => ({ url: absolute(`/p/${p.slug}`, url), title: p.web_title || p.title || null, published_at: p.override_scheduled_at || p.scheduled_at || p.published_at }));
  return [...new Map(posts.filter(p => p.url).map(p => [p.url, p])).values()];
}

// Follow actual publisher archive/pagination links only; never fabricate post slugs.
// Bounds prevent an old requested date from causing an unbounded web crawl.
async function discoverArchive(first, source, dir, status, selection, fetchImpl) {
  let page = first;
  const seen = new Set(), all = [];
  const host = new URL(page.url).hostname;
  for (let n = 1; n <= 24; n++) {
    if (seen.has(page.url)) { status.blockers.push('Archive pagination repeated a page; stopped without a current-issue fallback.'); break; }
    seen.add(page.url);
    await writeFile(join(dir, `archive-${n}.html`), page.body);
    const posts = publishedPosts(page.body, page.url);
    all.push(...posts);
    await writeJson(join(dir, 'discovered-issues.json'), [...new Map(all.map(p => [p.url, p])).values()]);
    const selected = selectIssue(posts, selection);
    if (selected) return selected;
    const links = metadata(page.body, page.url).links;
    // Some publishers render dates next to links instead of Remix post data.
    // Inspect a bounded number of real article links; require page date metadata.
    if (!posts.length) {
      const candidates = [...new Set(links.filter(l => /\/p\/[^/?#]+/.test(new URL(l.url).pathname) && new URL(l.url).hostname === host).map(l => l.url))].slice(0, 20);
      const dated = [];
      for (const url of candidates) {
        const article = await request(url, status.attempts, fetchImpl);
        const m = metadata(article.body, article.url);
        dated.push({ url: article.url, title: m.title, published_at: m.published_at });
        await writeFile(join(dir, `archive-${n}-article-${dated.length}.html`), article.body);
      }
      all.push(...dated);
      await writeJson(join(dir, 'discovered-issues.json'), all);
      const match = selectIssue(dated, selection);
      if (match) return match;
    }
    const next = links.find(l => new URL(l.url).hostname === host && !seen.has(l.url) && /\/archives?(?:\/|$)/.test(new URL(l.url).pathname) && (/load more|older|next|更多|下一/i.test(l.text) || /[?&]page=/.test(l.url)));
    if (!next) { status.blockers.push('Publisher archive exposes no further pagination link.'); break; }
    if (n === 24) { status.blockers.push('Historical discovery reached the 24-page limit.'); break; }
    page = await request(next.url, status.attempts, fetchImpl);
  }
  throw new Error(`No verifiable issue on or before ${selection.date} in the bounded publisher archive; latest content was not substituted`);
}

async function collectSource(source, dir, selection, fetchImpl) {
  await mkdir(dir, { recursive: true });
  const status = { source: source.id, name: source.name, checked_at: new Date().toISOString(), briefing_date: selection.date, acquisition_policy: selection.mode === 'latest' ? 'latest_public_at_check_time' : 'latest_public_on_or_before_requested_date', selection, timezone: selection.timezone, entry_url: source.entry, attempts: [], state: 'failed', completeness: 'unavailable', blockers: [] };
  try {
    const discovery = await request(source.entry, status.attempts, fetchImpl);
    await writeFile(join(dir, source.id === 'rundown' ? 'feed.xml' : 'discovery.html'), discovery.body);
    let issue, body;
    if (source.id === 'rundown') {
      const items = [...discovery.body.matchAll(/<item\b[^>]*>([\s\S]*?)<\/item\s*>/gi)].map(m => ({ xml: m[1], title: textOf(field(m[1], 'title')), url: decode(field(m[1], 'link').trim()), published_at: field(m[1], 'pubDate').trim() || null }));
      await writeJson(join(dir, 'discovered-issues.json'), items.map(({ xml, ...v }) => v));
      issue = selectIssue(items, selection);
      if (!issue && selection.mode === 'as-of') {
        const channel = discovery.body.split(/<item\b/i)[0];
        const homeUrl = absolute(decode(field(channel, 'link').trim()), discovery.url);
        if (!homeUrl) throw new Error('RSS has no issue before cutoff and no publisher homepage link for historical discovery');
        const home = await request(homeUrl, status.attempts, fetchImpl);
        await writeFile(join(dir, 'publisher-home.html'), home.body);
        const archive = metadata(home.body, home.url).links.find(l => /\/archive(?:[/?#]|$)/.test(l.url) && new URL(l.url).hostname === new URL(home.url).hostname);
        if (!archive) throw new Error('RSS has no issue before cutoff; publisher exposes no archive link, historical source unavailable');
        issue = await discoverArchive(await request(archive.url, status.attempts, fetchImpl), source, dir, status, selection, fetchImpl);
        status.acquisition_path = 'official_archive_historical_fallback';
      }
      if (!issue) throw new Error('RSS returned no issue with a valid publication date eligible for the requested selection');
      if (!absolute(issue.url, source.entry)) throw new Error('Selected RSS item has no HTTP issue URL');
      body = issue.xml ? field(issue.xml, 'content:encoded') : '';
      if (body.trim()) { status.acquisition_path = 'rss_content_encoded'; status.issue_fetched_at = discovery.fetched_at; }
      else {
        const web = await request(issue.url, status.attempts, fetchImpl); body = web.body;
        await writeFile(join(dir, 'issue-page.html'), body); status.acquisition_path ||= 'official_issue_page_fallback'; status.issue_fetched_at = web.fetched_at;
      }
    } else if (source.id === 'tldr') {
      let page = discovery;
      const seen = new Set(), candidates = [];
      for (let n = 1; n <= 24; n++) {
        seen.add(page.url);
        const links = metadata(page.body, page.url).links;
        candidates.push(...links.filter(l => /^https:\/\/tldr\.tech\/ai\/\d{4}-\d{2}-\d{2}(?:[/?#]|$)/.test(l.url)).map(l => ({ url: l.url, title: l.text, published_at: l.url.match(/\/(\d{4}-\d{2}-\d{2})(?:[/?#]|$)/)[1] })));
        issue = selectIssue(candidates, selection);
        if (issue || selection.mode === 'latest') break;
        const next = links.find(l => new URL(l.url).hostname === 'tldr.tech' && /\/ai\/archives(?:\/|$)/.test(new URL(l.url).pathname) && !seen.has(l.url) && /next|older|more|[?&]page=/i.test(l.text + l.url));
        if (!next || n === 24) break;
        page = await request(next.url, status.attempts, fetchImpl);
        await writeFile(join(dir, `archive-${n + 1}.html`), page.body);
      }
      await writeJson(join(dir, 'discovered-issues.json'), [...new Map(candidates.map(c => [c.url, c])).values()]);
      if (!issue) throw new Error(`Official TLDR archive exposes no dated issue eligible for ${selection.mode === 'as-of' ? selection.date : 'latest'}; no newer issue substituted`);
      const web = await request(issue.url, status.attempts, fetchImpl); body = web.body;
      await writeFile(join(dir, 'issue-page.html'), body);
      const m = metadata(body, web.url);
      const resolvedDate = web.url.match(/^https:\/\/tldr\.tech\/ai\/(\d{4}-\d{2}-\d{2})(?:[/?#]|$)/)?.[1];
      if (resolvedDate !== issue.published_at) throw new Error('TLDR selected dated issue redirected to another issue; rejected');
      if (m.published_at && !selectIssue([{ published_at: m.published_at }], selection))
        throw new Error('TLDR page publication metadata is invalid or after the requested cutoff');
      issue = { ...issue, ...m, url: web.url, published_at: m.published_at || issue.published_at };
      status.acquisition_path = 'official_archive_to_dated_issue'; status.issue_fetched_at = web.fetched_at;
    } else {
      const posts = publishedPosts(discovery.body, discovery.url);
      const candidates = posts.length ? posts : metadata(discovery.body, discovery.url).links.filter(x => /^https:\/\/(?:www\.)?superhuman\.ai\/p\/[^/?#]+(?:[?#]|$)/.test(x.url)).map(x => ({ url: x.url, title: x.text, published_at: null }));
      await writeJson(join(dir, 'discovered-issues.json'), candidates);
      if (selection.mode === 'as-of') {
        const archive = metadata(discovery.body, discovery.url).links.find(l => /^https:\/\/(?:www\.)?superhuman\.ai\/archive(?:[/?#]|$)/.test(l.url));
        if (!archive) throw new Error('Superhuman homepage exposes no archive link; cannot establish historical issue');
        issue = await discoverArchive(await request(archive.url, status.attempts, fetchImpl), source, dir, status, selection, fetchImpl);
        status.acquisition_path = 'official_paginated_archive_historical';
      } else {
        issue = selectIssue(candidates, selection) || (!posts.length ? candidates[0] : null);
        if (!issue) throw new Error('Official Superhuman homepage exposes no post link; cannot establish latest');
        status.acquisition_path = posts.length ? 'official_home_json_publication_order' : 'official_home_first_public_post_needs_latest_confirmation';
      }
      const web = await request(issue.url, status.attempts, fetchImpl); body = web.body;
      await writeFile(join(dir, 'issue-page.html'), body);
      if (new URL(web.url).pathname !== new URL(issue.url).pathname) throw new Error('Selected Superhuman issue redirected to a different article; rejected');
      const m = metadata(body, web.url); issue = { ...issue, ...m, url: web.url, published_at: m.published_at || issue.published_at };
      status.issue_fetched_at = web.fetched_at;
    }
    await writeFile(join(dir, 'issue.html'), body);
    if (selection.mode === 'as-of' && !selectIssue([issue], selection)) throw new Error('Selected issue publication date is missing, invalid, or after the requested cutoff; rejected');
    if (selection.mode === 'latest' && issue.published_at && !selectIssue([issue], selection)) throw new Error('Selected issue publication date is invalid or after the actual check time; rejected');
    const extraction = metadata(body, issue.url);
    if (extraction.published_at && !selectIssue([{ published_at: extraction.published_at }], selection)) throw new Error('Fetched article metadata is invalid or after the source selection cutoff; rejected');
    const scope = source.id === 'superhuman' ? regionById(body, 'content-blocks') : null;
    const text = textOf(scope || body);
    await writeFile(join(dir, 'body.txt'), text + '\n');
    await writeJson(join(dir, 'extracted.json'), { ...extraction, extraction_scope: scope ? 'content-blocks HTML region' : source.id === 'rundown' ? 'RSS content or fallback HTML; inspect acquisition_path' : 'visible HTML document; editorial scope review required', body_characters: text.length, publication_metadata: issue.published_at, issue_url: issue.url, selection, text_tail: text.slice(-1500), image_policy: 'metadata_only_select_before_download' });
    const pubTime = publicationTime(issue.published_at, selection);
    Object.assign(status, { state: text.length ? 'fetched' : 'partial', completeness: 'needs_editorial_completeness', latest_confirmation: selection.mode === 'as-of' ? 'latest_eligible_in_discovered_publisher_material' : source.id === 'superhuman' && !status.acquisition_path.includes('json') ? 'needs_editorial_latest_check' : 'discovered_from_current_publisher_entry', issue_url: issue.url, issue_title: issue.title || extraction.title, published_at: issue.published_at, publication_date: Number.isFinite(pubTime) ? new Intl.DateTimeFormat('en-CA', { timeZone: selection.timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(pubTime)) : null, body_characters: text.length, headings: extraction.headings, link_count: extraction.links.length, image_candidate_count: extraction.image_candidates.length, editorial_check_required: ['Read full body and headings', 'Confirm ending and absence of truncation/paywall', 'Confirm exact issue date and latest eligible public issue', 'Record full/partial/summary/unavailable with evidence before selection'] });
    if (selection.mode === 'as-of' && status.publication_date < selection.date) status.blockers.push(`No same-day issue was discovered; using actual publication date ${status.publication_date}.`);
    if (!text.length) status.blockers.push('Fetched document has no extracted visible text; raw response retained.');
  } catch (e) {
    status.blockers.push(e.message); status.error = { message: e.message, cause: e.cause?.message || null };
    if (e.responseBody) { await writeFile(join(dir, 'failed-response.html'), e.responseBody); status.failed_response_url = e.responseUrl; }
  }
  await writeJson(join(dir, 'status.json'), status);
  return status;
}

export async function collectProducts({ outputDir, date, timezone = 'Asia/Shanghai', mode, fetchImpl = globalThis.fetch } = {}) {
  if (!outputDir) throw new Error('outputDir is required');
  const selection = resolveSelection({ date, timezone, mode });
  const briefingDate = selection.date;
  const out = resolve(outputDir); await mkdir(out, { recursive: true });
  const started = new Date().toISOString();
  const sources = await Promise.all(SOURCES.map(s => collectSource(s, join(out, s.id), selection, fetchImpl)));
  for (const s of sources) { s.timezone = timezone; await writeJson(join(out, s.source, 'status.json'), s); }
  const count = sources.filter(s => s.state === 'fetched').length;
  const manifest = { version: 1, collector: 'daily-news-site/products-source', briefing_date: briefingDate, timezone, selection, started_at: started, finished_at: new Date().toISOString(), state: count === SOURCES.length ? 'fetched_all_sources' : count ? 'partial_sources' : 'failed', completeness: 'needs_editorial_completeness', source_count: sources.length, fetched_source_count: count, sources };
  await writeJson(join(out, 'products-manifest.json'), manifest);
  return manifest;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2); const options = {};
  for (let i = 0; i < args.length; i++) {
    const k = args[i];
    if (k === '--help') { console.log('node products-source.mjs --output-dir RUN/products [--date YYYY-MM-DD] [--timezone Asia/Shanghai] [--mode latest|as-of]\nOmit date for latest. Explicit date selects the latest issue available by that local date; unavailable history fails explicitly.'); process.exit(0); }
    if (!['--output-dir', '--date', '--timezone', '--mode'].includes(k) || !args[i + 1] || args[i + 1].startsWith('--')) throw new Error(`Unknown or missing argument ${k}`);
    options[k.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = args[++i];
  }
  collectProducts(options).then(m => { console.log(JSON.stringify(m, null, 2)); if (!m.fetched_source_count) process.exitCode = 1; }).catch(e => { console.error(e.message); process.exitCode = 1; });
}
