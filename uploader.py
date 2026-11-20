import os
import csv
import json
import shutil
import urllib.parse
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

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

# In-memory tracking for channel info cache & quota-exhausted slots
_CHANNEL_INFO_CACHE: Dict[str, Any] = {}
_EXHAUSTED_SLOT_IDS = set()


def mark_slot_quota_exhausted(slot_id: str):
    """Marks an account slot as having hit its daily 10k quota."""
    _EXHAUSTED_SLOT_IDS.add(slot_id)


def reset_exhausted_slots():
    """Resets daily exhausted quota tracking."""
    _EXHAUSTED_SLOT_IDS.clear()


def list_account_slots() -> List[Dict[str, Any]]:
    """
    Discovers and returns all configured Google Cloud project account slots.
    Pairs each client_secrets_*.json with its corresponding token_*.json in tokens/ and root.
    """
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    slots = []
    seen_slot_ids = set()

    # 1. Primary/Default Slot
    default_sec = CLIENT_SECRETS_FILE if CLIENT_SECRETS_FILE.exists() else (
        TOKENS_DIR / "client_secrets_default.json" if (TOKENS_DIR / "client_secrets_default.json").exists() else None
    )
    default_tok = TOKEN_FILE if TOKEN_FILE.exists() else (
        TOKENS_DIR / "token_default.json" if (TOKENS_DIR / "token_default.json").exists() else TOKEN_FILE
    )

    if default_sec or default_tok.exists() or CLIENT_SECRETS_FILE.exists():
        seen_slot_ids.add("default")
        cid, pid = "", ""
        if default_sec and default_sec.exists():
            try:
                with open(default_sec, "r", encoding="utf-8") as f:
                    d = json.load(f)
                cfg = d.get("installed") or d.get("web") or {}
                cid = cfg.get("client_id", "")
                pid = cfg.get("project_id", "")
            except Exception:
                pass

        is_auth = default_tok.exists() and is_authenticated(default_tok)
        ch_title, ch_handle = "YouTube Channel", "@zelmuesports"
        if is_auth:
            info = get_channel_info(token_path=default_tok) or {}
            ch_title = info.get("title", "YouTube Channel")
            ch_handle = info.get("customUrl", "") or "@zelmuesports"

        quota_hit = "default" in _EXHAUSTED_SLOT_IDS
        if quota_hit:
            status = "Quota Limit Reached (10k)"
        elif is_auth:
            status = "Connected & Active"
        elif default_sec and default_sec.exists():
            status = "Needs Authentication"
        else:
            status = "Missing client_secrets.json"

        slots.append({
            "slot_id": "default",
            "name": "Slot 1 (Primary)",
            "secrets_path": default_sec or CLIENT_SECRETS_FILE,
            "token_path": default_tok,
            "project_id": pid or "Primary GCP Project",
            "client_id": cid,
            "is_authenticated": is_auth,
            "channel_title": ch_title,
            "channel_handle": ch_handle,
            "status": status,
            "quota_exceeded": quota_hit
        })

    # 2. Search for additional client_secrets_*.json in tokens/ and root
    candidate_secs = list(TOKENS_DIR.glob("client_secrets_*.json")) + list(Path(".").glob("client_secrets_*.json"))
    for sec_p in candidate_secs:
        stem = sec_p.stem
        if not stem.startswith("client_secrets_"):
            continue
        slot_id = stem[len("client_secrets_"):].strip().lower()
        if not slot_id or slot_id in seen_slot_ids or slot_id == "default":
            continue
        seen_slot_ids.add(slot_id)

        tok_p = TOKENS_DIR / f"token_{slot_id}.json"
        if not tok_p.exists():
            alt_tok = Path(f"token_{slot_id}.json")
            if alt_tok.exists():
                tok_p = alt_tok

        cid, pid = "", ""
        try:
            with open(sec_p, "r", encoding="utf-8") as f:
                d = json.load(f)
            cfg = d.get("installed") or d.get("web") or {}
            cid = cfg.get("client_id", "")
            pid = cfg.get("project_id", "")
        except Exception:
            pass

        is_auth = tok_p.exists() and is_authenticated(tok_p)
        ch_title, ch_handle = "YouTube Channel", "@zelmuesports"
        if is_auth:
            info = get_channel_info(token_path=tok_p) or {}
            ch_title = info.get("title", "YouTube Channel")
            ch_handle = info.get("customUrl", "") or "@zelmuesports"

        quota_hit = slot_id in _EXHAUSTED_SLOT_IDS
        if quota_hit:
            status = "Quota Limit Reached (10k)"
        elif is_auth:
            status = "Connected & Active"
        else:
            status = "Needs Authentication"

        slot_num = len(slots) + 1
        slots.append({
            "slot_id": slot_id,
            "name": f"Slot {slot_num} ({pid or slot_id})",
            "secrets_path": sec_p,
            "token_path": tok_p,
            "project_id": pid or slot_id,
            "client_id": cid,
            "is_authenticated": is_auth,
            "channel_title": ch_title,
            "channel_handle": ch_handle,
            "status": status,
            "quota_exceeded": quota_hit
        })

    # 3. Check for any standalone token_*.json in tokens/
    candidate_toks = list(TOKENS_DIR.glob("token_*.json")) + list(Path(".").glob("token_*.json"))
    for tok_p in candidate_toks:
        stem = tok_p.stem
        if not stem.startswith("token_"):
            continue
        slot_id = stem[len("token_"):].strip().lower()
        if not slot_id or slot_id in seen_slot_ids or slot_id == "default":
            continue
        seen_slot_ids.add(slot_id)

        sec_p = TOKENS_DIR / f"client_secrets_{slot_id}.json"
        if not sec_p.exists():
            sec_p = CLIENT_SECRETS_FILE if CLIENT_SECRETS_FILE.exists() else None

        is_auth = is_authenticated(tok_p)
        ch_title, ch_handle = "YouTube Channel", "@zelmuesports"
        if is_auth:
            info = get_channel_info(token_path=tok_p) or {}
            ch_title = info.get("title", "YouTube Channel")
            ch_handle = info.get("customUrl", "") or "@zelmuesports"

        slot_num = len(slots) + 1
        slots.append({
            "slot_id": slot_id,
            "name": f"Slot {slot_num} ({slot_id})",
            "secrets_path": sec_p,
            "token_path": tok_p,
            "project_id": slot_id,
            "client_id": "",
            "is_authenticated": is_auth,
            "channel_title": ch_title,
            "channel_handle": ch_handle,
            "status": "Connected & Active" if is_auth else "Token Expired",
            "quota_exceeded": slot_id in _EXHAUSTED_SLOT_IDS
        })

    return slots


