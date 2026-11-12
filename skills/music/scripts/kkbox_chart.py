#!/usr/bin/env python3
"""KKBOX 榜单抓取器 —— 解析 kma.kkbox.com 的周榜/新歌榜历史页。"""
import re, html, json, sys, time, urllib.request, urllib.error

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

TAGS = ("charts-list-rank", "charts-list-prev-rank", "charts-list-song",
        "charts-list-artist", "charts-list-date")


def fetch(url, tries=3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            time.sleep(1.5)
    raise last


def _text(blk, cls):
    m = re.search(r'class="' + cls + r'"[^>]*>(.*?)</', blk, re.S)
    if not m:
        return ""
    t = re.sub(r"<[^>]+>", "", m.group(1))
    return html.unescape(t).strip()


def parse(h):
    """从页面提取榜单条目。返回 (entries, has_data)。"""
    entries = []
    for m in re.finditer(r'<li class="charts-list-row"[^>]*>(.*?)</li>', h, re.S):
        blk = m.group(1)
        song = _text(blk, "charts-list-song")
        if not song:
            continue
        entries.append({
            "rank": _text(blk, "charts-list-rank"),
            "prev_rank": _text(blk, "charts-list-prev-rank"),
            "song": song,
            "artist": _text(blk, "charts-list-artist"),
            "release_date": _text(blk, "charts-list-date"),
            "unauthorized": "charts-list-unauth" in blk,
        })
    return entries


def chart_url(date=None, chart="weekly/newrelease", terr="tw", lang="tc", cate="297"):
    u = f"https://kma.kkbox.com/charts/{chart}?terr={terr}&lang={lang}&cate={cate}"
    if date:
        u += f"&date={date}"
    return u


def get(date=None, chart="weekly/newrelease", terr="tw", lang="tc", cate="297"):
    h = fetch(chart_url(date, chart, terr, lang, cate))
    return parse(h), h


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if mode == "probe":
        for d in sys.argv[2:]:
            try:
                e, h = get(d)
                print(f"  date={d}  size={len(h):>7}  entries={len(e)}")
                for x in e[:3]:
                    print(f"      #{x['rank']} {x['song']} - {x['artist']} | {x['release_date']}")
            except Exception as ex:
                print(f"  date={d}  ERROR {ex}")
    elif mode == "json":
        e, _ = get(sys.argv[2] if len(sys.argv) > 2 else None)
        print(json.dumps(e, ensure_ascii=False, indent=2))
