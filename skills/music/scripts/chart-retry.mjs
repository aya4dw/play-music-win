#!/usr/bin/env node
/**
 * 失败清单重试
 * ============
 * 读 chart-download.mjs 产出的 failures.json，逐首再做两轮尝试：
 *
 *   1) 严格轮：歌名 + 艺人（可配多个艺人别名，繁简/别名/组合拆分）
 *   2) 放宽轮：仍按歌名 + 艺人搜索，但找不到原唱时接受同名曲，结果标记 artistMismatch
 *
 * 每轮都走 engine-adapter 的「多引擎 × 多音源 + 完整性校验」，
 * 成功后按「[年份] 艺人 - 歌名.ext」落到曲库，并追加写 results.jsonl。
 *
 * 用法：
 *   node chart-retry.mjs --failures ~/Music/华语年度金曲/failures.json \
 *                        --out ~/Music/华语年度金曲 [--workers 2]
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ADAPTER = path.join(HERE, 'engine-adapter.mjs');

const argv = process.argv.slice(2);
const flag = (n, d = null) => {
  const i = argv.indexOf(`--${n}`);
  return i >= 0 ? argv[i + 1] : d;
};

const outDir = flag('out', path.join(os.homedir(), 'Music', '华语年度金曲'));
const failuresPath = flag('failures', path.join(outDir, 'failures.json'));
const workers = Math.max(1, parseInt(flag('workers', '2'), 10));
const resultsPath = path.join(outDir, 'results.jsonl');

const items = JSON.parse(fs.readFileSync(failuresPath, 'utf8'));
fs.mkdirSync(outDir, { recursive: true });

const sanitize = (s) => (s || '')
  .replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_')
  .replace(/\s+/g, ' ').trim().slice(0, 120);

const targetBase = (it) =>
  sanitize(`${it.year ? `[${it.year}] ` : ''}${it.artist} - ${it.title}`);

// 艺人别名：去空格、括号内容、常见组合拆分
function artistVariants(a) {
  const raw = (a || '').trim();
  const out = new Set([raw]);
  out.add(raw.replace(/\s+/g, ''));
  out.add(raw.split(/\s*(?:、|,|，|&|／|\/|feat\.|ft\.|with)\s*/i)[0]);
  out.add(raw.replace(/[（(].*?[）)]/g, '').trim());
  return [...out].filter(x => x && x.length <= 30);
}

function runFetch(keyword, name, anyArtist) {
  return new Promise((resolve) => {
    const args = [ADAPTER, 'fetch', keyword, '--out', outDir, '--name', name];
    const env = {
      ...process.env,
      GO_MUSIC_DL_BASE: process.env.GO_MUSIC_DL_BASE || 'http://127.0.0.1:8080/music',
      MUSIC_ANY_ARTIST: anyArtist ? '1' : '0',
    };
    const child = spawn(process.execPath, args, { env });
    let stdout = '', stderr = '';
    child.stdout.on('data', d => { stdout += d; });
    child.stderr.on('data', d => { stderr += d; });
    child.on('close', () => {
      let res = { ok: false };
      try { res = JSON.parse(stdout.trim()); }
      catch {
        const i = stdout.indexOf('{');
        if (i >= 0) { try { res = JSON.parse(stdout.slice(i)); } catch { /* ignore */ } }
      }
      resolve({ ...res, log: stderr.slice(-800) });
    });
  });
}

function move(item, src, suffix = '') {
  const dest = path.join(outDir, targetBase(item) + suffix + path.extname(src));
  if (path.resolve(src) !== path.resolve(dest)) {
    try { fs.renameSync(src, dest); } catch { return src; }
  }
  return dest;
}

const results = fs.createWriteStream(resultsPath, { flags: 'a' });
let ok = 0, okLoose = 0, failed = 0;
const still = [];

async function handle(it) {
  const name = it.title;
  // 1) 严格轮
  for (const a of artistVariants(it.artist)) {
    const r = await runFetch(`${name} ${a}`, name, false);
    if (r.ok && r.path) {
      const dest = move(it, r.path);
      ok++;
      console.log(`✓ ${it.year || '----'} ${it.artist} - ${it.title}  ${r.quality || ''} (${a})`);
      results.write(JSON.stringify({ ...it, status: 'ok', path: dest, quality: r.quality,
        engine: r.engine, source: r.source, artistFound: r.artist, attempt: 'strict' }) + '\n');
      return;
    }
  }
  // 2) 放宽轮（同名不同歌手，标记待复核）
  for (const a of artistVariants(it.artist).slice(0, 2)) {
    const r = await runFetch(`${name} ${a}`, name, true);
    if (r.ok && r.path) {
      const dest = move(it, r.path);
      okLoose++;
      console.log(`~ ${it.year || '----'} ${it.artist} - ${it.title}  同名曲: ${r.artist}  ${r.quality || ''}`);
      results.write(JSON.stringify({ ...it, status: 'ok', path: dest, quality: r.quality,
        engine: r.engine, source: r.source, artistFound: r.artist,
        artistMismatch: true, attempt: 'relaxed' }) + '\n');
      return;
    }
  }
  failed++;
  still.push(it);
  console.log(`✗ ${it.year || '----'} ${it.artist} - ${it.title}`);
  results.write(JSON.stringify({ ...it, status: 'fail', attempt: 'retry' }) + '\n');
}

async function main() {
  console.log(`重试 ${items.length} 首 → ${outDir}  (并发 ${workers})`);
  const pending = [...items];
  const runner = async () => {
    while (pending.length) {
      const it = pending.shift();
      try { await handle(it); } catch (e) { failed++; still.push(it); console.log(`✗ ${it.title}: ${e.message}`); }
    }
  };
  await Promise.all(Array.from({ length: workers }, runner));
  console.log(`\n重试完成：原唱 ${ok} / 同名曲 ${okLoose} / 仍失败 ${failed}`);
  if (still.length) {
    const p = path.join(outDir, 'failures.json');
    fs.writeFileSync(p, JSON.stringify(still, null, 1));
    console.log(`剩余失败清单 → ${p}`);
  }
  results.end();
}

main().catch(e => { console.error(e); process.exit(1); });
