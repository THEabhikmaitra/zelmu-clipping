import os
import csv
import json
import shutil
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Scopes: Upload + Readonly (for channel verification)
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]
CLIENT_SECRETS_FILE = Path("client_secrets.json")
TOKEN_FILE = Path("token.json")
TOKENS_DIR = Path("tokens")
LOG_FILE = Path("upload_log.csv")
READY_DIR = Path("ready_to_upload")
ARCHIVE_DIR = Path("uploaded_archive")
DEFAULT_REDIRECT_URI = "http://localhost:8080/"


def get_available_token_files() -> List[Path]:
    """Finds all available token.json files in root and tokens/ directory for multi-account quota rotation."""
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    tokens = []
    if TOKEN_FILE.exists():
        tokens.append(TOKEN_FILE)
    tokens.extend(sorted(list(TOKENS_DIR.glob("*.json"))))
    tokens.extend(sorted([f for f in Path(".").glob("token_*.json") if f not in tokens]))
    return tokens


def get_credentials(token_path: Optional[Path] = None) -> Optional[Credentials]:
    """Returns valid Credentials for specified token file (or default token.json), else None."""
    target_token = Path(token_path) if token_path else TOKEN_FILE
    creds = None
    if target_token.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(target_token), SCOPES)
        except Exception:
            creds = None

    if creds:
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(target_token, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
                return creds
            except Exception:
                return None
    return None


def is_authenticated(token_path: Optional[Path] = None) -> bool:
    """Checks whether valid YouTube OAuth credentials exist."""
    return get_credentials(token_path) is not None


def get_authenticated_service(token_path: Optional[Path] = None):
    """
    Returns YouTube API client. Raises RuntimeError if not authenticated.
    """
    creds = get_credentials(token_path)
    if not creds:
        if not CLIENT_SECRETS_FILE.exists():
            raise FileNotFoundError(
                f"'{CLIENT_SECRETS_FILE}' not found. Place client_secrets.json in root."
            )
        raise RuntimeError("YouTube not authenticated. Complete Google OAuth sign-in first.")
    return build("youtube", "v3", credentials=creds)
    if not creds:
        if not CLIENT_SECRETS_FILE.exists():
            raise FileNotFoundError(
                f"'{CLIENT_SECRETS_FILE}' not found. Place client_secrets.json in root."
            )
        raise RuntimeError("YouTube not authenticated. Complete Google OAuth sign-in first.")
    return build("youtube", "v3", credentials=creds)


def get_auth_url(redirect_uri: str = DEFAULT_REDIRECT_URI) -> str:
    """Generates direct Google OAuth consent URL without PKCE constraint for bulletproof copy-paste token exchange."""
    if not CLIENT_SECRETS_FILE.exists():
        raise FileNotFoundError(f"'{CLIENT_SECRETS_FILE}' not found.")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRETS_FILE),
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    flow.autogenerate_code_verifier = False
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    return auth_url


def exchange_code_for_token(code_or_url: str, redirect_uri: str = DEFAULT_REDIRECT_URI) -> Credentials:
    """
    Exchanges authorization code (or full redirected callback URL) for tokens and saves token.json.
    """
    if not CLIENT_SECRETS_FILE.exists():
        raise FileNotFoundError(f"'{CLIENT_SECRETS_FILE}' not found.")

    raw = code_or_url.strip()
    if "code=" in raw:
        parsed = urllib.parse.urlparse(raw)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [raw])[0]
    else:
        code = raw

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRETS_FILE),
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    flow.autogenerate_code_verifier = False
    flow.fetch_token(code=code)

    creds = flow.credentials
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    return creds


def find_available_port(preferred_port: int = 8080) -> int:
    """Finds a free port to avoid WinError 10048 socket collisions."""
    import socket
    for p in range(preferred_port, preferred_port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('localhost', p))
                return p
            except OSError:
                continue
    return 0


def run_local_server_auth(port: int = 8080, timeout_seconds: int = 60) -> Credentials:
    """
    Launches local OAuth listener on free port with a timeout to prevent hanging.
    """
    if not CLIENT_SECRETS_FILE.exists():
        raise FileNotFoundError(f"'{CLIENT_SECRETS_FILE}' not found.")

    free_port = find_available_port(port)
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), SCOPES)
    creds = flow.run_local_server(
        port=free_port,
        open_browser=True,
        timeout_seconds=timeout_seconds,
        success_message="Authentication successful! You can now close this tab and return to Zelmu Clipping."
    )
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    return creds


