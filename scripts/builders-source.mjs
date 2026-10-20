#!/usr/bin/env node
// Independent collector for the daily-news-site package. Public feed attribution
// and license verification are recorded in references/THIRD_PARTY_NOTICES.md.
import { readFile, writeFile, mkdir, rename, rm } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createHash, randomUUID } from 'node:crypto';
import { resolveSelection, publicationTime } from './products-source.mjs';

const packageDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const configUrl = new URL('../resources/builders-sources.json', import.meta.url);
const promptUrl = new URL('../references/builders-remix.md', import.meta.url);
const digest = bytes => createHash('sha256').update(bytes).digest('hex');

async function save(path, value) {
  const temporary = `${path}.${randomUUID()}.tmp`;
  await writeFile(temporary, value);
  await rename(temporary, path);
}

function checkConfig(config) {
  if (config.schemaVersion !== 1 || !Array.isArray(config.feeds) || config.feeds.length !== 3)
    throw new Error('Expected the three bundled public feed definitions');
  if (!Number.isInteger(config.timeoutMs) || config.timeoutMs < 1 || config.timeoutMs > 60000 ||
      !Number.isInteger(config.retries) || config.retries < 0 || config.retries > 3 ||
      !Number.isInteger(config.maxResponseBytes) || config.maxResponseBytes < 1)
    throw new Error('Invalid bundled network limits');
  const keys = new Set();
  for (const feed of config.feeds) {
    const url = new URL(feed.url);
    if (url.protocol !== 'https:' || !['x', 'podcasts', 'blogs'].includes(feed.key) || keys.has(feed.key) ||
        !/^[a-z-]+\.json$/.test(feed.file) || !/^[a-z]+$/.test(feed.id))
      throw new Error('Invalid bundled feed definition');
    keys.add(feed.key);
  }
}

export async function resolveHistoricalFeed(feed, selection, config, fetchImpl = globalThis.fetch) {
  const match = new URL(feed.url).pathname.match(/^\/([^/]+)\/([^/]+)\/([^/]+)\/(.+)$/);
  if (new URL(feed.url).hostname !== 'raw.githubusercontent.com' || !match) throw new Error('Historical feed requires a configured public GitHub raw source');
  const [, owner, repo, branch, file] = match;
  const api = new URL(`https://api.github.com/repos/${owner}/${repo}/commits`);
  api.searchParams.set('path', file); api.searchParams.set('sha', branch);
  api.searchParams.set('until', new Date(Date.parse(selection.cutoff_exclusive) - 1).toISOString());
  api.searchParams.set('per_page', '1');
  const attempts = [];
  let body, commits, last;
  for (let attempt = 1; attempt <= config.retries + 1; attempt++) {
    try {
      const response = await fetchImpl(api.href, { signal: AbortSignal.timeout(config.timeoutMs), redirect: 'follow', headers: { accept: 'application/vnd.github+json', 'user-agent': 'daily-news-site/1.0' } });
      body = await response.text();
      attempts.push({ attempt, url: api.href, resolvedUrl: response.url || api.href, httpStatus: response.status, fetchedAt: new Date().toISOString() });
      if (Buffer.byteLength(body) > config.maxResponseBytes) throw new Error('GitHub history response exceeds configured limit');
      if (!response.ok) { const error = new Error(`GitHub history HTTP ${response.status}`); error.retryable = response.status === 429 || response.status >= 500; throw error; }
      commits = JSON.parse(body);
      if (!Array.isArray(commits) || !commits.length) throw new Error('No public GitHub file revision exists on or before the requested date');
      const commit = commits[0], committedAt = commit.commit?.committer?.date;
      if (!/^[0-9a-f]{40}$/i.test(commit.sha || '') || !Number.isFinite(Date.parse(committedAt)) || Date.parse(committedAt) >= Date.parse(selection.cutoff_exclusive)) throw new Error('GitHub returned an invalid or future historical revision');
      return { feed: { ...feed, url: `https://raw.githubusercontent.com/${owner}/${repo}/${commit.sha}/${file}`, originalUrl: feed.url }, history: { apiUrl: api.href, commitSha: commit.sha, committedAt, sha256: digest(body), attempts }, body };
    } catch (error) {
      last = error;
      if (!attempts.some(a => a.attempt === attempt)) attempts.push({ attempt, url: api.href, error: error.message });
      if (error.retryable === false || attempt > config.retries || (commits && Array.isArray(commits) && !commits.length)) break;
    }
  }
  last.history = { apiUrl: api.href, attempts, sha256: body ? digest(body) : null };
  last.historyBody = body;
  throw last;
}

