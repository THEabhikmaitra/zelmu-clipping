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
LOG_FILE = Path("upload_log.csv")
READY_DIR = Path("ready_to_upload")
ARCHIVE_DIR = Path("uploaded_archive")
DEFAULT_REDIRECT_URI = "http://localhost:8080/"


def get_credentials() -> Optional[Credentials]:
    """Returns valid Credentials if available and refreshed, else None."""
    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception:
            creds = None

    if creds:
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
                return creds
            except Exception:
                return None
    return None


def is_authenticated() -> bool:
    """Checks whether valid YouTube OAuth credentials exist."""
    return get_credentials() is not None


def get_authenticated_service():
    """
    Returns YouTube API client. Raises RuntimeError if not authenticated.
    """
    creds = get_credentials()
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


def ensure_upload_log():
    """Ensures CSV log file exists with proper headers."""
    if not LOG_FILE.exists():
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "Original_File", "Video_ID", "Title", "Studio_URL", "Privacy"])


def log_upload(filename: str, video_id: str, title: str):
    """Logs uploaded video ID and Studio URL to upload_log.csv."""
    import datetime
    ensure_upload_log()
    studio_url = f"https://studio.youtube.com/video/{video_id}/edit"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([now_str, filename, video_id, title, studio_url, "private"])


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
    Optionally schedules publication using RFC 3339 publish_at timestamp.
    """
    file_path = file_path.resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"Video file does not exist: {file_path}")

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

    media = MediaFileUpload(
        str(file_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024 * 4
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and chunk_callback:
            chunk_callback(int(status.progress() * 100))

    video_id = response.get("id")
    log_upload(file_path.name, video_id, full_title)

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
        "archive_path": str(dest_path)
    }


def upload_batch_private(
    max_batch_size: int = 150,
    auto_schedule: bool = False,
    slots_per_day: int = 6,
    progress_callback=None,
    chunk_callback=None
) -> List[Dict[str, Any]]:
    """
    Uploads up to max_batch_size videos from ./ready_to_upload/ to YouTube as Private/Scheduled.
    If auto_schedule=True, spreads 100s of Shorts across daily peak High-CPM slots into the future.
    Safely captures quota limits without losing un-uploaded video files.
    """
    READY_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    video_files = sorted(list(READY_DIR.glob("*.mp4")))
    if not video_files:
        return []

    batch = video_files[:max_batch_size]
    youtube = get_authenticated_service()

    slots = calculate_monetization_schedule_slots(len(batch), slots_per_day=slots_per_day) if auto_schedule else [None] * len(batch)

    results = []
    total = len(batch)

    for idx, (video_path, pub_time) in enumerate(zip(batch, slots)):
        title_raw = video_path.stem.replace("_", " ")
        if progress_callback:
            progress_callback(idx + 1, total, video_path.name)

        def on_single_chunk(pct: int):
            if chunk_callback:
                chunk_callback(idx + 1, total, video_path.name, pct)

        try:
            res = upload_single_video(
                youtube,
                video_path,
                title=title_raw,
                publish_at=pub_time,
                chunk_callback=on_single_chunk
            )
            if pub_time:
                res["publish_at"] = pub_time
            results.append(res)
        except Exception as e:
            err_msg = str(e)
            if "quotaExceeded" in err_msg or "uploadLimitExceeded" in err_msg:
                results.append({
                    "error": f"Daily YouTube upload quota reached at clip #{idx+1}. Remaining {total - idx} clips safely saved in ready_to_upload/ for tomorrow.",
                    "video_id": None
                })
                break
            else:
                raise

    return results
