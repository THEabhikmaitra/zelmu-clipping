"""
Autonomous Channel Watcher Daemon for Zelmu Clipping.
Monitors YouTube channels for new uploads 24/7, auto-extracts viral Shorts,
and schedules them to YouTube Studio across peak High-CPM monetization windows.
"""

import os
import sys
import time
import json
import subprocess
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional

from transcriber import (
    get_ytdlp_cmd,
    get_ffmpeg_path,
    get_video_metadata,
    fetch_youtube_captions,
    extract_audio_wav,
    transcribe_audio_whisper
)
from analyzer import extract_candidates_full
from editor import generate_karaoke_ass, render_mode_a_short, check_internet_connection
from uploader import upload_batch_private, calculate_monetization_schedule_slots, is_authenticated

CONFIG_FILE = Path("watcher_config.json")
STATE_FILE = Path("watcher_state.json")
WORKSPACE_DIR = Path("workspace")
READY_DIR = Path("ready_to_upload")

DEFAULT_CONFIG = {
    "enabled": False,
    "channels": [
        "https://www.youtube.com/@RockstarGames/videos",
        "https://www.youtube.com/@TmarTn2/videos"
    ],
    "check_interval_minutes": 30,
    "shorts_per_video": 4,
    "auto_upload": True,
    "caption_style": "neon",
    "enable_tracking": False,
    "enable_hook_badge": True
}

_WATCHER_THREAD = None
_WATCHER_STOP_EVENT = threading.Event()
_WATCHER_LOGS = []
_WATCHER_LOCK = threading.Lock()


def push_watcher_log(msg: str):
    import datetime
    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    entry = f"[{now_str}] {msg}"
    with _WATCHER_LOCK:
        _WATCHER_LOGS.append(entry)
        if len(_WATCHER_LOGS) > 100:
            _WATCHER_LOGS.pop(0)


def get_watcher_logs() -> List[str]:
    with _WATCHER_LOCK:
        return list(_WATCHER_LOGS)


def load_watcher_config() -> Dict[str, Any]:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                merged = dict(DEFAULT_CONFIG)
                merged.update(cfg)
                return merged
        except Exception:
            return dict(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_watcher_config(cfg: Dict[str, Any]):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def load_watcher_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"processed_video_ids": [], "last_check_timestamp": 0}
    return {"processed_video_ids": [], "last_check_timestamp": 0}