def get_channel_info(creds: Optional[Credentials] = None) -> Optional[Dict[str, str]]:
    """Retrieves channel snippet for authenticated account."""
    if creds is None:
        creds = get_credentials()
    if not creds:
        return None
    try:
        yt = build("youtube", "v3", credentials=creds)
        resp = yt.channels().list(mine=True, part="snippet").execute()
        items = resp.get("items", [])
        if items:
            snip = items[0]["snippet"]
            return {
                "title": snip.get("title", "YouTube Channel"),
                "customUrl": snip.get("customUrl", ""),
                "thumbnail": snip.get("thumbnails", {}).get("default", {}).get("url", "")
            }
        return {"title": "Connected Account", "customUrl": "", "thumbnail": ""}
    except Exception as e:
        return {"title": "Connected", "error": str(e)}


def revoke_token():
    """Removes token.json to disconnect current account."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()


LOG_HEADERS = [
    "Timestamp", "Original_File", "Video_ID", "Title",
    "Scheduled_Time", "File_Size_MB", "Upload_Sec", "Speed_MBps",
    "Studio_URL", "Privacy"
]


def ensure_upload_log():
    """Ensures CSV log file exists with proper headers and auto-migrates old formats."""
    if not LOG_FILE.exists():
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(LOG_HEADERS)
        return

    # Check and migrate legacy log headers if needed
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        if rows and rows[0] != LOG_HEADERS:
            old_hdr = rows[0]
            migrated_rows = [LOG_HEADERS]
            for r in rows[1:]:
                row_dict = dict(zip(old_hdr, r))
                migrated_rows.append([
                    row_dict.get("Timestamp", ""),
                    row_dict.get("Original_File", ""),
                    row_dict.get("Video_ID", ""),
                    row_dict.get("Title", ""),
                    row_dict.get("Scheduled_Time", ""),
                    row_dict.get("File_Size_MB", "15.0"),
                    row_dict.get("Upload_Sec", "12.0"),
                    row_dict.get("Speed_MBps", "10.0"),
                    row_dict.get("Studio_URL", ""),
                    row_dict.get("Privacy", "private")
                ])
            with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerows(migrated_rows)
    except Exception:
        pass


def log_upload(
    filename: str,
    video_id: str,
    title: str,
    scheduled_time: str = "",
    file_size_mb: float = 0.0,
    upload_sec: float = 0.0,
    speed_mbps: float = 0.0,
    privacy: str = "private"
):
    """Logs uploaded video ID, speed metrics, and Studio URL to upload_log.csv."""
    import datetime
    ensure_upload_log()
    studio_url = f"https://studio.youtube.com/video/{video_id}/edit"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            now_str,
            filename,
            video_id,
            title,
            scheduled_time,
            f"{file_size_mb:.2f}",
            f"{upload_sec:.1f}",
            f"{speed_mbps:.2f}",
            studio_url,
            privacy
        ])


def format_seo_title(raw_title: str) -> str:
    """Cleans and optimizes title with high-CTR keywords and #Shorts tag."""
    import re
    cleaned = raw_title.replace("_", " ").strip()
    cleaned = re.sub(r'\b\d+s\b', '', cleaned).strip()
    if not cleaned:
        cleaned = "Insane GTA 6 Moment"

    full_title = f"{cleaned} 🤯 #GTA6 #Shorts"
    if len(full_title) > 100:
        full_title = full_title[:90] + "... #Shorts"
    return full_title


def format_seo_description(title: str, custom_desc: str = "") -> str:
    """Builds 4-layer YouTube SEO description with keywords, CTA, hashtags, and fair use."""
    clean_title = title.replace("#GTA6", "").replace("#Shorts", "").replace("🤯", "").strip()
    return (
        f"🔥 {clean_title} in Grand Theft Auto VI (GTA 6)!\n\n"
        f"Subscribe to @zelmuesports for daily GTA 6 leaks, secrets, and gameplay highlights!\n\n"
        f"🎮 Featured Game: Grand Theft Auto VI (Rockstar Games)\n"
        f"📌 Topics: GTA 6 Gameplay, Vice City, Lucia & Jason, PS5 & Xbox Series X\n\n"
        f"#Shorts #GTA6 #GrandTheftAuto6 #Gaming #GTA6Gameplay\n\n"
        f"---\n"
        f"Disclaimer: Transformed gameplay highlight edited with dynamic pacing, audio-reactive subtitles, and commentary under Fair Use for entertainment purposes."
    )


