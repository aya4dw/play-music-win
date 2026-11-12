#!/usr/bin/env python3
"""
把去重后的榜单歌单转成下载队列。

输入: chart_songs.json
输出: download_queue.json  [{n, title, artist, artist_full, year, families, years}]

清洗规则：
  · 剔除奖项名被误当歌名的条目（如《歌曲》）
  · 剔除无艺人条目（无法可靠匹配，避免下错同名歌）
  · 艺人取第一位（多人群唱取首位），用于搜索与命名
  · 歌名去掉尾部语言/版本注释
"""
import json
import re
import sys

import opencc

CC = opencc.OpenCC("t2s")   # 音源（QQ/酷我/网易/咪咕）以简体为主

BOGUS_TITLES = {
    "歌曲", "編號", "编号", "排名", "歌名", "曲名", "演唱", "主唱",
    "獎項", "奖项", "金曲", "十大中文金曲", "十大中文金曲獎", "待定",
}
WIKI_NOTE = re.compile(r"\[\s*(?:註|注|nb|Note)?\s*\d+\s*\]", flags=re.I)
TAIL_NOTE = re.compile(
    r"\s*[（(]\s*(?:粤语|粵語|国语|國語|粤|粵|国|國|live|Live|LIVE|"
    r"remix|Remix|版|伴奏|纯音乐|純音樂)\s*[：:]?\s*[^）)]{0,12}[）)]\s*$"
)


def clean_title(t):
    t = CC.convert((t or "").strip())
    t = WIKI_NOTE.sub("", t).strip()
    prev = None
    while prev != t:
        prev = t
        t = TAIL_NOTE.sub("", t).strip()
    return t


AWARD_ARTIST = ("最佳", "唱片", "大碟", "专辑", "專輯", "EP", "原聲", "原声", "入圍", "入围", "大獎", "大奖", "金獎", "金奖", "銀獎", "银奖",
                "至尊", "最受歡迎", "最受欢迎", "傳媒", "传媒", "榮譽", "荣誉",
                "新人", "優秀", "优秀", "唱作", "年度")


def looks_like_award(a):
    return any(k in (a or "") for k in AWARD_ARTIST)


def primary_artist(a):
    a = CC.convert((a or "").strip())
    a = WIKI_NOTE.sub("", a).strip()
    a = re.split(r"\s*(?:、|,|，|&|／|/|feat\.|ft\.|with)\s*", a, flags=re.I)[0]
    return a.strip()


def main(src="chart_songs.json", out="download_queue.json"):
    d = json.load(open(src))
    queue, dropped = [], {"bogus": 0, "no_artist": 0}

    rows = sorted(d["songs"], key=lambda s: (min(s["years"]) if s["years"] else 9999,
                                             s["artist"], s["title"]))
    for s in rows:
        title = clean_title(s["title"])
        artist_full = (s["artist"] or "").strip()
        artist = primary_artist(artist_full)
        if not title or title in BOGUS_TITLES:
            dropped["bogus"] += 1
            continue
        if not artist or looks_like_award(artist):
            dropped["no_artist"] += 1
            continue
        queue.append({
            "n": len(queue) + 1,
            "title": title,
            "artist": artist,
            "artist_full": CC.convert(artist_full),
            "year": min(s["years"]) if s["years"] else None,
            "years": s["years"],
            "families": s["families"],
            "occurrences": s["occurrences"],
        })

    json.dump(queue, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"队列 {len(queue)} 首  →  {out}")
    print(f"  剔除：奖项名 {dropped['bogus']} / 无艺人 {dropped['no_artist']}")
    from collections import Counter
    c = Counter(q["year"] for q in queue)
    print("  年份分布:", " ".join(f"{y}:{c[y]}" for y in sorted(k for k in c if k)))


if __name__ == "__main__":
    main(*sys.argv[1:])
