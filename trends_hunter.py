"""
US Realtime Google Trends Hunter for Zelmu Clipping.
Fetches pre-peak USA breakout trends from:
https://trends.google.com/trending?geo=US&status=active&hours=4&sort=recency
Directly parses the native ds:0 payload without 3rd-party API keys or rate limits.
"""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import re
import json
import time
import datetime
import subprocess
from typing import List, Dict, Any, Optional
from transcriber import get_ytdlp_cmd


CATEGORIES = {
    "all": {"label": "🌐 All Categories", "cat_id": 0, "default_suffix": ""},
    "entertainment": {"label": "🎬 Entertainment & Pop Culture", "cat_id": 3, "default_suffix": "reaction"},
    "sports": {"label": "⚽ Sports & Highlights", "cat_id": 20, "default_suffix": "highlights"},
    "gaming": {"label": "🎮 Gaming & Esports", "cat_id": 8, "default_suffix": "gameplay"},
    "news": {"label": "📰 News & Politics", "cat_id": 16, "default_suffix": "news"},
    "tech": {"label": "💻 Tech & Science", "cat_id": 5, "default_suffix": "explained"},
    "business": {"label": "📈 Business & Finance", "cat_id": 7, "default_suffix": ""}
}


def _format_time_ago(timestamp: float) -> str:
    """Formats epoch timestamp into relative time (e.g. '20 minutes ago', '2 hours ago')."""
    now = time.time()
    diff = max(0, int(now - timestamp))
    mins = diff // 60
    if mins < 60:
        return f"{max(1, mins)} minutes ago"
    hours = mins // 60
    return f"{hours} hour ago" if hours == 1 else f"{hours} hours ago"


def get_trend_news_articles(query: str, max_articles: int = 3) -> List[Dict[str, str]]:
    """Fetches top recent news headline links for a trending topic via Google News RSS."""
    clean_q = urllib.parse.quote(query.strip())
    url = f"https://news.google.com/rss/search?q={clean_q}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    articles = []
    try:
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            root = ET.fromstring(resp.read())
            for item in root.findall(".//item")[:max_articles]:
                t = item.find("title")
                l = item.find("link")
                pub = item.find("source")
                source_name = pub.text if pub is not None and pub.text else "News"
                if t is not None and l is not None and t.text and l.text:
                    articles.append({
                        "title": t.text.strip(),
                        "url": l.text.strip(),
                        "source": source_name
                    })
    except Exception:
        pass
    return articles


