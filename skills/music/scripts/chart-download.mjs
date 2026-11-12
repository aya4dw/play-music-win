#!/usr/bin/env node
/**
 * 榜单歌单批量下载器
 * ==================
 * 读 download_queue.json，逐首调用 engine-adapter 的 fetch（多引擎 × 多音源降级，
 * 每次下载过完整性校验），成功后按「[年份] 艺人 - 歌名.ext」命名落到目标目录。
 *
 * 特性：
 *   · 断点续传：目标文件已存在则跳过（CSV 里有记录也复用）
 *   · 并发可配（默认 2，音源限流下比单线程快、比高并发稳）
 *   · 每首结果追加写入 results.jsonl，失败不阻塞队列
 *   · 计时 + 进度 + 失败清单
 *
 * 用法：
 *   node chart-download.mjs --queue download_queue.json --out ~/Music/华语年度金曲 [--workers 2] [--limit 0]
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

const queuePath = flag('queue', 'download_queue.json');
const outDir = flag('out', path.join(os.homedir(), 'Music', '华语年度金曲'));
const workers = Math.max(1, parseInt(flag('workers', '2'), 10));
const limit = parseInt(flag('limit', '0'), 10);
const resultsPath = flag('results', path.join(outDir, 'results.jsonl'));

fs.mkdirSync(outDir, { recursive: true });

const queue = JSON.parse(fs.readFileSync(queuePath, 'utf8'));
const todo = limit > 0 ? queue.slice(0, limit) : queue;

const sanitize = (s) => (s || '')
  .replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_')
  .replace(/\s+/g, ' ')
  .trim()
  .slice(0, 120);

function targetBase(item) {
  const y = item.year ? `[${item.year}] ` : '';
  return sanitize(`${y}${item.artist} - ${item.title}`);
}

function findExisting(item) {
  const base = targetBase(item);
  for (const ext of ['.flac', '.mp3', '.m4a', '.ogg', '.wav']) {
    const p = path.join(outDir, base + ext);
    if (fs.existsSync(p)) return p;
  }
  // 兼容平台自报曲名与我们的标题略有差异：同前缀也算已下载
  const prefix = sanitize(`${item.year ? `[${item.year}] ` : ''}${item.artist} - `);
  try {
    const hit = fs.readdirSync(outDir).find(f => f.startsWith(prefix) &&
      item.title && f.includes(sanitize(item.title).slice(0, 12)));
    if (hit) return path.join(outDir, hit);
  } catch { /* ignore */ }
  return null;
}

function runFetch(item) {
  return new Promise((resolve) => {
    const kw = `${item.title} ${item.artist}`;
    const args = [ADAPTER, 'fetch', kw, '--out', outDir, '--name', item.title];
    const env = {
      ...process.env,
      GO_MUSIC_DL_BASE: process.env.GO_MUSIC_DL_BASE || 'http://127.0.0.1:8080/music',
      MUSICDL_PYTHON: process.env.MUSICDL_PYTHON || path.join(os.homedir(), 'venvs', 'musicdl', 'bin', 'python'),
    };
    const child = spawn(process.execPath, args, { env });
    let stdout = '', stderr = '';
    child.stdout.on('data', d => { stdout += d; });
    child.stderr.on('data', d => { stderr += d; });
    child.on('close', () => {
      let res = { ok: false };
      try {
        res = JSON.parse(stdout.trim());
      } catch {
        // 适配器在 stderr 有日志，stdout 只有最后的 JSON 对象
        const i = stdout.indexOf('{');
        if (i >= 0) { try { res = JSON.parse(stdout.slice(i)); } catch { /* ignore */ } }
      }
      resolve({ ...res, log: stderr.slice(-1200) });
    });
  });
}

function renameToTarget(item, src) {
  const dest = path.join(outDir, targetBase(item) + path.extname(src));
  if (path.resolve(src) === path.resolve(dest)) return dest;
  try {
    fs.renameSync(src, dest);
    return dest;
  } catch {
    return src;
  }
}

const results = fs.createWriteStream(resultsPath, { flags: 'a' });
let done = 0, ok = 0, skipped = 0, failed = 0;
const t0 = Date.now();
const failures = [];

async function handle(item) {
  const existing = findExisting(item);
  if (existing) {
    skipped++;
    done++;
    results.write(JSON.stringify({ ...item, status: 'skip', path: existing }) + '\n');
    return;
  }
  const t = Date.now();
  const r = await runFetch(item);
  const secs = ((Date.now() - t) / 1000).toFixed(0);
  done++;
  if (r.ok && r.path) {
    const final = renameToTarget(item, r.path);
    ok++;
    console.log(`✓ [${done}/${todo.length}] ${item.year || '----'} ${item.artist} - ${item.title}  ${r.quality || ''} ${secs}s`);
    results.write(JSON.stringify({ ...item, status: 'ok', path: final, quality: r.quality, engine: r.engine, source: r.source }) + '\n');
  } else {
    failed++;
    failures.push(item);
    console.log(`✗ [${done}/${todo.length}] ${item.year || '----'} ${item.artist} - ${item.title}  ${secs}s`);
    results.write(JSON.stringify({ ...item, status: 'fail', log: r.log }) + '\n');
  }
}

async function main() {
  console.log(`队列 ${todo.length} 首 → ${outDir}  (并发 ${workers})`);
  const pending = [...todo];
  const runner = async () => {
    while (pending.length) {
      const item = pending.shift();
      try { await handle(item); }
      catch (e) { failed++; failures.push(item); console.log(`✗ ${item.artist} - ${item.title}: ${e.message}`); }
    }
  };
  await Promise.all(Array.from({ length: workers }, runner));

  const mins = ((Date.now() - t0) / 60000).toFixed(1);
  console.log(`\n完成：成功 ${ok} / 跳过 ${skipped} / 失败 ${failed}   用时 ${mins} 分钟`);
  if (failures.length) {
    const p = path.join(outDir, 'failures.json');
    fs.writeFileSync(p, JSON.stringify(failures, null, 1));
    console.log(`失败清单 → ${p}`);
  }
  results.end();
}

main().catch(e => { console.error(e); process.exit(1); });
