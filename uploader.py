import os
import csv
import json
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# YouTube Data API V3 Upload Scope
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRETS_FILE = Path("client_secrets.json")
TOKEN_FILE = Path("token.json")
LOG_FILE = Path("upload_log.csv")
READY_DIR = Path("ready_to_upload")
ARCHIVE_DIR = Path("uploaded_archive")

def get_authenticated_service():
    """
    Handles OAuth 2.0 flow using client_secrets.json and caches token.json.
    """
    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRETS_FILE.exists():
                raise FileNotFoundError(
                    f"'{CLIENT_SECRETS_FILE}' not found in project directory. "
                    "Place your Google Cloud client_secrets.json to authenticate."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w", encoding="utf-8") as token_out:
            token_out.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)

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

def upload_single_video(
    youtube,
    file_path: Path,
    title: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    chunk_callback: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Uploads a single video strictly enforcing private status, defaultLanguage=en-US, and gaming category.
    """
    file_path = file_path.resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"Video file does not exist: {file_path}")

    # Enforce title formatting and tags
    full_title = f"{title} #GTA6 #Shorts"
    if len(full_title) > 100:
        full_title = full_title[:97] + "..."

    full_tags = ["GTA6", "Grand Theft Auto VI", "Shorts", "Gaming", "GTA6 Gameplay"]
    if tags:
        full_tags.extend(tags)

    full_description = (
        f"{description}\n\n"
        "#GTA6 #Shorts #GrandTheftAuto6\n"
        "Transformed gameplay highlight. Created for entertainment and commentary purposes."
    )

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
            "selfDeclaredMadeForKids": False
        }
    }

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

    # Move to uploaded_archive directory
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = ARCHIVE_DIR / file_path.name
    if dest_path.exists():
        dest_path.unlink()
    shutil.move(str(file_path), str(dest_path))

    return {
        "video_id": video_id,
        "title": full_title,
        "studio_url": f"https://studio.youtube.com/video/{video_id}/edit",
        "archive_path": str(dest_path)
    }

def upload_batch_private(
    max_batch_size: int = 25,
    progress_callback=None,
    chunk_callback=None
) -> List[Dict[str, Any]]:
    """
    Uploads up to 25 videos from ./ready_to_upload/ to YouTube as Private.
    Strictly caps at 25 videos to protect channel health.
    """
    READY_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    video_files = sorted(list(READY_DIR.glob("*.mp4")))
    if not video_files:
        return []

    # Cap at max_batch_size
    batch = video_files[:max_batch_size]
    youtube = get_authenticated_service()

    results = []
    total = len(batch)

    for idx, video_path in enumerate(batch):
        # Extract title from filename (removing extension and underscores)
        title_raw = video_path.stem.replace("_", " ")
        if progress_callback:
            progress_callback(idx + 1, total, video_path.name)

        def on_single_chunk(pct: int):
            if chunk_callback:
                chunk_callback(idx + 1, total, video_path.name, pct)

        res = upload_single_video(youtube, video_path, title=title_raw, chunk_callback=on_single_chunk)
        results.append(res)

    return results