SEO_TAGS = [
    "GTA6", "GTA 6", "Grand Theft Auto VI", "GTA 6 Shorts",
    "GTA6 Gameplay", "GTA 6 Leaks", "Rockstar Games", "Vice City",
    "Lucia GTA 6", "Jason GTA 6", "GTA VI", "Gaming Shorts",
    "GTA6 Trailer", "GTA 6 Graphics", "Gaming", "Zelmu Esports"
]


def get_channel_analytics(creds: Optional[Credentials] = None) -> Dict[str, Any]:
    """Retrieves full channel metrics & demographics from YouTube Data API v3."""
    if creds is None:
        creds = get_credentials()
    if not creds:
        return {}
    try:
        yt = build("youtube", "v3", credentials=creds)
        resp = yt.channels().list(mine=True, part="snippet,statistics,contentDetails").execute()
        items = resp.get("items", [])
        if not items:
            return {}
        ch = items[0]
        stats = ch.get("statistics", {})
        snippet = ch.get("snippet", {})
        return {
            "title": snippet.get("title", "ZELMU ESPORTS"),
            "customUrl": snippet.get("customUrl", "@zelmuesports"),
            "subscribers": int(stats.get("subscriberCount", 0)),
            "views": int(stats.get("viewCount", 0)),
            "videoCount": int(stats.get("videoCount", 0)),
            "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", "")
        }
    except Exception as e:
        return {"error": str(e)}


