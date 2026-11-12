#!/usr/bin/env python3
"""
华语权威年度榜 —— 歌单采集 / 去重 / 统计
==========================================
流程：
  1. 发现：种子条目 → 所属分类 → 逐届页面清单
  2. 提取：渲染后 HTML → 歌单条目（分组/歌名/艺人/名次）
            折叠块（候選名單）不计入
  3. 归一：繁简统一(OpenCC) + 全半角 + 去标点 + 艺人别名归并
  4. 去重：标题+艺人精确 → 缺艺人按标题 → 同年代标题模糊
  5. 统计：逐家族 / 逐年 / 重复次数分布

输出 chart_songs.json + chart_entries.json
"""
import sys, re, json, time, unicodedata, difflib
from collections import defaultdict, Counter

sys.path.insert(0, "skills/music/scripts")
from wiki_chart import api, category_members, page_categories, extract as extract_page

import opencc
CC = opencc.OpenCC("t2s")          # 繁體 → 简体

# ---------------------------------------------------------------- 榜单家族
# 只收「有逐届独立条目」的权威奖/榜；regex 用于从分类成员里筛逐届页
FAMILIES = [
    # name, 种子页, 分类, 逐届页 regex, 搜索补充 query
    ("十大中文金曲", "十大中文金曲頒獎音樂會", ["十大中文金曲"],
     r"^第[一二三四五六七八九十百]+屆十大中文金曲.*名單$", None),
    ("东方风云榜", "东方风云榜", ["东方风云榜"],
     r"^第[一二三四五六七八九十百]+届东方风云榜$", None),
    ("叱咤乐坛流行榜", "叱咤903", ["叱咤903", "叱咤樂壇流行榜"],
     r"^\d{4}年度叱咤樂壇流行榜頒獎典禮得獎名單$",
     "intitle:叱咤樂壇流行榜頒獎典禮得獎名單"),
    ("全球华语歌曲排行榜", "全球華語歌曲排行榜", ["全球華語歌曲排行榜"],
     r"^第[一二三四五六七八九十]+屆全球華語歌曲排行榜$", None),
    ("新城国语力", "新城國語力頒獎禮", ["新城國語力"],
     r"^\d{4}年度新城國語力頒獎禮得獎名單$",
     "intitle:新城國語力頒獎禮得獎名單"),
    ("金曲奖", "金曲獎", ["金曲獎"],
     r"^第\d+屆金曲獎$", "intitle:屆金曲獎"),
    ("音乐风云榜", "音乐风云榜年度盛典", ["音乐风云榜"],
     r"^第[一二三四五六七八九十百]+届音乐风云榜", "intitle:音乐风云榜颁奖盛典"),
]

# ---------------------------------------------------------------- 归一化
PUNCT = re.compile(
    r"[\s\u3000《》〈〉「」『』()（）\[\]【】{}<>\"'“”‘’,，.。·・:：;；!！?？\-—–_/\\|~～+&]"
)
# 艺人别名（右侧为规范名）—— 常见简称/组合写法
ARTIST_ALIAS = {
    "gem": "邓紫棋", "gem邓紫棋": "邓紫棋", "鄧紫棋": "邓紫棋",
    "jj": "林俊杰", "jj林俊杰": "林俊杰",
    "jolin": "蔡依林", "蔡依林jolin": "蔡依林",
    "eason": "陈奕迅", "陈奕迅eason": "陈奕迅",
    "jay": "周杰伦", "周杰伦jay": "周杰伦",
    "amei": "张惠妹", "张惠妹amei": "张惠妹",
    "mayday": "五月天",
    "sodagreen": "苏打绿",
    "fir": "飞儿乐团",
    "twins": "twins",
}
# 艺人后缀噪声
ARTIST_SUFFIX = ("乐队", "樂隊", "组合", "組合", "合唱", "群星", "等")


def to_simp(s):
    return CC.convert(s or "")


def norm_title(t):
    t = to_simp(t)
    t = PUNCT.sub("", t)
    return unicodedata.normalize("NFKC", t).lower()


