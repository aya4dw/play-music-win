#!/usr/bin/env python3
"""
榜单曲库汇总报告 + M3U8 生成

读取下载目录下的 results.jsonl（由 chart-download.mjs 追加写入），输出：
  · 成功率、音质分布、逐年覆盖
  · 失败清单（含失败原因摘要）
  · 按十年生成 M3U8 播放列表（相对路径，可整目录搬移）
"""
import json
import os
import sys
from collections import Counter, defaultdict

AUDIO_EXT = (".flac", ".mp3", ".m4a", ".ogg", ".wav")


def load(results_path):
    rows = []
    if not os.path.exists(results_path):
        return rows
    with open(results_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def main(out_dir):
    results_path = os.path.join(out_dir, "results.jsonl")
    rows = load(results_path)
    if not rows:
        print(f"没有结果记录: {results_path}")
        return

    # 同一首可能被记录多次（重试），以最后一次为准
    latest = {}
    for r in rows:
        latest[(r.get("year"), r.get("artist"), r.get("title"))] = r
    recs = list(latest.values())

    by_status = Counter(r.get("status") for r in recs)
    print("=" * 62)
    print("榜单曲库下载报告")
    print("=" * 62)
    print(f"记录 {len(recs)} 首：" + "  ".join(f"{k} {v}" for k, v in by_status.items()))

    ok = [r for r in recs if r.get("status") in ("ok", "skip") and os.path.exists(r.get("path", ""))]
    print(f"实际在库 {len(ok)} 首，总体积 {sum(os.path.getsize(r['path']) for r in ok)/1e9:.2f} GB")
    q = Counter(r.get("quality", "?") for r in ok)
    print("音质分布：" + "  ".join(f"{k} {v}" for k, v in q.most_common()))

    yr = Counter(r.get("year") for r in ok)
    print("\n逐年入库：")
    line = []
    for y in sorted(k for k in yr if k):
        line.append(f"{y}:{yr[y]}")
        if len(line) == 10:
            print("  " + "  ".join(line))
            line = []
    if line:
        print("  " + "  ".join(line))

    fails = [r for r in recs if r.get("status") == "fail"]
    if fails:
        print(f"\n失败 {len(fails)} 首：")
        for r in fails[:25]:
            print(f"  {r.get('year') or '----'} {r.get('artist')} - {r.get('title')}")
        if len(fails) > 25:
            print(f"  … 还有 {len(fails)-25} 首（见 results.jsonl）")

    # M3U8：按十年
    groups = defaultdict(list)
    for r in ok:
        y = r.get("year") or 0
        decade = f"{y//10*10}s" if y else "未知年份"
        groups[decade].append(r)

    print("\n生成 M3U8：")
    for decade, items in sorted(groups.items()):
        items.sort(key=lambda r: (r.get("year") or 0, r.get("artist") or ""))
        path = os.path.join(out_dir, f"华语年度金曲 {decade}.m3u8")
        with open(path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for r in items:
                dur = int(r.get("duration") or 0)
                f.write(f"#EXTINF:{dur},{r.get('artist')} - {r.get('title')}\n")
                f.write(os.path.basename(r["path"]) + "\n")
        print(f"  {decade:<8} {len(items):>4} 首 → {os.path.basename(path)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Music/华语年度金曲"))