async function download(feed, config, fetchImpl, selection) {
  const attempts = [];
  let rejectedBytes = null;
  for (let attempt = 1; attempt <= config.retries + 1; attempt++) {
    const attemptStartedAt = new Date().toISOString();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), config.timeoutMs);
    try {
      const response = await fetchImpl(feed.url, {
        signal: controller.signal,
        redirect: 'follow',
        headers: { accept: 'application/json', 'user-agent': 'daily-news-site/1.0' }
      });
      attempts.push({ attempt, startedAt: attemptStartedAt, httpStatus: response.status, resolvedUrl: response.url || feed.url });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      if (response.url && new URL(response.url).protocol !== 'https:')
        throw new Error('HTTPS feed redirected to an insecure URL');
      const chunks = [];
      let byteLength = 0;
      for await (const part of response.body) {
        byteLength += part.length;
        if (byteLength > config.maxResponseBytes) {
          controller.abort();
          throw new Error(`Feed exceeds ${config.maxResponseBytes} bytes`);
        }
        chunks.push(part);
      }
      const bytes = Buffer.concat(chunks);
      rejectedBytes = bytes;
      const parsed = JSON.parse(bytes.toString('utf8'));
      if (!parsed || typeof parsed !== 'object' || !Array.isArray(parsed[feed.key]))
        throw new Error(`Feed must contain an array named ${feed.key}`);
      if (feed.key === 'x' && parsed.x.some(person => !person || typeof person !== 'object' || !Array.isArray(person.tweets)))
        throw new Error('Each returned builder must contain a tweets array');
      if (selection.mode === 'as-of') {
        if (!Number.isFinite(publicationTime(parsed.generatedAt, selection)) || publicationTime(parsed.generatedAt, selection) >= Date.parse(selection.cutoff_exclusive))
          throw new Error('Historical feed generation time is invalid or after the requested cutoff');
        const items = feed.key === 'x' ? parsed.x.flatMap(p => p.tweets).map(t => t.createdAt) : parsed[feed.key].map(item => item.publishedAt);
        if (items.some(time => time && Number.isFinite(publicationTime(time, selection)) && publicationTime(time, selection) >= Date.parse(selection.cutoff_exclusive)))
          throw new Error('Historical feed contains an item published after the requested cutoff');
      }
      attempts.push({ attempt, startedAt: attemptStartedAt, status: 'ok' });
      return { bytes, parsed, manifest: {
        id: feed.id, key: feed.key, url: feed.url, originalUrl: feed.originalUrl || feed.url, resolvedUrl: response.url || feed.url,
        status: 'ok', fetchedAt: new Date().toISOString(),
        generatedAt: parsed.generatedAt ?? null, file: feed.file,
        bytes: byteLength, sha256: digest(bytes), itemCount: parsed[feed.key].length, attempts
      } };
    } catch (error) {
      attempts.push({ attempt, startedAt: attemptStartedAt, status: 'error',
        error: controller.signal.aborted ? `Request timed out or exceeded limits (${config.timeoutMs}ms)` : error.message });
    } finally {
      clearTimeout(timer);
    }
    if (attempt <= config.retries) await new Promise(done => setTimeout(done, attempt * 300));
  }
  return { bytes: null, parsed: null, rejectedBytes, manifest: {
    id: feed.id, key: feed.key, url: feed.url, resolvedUrl: null,
    status: 'error', fetchedAt: new Date().toISOString(), generatedAt: null,
    file: null, bytes: null, sha256: null, itemCount: null, attempts,
    error: attempts.at(-1).error
  } };
}

