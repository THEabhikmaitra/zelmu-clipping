"""
US Realtime Google Trends Hunter for Zelmu Clipping.
Fetches pre-peak USA breakout trends from:
https://trends.google.com/trending?geo=US&status=active&hours=4&sort=recency
Directly parses the native ds:0 payload without 3rd-party API keys or rate limits.
"""

import urllib.request
import urllib.parse
import re
import json
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


def fetch_google_trends_us(
    geo: str = "US",
    hours: int = 4,
    sort: str = "recency",
    status: str = "active",
    category_id: int = 0
) -> List[Dict[str, Any]]:
    """
    Fetches real-time breakout trends across All Categories or specific category from:
    https://trends.google.com/trending?geo=US&status=active&hours=4&sort=recency
    Parses native ds:0 payload directly. 0 API keys required.
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
            return []
        content = m.group(1)
        data_match = re.search(r'data:\s*(\[.*?\])\s*,\s*sideChannel', content, re.DOTALL)
        if not data_match:
            data_match = re.search(r'data:\s*(\[.*?\])\s*\}\s*$', content, re.DOTALL)
        if not data_match:
            return []

        parsed = json.loads(data_match.group(1))
        items = parsed[1] if len(parsed) > 1 and isinstance(parsed[1], list) else []
        results = []
        for it in items:
            if not isinstance(it, list) or len(it) == 0:
                continue
            query = it[0]
            traffic = it[6] if len(it) > 6 else 0
            fmt_traffic = f"{traffic:,}+" if isinstance(traffic, (int, float)) and traffic > 0 else "🔥 Breakout"
            explore_link = f"https://trends.google.com/trends/explore?q={urllib.parse.quote(str(query))}&geo={geo}"
            results.append({
                "query": query,
                "traffic": traffic,
                "formatted_traffic": fmt_traffic,
                "explore_url": explore_link
            })
        return results
    except Exception as e:
        print(f"Error fetching Google Trends: {e}")
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