def fetch_google_trends_us(
    geo: str = "US",
    hours: int = 4,
    sort: str = "recency",
    status: str = "active",
    category_id: int = 0,
    include_news: bool = True
) -> List[Dict[str, Any]]:
    """
    Fetches real-time breakout trends across All Categories or specific category from:
    https://trends.google.com/trending?geo=US&status=active&hours=4&sort=recency
    Extracts all table columns:
    - Trends Time
    - Search Vol (+ growth %)
    - Started time (e.g. '20 minutes ago', Active status)
    - Trend breakdown(all)
    - In the news links
    - Search link
    - Explore link
    """
    cat_param = f"&cat={category_id}" if category_id and category_id > 0 else ""
    url = f"https://trends.google.com/trending?geo={geo}&status={status}&hours={hours}&sort={sort}{cat_param}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8")

        m = re.search(r'AF_initDataCallback\((\{key:\s*\'ds:0\'.*?\})\);', text, re.DOTALL)
        if not m:
            return fetch_google_trends_rss_fallback(geo=geo)
        content = m.group(1)
        data_match = re.search(r'data:\s*(\[.*?\])\s*,\s*sideChannel', content, re.DOTALL)
        if not data_match:
            data_match = re.search(r'data:\s*(\[.*?\])\s*\}\s*$', content, re.DOTALL)
        if not data_match:
            return fetch_google_trends_rss_fallback(geo=geo)

        parsed = json.loads(data_match.group(1))
        items = parsed[1] if len(parsed) > 1 and isinstance(parsed[1], list) else []
        snapshot_time_str = datetime.datetime.now().strftime("%m/%d/%y, %I:%M %p")

        results = []
        for it in items:
            if not isinstance(it, list) or len(it) == 0:
                continue
            query = it[0]
            if not query:
                continue

            # Timestamp when trend started
            started_ts = float(it[3][0]) if len(it) > 3 and it[3] and isinstance(it[3], list) else time.time()
            started_str = _format_time_ago(started_ts)

            # Search volume and growth percentage
            traffic = it[6] if len(it) > 6 and it[6] is not None else 0
            pct_raw = it[8] if len(it) > 8 and it[8] is not None else 0
            pct_formatted = f"+{pct_raw*10}%" if pct_raw > 0 else ""

            if isinstance(traffic, (int, float)) and traffic >= 1000:
                vol_str = f"{traffic//1000}K+" if traffic < 1000000 else f"{traffic//1000000}M+"
            elif isinstance(traffic, (int, float)) and traffic > 0:
                vol_str = f"{traffic}+"
            else:
                vol_str = "Rising"

            search_vol_display = f"{vol_str} ({pct_formatted})" if pct_formatted else vol_str

            # Trend breakdown (all related keywords / subqueries)
            breakdown_list = it[9] if len(it) > 9 and isinstance(it[9], list) else []

            # Direct links
            encoded_q = urllib.parse.quote(str(query))
            search_link = f"https://www.google.com/search?q={encoded_q}"
            explore_link = f"https://trends.google.com/trends/explore?q={encoded_q}&geo={geo}"

            results.append({
                "query": query,
                "search_vol": traffic,
                "search_vol_fmt": vol_str,
                "search_vol_display": search_vol_display,
                "growth_pct": pct_formatted,
                "started_time": started_str,
                "started_ts": started_ts,
                "is_active": True,
                "trend_breakdown": breakdown_list,
                "breakdown_display": " · ".join(breakdown_list[:5]) if breakdown_list else query,
                "search_link": search_link,
                "explore_link": explore_link,
                "trends_time": snapshot_time_str,
                "news_articles": []  # Loaded on demand or batch
            })

        # Explicitly sort: recent trends first (highest started_ts first)
        if sort == "recency":
            results.sort(key=lambda x: x.get("started_ts", 0), reverse=True)
        elif sort == "search-volume":
            results.sort(key=lambda x: x.get("search_vol", 0), reverse=True)

        return results if results else fetch_google_trends_rss_fallback(geo=geo)
    except Exception as e:
        print(f"Error fetching Google Trends: {e}")
        return fetch_google_trends_rss_fallback(geo=geo)


def fetch_google_trends_rss_fallback(geo: str = "US") -> List[Dict[str, Any]]:
    """Emergency fallback: fetches trends from Google Trends official RSS feed with recency sorting."""
    url = f"https://trends.google.com/trending/rss?geo={geo}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    })
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            xml_data = r.read()
        import xml.etree.ElementTree as ET
        import email.utils
        root = ET.fromstring(xml_data)
        items = root.findall('.//item')
        snapshot_time_str = datetime.datetime.now().strftime("%m/%d/%y, %I:%M %p")
        results = []
        for it in items:
            title = it.findtext("title")
            if not title:
                continue
            traffic = it.findtext("{https://trends.google.com/trending/rss}approx_traffic") or "10K+"
            news_items = []
            for ni in it.findall("{https://trends.google.com/trending/rss}news_item")[:3]:
                n_title = ni.findtext("{https://trends.google.com/trending/rss}news_item_title") or ""
                n_url = ni.findtext("{https://trends.google.com/trending/rss}news_item_url") or ""
                n_src = ni.findtext("{https://trends.google.com/trending/rss}news_item_source") or "Google News"
                if n_title and n_url:
                    news_items.append({"title": n_title, "url": n_url, "source": n_src})

            pub_date_str = it.findtext("pubDate")
            started_ts = time.time()
            if pub_date_str:
                try:
                    started_ts = email.utils.parsedate_to_datetime(pub_date_str).timestamp()
                except Exception:
                    pass
            started_str = _format_time_ago(started_ts)

            q_enc = urllib.parse.quote(title)
            results.append({
                "query": title,
                "search_vol": 10000,
                "search_vol_fmt": traffic,
                "search_vol_display": f"{traffic} (+1,000%)",
                "growth_pct": "+1,000%",
                "started_time": started_str,
                "started_ts": started_ts,
                "is_active": True,
                "trend_breakdown": [title],
                "breakdown_display": title,
                "search_link": f"https://www.google.com/search?q={q_enc}",
                "explore_link": f"https://trends.google.com/trends/explore?q={q_enc}&geo={geo}",
                "trends_time": snapshot_time_str,
                "news_articles": news_items
            })

        # Recent trends first in RSS fallback
        results.sort(key=lambda x: x.get("started_ts", 0), reverse=True)
        return results
    except Exception as e:
        print(f"Error fetching Google Trends RSS: {e}")
        return []