function inspectReturnedItems(x, podcasts, blogs) {
  const missing = [];
  for (const [personIndex, person] of x.entries()) {
    for (const key of ['name', 'handle']) if (!person[key]) missing.push({ kind: 'builder', personIndex, field: key });
    for (const [tweetIndex, tweet] of person.tweets.entries()) {
      for (const key of ['url', 'createdAt', 'text']) {
        if (!tweet?.[key]) missing.push({ kind: 'tweet', personIndex, tweetIndex, field: key });
      }
      if (tweet?.createdAt && Number.isNaN(Date.parse(tweet.createdAt)))
        missing.push({ kind: 'tweet', personIndex, tweetIndex, field: 'createdAt', reason: 'invalid timestamp' });
      if (tweet?.url) {
        try { if (!['https:', 'http:'].includes(new URL(tweet.url).protocol)) throw new Error(); }
        catch { missing.push({ kind: 'tweet', personIndex, tweetIndex, field: 'url', reason: 'invalid source URL' }); }
      }
    }
  }
  for (const [kind, items] of [['podcast', podcasts], ['blog', blogs]]) {
    for (const [index, item] of items.entries()) {
      for (const field of ['url', 'publishedAt']) if (!item?.[field]) missing.push({ kind, index, field });
      if (kind === 'podcast' && item?.url && /[?&]list=/.test(item.url) && !/[?&]v=/.test(item.url))
        missing.push({ kind, index, field: 'url', reason: 'playlist rather than an individual episode' });
    }
  }
  return missing;
}

