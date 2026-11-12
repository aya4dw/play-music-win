#!/usr/bin/env python3
"""核查每个榜单家族在 Wikipedia 上有哪些可提取的逐届/逐期页面。"""
import sys, re, time
sys.path.insert(0, "skills/music/scripts")
from wiki_chart import api, category_members

FAMILIES = {
    "东方风云榜":      ("第.届东方风云榜", r"^第[一二三四五六七八九十]+届东方风云榜$"),
    "十大中文金曲":    ("第.届十大中文金曲", r"^第[一二三四五六七八九十百]+屆十大中文金曲"),
    "全球华语歌曲排行榜": ("第.届全球华语歌曲排行榜", r"^第[一二三四五六七八九十]+屆全球華語歌曲排行榜"),
    "音乐风云榜":      ("音乐风云榜", r"音乐风云榜"),
    "全球中文音乐榜":  ("全球中文音乐榜", r"全球中文音乐榜"),
    "全球华语榜中榜":  ("全球华语榜中榜", r"全球华语榜中榜|全球华语音乐榜中榜"),
    "叱咤903":        ("叱咤", r"^第[一二三四五六七八九十百]+届叱咤|叱咤903"),
    "金曲奖":          ("金曲奖", r"^第[一二三四五六七八九十百]+届金曲奖|金曲奖"),
    "金针奖":          ("金针奖", r"^第[一二三四五六七八九十百]+届金针奖|金针奖"),
    "新城国语力":      ("新城国语力", r"^第[一二三四五六七八九十百]+届新城国语力|新城国语力"),
    "华语音乐传媒大奖": ("华语音乐传媒大奖", r"^第[一二三四五六七八九十百]+届华语音乐传媒大奖"),
    "Hito流行音乐奖":  ("Hito流行音乐奖", r"^第[一二三四五六七八九十百]+届Hito|Hito流行音乐奖"),
    "亚洲新歌榜":      ("亚洲新歌榜", r"亚洲新歌榜"),
    "Billboard China": ("Billboard China", r"Billboard.*中国|Billboard China|華語榜"),
}

for fam, (q, pat) in FAMILIES.items():
    rx = re.compile(pat)
    found = {}
    cont = None
    for _ in range(4):
        p = {"action": "query", "list": "search", "srsearch": q, "srlimit": 50}
        if cont:
            p["sroffset"] = cont
        j = api(p)
        for r in j.get("query", {}).get("search", []):
            t = r["title"]
            if rx.search(t):
                found[t] = r.get("wordcount", 0)
        cont = j.get("continue", {}).get("sroffset")
        if cont is None:
            break
        time.sleep(0.4)
    titles = sorted(found.keys())
    print(f"\n  ▸ {fam}: {len(titles)} 个候选页面")
    for t in titles[:8]:
        print(f"      {t}")
    if len(titles) > 8:
        print(f"      … 还有 {len(titles)-8} 个")
    time.sleep(0.5)
