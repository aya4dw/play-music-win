#!/usr/bin/env python3
"""核查各华语权威榜单/奖项的存续年限（从 Wikipedia 取权威口径）。"""
import sys, re, time
sys.path.insert(0, "skills/music/scripts")
from wiki_chart import wikitext, category_members

PAGES = [
    "十大中文金曲頒獎音樂會", "叱咤903", "金曲獎", "金針獎", "新城國語力頒獎禮",
    "中國歌曲排行榜", "中國音樂排行榜", "華語音樂傳媒大獎", "Hito流行音樂獎",
    "Hit FM", "Billboard China", "KKBOX", "IFPI香港唱片銷量大獎",
    "東方風雲榜", "全球華語歌曲排行榜", "全球華語流行歌曲榜", "音樂風雲榜",
    "全球中文音樂榜上榜", "全球華語榜中榜", "亞洲新歌榜",
]

PAT = re.compile(
    r"(?:創(办|立)於|成立於|始於|创办于|创办|成立|推出於|第一届|第一屆|首届|"
    r"停(办|止)於|停播|結束|最後一(届|屆)|末(届|屆)|自\s*(\d{4})|(\d{4})\s*年?\s*(?:創|开|開|推))")

for p in PAGES:
    try:
        w = wikitext(p)
    except Exception as e:
        print(f"  ✗ {p}: {e}")
        continue
    # 抓开头的年份线索
    head = re.sub(r"<ref[^>]*>.*?</ref>", "", w[:4000], flags=re.S)
    years = sorted(set(re.findall(r"(1[89]\d{2}|20[0-2]\d)\s*年?", head)))[:14]
    # 找含"创办/成立/停办/终止"的关键句
    clues = []
    for m in re.finditer(r"[^。；\n]{0,70}(?:創辦|创办|成立|推出|停辦|停办|停播|結束|结束|終止|终止|最后一?届|末?届|改為|改为|轉型|转型)[^。；\n]{0,70}", head):
        s = re.sub(r"\s+", "", m.group(0))
        if s not in clues:
            clues.append(s)
    print(f"\n  ▸ {p}  ({len(w)} 字符)")
    print(f"    年份线索: {years}")
    for c in clues[:5]:
        print(f"    · {c[:110]}")
    time.sleep(0.4)
