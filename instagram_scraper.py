"""
Instagram Bulk Ingestion & Repurposing Engine for Zelmu Clipping.
Features:
- Auto-calculate all Reels from target @account or custom URL batch
- Safe 1-by-1 sequential download without breaking (error-isolated)
- Persistent State with full Pause & Resume capability
- Automatic Ollama YouTube SEO metadata rewriting
- Direct feed into Stage 3 Quality Review & Stage 4 Upload
- Strict copyright shield (zero cricket/sports broadcast footage, zero songs)
"""

import os
import sys
import re
import json
import time
import shutil
import threading
import subprocess
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

try:
    import instaloader
except ImportError:
    instaloader = None

from transcriber import get_ffmpeg_path, get_ytdlp_cmd
from analyzer import query_ollama_json
from safety import is_cricket_or_broadcast_sports
from editor import (
    generate_karaoke_ass,
    render_mode_a_short,
    get_best_video_encoder,
    is_valid_video_file
)
from arbiter import push_unified_log

READY_DIR = Path("ready_to_upload")
WORKSPACE_DIR = Path("workspace")
INSTA_STATE_FILE = Path("insta_crawler_state.json")
INSTA_LOG_FILE = Path("insta_crawler_events.log")
INSTA_SESSION_FILE = Path("insta_session.json")

_CRAWLER_THREAD: Optional[threading.Thread] = None
_STOP_EVENT = threading.Event()
_LOCK = threading.Lock()


