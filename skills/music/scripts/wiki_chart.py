#!/usr/bin/env python3
"""
Wikipedia 华语权威榜单 —— 歌单提取器
====================================
维基百科上华语榜单条目的歌单承载形式：

  A. bullet 列表   *十大金曲 → **[[刘惜君]]《怎么唱情歌》   （嵌套 <li>）
  B. wikitable     編號/歌曲/主唱/作曲…                     （全球华语榜、十大中文金曲等）

统一走**渲染后 HTML**：
  · 表格是干净的 <table>/<th>/<td>
  · 模板/转写生成的内容在 wikitext 里是空壳，只有渲染后才有真实歌单
  · 歌名与艺人已分离为独立节点

依赖: wikipedia / requests / beautifulsoup4 / lxml
"""
import re, sys, time, requests, wikipedia
from bs4 import BeautifulSoup

UA = "play-music-chartdata/0.1 (research; https://github.com/aya4dw/play-music)"
API = "https://zh.wikipedia.org/w/api.php"
REST = "https://zh.wikipedia.org/api/rest_v1"
wikipedia.set_user_agent(UA)
wikipedia.set_rate_limiting(rate_limit=0.3)

_s = requests.Session()
_s.headers["User-Agent"] = UA


def api(params, retries=5):
    params = {**params, "format": "json", "formatversion": "2"}
    delay = 2.0
    for _ in range(retries):
        r = _s.get(API, params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", delay)))
            delay = min(delay * 2, 60)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("API 重试耗尽")


def wikitext(title):
    j = api({"action": "query", "prop": "revisions", "rvprop": "content",
             "rvslots": "main", "titles": title})
    p = j["query"]["pages"][0]
    if p.get("missing"):
        raise KeyError(title)
    return p["revisions"][0]["slots"]["main"]["content"]


def html_of(title):
    r = _s.get(f"{REST}/page/html/{title}", timeout=40)
    if r.status_code == 200:
        return r.text
    j = api({"action": "parse", "page": title, "prop": "text"})
    t = j["parse"]["text"]
    return t if isinstance(t, str) else t["*"]


def page_categories(title):
    """取页面所属分类（用于自动发现逐届页面）。"""
    j = api({"action": "query", "prop": "categories", "cllimit": 500, "titles": title})
    p = j["query"]["pages"][0]
    return [c["title"][len("Category:"):] for c in p.get("categories", [])]


def category_members(cat, limit=500):
    j = api({"action": "query", "list": "categorymembers",
             "cmtitle": f"Category:{cat}", "cmlimit": limit})
    return [m["title"] for m in j["query"]["categorymembers"]]


# ---------------- 表头语义 ----------------
COL_SONG = ("歌曲", "歌名", "曲目", "曲名", "song", "作品名稱", "作品名称")
COL_ARTIST = ("主唱", "歌手", "歌者", "演唱", "藝人", "artist", "singer", "組合", "组合", "演唱者")
COL_RANK = ("排名", "編號", "编号", "rank", "順位", "名次", "次序", "序號")

# 只有「歌曲类」分组才收；排除唱片/专辑/歌手/新人等
SONG_GROUP_KEYS = ("金曲", "歌曲", "对唱", "對唱", "最佳歌曲", "熱門歌曲", "热门歌曲", "歌曲獎", "歌曲奖", "十大")
# 这些分组是「候选/投票/走势」，不是获奖名单
NON_AWARD_GROUP = ("投票", "二十強", "二十强", "十強", "十强", "走勢", "走势", "速報", "速报",
                   "候選", "候选", "入圍", "入围", "提名", "最後", "最后")
NON_SONG_KEYS = ("唱片", "專輯", "专辑", "歌手", "新人", "樂隊", "组合", "組合", "作詞", "作曲",
                 "編曲", "监制", "監製", "填詞", "填词", "出品", "唱片公司", "演出版本",
                 "最佳专辑", "最佳唱片", "樂團", "組合", "作曲人", "作詞人")


def clean(s):
    # 脚注：[1] / [ 註 1 ] / [ 注 1 ] / [nb 1] —— 不清掉会污染艺人与歌名
    s = re.sub(r"\[\s*(?:註|注|nb|Note)?\s*\d+\s*\]", "", s or "", flags=re.I)
    s = s.replace("\xa0", " ").replace("", "")
    return re.sub(r"\s+", " ", s).strip()


def tidy_artist(a):
    a = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", a or "")
    a = re.sub(r"\s*[、,，]\s*", "、", a)
    return re.sub(r"\s+", " ", a).strip()


def norm_head(h):
    return re.sub(r"[\s　()（）\[\]【】:：/／·、,，]+", "", h).lower()


NON_AWARD_SECTION = ("落選", "落选", "候選", "候选", "其他入圍", "入圍名單", "入围名单", "提名",
                     "歌曲補充資料", "歌曲补充资料", "原曲", "翻唱")


def is_non_award_section(name):
    """落选/候选/提名段落不属于获奖名单。"""
    return any(k in (name or "") for k in NON_AWARD_SECTION)


def is_song_group(name):
    n = name or ""
    if any(k in n for k in NON_SONG_KEYS):
        return False
    if any(k in n for k in NON_AWARD_GROUP):
        return False
    return any(k in n for k in SONG_GROUP_KEYS)


BOOK = re.compile(r"[《》〈〉「」『』]")


def strip_book(s):
    return BOOK.sub("", s or "").strip(" -—–、,，")


# 歌名尾部的语言/版本注释，如「（粤语：）」「（國）」「(Live版)」
TAIL_NOTE = re.compile(
    r"\s*[（(]\s*(?:粤语|粵語|国语|國語|粤|粵|国|國|live|Live|LIVE|remix|Remix|版|伴奏|纯音乐|純音樂)\s*[：:]?\s*[^）)]{0,12}[）)]\s*$"
)
# 歌名之后的艺人标记：《歌名》——（主唱：某某 作曲：…）
ARTIST_AFTER = re.compile(
    r"(?:主唱|演唱|歌手|歌者)\s*[：:]\s*([^\s（）()\[\]【】,，、/／]+)"
    r"|(?:——|—|–|-{1,2})\s*([^\s（）()\[\]【】,，、/／《》]+)"
)


def tidy_song(s):
    s = strip_book(s)
    prev = None
    while prev != s:
        prev = s
        s = TAIL_NOTE.sub("", s).strip()
    return s


def parse_table(tbl):
    """提取歌单；表头行 = 含最多 <th> 且不是「整表标题行」的行。"""
    rows = tbl.find_all("tr")
    if not rows:
        return []
    maxcells = max((len(tr.find_all(["th", "td"])) for tr in rows), default=0)
    hi, heads, ncol = None, [], 0
    for i, tr in enumerate(rows):
        ths = tr.find_all("th")
        if not ths:
            continue
        cand, span_total = [], 0
        for th in ths:
            txt = clean(th.get_text(" ", strip=True))
            span = 1
            cs = th.get("colspan")
            if cs and str(cs).isdigit():
                span = min(int(cs), 20)
            span_total += span
            cand.extend([txt] * span)
        # 整表标题行：只有 1 个单元格，而表有多列
        if len(tr.find_all(["th", "td"])) <= 1 and maxcells >= 2:
            title_txt = " ".join(c.strip() for c in cand if c.strip())
            if is_non_award_section(title_txt) and not any(
                    k in title_txt for k in ("得獎", "得奖", "獲獎", "获奖")):
                return []          # 「候選名單」整表不是获奖名单
            continue
        if hi is None or len(cand) > len(heads):
            hi, heads, ncol = i, cand, span_total
    if hi is None or not heads:
        return []
    ncol = max(ncol, len(heads))

    def find_col(keys):
        for i, h in enumerate(heads):
            if any(k in norm_head(h) for k in keys):
                return i
        return None

    i_song = find_col(COL_SONG)
    i_art = find_col(COL_ARTIST)
    i_rank = find_col(COL_RANK)
    if i_song is None:
        return []
    i_award = None
    for i, h in enumerate(heads):
        if any(k in norm_head(h) for k in ("獎項", "奖项", "獎", "奖")):
            i_award = i
            break

    out = []
    for tr in rows[hi + 1:]:
        tds = tr.find_all(["td", "th"])
        if not tds:
            continue
        cells = [clean(td.get_text(" ", strip=True)) for td in tds]
        if len(cells) < ncol:
            cells += [""] * (ncol - len(cells))
        song = tidy_song(cells[i_song])
        if not song or song in ("-", "—", "待定", "TBD"):
            continue
        if any(song == norm_head(h) or song == h for h in heads):
            continue
        artist = tidy_artist(strip_book(cells[i_art])) if i_art is not None else ""
        rank = cells[i_rank] if i_rank is not None else ""
        award = strip_book(cells[i_award]) if i_award is not None else ""
        out.append({"song": song, "artist": artist, "rank": rank or None, "award": award})
    return out


def heading_before(node):
    for prev in node.find_all_previous(["h2", "h3", "h4", "h5"], limit=1):
        return clean(prev.get_text(" ", strip=True))
    return ""


GENERIC_HEAD = ("获奖名单", "獲獎名單", "得獎名單", "得奖名单", "奖项", "獎項", "获颁奖项")


def parent_group(li):
    """
    分组名来源（按优先级）:
      1. 祖先 <li> 的直接文本（嵌套结构，如「十大金曲」下的歌单）
      2. 前方最近的具体小节标题（非「获奖名单」这类容器名）
      3. 前一个非歌曲 <li>（平级结构：*分组名 / 换行后跟歌曲列表）
      4. 容器型小节标题兜底
    """
    for anc in li.find_parents("li"):
        direct = anc.find(string=True, recursive=False)
        txt = clean(direct) if direct else ""
        if txt:
            txt = txt.split("：")[0].split(":")[0].strip()
            if txt:
                return txt
    head = heading_before(li)
    if head and not any(g in head for g in GENERIC_HEAD):
        return head
    for prev in li.find_all_previous("li"):
        txt = clean(prev.get_text(" ", strip=True))
        if not txt or "《" in txt or len(txt) > 40:
            continue
        return txt.split("：")[0].split(":")[0].strip()
    return head or "未分组"


_TABLE_GROUPS = set()


def parse_html(html):
    soup = BeautifulSoup(html, "lxml")
    groups = {}
    _TABLE_GROUPS.clear()

    # A. bullet 列表
    for li in soup.select("li"):
        m = re.search(r"《([^》]+)》", li.get_text(" ", strip=True))
        if not m:
            continue
        # 排除外层容器 li（它包含内层所有歌名）
        if li.select("li"):
            continue
        song = tidy_song(clean(m.group(1)))
        if not song:
            continue
        txt = li.get_text(" ", strip=True)
        before = txt[:m.start()]
        # 艺人：歌名前的链接文字优先
        links = [clean(a.get_text(" ", strip=True)) for a in li.find_all("a")]
        artist = ""
        for a in links:
            if not a or a == song or len(a) > 30:
                continue
            if re.fullmatch(r"[\[\]（）()\s]*(?:註|注|nb)?\s*\d*[\[\]（）()\s]*", a, flags=re.I):
                continue
            artist = a
            break
        if not artist:
            tail = txt[m.end():]
            am = ARTIST_AFTER.search(tail)
            if am:
                artist = clean(am.group(1) or am.group(2) or "")
        if not artist:
            artist = clean(re.sub(r"[·、,，:：\-—–()（）《》]", " ", before))
        artist = tidy_artist(re.sub(r"\s+", " ", artist).strip())
        if len(artist) > 40:
            artist = ""
        if is_non_award_section(heading_before(li)) or is_non_award_section(parent_group(li)):
            continue
        g = parent_group(li) or heading_before(li)
        groups.setdefault(g, []).append({"song": song, "artist": artist, "rank": None})

    # B. 所有表格（含无 wikitable 类的老式 border=1 表格）
    for tbl in soup.find_all("table"):
        # 折叠块里的表格是「候選名單」，不是获奖名单 → 跳过
        if tbl.find_parent("div", class_="mw-collapsible"):
            continue
        if is_non_award_section(heading_before(tbl)):
            continue
        entries = parse_table(tbl)
        if not entries:
            continue
        cap = tbl.find("caption")
        cap_txt = clean(cap.get_text(" ", strip=True)) if cap else ""
        # caption 明确是候選/入圍名單 → 不是获奖名单
        if cap_txt and is_non_award_section(cap_txt) and not any(k in cap_txt for k in ("得獎", "得奖", "獲獎", "获奖")):
            continue
        if cap_txt:
            _TABLE_GROUPS.add(cap_txt)
        head_txt = heading_before(tbl)
        if cap_txt:
            for e in entries:
                # 行内「獎項」优先，其次 caption
                groups.setdefault(e.get("award") or cap_txt, []).append(
                    {k: v for k, v in e.items() if k != "award"})
        else:
            _TABLE_GROUPS.add(head_txt)
            for e in entries:
                groups.setdefault(e.get("award") or head_txt, []).append(
                    {k: v for k, v in e.items() if k != "award"})

    return {k: v for k, v in groups.items() if v}


def page_year(html, title):
    """从页面推断年份（Infobox date 优先，其次正文首个四位年份）。"""
    soup = BeautifulSoup(html, "lxml")
    for inf in soup.select("table.infobox"):
        for tr in inf.select("tr"):
            th = tr.find("th")
            tds = tr.find_all("td")
            if th and tds:
                k = norm_head(th.get_text(" ", strip=True))
                if k in ("date", "日期", "舉行日期", "举行日期", "年"):
                    m = re.search(r"(1[89]\d{2}|20[0-2]\d)", tds[0].get_text(" ", strip=True))
                    if m:
                        return int(m.group(1))
    m = re.match(r"^(\d{4})年度", title or "")
    if m:
        return int(m.group(1))
    m = re.search(r"(1[89]\d{2}|20[0-2]\d)", soup.get_text(" ", strip=True)[:1500])
    return int(m.group(1)) if m else None


def extract(title):
    """提取歌单。返回 all_songs（含分组），便于统计入围条目。"""
    html = html_of(title)
    g = parse_html(html)
    song_groups = {k: v for k, v in g.items() if is_song_group(k)}
    all_songs = []
    for grp, items in song_groups.items():
        for it in items:
            all_songs.append({"group": grp, **it})
    return {"title": title, "html": len(html), "groups": len(song_groups),
            "year": page_year(html, title),
            "songs": len(all_songs), "sample": all_songs[:3],
            "group_names": list(song_groups.keys())[:10],
            "all_groups": list(g.keys())[:10],
            "all_songs": all_songs}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--cat":
        cat = sys.argv[2]
        titles = category_members(cat)
        print(f"分类 Category:{cat} → {len(titles)} 页\n")
        tot = 0
        for t in titles:
            try:
                r = extract(t)
                tot += r["songs"]
                flag = "✓" if r["songs"] else "·"
                print(f"  {flag} {r['songs']:>4} 首 / {r['groups']:>2} 组   {t}")
                for s in r["sample"][:1]:
                    print(f"          例: {s['artist']}《{s['song']}》")
            except Exception as e:
                print(f"  ✗ {t}: {type(e).__name__} {e}")
            time.sleep(0.4)
        print(f"\n  合计 {tot} 首")
    else:
        for t in sys.argv[1:]:
            try:
                r = extract(t)
                print(f"  {r['songs']:>4} 首 / {r['groups']:>2} 组   {r['title']}")
                print(f"        歌曲分组: {r['group_names']}")
                print(f"        其它分组: {[g for g in r['all_groups'] if g not in r['group_names']][:5]}")
                for s in r["sample"][:3]:
                    print(f"        例: {s['artist']}《{s['song']}》")
            except Exception as e:
                print(f"  ✗ {t}: {type(e).__name__} {e}")