def norm_artist(a):
    a = to_simp(a)
    # 只取第一个艺人（feat./、/&）
    a = re.split(r"、|,|，|&|／|/|feat\.|ft\.|with", a, flags=re.I)[0]
    a = PUNCT.sub("", a)
    a = unicodedata.normalize("NFKC", a).lower()
    a = ARTIST_ALIAS.get(a, a)
    for suf in ARTIST_SUFFIX:
        if a.endswith(suf) and len(a) > len(suf) + 1:
            a = a[: -len(suf)]
    return a


# ---------------------------------------------------------------- 发现
def search_titles(query, rx, max_pages=8):
    """MediaWiki 搜索 + 正则过滤（补充分类遍历的盲区）。"""
    out, offset, pages = set(), None, 0
    while pages < max_pages:
        p = {"action": "query", "list": "search", "srsearch": query,
             "srlimit": 50, "srnamespace": 0}
        if offset:
            p["sroffset"] = offset
        j = api(p)
        for r in j.get("query", {}).get("search", []):
            if re.match(rx, r["title"]):
                out.add(r["title"])
        offset = j.get("continue", {}).get("sroffset")
        pages += 1
        if not offset:
            break
        time.sleep(0.25)
    return out


def discover(seed, cats, rx, query=None):
    allcats = list(cats)
    try:
        allcats += page_categories(seed)
    except Exception:
        pass
    titles = set()
    for c in dict.fromkeys(allcats):
        try:
            for t in category_members(c, 500):
                if re.match(rx, t):
                    titles.add(t)
        except Exception:
            pass
    if query:
        titles |= search_titles(query, rx)
    return sorted(titles)


# ---------------------------------------------------------------- 去重索引
class SongIndex:
    """标题 + 艺人 的去重索引。"""

    def __init__(self):
        self.songs = {}                       # id -> record
        self.by_key = {}                      # (nt, na) -> id
        self.by_title = defaultdict(list)     # nt -> [id]

    def add(self, title, artist, meta):
        nt, na = norm_title(title), norm_artist(artist)
        if not nt:
            return None
        hit = self._lookup(nt, na, meta.get("year"))
        if hit is None:
            sid = f"s{len(self.songs):05d}"
            self.songs[sid] = {
                "nt": nt, "na": na,
                "titles": Counter(), "artists": Counter(),
                "families": set(), "years": set(), "groups": set(),
                "entries": [],
            }
            hit = sid
        r = self.songs[hit]
        r["titles"][title] += 1
        if artist:
            r["artists"][artist] += 1
        r["families"].add(meta["family"])
        if meta.get("year"):
            r["years"].add(meta["year"])
        if meta.get("group"):
            r["groups"].add(meta["group"])
        r["entries"].append(meta)
        self.by_key[(nt, na)] = hit
        if hit not in self.by_title[nt]:
            self.by_title[nt].append(hit)
        return hit

    def _lookup(self, nt, na, year):
        # 1) 标题 + 艺人 精确
        if na and (nt, na) in self.by_key:
            return self.by_key[(nt, na)]
        cands = self.by_title.get(nt, [])
        if cands:
            if na:
                for sid in cands:
                    other = self.songs[sid]["na"]
                    if not other:
                        return sid
                    if na in other or other in na:
                        return sid
            else:
                # 无艺人：标题唯一才归并
                if len(cands) == 1:
                    return cands[0]
        # 2) 同年代窗口内标题模糊
        best, best_r = None, 0.0
        for nt2, sids in self.by_title.items():
            if abs(len(nt2) - len(nt)) > 4:
                continue
            r = difflib.SequenceMatcher(None, nt, nt2).ratio()
            if r <= best_r:
                continue
            for sid in sids:
                yrs = self.songs[sid]["years"]
                if year and yrs and min(abs(year - y) for y in yrs) > 3:
                    continue
                best, best_r = sid, r
        if best and best_r >= 0.90:
            return best
        return None