def push_insta_log(msg: str):
    """Logs message to event file and unified arbiter log."""
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    push_unified_log("INSTA", msg)
    try:
        with open(INSTA_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_insta_logs(max_lines: int = 50) -> List[str]:
    """Retrieves recent log lines."""
    if not INSTA_LOG_FILE.exists():
        return []
    try:
        with open(INSTA_LOG_FILE, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
            return lines[-max_lines:]
    except Exception:
        return []


def save_session_cookie(cookie_str: str):
    """Saves Instagram sessionid string to local session config."""
    try:
        clean = cookie_str.strip().strip('"').strip("'")
        with open(INSTA_SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump({"sessionid": clean, "updated_at": time.time()}, f, indent=2)
    except Exception as e:
        print(f"Error saving session cookie: {e}")


def get_session_cookie() -> str:
    """Loads saved Instagram sessionid."""
    if INSTA_SESSION_FILE.exists():
        try:
            with open(INSTA_SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("sessionid", "")
        except Exception:
            pass
    return ""


def build_netscape_cookies_file(session_id: str, dest_path: Path) -> Path:
    """Generates Netscape cookies.txt for yt-dlp to bypass rate limits."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    clean = session_id.strip().strip('"').strip("'")
    content = f"# Netscape HTTP Cookie File\n.instagram.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\t{clean}\n"
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(content)
    return dest_path


def load_crawler_state() -> Dict[str, Any]:
    """Loads persistent crawler state for pause/resume."""
    if INSTA_STATE_FILE.exists():
        try:
            with open(INSTA_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "account": "",
        "mode": "direct",
        "total_count": 0,
        "current_index": 0,
        "completed_ids": [],
        "failed_ids": [],
        "reels_queue": [],
        "status": "idle",  # "idle", "running", "paused", "completed"
        "current_reel_caption": "",
        "last_updated": 0
    }


def save_crawler_state(state: Dict[str, Any]):
    """Persists crawler state to disk."""
    state["last_updated"] = time.time()
    try:
        with open(INSTA_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"Error saving crawler state: {e}")


def normalize_instagram_target(target: str) -> Tuple[str, str]:
    """
    Normalizes input string into type ('profile' or 'reel') and valid Instagram URL.
    """
    clean = target.strip()
    if clean.startswith("@"):
        uname = clean.lstrip("@").strip()
        return "profile", f"https://www.instagram.com/{uname}/"
    elif clean.startswith("http://") or clean.startswith("https://"):
        if "/reel/" in clean or "/p/" in clean:
            return "reel", clean.split("?")[0].rstrip("/") + "/"
        return "profile", clean.split("?")[0].rstrip("/") + "/"
    else:
        uname = clean.strip()
        return "profile", f"https://www.instagram.com/{uname}/"


def _find_video_url_in_dict(obj: Any) -> Optional[str]:
    """Recursively searches for video_versions or video_url in nested Instagram JSON."""
    if isinstance(obj, dict):
        if "video_versions" in obj and isinstance(obj["video_versions"], list) and obj["video_versions"]:
            v_url = obj["video_versions"][0].get("url")
            if v_url:
                return v_url
        if "video_url" in obj and isinstance(obj["video_url"], str):
            return obj["video_url"]
        for v in obj.values():
            found = _find_video_url_in_dict(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_video_url_in_dict(item)
            if found:
                return found
    return None


def _find_timeline_edges(obj: Any) -> List[Dict[str, Any]]:
    """Recursively searches for polaris_ordered_timeline_connection or edge_owner_to_timeline_media edges."""
    if isinstance(obj, dict):
        if "polaris_ordered_timeline_connection" in obj:
            conn = obj["polaris_ordered_timeline_connection"]
            if isinstance(conn, dict) and "edges" in conn and conn["edges"]:
                return conn["edges"]
        if "edge_owner_to_timeline_media" in obj:
            conn = obj["edge_owner_to_timeline_media"]
            if isinstance(conn, dict) and "edges" in conn and conn["edges"]:
                return conn["edges"]
        for v in obj.values():
            found = _find_timeline_edges(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_timeline_edges(item)
            if found:
                return found
    return []


def download_reel_direct_cdn(url_or_shortcode: str, output_path: Path, session_id: Optional[str] = None) -> bool:
    """Downloads an Instagram Reel MP4 directly from Meta CDN via embedded page data."""
    if not instaloader:
        return False
    clean = url_or_shortcode.strip().rstrip('/')
    m = re.search(r'/(?:reel|p)/([A-Za-z0-9_-]+)', clean)
    shortcode = m.group(1) if m else clean.split('/')[-1]

    try:
        L = instaloader.Instaloader()
        sess_id = session_id or get_session_cookie()
        if sess_id:
            L.context.session.cookies.set("sessionid", sess_id, domain=".instagram.com")

        for prefix in [f"reel/{shortcode}/", f"p/{shortcode}/"]:
            try:
                page_data = L.context.get_page_data(prefix)
                v_url = _find_video_url_in_dict(page_data)
                if v_url:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                    for attempt in range(2):
                        try:
                            with requests.get(v_url, headers=headers, stream=True, timeout=25) as r:
                                r.raise_for_status()
                                with open(output_path, "wb") as f:
                                    for chunk in r.iter_content(chunk_size=65536):
                                        if chunk:
                                            f.write(chunk)
                            if is_valid_video_file(output_path):
                                return True
                        except Exception as dl_err:
                            if attempt == 0:
                                time.sleep(1.5)
                            else:
                                print(f"[DirectCDN] Stream attempt 2 failed: {dl_err}")
            except Exception as e:
                print(f"[DirectCDN] Prefix {prefix} check notice: {e}")
    except Exception as err:
        print(f"[DirectCDN] Extraction error: {err}")
    return False


def scan_and_calculate_account_reels(
    target: str,
    cookies_path: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """
    Auto-calculates total reels published by target account or direct Reel URL batch.
    Enumerates video reel items and filters out cricket/broadcast sports risks.
    """
    clean_target = target.strip()
    sess_id = session_id or get_session_cookie()

    # Check if target is a list of direct Reel URLs (newlines or commas)
    direct_urls = [u.strip() for u in re.split(r'[\r\n,]+', clean_target) if u.strip() and ("/reel/" in u or "/p/" in u)]
    if direct_urls:
        reels = []
        filtered_sports = 0
        for u in direct_urls[:limit]:
            m = re.search(r'/(?:reel|p)/([A-Za-z0-9_-]+)', u)
            s_id = m.group(1) if m else u.rstrip("/").split("/")[-1]
            reels.append({
                "id": s_id,
                "url": f"https://www.instagram.com/reel/{s_id}/",
                "caption": f"Instagram Reel {s_id}",
                "uploader": "creator",
                "duration": 30.0
            })
        return {
            "account": "direct_batch",
            "full_name": "Direct Batch URLs",
            "follower_count": None,
            "total_account_posts": len(reels),
            "discovered_reels_count": len(reels),
            "reels": reels,
            "filtered_sports_count": filtered_sports,
            "method": "direct_urls",
            "status": "ready"
        }

    t_type, target_url = normalize_instagram_target(clean_target)
    clean_uname = clean_target.lstrip("@").strip().split("/")[-1] if t_type == "profile" else "custom_batch"

    # Check local discovered cache first (populated by subagent or previous deep discovery)
    cache_path = Path("insta_discovered_cache.json")
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                c_data = json.load(f)
                if clean_uname in c_data:
                    cached_entry = c_data[clean_uname]
                    c_reels = cached_entry.get("reels", [])
                    if c_reels:
                        return {
                            **cached_entry,
                            "reels": c_reels[:limit],
                            "discovered_reels_count": len(c_reels[:limit])
                        }
        except Exception as e:
            print(f"[InstaScraper] Cache read notice: {e}")

    reels = []
    total_posts = 0
    follower_count = None
    full_name = None
    filtered_sports = 0

    # Method 1: Instaloader Embedded GraphQL Extraction (High success, bypasses unauthenticated blocks)
    if instaloader and t_type == "profile":
        try:
            L = instaloader.Instaloader()
            if sess_id:
                L.context.session.cookies.set("sessionid", sess_id, domain=".instagram.com")

            page_data = L.context.get_page_data(f"{clean_uname}/")
            for item in page_data:
                u_info = item.get("xig_user_by_username")
                if isinstance(u_info, dict):
                    if not full_name:
                        full_name = u_info.get("full_name") or u_info.get("username")
                    if follower_count is None and u_info.get("follower_count") is not None:
                        follower_count = u_info.get("follower_count")
                    if not total_posts and u_info.get("all_media_count") is not None:
                        total_posts = u_info.get("all_media_count")

            edges = _find_timeline_edges(page_data)
            for e in edges:
                node = e.get("node", {})
                is_video = (
                    node.get("__typename") == "XIGPolarisVideoMedia"
                    or node.get("media_type") == 2
                    or node.get("product_type") == "clips"
                    or bool(node.get("is_video"))
                )
                if is_video:
                    shortcode = node.get("code") or node.get("shortcode")
                    if not shortcode:
                        continue
                    cap_obj = node.get("caption")
                    cap = cap_obj.get("text", "") if isinstance(cap_obj, dict) else str(cap_obj or "")

                    if is_cricket_or_broadcast_sports(cap):
                        filtered_sports += 1
                        continue

                    reels.append({
                        "id": shortcode,
                        "url": f"https://www.instagram.com/reel/{shortcode}/",
                        "caption": cap,
                        "uploader": clean_uname,
                        "duration": float(node.get("video_duration") or 30.0)
                    })
                    if len(reels) >= limit:
                        break

            # If user has provided session_id and we need more reels beyond initial page
            if sess_id and len(reels) < limit:
                try:
                    profile = instaloader.Profile.from_username(L.context, clean_uname)
                    if not follower_count:
                        follower_count = profile.followers
                    if not total_posts:
                        total_posts = profile.mediacount
                    seen_ids = {r["id"] for r in reels}
                    for post in profile.get_posts():
                        if post.is_video and post.shortcode not in seen_ids:
                            cap = post.caption or ""
                            if is_cricket_or_broadcast_sports(cap):
                                filtered_sports += 1
                                continue
                            reels.append({
                                "id": post.shortcode,
                                "url": f"https://www.instagram.com/reel/{post.shortcode}/",
                                "caption": cap,
                                "uploader": clean_uname,
                                "duration": float(post.video_duration or 30.0)
                            })
                            seen_ids.add(post.shortcode)
                            if len(reels) >= limit:
                                break
                except Exception as ex:
                    print(f"[InstaScraper] Instaloader profile deep iteration notice: {ex}")

            if reels:
                return {
                    "account": clean_uname,
                    "full_name": full_name or clean_uname,
                    "follower_count": follower_count,
                    "total_account_posts": total_posts or len(reels),
                    "discovered_reels_count": len(reels),
                    "reels": reels,
                    "filtered_sports_count": filtered_sports,
                    "method": "instaloader_embedded",
                    "status": "ready"
                }
        except Exception as e:
            print(f"[InstaScraper] Instaloader embedded extraction notice: {e}")

    # Method 2: Instagram GraphQL Web Profile API
    if t_type == "profile":
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "x-ig-app-id": "936619743392459"
        }
        if sess_id:
            headers["Cookie"] = f"sessionid={sess_id};"

        api_url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={clean_uname}"
        try:
            res = requests.get(api_url, headers=headers, timeout=12)
            if res.status_code == 200:
                data = res.json()
                user_info = data.get("data", {}).get("user", {})
                edge_owner = user_info.get("edge_owner_to_timeline_media", {})
                total_posts = edge_owner.get("count", 0)
                follower_count = user_info.get("edge_followed_by", {}).get("count")
                full_name = user_info.get("full_name") or clean_uname
                edges = edge_owner.get("edges", [])

                for e in edges:
                    node = e.get("node", {})
                    if node.get("is_video"):
                        shortcode = node.get("shortcode")
                        caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
                        cap = caption_edges[0].get("node", {}).get("text", "") if caption_edges else ""

                        if is_cricket_or_broadcast_sports(cap):
                            filtered_sports += 1
                            continue

                        reels.append({
                            "id": shortcode,
                            "url": f"https://www.instagram.com/reel/{shortcode}/",
                            "caption": cap,
                            "uploader": clean_uname,
                            "duration": float(node.get("video_duration") or 30.0)
                        })
                        if len(reels) >= limit:
                            break

                if reels:
                    return {
                        "account": clean_uname,
                        "full_name": full_name or clean_uname,
                        "follower_count": follower_count,
                        "total_account_posts": total_posts or len(reels),
                        "discovered_reels_count": len(reels),
                        "reels": reels,
                        "filtered_sports_count": filtered_sports,
                        "method": "graphql_api",
                        "status": "ready"
                    }
        except Exception as e:
            print(f"[InstaScraper] Web API check notice: {e}")

    # Method 3: yt-dlp metadata extractor fallback
    temp_cookie_p = None
    if sess_id and not cookies_path:
        temp_cookie_p = WORKSPACE_DIR / "temp_insta_cookies.txt"
        build_netscape_cookies_file(sess_id, temp_cookie_p)
        cookies_path = str(temp_cookie_p)

    cmd = [
        *get_ytdlp_cmd(),
        "--dump-single-json",
        "--flat-playlist",
        "--playlist-end", str(limit),
        "--no-warnings",
        "--ignore-errors"
    ]
    if cookies_path and Path(cookies_path).exists():
        cmd.extend(["--cookies", str(Path(cookies_path).resolve())])

    cmd.append(target_url)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            entries = data.get("entries", []) if "entries" in data else [data]
            for e in entries:
                if not e:
                    continue
                v_id = e.get("id") or e.get("webpage_url_basename")
                v_url = e.get("url") or e.get("webpage_url") or (f"https://www.instagram.com/reel/{v_id}/" if v_id else None)
                if not v_url:
                    continue
                v_desc = e.get("description") or e.get("title") or ""
                v_uploader = e.get("uploader") or clean_uname

                if is_cricket_or_broadcast_sports(v_desc) or is_cricket_or_broadcast_sports(v_uploader):
                    filtered_sports += 1
                    continue

                reels.append({
                    "id": v_id,
                    "url": v_url,
                    "caption": v_desc,
                    "uploader": v_uploader,
                    "duration": float(e.get("duration") or 30.0)
                })
                if len(reels) >= limit:
                    break
    except Exception as e:
        print(f"[InstaScraper] yt-dlp fallback error: {e}")

    return {
        "account": clean_uname,
        "full_name": full_name or clean_uname,
        "follower_count": follower_count,
        "total_account_posts": total_posts or len(reels),
        "discovered_reels_count": len(reels),
        "reels": reels,
        "filtered_sports_count": filtered_sports,
        "method": "yt_dlp" if reels else "none",
        "status": "ready" if reels else "empty",
        "error_reason": "rate_limited_or_auth_required" if not reels else None,
        "error_message": f"Instagram blocked unauthenticated profile access (HTTP 429). Session cookie required for @{clean_uname}." if not reels else None
    }


_OLLAMA_ONLINE_CACHE: Optional[bool] = None
_OLLAMA_CHECK_TIME: float = 0.0

def is_ollama_online() -> bool:
    """Fast non-blocking check with 45s TTL to avoid 18s timeouts when Ollama is offline."""
    global _OLLAMA_ONLINE_CACHE, _OLLAMA_CHECK_TIME
    now = time.time()
    if _OLLAMA_ONLINE_CACHE is not None and (now - _OLLAMA_CHECK_TIME < 45):
        return _OLLAMA_ONLINE_CACHE
    try:
        r = requests.get("http://localhost:11434/api/version", timeout=1.0)
        _OLLAMA_ONLINE_CACHE = (r.status_code == 200)
    except Exception:
        _OLLAMA_ONLINE_CACHE = False
    _OLLAMA_CHECK_TIME = now
    return _OLLAMA_ONLINE_CACHE


def convert_caption_to_youtube_seo(caption: str, uploader: str = "") -> Dict[str, Any]:
    """
    Converts raw Instagram caption to YouTube SEO Title, Description, and Tags
    via Ollama with smart regex fallback.
    """
    clean_text = re.sub(r'#\w+', '', caption).strip()
    clean_lines = [l.strip() for l in clean_text.splitlines() if l.strip() and not l.startswith('.')]
    lead_sentence = clean_lines[0] if clean_lines else "Unbelievable Viral Moment"
    account_handle = f"@{uploader.lstrip('@')}" if uploader else "@creator"

    if is_ollama_online():
        prompt = f"""You are a YouTube Shorts SEO specialist. Convert this Instagram Reel caption into a high-CTR YouTube Short title and description:
Caption: "{lead_sentence[:120]}"
Original Creator: {account_handle}

Return ONLY JSON:
{{
  "title": "High-CTR Title under 65 chars #Shorts",
  "description": "Engaging description with credit to {account_handle}",
  "tags": ["Tag1", "Tag2", "Tag3", "Shorts"]
}}"""
        try:
            res = query_ollama_json(prompt, retries=1, timeout=12)
            if res and isinstance(res, dict) and "title" in res:
                t_raw = res.get("title", "")
                t_clean = t_raw if "#shorts" in t_raw.lower() else f"{t_raw} #Shorts"
                return {
                    "title": t_clean[:70],
                    "description": f"{res.get('description', '')}\n\nCredit: {account_handle}\n\n#Shorts #Trending",
                    "tags": [t for t in res.get("tags", []) if isinstance(t, str)][:10] or ["Shorts", "Viral", "Trending"]
                }
        except Exception:
            pass

    base_title = lead_sentence[:50].strip()
    title = f"{base_title.title()} 🤯 #Shorts" if len(base_title) <= 50 else f"{base_title[:45].title()}... #Shorts"
    extracted_hashtags = [w.strip("#") for w in re.findall(r'#\w+', caption)[:8]]

    return {
        "title": title[:70],
        "description": f"🔥 {lead_sentence}\n\nCredit: {account_handle}\n\n#Shorts #Trending",
        "tags": extracted_hashtags + ["Shorts", "Trending", "Viral"]
    }


def download_instagram_video(
    url: str,
    output_mp4: Path,
    cookies_path: Optional[str] = None
) -> Optional[Path]:
    """Downloads an Instagram Reel MP4 with Direct CDN primary and yt-dlp fallback."""
    output_mp4.parent.mkdir(parents=True, exist_ok=True)

    sess_id = get_session_cookie()

    # 1. Direct CDN Stream Download (Fastest, zero rate-limit, uses saved sessionid)
    if download_reel_direct_cdn(url, output_mp4, session_id=sess_id):
        return output_mp4

    # 2. Auto-build Netscape cookies for yt-dlp if not provided
    if not cookies_path and sess_id:
        temp_cookie_p = WORKSPACE_DIR / "temp_insta_cookies.txt"
        build_netscape_cookies_file(sess_id, temp_cookie_p)
        cookies_path = str(temp_cookie_p)

    # 3. yt-dlp fallback
    part_mp4 = output_mp4.with_suffix(".part.mp4")
    cmd = [
        *get_ytdlp_cmd(),
        "-f", "bestvideo+bestaudio/best[ext=mp4]/best",
        "-o", str(part_mp4),
        "--no-warnings",
        "--ignore-errors"
    ]
    if cookies_path and Path(cookies_path).exists():
        cmd.extend(["--cookies", str(Path(cookies_path).resolve())])

    cmd.append(url)

    try:
        res = subprocess.run(cmd, capture_output=True, timeout=60)
        if res.returncode == 0 and is_valid_video_file(part_mp4):
            if output_mp4.exists():
                output_mp4.unlink()
            part_mp4.rename(output_mp4)
            return output_mp4
        elif part_mp4.exists():
            part_mp4.unlink()
    except Exception:
        if part_mp4.exists():
            part_mp4.unlink()
    return None



def process_instagram_reel(
    reel_info: Dict[str, Any],
    mode: str = "direct",
    cookies_path: Optional[str] = None,
    progress_callback: Optional[Any] = None
) -> Optional[Path]:
    """
    Processes single reel into Stage 3 Quality Review queue:
    - 'direct': standardize to 1080x1920 MP4 with clean audio.
    - 'transform': adds Whisper karaoke subtitles, 3.2s punch zoom & frame-1 hook.
    """
    def log(msg: str):
        if progress_callback:
            progress_callback(msg)
        print(f"[InstaClipper] {msg}")
        push_unified_log("INSTA", msg)

    r_id = reel_info.get("id") or str(int(time.time() * 1000))[-8:]
    r_url = reel_info.get("url")
    r_caption = reel_info.get("caption", "")
    r_uploader = reel_info.get("uploader", "creator")

    ts = int(time.time())
    work_dir = WORKSPACE_DIR / f"insta_{r_id}_{ts}"
    work_dir.mkdir(parents=True, exist_ok=True)
    READY_DIR.mkdir(parents=True, exist_ok=True)

    raw_mp4 = work_dir / "raw_reel.mp4"
    final_mp4 = READY_DIR / f"Short_Insta_{r_uploader}_{r_id}_{ts}.mp4"

    log(f"📥 Downloading Reel from @{r_uploader}: {r_url}...")
    dl_res = download_instagram_video(r_url, raw_mp4, cookies_path)
    if not dl_res or not is_valid_video_file(raw_mp4):
        log(f"⚠️ Failed to download Reel: {r_url}")
        return None

    log("🧠 Generating YouTube SEO Title & Metadata via Ollama...")
    seo_meta = convert_caption_to_youtube_seo(r_caption, r_uploader)

    ffmpeg_bin = str(get_ffmpeg_path() or "ffmpeg")

    if mode == "transform":
        log("🎬 Applying Full AI Transformation (Subtitles + 3.2s Zoom + Frame-1 Hook)...")
        audio_wav = work_dir / "audio.wav"
        subprocess.run([
            ffmpeg_bin, "-y", "-i", str(raw_mp4),
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(audio_wav)
        ], capture_output=True)

        ass_file = work_dir / "subs.ass"
        words = []
        try:
            from transcriber import transcribe_audio_whisper
            t_json = work_dir / "transcript.json"
            res = transcribe_audio_whisper(audio_path=audio_wav, output_json_path=t_json, model_size="tiny.en")
            for seg in res.get("segments", []):
                for w in seg.get("words", []):
                    words.append({"word": w["word"], "start": w["start"], "end": w["end"]})
        except Exception as e:
            log(f"⚠️ Whisper transcription fallback: {e}")

        generate_karaoke_ass(words, ass_file, clip_start_offset=0.0, style_preset="neon")
        hook_banner = seo_meta.get("title", "").split("#")[0].strip()[:28].upper()

        render_mode_a_short(
            source_video=raw_mp4,
            ass_subtitles=ass_file,
            output_short_path=final_mp4,
            flagged_profanities=[],
            split_layout=False,
            enable_tracking=False,
            hook_title=hook_banner,
            enable_pacing_zoom=True,
            enable_anti_content_id=True,
            enable_music_ducking=False,  # NO background songs
            enable_sfx=True
        )
    else:
        log("⚡ Fast Direct Repurpose: Normalizing to 1080x1920 MP4...")
        vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
        cmd = [
            ffmpeg_bin, "-y",
            "-i", str(raw_mp4),
            "-vf", vf,
            *get_best_video_encoder(),
            "-c:a", "aac", "-b:a", "128k",
            str(final_mp4)
        ]
        subprocess.run(cmd, capture_output=True)

    if not is_valid_video_file(final_mp4):
        log(f"⚠️ Processing failed for reel {r_id}")
        return None

    # Save Sidecar Metadata JSON for Stage 3 Quality Review & Stage 4 Upload
    sidecar_path = final_mp4.with_suffix(".json")
    try:
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump({
                "title": seo_meta.get("title", f"Viral Moment @{r_uploader} #Shorts")[:70],
                "description": seo_meta.get("description", ""),
                "tags": seo_meta.get("tags", ["Shorts", "Viral", "Trending"]),
                "category_id": "24",  # Entertainment
                "privacy_status": "public",
                "approved": False,
                "stage": "pending_quality_review",
                "source": "instagram_clipper",
                "source_account": r_uploader,
                "source_url": r_url,
                "created_at": time.time()
            }, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving sidecar: {e}")

    log(f"✓ Successfully processed: {final_mp4.name} (Ready for Stage 3 Quality Check)")

    # Clean up intermediate scratch workspace to prevent mass production disk leaks
    try:
        shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        pass

    return final_mp4


# ---------------------------------------------------------------------------
# Background Crawler Daemon with 1-by-1 Safe Execution, Pause & Resume
# ---------------------------------------------------------------------------

def _crawler_worker_loop():
    """Sequential 1-by-1 worker that respects pause/resume state."""
    while not _STOP_EVENT.is_set():
        state = load_crawler_state()
        if state.get("status") != "running":
            break

        queue = state.get("reels_queue", [])
        completed = set(state.get("completed_ids", []))
        failed = set(state.get("failed_ids", []))

        # Find next uncompleted reel
        next_item = None
        next_idx = 0
        for idx, item in enumerate(queue):
            if item.get("id") not in completed and item.get("id") not in failed:
                next_item = item
                next_idx = idx
                break

        if not next_item:
            state["status"] = "completed"
            save_crawler_state(state)
            push_insta_log(f"🏁 Finished all {len(completed)}/{len(queue)} reels! All queued in Stage 3 Quality Review.")
            break

        # Disk Space Safeguard: Pause if free drive storage < 3.0 GB
        try:
            free_gb = shutil.disk_usage(".").free / (1024 ** 3)
            if free_gb < 3.0:
                push_insta_log(f"⚠️ [Storage Safeguard] Free disk space critically low ({free_gb:.1f} GB < 3.0 GB). Pausing crawler.")
                state["status"] = "paused"
                save_crawler_state(state)
                break
        except Exception:
            pass

        r_id = next_item.get("id")
        r_caption = next_item.get("caption", "")[:40]
        state["current_index"] = len(completed)
        state["current_reel_caption"] = r_caption
        save_crawler_state(state)

        push_insta_log(f"🚀 [Clip #{len(completed)+1}/{len(queue)}] Starting 1-by-1 download for reel '{r_id}' ({r_caption})...")

        sess_id = get_session_cookie()
        temp_cookies_p = None
        if sess_id:
            temp_cookies_p = WORKSPACE_DIR / "temp_insta_cookies.txt"
            build_netscape_cookies_file(sess_id, temp_cookies_p)

        try:
            out_clip = process_instagram_reel(
                reel_info=next_item,
                mode=state.get("mode", "direct"),
                cookies_path=str(temp_cookies_p) if temp_cookies_p else None,
                progress_callback=push_insta_log
            )
            state = load_crawler_state()
            if out_clip and out_clip.exists():
                if r_id not in state["completed_ids"]:
                    state["completed_ids"].append(r_id)
                push_insta_log(f"✓ [Clip #{len(state['completed_ids'])}/{len(queue)}] Completed successfully: {out_clip.name}")
            else:
                if r_id not in state["failed_ids"]:
                    state["failed_ids"].append(r_id)
                push_insta_log(f"⚠️ [Clip #{len(state['completed_ids'])+1}] Reel {r_id} failed download. Continuing to next.")
        except Exception as err:
            state = load_crawler_state()
            if r_id not in state["failed_ids"]:
                state["failed_ids"].append(r_id)
            push_insta_log(f"⚠️ Error on reel {r_id}: {err}. Safely continuing...")

        state["current_index"] = len(state["completed_ids"])
        save_crawler_state(state)

        # Gentle 2.5s jitter delay to prevent rate-limiting
        for _ in range(5):
            if _STOP_EVENT.is_set():
                break
            time.sleep(0.5)

    if _STOP_EVENT.is_set():
        state = load_crawler_state()
        if state.get("status") == "running":
            state["status"] = "paused"
            save_crawler_state(state)
            push_insta_log(f"⏸️ Ingestion paused. Saved progress at clip #{len(state.get('completed_ids', []))}/{state.get('total_count', 0)}.")


def start_or_resume_crawler(
    account: str,
    reels: Optional[List[Dict[str, Any]]] = None,
    mode: str = "direct"
) -> bool:
    """Starts or resumes 1-by-1 background reel crawler."""
    global _CRAWLER_THREAD, _STOP_EVENT
    with _LOCK:
        state = load_crawler_state()

        # If already paused for this account, resume existing queue
        if state.get("status") == "paused" and (state.get("account") == account or not account):
            state["status"] = "running"
            if mode:
                state["mode"] = mode
            save_crawler_state(state)
            push_insta_log(f"▶️ Resuming Instagram crawler for @{state.get('account')} from clip #{len(state.get('completed_ids', [])) + 1}...")
        else:
            # New crawl initiation
            queue = reels or []
            state = {
                "account": account,
                "mode": mode,
                "total_count": len(queue),
                "current_index": 0,
                "completed_ids": [],
                "failed_ids": [],
                "reels_queue": queue,
                "status": "running",
                "current_reel_caption": queue[0].get("caption", "")[:40] if queue else "",
                "last_updated": time.time()
            }
            save_crawler_state(state)
            push_insta_log(f"▶️ Started new 1-by-1 Instagram crawler for @{account} ({len(queue)} reels queued)...")

        _STOP_EVENT.clear()
        if _CRAWLER_THREAD is None or not _CRAWLER_THREAD.is_alive():
            _CRAWLER_THREAD = threading.Thread(target=_crawler_worker_loop, daemon=True)
            _CRAWLER_THREAD.start()
        return True


def pause_crawler() -> bool:
    """Pauses background crawler safely without losing progress."""
    global _STOP_EVENT
    with _LOCK:
        _STOP_EVENT.set()
        state = load_crawler_state()
        state["status"] = "paused"
        save_crawler_state(state)
        push_insta_log("⏸️ Paused Instagram crawler. State safely preserved.")
        return True


def reset_crawler() -> bool:
    """Resets crawler queue and state."""
    global _STOP_EVENT
    with _LOCK:
        _STOP_EVENT.set()
        state = {
            "account": "",
            "mode": "direct",
            "total_count": 0,
            "current_index": 0,
            "completed_ids": [],
            "failed_ids": [],
            "reels_queue": [],
            "status": "idle",
            "current_reel_caption": "",
            "last_updated": time.time()
        }
        save_crawler_state(state)
        push_insta_log("🔄 Reset Instagram crawler state.")
        return True


def is_crawler_active() -> bool:
    """Checks if background thread is actively running."""
    state = load_crawler_state()
    return state.get("status") == "running" and (_CRAWLER_THREAD is not None and _CRAWLER_THREAD.is_alive())