def save_watcher_state(state: Dict[str, Any]):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def get_channel_recent_videos(channel_url: str, max_videos: int = 3) -> List[Dict[str, str]]:
    """Fetches the latest video IDs and titles from a YouTube channel in ~2s."""
    clean_url = channel_url.strip()
    if not clean_url:
        return []
    if "/videos" not in clean_url and not clean_url.endswith("/"):
        clean_url = f"{clean_url}/videos"

    cmd = [
        *get_ytdlp_cmd(),
        "--flat-playlist",
        "--no-warnings",
        "--print", "%(id)s\t%(title)s",
        clean_url,
        "--playlist-end", str(max_videos)
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        videos = []
        if proc.returncode == 0 and proc.stdout:
            for line in proc.stdout.splitlines():
                parts = line.strip().split("\t")
                if len(parts) >= 2:
                    vid_id = parts[0].strip()
                    title = parts[1].strip()
                    if vid_id and len(vid_id) == 11:
                        videos.append({"id": vid_id, "title": title, "url": f"https://www.youtube.com/watch?v={vid_id}"})
        return videos
    except Exception as e:
        push_watcher_log(f"Channel poll error ({channel_url}): {e}")
        return []


def process_video_autonomous(
    video_url: str,
    shorts_count: int = 4,
    caption_style: str = "neon",
    enable_tracking: bool = False,
    enable_hook_badge: bool = True,
    auto_upload: bool = True
) -> List[Path]:
    """Runs end-to-end extraction, karaoke rendering, and scheduling for a new video."""
    meta = get_video_metadata(video_url)
    vid_id = meta.get("id") or "unknown"
    title = meta.get("title") or "GTA 6 Video"
    author = meta.get("author") or "Creator"

    push_watcher_log(f"Processing new video: '{title}' ({vid_id}) by @{author}...")

    work_dir = WORKSPACE_DIR / vid_id
    work_dir.mkdir(parents=True, exist_ok=True)
    segments_dir = work_dir / "04_segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    READY_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Transcript
    transcript_json = work_dir / "02_transcript.json"
    transcript = None
    if transcript_json.exists():
        with open(transcript_json, "r", encoding="utf-8") as f:
            transcript = json.load(f)

    if not transcript:
        transcript = fetch_youtube_captions(video_url, transcript_json, max_duration_sec=900.0)

    if not transcript:
        audio_wav = work_dir / "01_audio.wav"
        extract_audio_wav(video_url, audio_wav, max_duration_sec=900.0)
        transcript = transcribe_audio_whisper(audio_wav, transcript_json)

    # 2. Candidate Analysis
    cand_json = work_dir / "03_candidates_mode_a.json"
    if cand_json.exists():
        with open(cand_json, "r", encoding="utf-8") as f:
            analysis = json.load(f)
    else:
        analysis = extract_candidates_full(
            transcript,
            mode="Mode A",
            channel_name=author,
            target_clips=shorts_count
        )
        with open(cand_json, "w", encoding="utf-8") as f:
            json.dump(analysis, f, indent=2)

    candidates = analysis.get("candidates", [])
    style_key = "neon" if "neon" in caption_style.lower() else ("clean" if "clean" in caption_style.lower() else "karaoke")

    rendered_files = []
    from editor import download_video_section, find_profanities_in_words

    for c_idx, cand in enumerate(candidates):
        start_t = cand["start"]
        end_t = cand["end"]
        safe_title = cand.get("safe_title", f"GTA6_Moment_{c_idx+1}")
        dest_stem = f"{safe_title}_{c_idx+1}_{int(start_t)}s"
        final_dest = READY_DIR / f"{dest_stem}.mp4"

        if final_dest.exists() and final_dest.stat().st_size > 102400:
            rendered_files.append(final_dest)
            continue

        raw_seg = segments_dir / f"seg_raw_{c_idx}.mp4"
        download_video_section(video_url, start_t, end_t, raw_seg)

        seg_words = []
        for s in transcript.get("segments", []):
            for w in s.get("words", []):
                if start_t <= w["start"] <= end_t:
                    seg_words.append(w)

        ass_file = segments_dir / f"subs_{c_idx}.ass"
        generate_karaoke_ass(seg_words, ass_file, clip_start_offset=start_t, style_preset=style_key)

        flagged = find_profanities_in_words(seg_words)

        render_mode_a_short(
            source_video=raw_seg,
            ass_subtitles=ass_file,
            output_short_path=final_dest,
            flagged_profanities=flagged,
            split_layout=False,
            enable_tracking=enable_tracking,
            hook_title=cand.get("title", "GTA 6 INSANE MOMENT") if enable_hook_badge else None
        )
        push_watcher_log(f"✓ Rendered autonomous short: {final_dest.name}")
        rendered_files.append(final_dest)

    # 3. Autonomous Scheduling
    if auto_upload and rendered_files and is_authenticated():
        push_watcher_log(f"Scheduling {len(rendered_files)} new Shorts across peak monetization slots...")
        try:
            results = upload_batch_private(
                max_batch_size=len(rendered_files),
                auto_schedule=True,
                slots_per_day=6,
                concurrency=2
            )
            push_watcher_log(f"✓ Scheduled {len(results)} Shorts to YouTube Studio!")
        except Exception as e:
            push_watcher_log(f"Auto-upload error: {e}")

    return rendered_files


def run_watcher_loop():
    """Main background loop executed by the autonomous watcher thread."""
    push_watcher_log("Autonomous Channel Watcher Daemon started.")
    while not _WATCHER_STOP_EVENT.is_set():
        cfg = load_watcher_config()
        if not cfg.get("enabled", False):
            time.sleep(5)
            continue

        if not check_internet_connection():
            push_watcher_log("Internet connection dropped. Pausing watcher poll...")
            time.sleep(30)
            continue

        state = load_watcher_state()
        processed_ids = set(state.get("processed_video_ids", []))
        channels = cfg.get("channels", [])

        push_watcher_log(f"Scanning {len(channels)} target channels for new GTA 6 uploads...")
        new_found = 0

        for ch in channels:
            if _WATCHER_STOP_EVENT.is_set():
                break
            recent = get_channel_recent_videos(ch, max_videos=2)
            for v in recent:
                vid_id = v["id"]
                if vid_id not in processed_ids:
                    push_watcher_log(f"🔔 NEW VIDEO DETECTED: {v['title']} ({v['url']})")
                    try:
                        process_video_autonomous(
                            video_url=v["url"],
                            shorts_count=cfg.get("shorts_per_video", 4),
                            caption_style=cfg.get("caption_style", "neon"),
                            enable_tracking=cfg.get("enable_tracking", False),
                            enable_hook_badge=cfg.get("enable_hook_badge", True),
                            auto_upload=cfg.get("auto_upload", True)
                        )
                        processed_ids.add(vid_id)
                        new_found += 1
                        state["processed_video_ids"] = list(processed_ids)
                        save_watcher_state(state)
                    except Exception as ex:
                        push_watcher_log(f"Error processing {vid_id}: {ex}")

        interval_sec = max(60, int(cfg.get("check_interval_minutes", 30)) * 60)
        push_watcher_log(f"Scan complete. {new_found} new upload(s) processed. Next scan in {interval_sec // 60}m.")

        # Sleep in small slices to respond quickly to stop requests
        for _ in range(interval_sec // 5):
            if _WATCHER_STOP_EVENT.is_set():
                break
            time.sleep(5)

    push_watcher_log("Autonomous Channel Watcher Daemon stopped.")


def start_watcher_daemon():
    """Starts the background watcher daemon thread if not already running."""
    global _WATCHER_THREAD, _WATCHER_STOP_EVENT
    if _WATCHER_THREAD is not None and _WATCHER_THREAD.is_alive():
        return False
    _WATCHER_STOP_EVENT.clear()
    _WATCHER_THREAD = threading.Thread(target=run_watcher_loop, daemon=True)
    _WATCHER_THREAD.start()
    return True


def stop_watcher_daemon():
    """Signals the background watcher daemon to stop."""
    global _WATCHER_STOP_EVENT
    _WATCHER_STOP_EVENT.set()
    return True


def is_watcher_running() -> bool:
    global _WATCHER_THREAD
    return _WATCHER_THREAD is not None and _WATCHER_THREAD.is_alive()