/** Fetch every bundled public feed; never invokes another skill or reuses an old run. */
export async function collectBuilders({ outputDir, date, timezone = 'Asia/Shanghai', mode, fetchImpl = globalThis.fetch } = {}) {
  if (!outputDir) throw new Error('outputDir is required');
  if (typeof fetchImpl !== 'function') throw new Error('Node.js with built-in fetch is required');
  const selection = resolveSelection({ date, timezone, mode });
  const [configText, remix] = await Promise.all([readFile(configUrl, 'utf8'), readFile(promptUrl, 'utf8')]);
  const config = JSON.parse(configText);
  checkConfig(config);
  const destination = resolve(outputDir);
  await mkdir(destination, { recursive: true });
  const startedAt = new Date().toISOString();
  const results = await Promise.all(config.feeds.map(async feed => {
    if (selection.mode === 'latest') return download(feed, config, fetchImpl, selection);
    try {
      const resolved = await resolveHistoricalFeed(feed, selection, config, fetchImpl);
      const historyFile = `${feed.id}-history.json`;
      await save(join(destination, historyFile), resolved.body);
      const result = await download(resolved.feed, config, fetchImpl, selection);
      result.manifest.history = { ...resolved.history, file: historyFile };
      result.manifest.selection = selection;
      return result;
    } catch (error) {
      const historyFile = `${feed.id}-history.json`;
      if (error.historyBody) await save(join(destination, historyFile), error.historyBody);
      return { bytes: null, parsed: null, manifest: { id: feed.id, key: feed.key, url: feed.url, resolvedUrl: null, status: 'error', fetchedAt: new Date().toISOString(), generatedAt: null, file: null, bytes: null, sha256: null, itemCount: null, selection, history: error.history ? { ...error.history, file: error.historyBody ? historyFile : null } : null, attempts: [], error: error.message } };
    }
  }));
  for (const [index, result] of results.entries()) {
    const path = join(destination, config.feeds[index].file);
    if (result.bytes) await save(path, result.bytes);
    else await rm(path, { force: true }); // Failed repeat runs cannot leave an old file looking fresh.
    if (result.rejectedBytes) {
      const rejectedFile = `${config.feeds[index].file}.rejected`;
      await save(join(destination, rejectedFile), result.rejectedBytes);
      result.manifest.rejectedResponse = { file: rejectedFile, bytes: result.rejectedBytes.length, sha256: digest(result.rejectedBytes) };
    }
  }
  const byKey = Object.fromEntries(results.map(result => [result.manifest.key, result]));
  const x = byKey.x.parsed?.x ?? [];
  const podcasts = byKey.podcasts.parsed?.podcasts ?? [];
  const blogs = byKey.blogs.parsed?.blogs ?? [];
  const feedStatus = Object.fromEntries(results.map(result => [result.manifest.key, result.manifest]));
  const failed = results.filter(result => result.manifest.status !== 'ok');
  const status = byKey.x.manifest.status !== 'ok' ? 'error' : failed.length ? 'partial' : 'ok';
  const fetchedAt = new Date().toISOString();
  const inputIssues = inspectReturnedItems(x, podcasts, blogs);
  for (const result of results) {
    if (result.manifest.status === 'ok' && (!result.manifest.generatedAt || Number.isNaN(Date.parse(result.manifest.generatedAt))))
      inputIssues.push({ kind: 'feed', source: result.manifest.key, field: 'generatedAt', reason: 'missing or invalid feed generation time' });
  }
  const output = {
    schemaVersion: 1, status, startedAt, fetchedAt, generatedAt: fetchedAt, selection,
    collector: { name: 'daily-news-site/builders-source', bundledConfig: 'resources/builders-sources.json',
      configSha256: digest(configText), bundledRemix: 'references/builders-remix.md',
      remixSha256: digest(remix), packageDir, usesExternalSkill: false, usesUserConfig: false,
      usesRemotePrompt: false, fallbackToOldFiles: false },
    config: { language: config.language, frequency: 'on-demand', delivery: { method: 'local-files' } },
    x, podcasts, blogs,
    stats: { xBuilders: x.length, totalTweets: x.reduce((sum, person) => sum + person.tweets.length, 0),
      podcastEpisodes: podcasts.length, blogPosts: blogs.length,
      feedGeneratedAt: byKey.x.manifest.generatedAt,
      feedGeneratedAtBySource: Object.fromEntries(results.map(result => [result.manifest.key, result.manifest.generatedAt])) },
    feedStatus, inputIssues,
    prompts: { builders_remix: remix },
    errors: failed.map(result => ({ source: result.manifest.key, error: result.manifest.error }))
  };
  await save(join(destination, 'feed-manifest.json'), JSON.stringify({ schemaVersion: 1, status, startedAt, fetchedAt, selection, feedStatus }, null, 2) + '\n');
  await save(join(destination, 'raw.json'), JSON.stringify(output, null, 2) + '\n');
  return output;
}

async function cli() {
  const args = process.argv.slice(2);
  const options = {};
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--help') { process.stdout.write('Usage: node builders-source.mjs --output-dir <run-directory> [--date YYYY-MM-DD] [--mode latest|as-of] [--timezone Asia/Shanghai]\nOmit date for current feeds; explicit date resolves immutable public GitHub history.\n'); return; }
    if (!['--output-dir', '--date', '--mode', '--timezone'].includes(args[i]) || !args[i + 1]) throw new Error('Unknown or missing argument: ' + args[i]);
    options[args[i].slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = args[++i];
  }
  const result = await collectBuilders(options);
  process.stdout.write(JSON.stringify({ status: result.status, fetchedAt: result.fetchedAt,
    stats: result.stats, inputIssues: result.inputIssues, errors: result.errors,
    output: resolve(options.outputDir, 'raw.json') }, null, 2) + '\n');
  if (result.status !== 'ok') process.exitCode = 1;
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  cli().catch(error => {
    process.stderr.write(JSON.stringify({ status: 'error', error: error.message }) + '\n');
    process.exitCode = 1;
  });
}
