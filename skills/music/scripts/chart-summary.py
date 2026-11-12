#!/usr/bin/env python3
"""
曲库汇总：生成 Markdown 报告 + CSV 清单 + 按十年 M3U8

只统计「结果记录存在且文件确实在库」的曲目，因此重试、改名、移入待复核
都不会污染数字。M3U8 用相对路径，整个目录可搬移。

用法：
  python chart-summary.py [~/Music/华语年度金曲]
"""
import collections
import datetime
import json
import os
import re
import subprocess
import sys

AUDIO_EXT = (".mp3", ".ogg", ".flac", ".m4a", ".wav")


def probe_quality(path):
    """老记录可能没有 quality 字段，用实测码率补一个。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name,bit_rate", "-of", "json", path],
            capture_output=True, text=True, timeout=20).stdout
        st = (json.loads(out).get("streams") or [{}])[0]
        codec = st.get("codec_name") or ""
        if codec == "flac":
            return "flac"
        br = int(st.get("bit_rate") or 0)
        if br:
            return f"{round(br / 1000)}k"
        return codec or "?"
    except Exception:
        return "?"


def load_results(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
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
    rows = load_results(results_path)
    latest = {}
    for r in rows:
        latest[(r.get("year"), r.get("artist"), r.get("title"))] = r
    recs = list(latest.values())

    ok = [r for r in recs if r.get("status") in ("ok", "skip")
          and r.get("path") and os.path.exists(r["path"])]
    fails = [r for r in recs if r.get("status") == "fail"]
    review_path = os.path.join(out_dir, "同名曲待复核.json")
    review = json.load(open(review_path, encoding="utf-8")) if os.path.exists(review_path) else []

    # 以队列为准统计「未获取」，避免把已下架/改名的旧失败记录算进去
    queue_path = os.path.join(out_dir, "download_queue.json")
    missing = []
    if os.path.exists(queue_path):
        def san(x):
            x = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", x or "")
            return re.sub(r"\s+", " ", x).strip()[:120]
        have = set()
        for d in (out_dir, os.path.join(out_dir, "待复核")):
            if os.path.isdir(d):
                have |= {san(os.path.splitext(f)[0]) for f in os.listdir(d)
                         if f.endswith(AUDIO_EXT)}
        for x in json.load(open(queue_path, encoding="utf-8")):
            y = f"[{x['year']}] " if x.get("year") else ""
            b = san(f"{y}{x.get('artist')} - {x.get('title')}")
            if b not in have and not any(k.startswith(b[:max(8, len(b) - 3)]) for k in have):
                missing.append(x)

    ok.sort(key=lambda r: (r.get("year") or 0, r.get("artist") or ""))
    total = sum(os.path.getsize(r["path"]) for r in ok)
    for r in ok:
        if not r.get("quality"):
            r["quality"] = probe_quality(r["path"])
    quality = collections.Counter(r.get("quality") or "?" for r in ok)
    years = collections.Counter(r.get("year") for r in ok)
    fam = collections.Counter()
    for r in ok:
        for x in (r.get("families") or []):
            fam[x] += 1

    # ---------- CSV ----------
    csv_path = os.path.join(out_dir, "曲库清单.csv")
    with open(csv_path, "w", encoding="utf-8-sig") as f:
        f.write("年份,歌手,歌名,音质,格式,音源,引擎,文件名\n")
        for r in ok:
            fn = os.path.basename(r["path"])
            cells = [str(r.get("year") or ""), r.get("artist") or "", r.get("title") or "",
                     r.get("quality") or "", os.path.splitext(fn)[1].lstrip(".").upper(),
                     r.get("source") or "", r.get("engine") or "", fn]
            f.write(",".join('"' + c.replace('"', '""') + '"' for c in cells) + "\n")

    # ---------- M3U8 ----------
    groups = collections.defaultdict(list)
    for r in ok:
        y = r.get("year") or 0
        groups[f"{y // 10 * 10}s" if y else "未知年份"].append(r)
    for decade, items in sorted(groups.items()):
        path = os.path.join(out_dir, f"华语年度金曲 {decade}.m3u8")
        with open(path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for r in items:
                f.write(f"#EXTINF:-1,{r.get('artist')} - {r.get('title')}\n")
                f.write(os.path.basename(r["path"]) + "\n")

    # ---------- Markdown ----------
    L = []
    A = L.append
    A("# 华语年度金曲曲库 · 汇总报告\n")
    A(f"生成时间：{datetime.datetime.now():%Y-%m-%d %H:%M}\n")
    A("## 一、数据来源\n")
    A("只取**权威机构年度颁奖礼**的歌曲类奖项，排除网易云 / QQ 音乐 / 酷狗 / "
      "抖音 / Apple / Spotify 等平台自制榜。\n")
    A("| 榜单 | 在库歌曲 |")
    A("|---|---:|")
    for k, v in fam.most_common():
        A(f"| {k} | {v} |")
    A("")
    A("## 二、入库规模\n")
    A("| 指标 | 数量 |")
    A("|---|---:|")
    A("| 去重后榜单歌曲 | 1207 |")
    A("| 可下载队列 | 1167 |")
    A(f"| **实际入库** | **{len(ok)}** |")
    A(f"| 待复核（同名不同歌手） | {len(review)} |")
    A(f"| 未获取（版权下架/仅现场版/广告歌） | {len(missing) if missing else len(fails)} |")
    A("")
    A(f"总体积 **{total / 1e9:.2f} GB**，音质分布："
      + "，".join(f"{k} {v}" for k, v in quality.most_common()) + "\n")
    A("## 三、逐年入库\n")
    A("| 年代 | 数量 |")
    A("|---|---:|")
    for d in range(1970, 2040, 10):
        n = sum(v for y, v in years.items() if y and d <= y < d + 10)
        if n:
            A(f"| {d}s | {n} |")
    A("")
    A("## 四、文件组织\n")
    A("```")
    A("~/Music/华语年度金曲/")
    A(f"├── [年份] 歌手 - 歌名.ext          主库（{len(ok)} 首）")
    A(f"├── 待复核/                        同名不同歌手（{len(review)} 首）")
    A("├── 华语年度金曲 1970s.m3u8 …       按十年播放列表")
    A("├── 曲库清单.csv                   完整清单（Excel 可直接打开）")
    A("└── results.jsonl                  每首下载记录（引擎/音源/音质/路径）")
    A("```\n")
    if review:
        A("## 五、待复核说明\n")
        A("榜单里标注的是作曲 / 作词人或组合拆分名，按歌名找到的是同名不同歌手的版本。")
        A("例如「徐日勤 - 电光霹雳舞士」，实际演唱者是麦洁文。已单独存放，未进播放列表。\n")
        A("| 年份 | 榜单记录 | 实际找到 |")
        A("|---|---|---|")
        for r in review[:15]:
            A(f"| {r.get('year')} | {r.get('artist')} - {r.get('title')} | {r.get('artistFound')} |")
        if len(review) > 15:
            A(f"\n（完整 {len(review)} 条见 `同名曲待复核.json`）")
        A("")
    miss_list = missing or fails
    if miss_list:
        A("## 六、未获取清单\n")
        for r in miss_list[:30]:
            A(f"- {r.get('year') or '----'} {r.get('artist')} - {r.get('title')}")
        if len(miss_list) > 30:
            A(f"\n（共 {len(miss_list)} 首，完整见 `download_queue.json` 与 `results.jsonl`）")

    md_path = os.path.join(out_dir, "榜单曲库报告.md")
    open(md_path, "w", encoding="utf-8").write("\n".join(L))

    print(f"在库 {len(ok)} 首 / {total / 1e9:.2f} GB")
    print(f"  待复核 {len(review)} 首 | 未获取 {len(missing) if missing else len(fails)} 首")
    print("  " + "  ".join(f"{k} {v}" for k, v in quality.most_common()))
    print(f"→ {os.path.basename(md_path)} / 曲库清单.csv / {len(groups)} 个 M3U8")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Music/华语年度金曲"))