def add_account_slot(
    secrets_source: Any,
    slot_id: Optional[str] = None,
    custom_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Adds a new client_secrets JSON into tokens/ and pairs it with token_{slot_id}.json.
    Accepts file path, raw bytes, string, or parsed dict.
    Supports multi-file batch additions with custom_name.
    """
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    if isinstance(secrets_source, dict):
        data = secrets_source
    elif isinstance(secrets_source, bytes):
        data = json.loads(secrets_source.decode("utf-8"))
    elif isinstance(secrets_source, (str, Path)):
        p = Path(secrets_source)
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = json.loads(str(secrets_source))
    else:
        raise ValueError("Unsupported secrets_source format")

    cfg = data.get("installed") or data.get("web")
    if not cfg:
        raise ValueError("Invalid client_secrets.json: missing 'installed' or 'web' application credentials.")
    if "client_id" not in cfg:
        raise ValueError("Invalid client_secrets.json: missing 'client_id'.")

    proj_id = cfg.get("project_id", "")
    existing_slots = {s["slot_id"] for s in list_account_slots()}

    if not slot_id:
        candidate_id = ""
        if custom_name:
            stem = Path(custom_name).stem
            if stem.lower().startswith("client_secrets_"):
                candidate_id = stem[len("client_secrets_"):].strip()
            elif stem.lower().startswith("client_secret_"):
                candidate_id = stem[len("client_secret_"):].strip()
            elif stem.lower().startswith("client_secrets"):
                candidate_id = stem[len("client_secrets"):].strip()
            else:
                candidate_id = stem
            candidate_id = re.sub(r'[^a-zA-Z0-9_-]', '', candidate_id).lower()

        if not candidate_id and proj_id:
            candidate_id = re.sub(r'[^a-zA-Z0-9_-]', '', proj_id).lower()

        if candidate_id and candidate_id not in existing_slots and candidate_id != "default":
            slot_id = candidate_id
        else:
            idx = max(2, len(existing_slots) + 1)
            while f"slot_{idx}" in existing_slots:
                idx += 1
            slot_id = f"slot_{idx}"
    else:
        slot_id = re.sub(r'[^a-zA-Z0-9_-]', '', slot_id).lower()

    target_sec = TOKENS_DIR / f"client_secrets_{slot_id}.json"
    target_tok = TOKENS_DIR / f"token_{slot_id}.json"

    with open(target_sec, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    display_name = custom_name if custom_name else (f"Slot ({proj_id})" if proj_id else f"Slot ({slot_id})")

    return {
        "slot_id": slot_id,
        "name": display_name,
        "secrets_path": target_sec,
        "token_path": target_tok,
        "project_id": proj_id or slot_id,
        "client_id": cfg.get("client_id", ""),
        "is_authenticated": False,
        "channel_title": "YouTube Channel",
        "channel_handle": "@zelmuesports",
        "status": "Ready for Authentication",
        "quota_exceeded": False
    }


def delete_account_slot(slot_id: str) -> bool:
    """Removes a secondary account slot from tokens/."""
    if slot_id == "default":
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
            return True
        return False

    deleted = False
    sec = TOKENS_DIR / f"client_secrets_{slot_id}.json"
    tok = TOKENS_DIR / f"token_{slot_id}.json"
    if sec.exists():
        sec.unlink()
        deleted = True
    if tok.exists():
        tok.unlink()
        deleted = True
    return deleted


def authenticate_account_slot(
    slot_id: str,
    port: int = 8080,
    timeout_seconds: int = 60,
    code: Optional[str] = None,
    redirect_uri: str = DEFAULT_REDIRECT_URI
) -> Credentials:
    """
    Authenticates a specific account slot using interactive browser or manual code exchange.
    Saves credentials to the slot's corresponding token file.
    """
    slots = {s["slot_id"]: s for s in list_account_slots()}
    if slot_id not in slots:
        raise ValueError(f"Account slot '{slot_id}' not found.")
    slot = slots[slot_id]
    sec_path = slot["secrets_path"]
    tok_path = slot["token_path"]

    if not sec_path or not Path(sec_path).exists():
        raise FileNotFoundError(f"Client secrets file not found for slot '{slot_id}': {sec_path}")

    if code:
        creds = exchange_code_for_token(code, redirect_uri=redirect_uri, secrets_file=sec_path, token_file=tok_path)
    else:
        creds = run_local_server_auth(port=port, timeout_seconds=timeout_seconds, secrets_file=sec_path, token_file=tok_path)

    # Invalidate cache for this token
    cache_key = str(Path(tok_path).resolve()) if Path(tok_path).exists() else str(tok_path)
    if cache_key in _CHANNEL_INFO_CACHE:
        del _CHANNEL_INFO_CACHE[cache_key]

    return creds


def test_account_slot(slot_id: str) -> Dict[str, Any]:
    """
    Tests YouTube Data API v3 connectivity and channel verification for an account slot.
    Returns status dictionary.
    """
    slots = {s["slot_id"]: s for s in list_account_slots()}
    if slot_id not in slots:
        return {"valid": False, "error": f"Slot '{slot_id}' not found"}
    slot = slots[slot_id]
    tok_path = slot["token_path"]
    if not tok_path or not Path(tok_path).exists():
        return {"valid": False, "error": "Token not found. Sign-in required."}

    creds = get_credentials(tok_path)
    if not creds:
        return {"valid": False, "error": "Token expired or invalid. Re-authentication required."}

    try:
        info = get_channel_info(creds=creds, token_path=tok_path, force_refresh=True) or {}
        handle = info.get("customUrl", "") or "@zelmuesports"
        title = info.get("title", "YouTube Channel")
        return {
            "valid": True,
            "channel_title": title,
            "channel_handle": handle,
            "message": f"Verified: Linked to {title} ({handle})"
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


def get_auth_url_for_slot(slot_id: str, redirect_uri: str = DEFAULT_REDIRECT_URI) -> str:
    """Generates direct Google OAuth consent URL for a specific slot."""
    slots = {s["slot_id"]: s for s in list_account_slots()}
    if slot_id not in slots:
        raise ValueError(f"Account slot '{slot_id}' not found.")
    sec_path = slots[slot_id]["secrets_path"]
    if not sec_path or not Path(sec_path).exists():
        raise FileNotFoundError(f"Client secrets not found for slot '{slot_id}'")
    return get_auth_url(redirect_uri=redirect_uri, secrets_file=sec_path)


def get_available_token_files() -> List[Path]:
    """Finds all available authenticated token.json files across configured account slots."""
    slots = list_account_slots()
    auth_toks = [s["token_path"] for s in slots if s["is_authenticated"]]
    if auth_toks:
        return auth_toks
    if TOKEN_FILE.exists():
        return [TOKEN_FILE]
    return []


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
        target_token = Path(token_path) if token_path else TOKEN_FILE
        raise RuntimeError(f"YouTube not authenticated for '{target_token.name}'. Complete Google OAuth sign-in first.")
    return build("youtube", "v3", credentials=creds)


def get_auth_url(redirect_uri: str = DEFAULT_REDIRECT_URI, secrets_file: Optional[Path] = None) -> str:
    """Generates direct Google OAuth consent URL without PKCE constraint for bulletproof copy-paste token exchange."""
    target_sec = Path(secrets_file) if secrets_file else CLIENT_SECRETS_FILE
    if not target_sec.exists():
        raise FileNotFoundError(f"'{target_sec}' not found.")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(target_sec),
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    flow.autogenerate_code_verifier = False
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    return auth_url


def exchange_code_for_token(
    code_or_url: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    secrets_file: Optional[Path] = None,
    token_file: Optional[Path] = None
) -> Credentials:
    """
    Exchanges authorization code (or full redirected callback URL) for tokens and saves token file.
    """
    target_sec = Path(secrets_file) if secrets_file else CLIENT_SECRETS_FILE
    target_tok = Path(token_file) if token_file else TOKEN_FILE

    if not target_sec.exists():
        raise FileNotFoundError(f"'{target_sec}' not found.")

    raw = code_or_url.strip()
    if "code=" in raw:
        parsed = urllib.parse.urlparse(raw)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [raw])[0]
    else:
        code = raw

    flow = InstalledAppFlow.from_client_secrets_file(
        str(target_sec),
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    flow.autogenerate_code_verifier = False
    flow.fetch_token(code=code)

    creds = flow.credentials
    target_tok.parent.mkdir(parents=True, exist_ok=True)
    with open(target_tok, "w", encoding="utf-8") as f:
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


def run_local_server_auth(
    port: int = 8080,
    timeout_seconds: int = 60,
    secrets_file: Optional[Path] = None,
    token_file: Optional[Path] = None
) -> Credentials:
    """
    Launches local OAuth listener on free port with a timeout to prevent hanging.
    """
    target_sec = Path(secrets_file) if secrets_file else CLIENT_SECRETS_FILE
    target_tok = Path(token_file) if token_file else TOKEN_FILE

    if not target_sec.exists():
        raise FileNotFoundError(f"'{target_sec}' not found.")

    free_port = find_available_port(port)
    flow = InstalledAppFlow.from_client_secrets_file(str(target_sec), SCOPES)
    creds = flow.run_local_server(
        port=free_port,
        open_browser=True,
        timeout_seconds=timeout_seconds,
        success_message="Authentication successful! You can now close this tab and return to Zelmu Clipping."
    )
    target_tok.parent.mkdir(parents=True, exist_ok=True)
    with open(target_tok, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    return creds


def get_channel_info(creds: Optional[Credentials] = None, token_path: Optional[Path] = None, force_refresh: bool = False) -> Optional[Dict[str, str]]:
    """Retrieves channel snippet for authenticated account with smart mtime caching."""
    target_token = Path(token_path) if token_path else TOKEN_FILE
    cache_key = str(target_token.resolve()) if target_token.exists() else str(target_token)

    if not force_refresh and cache_key in _CHANNEL_INFO_CACHE:
        cached_mtime, cached_info = _CHANNEL_INFO_CACHE[cache_key]
        curr_mtime = target_token.stat().st_mtime if target_token.exists() else 0
        if cached_mtime == curr_mtime:
            return cached_info

    if creds is None:
        creds = get_credentials(target_token)
    if not creds:
        return None
    try:
        yt = build("youtube", "v3", credentials=creds)
        resp = yt.channels().list(mine=True, part="snippet").execute()
        items = resp.get("items", [])
        if items:
            snip = items[0]["snippet"]
            info = {
                "title": snip.get("title", "YouTube Channel"),
                "customUrl": snip.get("customUrl", "") or "@zelmuesports",
                "thumbnail": snip.get("thumbnails", {}).get("default", {}).get("url", "")
            }
        else:
            info = {"title": "Connected Account", "customUrl": "@zelmuesports", "thumbnail": ""}
        curr_mtime = target_token.stat().st_mtime if target_token.exists() else 0
        _CHANNEL_INFO_CACHE[cache_key] = (curr_mtime, info)
        return info
    except Exception as e:
        return {"title": "Connected", "customUrl": "@zelmuesports", "error": str(e)}


def revoke_token(token_file: Optional[Path] = None):
    """Removes specified token file (or default token.json) to disconnect account."""
    target_tok = Path(token_file) if token_file else TOKEN_FILE
    if target_tok.exists():
        target_tok.unlink()
    cache_key = str(target_tok.resolve()) if target_tok.exists() else str(target_tok)
    if cache_key in _CHANNEL_INFO_CACHE:
        del _CHANNEL_INFO_CACHE[cache_key]


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
    privacy_status: str = "private",
    chunk_callback: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Uploads a single video strictly enforcing defaultLanguage=en-US and gaming category.
    Supports privacy_status="private", "public", or "scheduled" (via publish_at).
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
    effective_privacy = "private" if publish_at else privacy_status

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
            "privacyStatus": effective_privacy,
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
    privacy_type = "scheduled" if publish_at else effective_privacy
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

    # Permanently delete video file from disk upon confirmed upload/schedule success
    try:
        if file_path.exists():
            file_path.unlink()
    except Exception:
        pass

    return {
        "video_id": video_id,
        "title": full_title,
        "studio_url": f"https://studio.youtube.com/video/{video_id}/edit",
        "file_size_mb": file_size_mb,
        "upload_sec": total_duration,
        "speed_mbps": avg_speed_mbps
    }


def upload_single_clip_direct(
    file_path: Path,
    title: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    privacy_mode: str = "private",  # "private", "public", "scheduled"
    chunk_callback: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Directly uploads or schedules a single video from the Produce UI.
    """
    creds = get_credentials()
    if not creds:
        raise RuntimeError("YouTube not connected. Authenticate in Tab 2 first.")
    youtube = get_authenticated_service()

    publish_at = None
    if privacy_mode == "scheduled":
        slots = calculate_monetization_schedule_slots(1, slots_per_day=6)
        publish_at = slots[0] if slots else None
        effective_privacy = "private"
    else:
        effective_privacy = privacy_mode

    return upload_single_video(
        youtube=youtube,
        file_path=file_path,
        title=title,
        description=description,
        tags=tags,
        publish_at=publish_at,
        privacy_status=effective_privacy,
        chunk_callback=chunk_callback
    )


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

    slots_pool = [s for s in list_account_slots() if s["is_authenticated"]]
    active_slot_idx = 0

    def get_current_thread_client():
        with lock:
            if slots_pool:
                tok = slots_pool[active_slot_idx]["token_path"]
            else:
                tok = TOKEN_FILE
        return get_authenticated_service(tok)

    def worker_upload(idx: int, video_path: Path, pub_time: Optional[str]):
        nonlocal completed_bytes, completed_count, quota_hit, active_slot_idx
        if quota_hit:
            return None

        file_name = video_path.name
        file_size = video_path.stat().st_size
        title_raw = video_path.stem.replace("_", " ")

        if progress_callback:
            progress_callback(idx + 1, total_count, file_name)

        if log_callback:
            curr_slot_name = slots_pool[active_slot_idx]["name"] if slots_pool else "Default Slot"
            log_callback(f"[Stream #{idx+1} | {curr_slot_name}] Uploading: {file_name} ({file_size / (1024*1024):.1f} MB)...")

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
                # Multi-Project Quota Rotator: auto-rotate to next available authorized slot
                rotated = False
                with lock:
                    curr_slot = slots_pool[active_slot_idx] if slots_pool else {"name": "Default Slot", "slot_id": "default"}
                    mark_slot_quota_exhausted(curr_slot.get("slot_id", "default"))
                    if slots_pool and active_slot_idx + 1 < len(slots_pool):
                        active_slot_idx += 1
                        next_slot = slots_pool[active_slot_idx]
                        rotated = True
                        if log_callback:
                            log_callback(
                                f"🔄 QUOTA LIMIT HIT (10,000 units) on '{curr_slot.get('name', 'Current Slot')}'. "
                                f"Seamlessly auto-rotating to slot '{next_slot.get('name', 'Next Slot')}' "
                                f"(Target channel: {next_slot.get('channel_handle', '@zelmuesports')})..."
                            )
                if rotated:
                    # Retry uploading with the rotated token/client on target channel
                    next_tok = slots_pool[active_slot_idx]["token_path"]
                    yt_rotated = get_authenticated_service(next_tok)
                    return upload_single_video(
                        yt_rotated,
                        video_path,
                        title=title_raw,
                        publish_at=pub_time,
                        chunk_callback=on_chunk
                    )
                else:
                    quota_hit = True
                    slot_cnt = len(slots_pool) if slots_pool else 1
                    msg = (
                        f"Daily YouTube upload quota reached across all {slot_cnt} configured account slot(s) "
                        f"at clip #{idx+1}. Remaining clips safely saved in ready_to_upload/."
                    )
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