def search_trend_source_videos(trend_query: str, max_results: int = 3, topic_filter: str = "") -> List[Dict[str, Any]]:
    """
    Searches YouTube via yt-dlp for top recent videos matching the breakout trend.
    """
    search_terms = f"{trend_query} {topic_filter}".strip() if topic_filter else trend_query
    cmd = [
        *get_ytdlp_cmd(),
        f"ytsearch{max_results}:{search_terms}",
        "--dump-single-json",
        "--flat-playlist",
        "--no-warnings"
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            entries = data.get("entries", [])
            out = []
            for e in entries:
                if not e:
                    continue
                v_id = e.get("id")
                v_url = f"https://www.youtube.com/watch?v={v_id}" if v_id else e.get("url")
                out.append({
                    "id": v_id,
                    "title": e.get("title", ""),
                    "url": v_url,
                    "uploader": e.get("uploader", "Creator"),
                    "duration": e.get("duration", 0)
                })
            return out
    except Exception as e:
        print(f"Error searching trend videos: {e}")
    return []


def get_trend_video_coverage() -> Dict[str, Any]:
    """
    Scans ready_to_upload/ and upload_history.json to index which trending
    topics already have videos generated or published.
    """
    from pathlib import Path
    ready_dir = Path("ready_to_upload")
    upload_hist_file = Path("upload_history.json")

    ready_meta = []
    if ready_dir.exists():
        for p in ready_dir.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    meta["_stem"] = p.stem
                    ready_meta.append(meta)
            except Exception:
                pass

    history = []
    if upload_hist_file.exists():
        try:
            with open(upload_hist_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            pass

    return {"ready_meta": ready_meta, "history": history}


def check_trend_coverage(query: str, index: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Matches a specific trend query against indexed ready files and upload history."""
    if index is None:
        index = get_trend_video_coverage()

    q_low = query.strip().lower()
    safe_q = "".join(c if c.isalnum() else "_" for c in q_low)[:25].strip("_")

    ready_meta = index.get("ready_meta", [])
    history = index.get("history", [])

    matched_ready = []
    ready_shorts = 0
    ready_landscapes = 0

    for m in ready_meta:
        stem = m.get("_stem", "").lower()
        tags = [t.lower() for t in m.get("tags", [])]
        title = m.get("title", "").lower()
        desc = m.get("description", "").lower()

        if safe_q in stem or q_low in tags or q_low in title or f"#{safe_q}" in desc:
            matched_ready.append(m)
            if stem.startswith("short_"):
                ready_shorts += 1
            elif stem.startswith("video_"):
                ready_landscapes += 1

    matched_uploaded = []
    for h in history:
        tags = [t.lower() for t in h.get("tags", [])]
        title = h.get("title", "").lower()
        stem = h.get("file_stem", "").lower()
        if safe_q in stem or q_low in tags or q_low in title:
            matched_uploaded.append(h)

    up_cnt = len(matched_uploaded)
    rd_cnt = len(matched_ready)

    if up_cnt > 0:
        status = "uploaded"
        badge = f"✅ DONE ({up_cnt} Published)"
        tag = "✅ DONE"
    elif rd_cnt > 0:
        status = "ready"
        badge = f"📦 READY ({rd_cnt} in Queue)"
        tag = "📦 READY"
    else:
        status = "fresh"
        badge = "⚪ FRESH"
        tag = ""

    return {
        "query": query,
        "status": status,
        "badge": badge,
        "tag": tag,
        "ready_count": rd_cnt,
        "ready_shorts": ready_shorts,
        "ready_landscapes": ready_landscapes,
        "uploaded_count": up_cnt,
        "uploaded_videos": matched_uploaded
    }