# ---------------------------------------------------------------- 主流程
def main():
    idx = SongIndex()
    rows = []
    skipped = Counter()

    for fam, seed, cats, rx, query in FAMILIES:
        titles = discover(seed, cats, rx, query)
        if not titles:
            print(f"  ▸ {fam:<12} 未发现逐届页面")
            continue
        n_entries = 0
        for t in titles:
            try:
                r = extract_page(t)
            except Exception as e:
                skipped[fam] += 1
                time.sleep(0.4)
                continue
            for g in r.get("all_songs", []):
                idx.add(g["song"], g.get("artist", ""), {
                    "family": fam, "year": r.get("year"), "page": t,
                    "group": g.get("group"), "rank": g.get("rank"),
                })
                n_entries += 1
            time.sleep(0.35)
        yrs = sorted({e["year"] for s in idx.songs.values() for e in s["entries"]
                      if e["family"] == fam and e["year"]})
        rows.append((fam, len(titles), n_entries, (yrs[0], yrs[-1]) if yrs else None,
                     sum(1 for s in idx.songs.values() if fam in s["families"])))
        span = f"{yrs[0]}–{yrs[-1]}" if yrs else "—"
        print(f"  ▸ {fam:<12} {len(titles):>3} 页 / {n_entries:>5} 条目 / {span}")

    like = len([1 for s in idx.songs.values()])   # noqa: F841

    # ---------------- 统计 ----------------
    total_entries = sum(r[2] for r in rows)
    print("\n" + "=" * 70)
    print("【权威年度榜 · 去重统计】")
    print("=" * 70)
    print(f"{'榜单家族':<20}{'页面':>5}{'条目':>8}{'去重歌曲':>10}   年份区间")
    print("-" * 70)
    for fam, np_, ne, yr, ns in rows:
        span = f"{yr[0]}–{yr[1]}" if yr else "—"
        print(f"{fam:<20}{np_:>5}{ne:>8}{ns:>10}   {span}")
    print("-" * 70)
    print(f"{'合计':<20}{'':>5}{total_entries:>8}{len(idx.songs):>10}")
    dup = total_entries - len(idx.songs)
    pct = 100 * dup / total_entries if total_entries else 0
    print(f"\n  重复条目 {dup} 条（{pct:.1f}%），去重后唯一歌曲 {len(idx.songs)} 首")

    # 年份分布
    yr_cnt = defaultdict(int)
    for s in idx.songs.values():
        for y in (s["years"] or {None}):
            yr_cnt[y] += 1
    print("\n【唯一歌曲 · 年份分布】")
    line = []
    for y in sorted(k for k in yr_cnt if k):
        line.append(f"{y}:{yr_cnt[y]}")
    print("  " + "  ".join(line))
    missing = [y for y in range(1980, 2027) if y not in yr_cnt]
    if missing:
        print(f"  缺年份: {missing}")

    # 跨年/跨榜重复最多的歌
    print("\n【重复出现最多的 15 首】")
    top = sorted(idx.songs.values(), key=lambda s: len(s["entries"]), reverse=True)[:15]
    for s in top:
        t = s["titles"].most_common(1)[0][0]
        a = s["artists"].most_common(1)[0][0] if s["artists"] else "?"
        print(f"  {len(s['entries']):>3} 次  {a}《{t}》  [{','.join(sorted(s['families']))}] {sorted(s['years'])}")

    # ---------------- 输出 ----------------
    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "families": [
            {"family": f, "pages": p, "entries": e, "songs": n,
             "year_from": y[0] if y else None, "year_to": y[1] if y else None}
            for f, p, e, y, n in rows
        ],
        "total_entries": total_entries,
        "total_songs": len(idx.songs),
        "duplicate_entries": dup,
        "songs": [
            {
                "id": sid,
                "title": s["titles"].most_common(1)[0][0],
                "title_variants": [t for t, _ in s["titles"].most_common()],
                "artist": s["artists"].most_common(1)[0][0] if s["artists"] else "",
                "artist_variants": [a for a, _ in s["artists"].most_common()],
                "families": sorted(s["families"]),
                "years": sorted(y for y in s["years"] if y),
                "groups": sorted(g for g in s["groups"] if g),
                "occurrences": len(s["entries"]),
            }
            for sid, s in idx.songs.items()
        ],
    }
    with open("chart_songs.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    with open("chart_entries.json", "w") as f:
        json.dump([e for s in idx.songs.values() for e in s["entries"]],
                  f, ensure_ascii=False, indent=1)
    print(f"\n→ chart_songs.json     {len(idx.songs)} 首")
    print(f"→ chart_entries.json   {total_entries} 条原始条目")


if __name__ == "__main__":
    main()
