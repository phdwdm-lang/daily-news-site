#!/usr/bin/env node
/** Independent daily-news-site input collection; no other local Skill is loaded. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { collectBuilders } from './builders-source.mjs';
import { collectProducts, resolveSelection } from './products-source.mjs';

export async function collectInputs({ outputDir, date, timezone = 'Asia/Shanghai', mode }) {
  if (!outputDir) throw new Error('outputDir is required');
  const selection = resolveSelection({ date, timezone, mode });
  date = selection.date;
  const root = path.resolve(outputDir);
  await fs.mkdir(root, { recursive: true });
  const marker = path.join(root, 'run.json');
  try { await fs.access(marker); throw new Error('运行目录已有 run.json，请使用新目录，保留原始输入。'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const run = { schema_version: 1, started_at: new Date().toISOString(), date, timezone, selection,
    status: 'collecting', implementation: 'daily-news-site-independent', branches: {} };
  await fs.writeFile(marker, JSON.stringify(run, null, 2) + '\n');
  const names = ['builders', 'products'];
  const results = await Promise.allSettled([
    collectBuilders({ outputDir: path.join(root, 'builders'), date, timezone, mode: selection.mode }),
    collectProducts({ outputDir: path.join(root, 'products'), date, timezone, mode: selection.mode }),
  ]);
  for (let i = 0; i < results.length; i++) {
    const result = results[i];
    const sourceState = result.status === 'fulfilled' ? (result.value?.status || result.value?.state) : 'failed';
    const status = ['error', 'failed'].includes(sourceState) ? 'failed'
      : ['partial', 'partial_sources'].includes(sourceState) ? 'partial' : 'returned';
    run.branches[names[i]] = result.status === 'fulfilled'
      ? { status, source_state: sourceState, result: result.value }
      : { status: 'failed', error: String(result.reason?.message || result.reason) };
  }
  run.finished_at = new Date().toISOString();
  const states = Object.values(run.branches).map(branch => branch.status);
  run.status = states.every(state => state === 'failed') ? 'failed'
    : states.some(state => state !== 'returned') ? 'partial' : 'inputs-returned';
  run.next = '读取各来源实际状态并检查完整性；读取指定待办；形成工作稿和当期数据，再完成候选验收。此状态不是网站已发布。';
  await fs.writeFile(marker, JSON.stringify(run, null, 2) + '\n');
  return run;
}

async function main() {
  const options = {};
  for (let i = 2; i < process.argv.length; i++) {
    const flag = process.argv[i];
    if (flag === '--help') {
      console.log('node collect.mjs --output-dir <new-run-directory> [--date YYYY-MM-DD] [--timezone Asia/Shanghai] [--mode latest|as-of]\nOmit date for latest inputs. Explicit date selects sources available by the end of that local date.');
      return;
    }
    if (!['--output-dir', '--date', '--timezone', '--mode'].includes(flag) || !process.argv[i + 1]) throw new Error('未知或缺值参数：' + flag);
    options[flag.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = process.argv[++i];
  }
  if (!options.outputDir) throw new Error('必须指定 --output-dir，不能覆盖以往采集。');
  options.timezone ||= 'Asia/Shanghai';
  const result = await collectInputs(options);
  console.log(JSON.stringify({ status: result.status, date: result.date, output_dir: path.resolve(options.outputDir), branches: Object.fromEntries(Object.entries(result.branches).map(([name, value]) => [name, value.status])) }, null, 2));
  if (result.status === 'failed') process.exitCode = 1;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main().catch(error => { console.error(error.message); process.exitCode = 1; });