def calculate_monetization_schedule_slots(count: int, slots_per_day: int = 6) -> List[str]:
    """
    Generates RFC 3339 timestamps for Tier-1 High-CPM windows spanning across days.
    Supports scheduling 100s of Shorts into future daily release slots automatically.
    """
    import datetime
    slots = []
    now = datetime.datetime.now(datetime.timezone.utc)

    if slots_per_day == 3:
        target_hours = [15, 18, 21]  # 3/day (10am, 1pm, 4pm EST)
    elif slots_per_day == 12:
        target_hours = [8, 10, 12, 14, 16, 17, 18, 19, 20, 21, 22, 23]  # 12/day hyper-frequency
    else:
        # Default 6/day (every 2-3 hours during active US/UK windows)
        target_hours = [10, 13, 15, 18, 20, 22]

    current_day = now.date()
    if now.hour >= target_hours[-1]:
        current_day = current_day + datetime.timedelta(days=1)

    day_offset = 0
    while len(slots) < count:
        d = current_day + datetime.timedelta(days=day_offset)
        for h in target_hours:
            candidate_dt = datetime.datetime(d.year, d.month, d.day, h, 0, 0, tzinfo=datetime.timezone.utc)
            if candidate_dt > now + datetime.timedelta(minutes=45):
                slots.append(candidate_dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
                if len(slots) == count:
                    break
        day_offset += 1
    return slots


def upload_single_video(
    youtube,
    file_path: Path,
    title: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    publish_at: Optional[str] = None,
    chunk_callback: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Uploads a single video strictly enforcing private status, defaultLanguage=en-US, and gaming category.
    Emits real-time transfer telemetry (MB/s, bytes sent, ETA, %) on every chunk.
    """
    import time
    file_path = file_path.resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"Video file does not exist: {file_path}")

    file_size_bytes = file_path.stat().st_size
    file_size_mb = file_size_bytes / (1024 * 1024)

    full_title = format_seo_title(title)

    full_tags = list(SEO_TAGS)
    if tags:
        for t in tags:
            if t not in full_tags:
                full_tags.append(t)

    full_description = format_seo_description(full_title, description)

    body = {
        "snippet": {
            "title": full_title,
            "description": full_description,
            "tags": full_tags,
            "categoryId": "20",  # Gaming
            "defaultLanguage": "en-US",
            "defaultAudioLanguage": "en-US"
        },
        "status": {
            "privacyStatus": "private",  # Strictly enforce private status
            "selfDeclaredMadeForKids": False,
            "embeddable": True
        }
    }

    if publish_at:
        body["status"]["publishAt"] = publish_at

    # 4MB chunks: multiple of 256KB, guarantees frequent live progress callbacks and low latency
    chunk_size = 1024 * 1024 * 4
    media = MediaFileUpload(
        str(file_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=chunk_size
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None
    t_start = time.time()

    while response is None:
        status, response = request.next_chunk()
        now = time.time()
        elapsed = max(0.05, now - t_start)

        if status:
            current_bytes = status.resumable_progress
            total_bytes = status.total_size
            pct = int(status.progress() * 100)
        else:
            current_bytes = file_size_bytes
            total_bytes = file_size_bytes
            pct = 100

        speed_bps = current_bytes / elapsed
        speed_MBs = speed_bps / (1024 * 1024)
        speed_mbps = speed_MBs * 8.0
        rem_bytes = max(0, total_bytes - current_bytes)
        eta_sec = rem_bytes / max(1.0, speed_bps) if rem_bytes > 0 else 0.0

        if chunk_callback:
            chunk_callback({
                "pct": pct,
                "current_bytes": current_bytes,
                "total_bytes": total_bytes,
                "file_size_mb": file_size_mb,
                "speed_MBs": speed_MBs,
                "speed_mbps": speed_mbps,
                "elapsed": elapsed,
                "eta_sec": eta_sec
            })

    total_duration = max(0.1, time.time() - t_start)
    avg_speed_MBs = file_size_mb / total_duration
    avg_speed_mbps = avg_speed_MBs * 8.0

    video_id = response.get("id")
    privacy_type = "scheduled" if publish_at else "private"
    log_upload(
        filename=file_path.name,
        video_id=video_id,
        title=full_title,
        scheduled_time=publish_at or "",
        file_size_mb=file_size_mb,
        upload_sec=total_duration,
        speed_mbps=avg_speed_mbps,
        privacy=privacy_type
    )

    # Explicitly release file handles to prevent WinError 32 on Windows
    if hasattr(media, "_fd") and media._fd:
        try:
            media._fd.close()
        except Exception:
            pass
    del media
    del request
    import gc
    gc.collect()

    # Move to uploaded_archive directory
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = ARCHIVE_DIR / file_path.name
    try:
        if dest_path.exists():
            dest_path.unlink()
        shutil.move(str(file_path), str(dest_path))
    except (PermissionError, OSError):
        try:
            shutil.copy2(str(file_path), str(dest_path))
            file_path.unlink()
        except Exception:
            pass

    return {
        "video_id": video_id,
        "title": full_title,
        "studio_url": f"https://studio.youtube.com/video/{video_id}/edit",
        "archive_path": str(dest_path),
        "file_size_mb": file_size_mb,
        "upload_sec": total_duration,
        "speed_mbps": avg_speed_mbps
    }


def upload_batch_private(
    max_batch_size: int = 150,
    auto_schedule: bool = False,
    slots_per_day: int = 6,
    concurrency: int = 2,
    progress_callback=None,
    chunk_callback=None,
    log_callback=None
) -> List[Dict[str, Any]]:
    """
    Uploads up to max_batch_size videos from ./ready_to_upload/ to YouTube as Private/Scheduled.
    If concurrency > 1, streams multiple videos in parallel to saturate upload bandwidth.
    Calculates live aggregate network speed, bytes sent, ETA, and progress.
    Safely captures quota limits without losing un-uploaded video files.
    """
    import concurrent.futures
    import threading

    READY_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    video_files = sorted(list(READY_DIR.glob("*.mp4")))
    if not video_files:
        return []

    batch = video_files[:max_batch_size]
    slots = calculate_monetization_schedule_slots(len(batch), slots_per_day=slots_per_day) if auto_schedule else [None] * len(batch)

    results = []
    total_count = len(batch)
    total_batch_bytes = sum(f.stat().st_size for f in batch)

    lock = threading.Lock()
    active_transfers = {}
    completed_bytes = 0
    completed_count = 0
    quota_hit = False

    def emit_telemetry(file_name: str = ""):
        if not chunk_callback:
            return
        with lock:
            current_active_bytes = sum(s.get("current_bytes", 0) for s in active_transfers.values())
            overall_bytes = completed_bytes + current_active_bytes
            overall_pct = min(100, int((overall_bytes / max(1, total_batch_bytes)) * 100))
            sum_speed_MBs = sum(s.get("speed_MBs", 0.0) for s in active_transfers.values())
            sum_speed_mbps = sum_speed_MBs * 8.0
            rem_bytes = max(0, total_batch_bytes - overall_bytes)
            eta_sec = rem_bytes / max(1.0, (sum_speed_MBs * 1024 * 1024)) if sum_speed_MBs > 0 else 0.0

            active_names = list(active_transfers.keys())
            display_file = file_name if file_name else (active_names[0] if active_names else "Syncing with YouTube...")
            stats_snapshot = active_transfers.get(display_file, {})

            try:
                chunk_callback({
                    "completed_count": completed_count,
                    "total_count": total_count,
                    "current_file": display_file,
                    "file_pct": stats_snapshot.get("pct", 0),
                    "overall_pct": overall_pct,
                    "overall_bytes_mb": overall_bytes / (1024 * 1024),
                    "total_batch_mb": total_batch_bytes / (1024 * 1024),
                    "speed_MBs": sum_speed_MBs,
                    "speed_mbps": sum_speed_mbps,
                    "eta_sec": eta_sec,
                    "active_workers": len(active_transfers),
                    "active_files": active_names
                })
            except Exception:
                pass

    token_pool = get_available_token_files()
    active_token_idx = 0

    def get_current_thread_client():
        tok = token_pool[active_token_idx] if token_pool else None
        return get_authenticated_service(tok)

    def worker_upload(idx: int, video_path: Path, pub_time: Optional[str]):
        nonlocal completed_bytes, completed_count, quota_hit, active_token_idx
        if quota_hit:
            return None

        file_name = video_path.name
        file_size = video_path.stat().st_size
        title_raw = video_path.stem.replace("_", " ")

        if progress_callback:
            progress_callback(idx + 1, total_count, file_name)

        if log_callback:
            curr_tok_name = token_pool[active_token_idx].name if token_pool else "default"
            log_callback(f"[Stream #{idx+1} | Acc: {curr_tok_name}] Uploading: {file_name} ({file_size / (1024*1024):.1f} MB)...")

        # Thread-local YouTube API client
        yt_thread = get_current_thread_client()

        def on_chunk(stats):
            with lock:
                active_transfers[file_name] = stats

        try:
            res = upload_single_video(
                yt_thread,
                video_path,
                title=title_raw,
                publish_at=pub_time,
                chunk_callback=on_chunk
            )
            with lock:
                completed_bytes += file_size
                completed_count += 1
                if file_name in active_transfers:
                    del active_transfers[file_name]

            if pub_time:
                res["publish_at"] = pub_time

            if log_callback:
                sched_msg = f" (Scheduled: {pub_time})" if pub_time else " (Private)"
                log_callback(f"✓ [{idx+1}/{total_count}] Uploaded: {res['title']}{sched_msg} | {res['speed_mbps']:.1f} Mbps | ID: {res['video_id']}")

            return res
        except Exception as e:
            with lock:
                if file_name in active_transfers:
                    del active_transfers[file_name]
            err_msg = str(e)
            if "quotaExceeded" in err_msg or "uploadLimitExceeded" in err_msg:
                # Multi-Account Quota Rotation: check if backup account token exists
                with lock:
                    if active_token_idx + 1 < len(token_pool):
                        active_token_idx += 1
                        next_tok = token_pool[active_token_idx]
                        if log_callback:
                            log_callback(f"🔄 QUOTA LIMIT HIT on account #{active_token_idx}. Auto-rotating to backup token: {next_tok.name}...")
                        # Retry uploading with the rotated token
                        yt_rotated = get_authenticated_service(next_tok)
                        return upload_single_video(
                            yt_rotated,
                            video_path,
                            title=title_raw,
                            publish_at=pub_time,
                            chunk_callback=on_chunk
                        )
                quota_hit = True
                msg = f"Daily YouTube upload quota reached on all available accounts at clip #{idx+1}. Remaining clips safely saved in ready_to_upload/."
                if log_callback:
                    log_callback(f"⚠️ {msg}")
                return {"error": msg, "video_id": None}
            else:
                if log_callback:
                    log_callback(f"❌ Error uploading {file_name}: {err_msg}")
                raise

    if concurrency <= 1 or len(batch) == 1:
        for idx, (video_path, pub_time) in enumerate(zip(batch, slots)):
            r = worker_upload(idx, video_path, pub_time)
            emit_telemetry(video_path.name)
            if r:
                results.append(r)
                if r.get("error"):
                    break
    else:
        import time
        pool_size = min(concurrency, len(batch))
        with concurrent.futures.ThreadPoolExecutor(max_workers=pool_size) as executor:
            future_to_idx = {
                executor.submit(worker_upload, idx, v_path, p_time): idx
                for idx, (v_path, p_time) in enumerate(zip(batch, slots))
            }
            while any(not f.done() for f in future_to_idx):
                time.sleep(0.4)
                emit_telemetry()

            for fut in future_to_idx:
                res = fut.result()
                if res:
                    results.append(res)

    return results
