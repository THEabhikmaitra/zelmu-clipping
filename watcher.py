"""
Autonomous Channel Watcher Daemon for Zelmu Clipping.
Monitors YouTube channels for new uploads & live streams 24/7,
auto-extracts viral Shorts using rolling HLS buffers / speech clustering,
and schedules them to YouTube Studio across peak High-CPM monetization windows.
"""

import os
import sys
import time
import json
import re
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
from arbiter import (
    acquire_compute_lock,
    release_compute_lock,
    should_yield,
    is_system_paused,
    push_unified_log,
    PRIORITY_VOD
)

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
    "enable_hook_badge": True,
    "enable_live_monitoring": True
}

_WATCHER_THREAD = None
_WATCHER_STOP_EVENT = threading.Event()
_WATCHER_LOGS = []
_WATCHER_LOCK = threading.Lock()

_WATCHER_PROGRESS = {
    "active": False,
    "video_id": "",
    "video_title": "",
    "stage": 0,
    "total_stages": 5,
    "stage_name": "Idle",
    "step_detail": "Daemon idle or waiting for next poll cycle",
    "next_step": "Scan channels",
    "percent": 0,
    "is_live": False,
    "current_clip": 0,
    "total_clips": 0,
    "last_updated": time.time()
}


def push_watcher_log(msg: str):
    import datetime
    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    entry = f"[{now_str}] {msg}"
    push_unified_log("VOD", msg)
    with _WATCHER_LOCK:
        _WATCHER_LOGS.append(entry)
        if len(_WATCHER_LOGS) > 150:
            _WATCHER_LOGS.pop(0)


def get_watcher_logs() -> List[str]:
    with _WATCHER_LOCK:
        return list(_WATCHER_LOGS)


def set_watcher_progress(
    active: bool = True,
    video_id: str = "",
    video_title: str = "",
    stage: int = 1,
    total_stages: int = 5,
    stage_name: str = "",
    step_detail: str = "",
    next_step: str = "",
    percent: int = 0,
    is_live: bool = False,
    current_clip: int = 0,
    total_clips: int = 0,
    channel_name: str = ""
):
    global _WATCHER_PROGRESS
    with _WATCHER_LOCK:
        _WATCHER_PROGRESS = {
            "active": active,
            "status": "running" if active else ("waiting" if percent == 100 else "idle"),
            "video_id": video_id,
            "video_title": video_title,
            "channel_name": channel_name,
            "stage": stage,
            "total_stages": total_stages,
            "stage_name": stage_name,
            "stage_label": f"Stage {stage}/{total_stages}: {stage_name}" if active else stage_name,
            "step_detail": step_detail,
            "next_step": next_step,
            "percent": max(0, min(100, percent)),
            "percentage": max(0, min(100, percent)),
            "is_live": is_live,
            "current_clip": current_clip,
            "total_clips": total_clips,
            "last_updated": time.time()
        }


def get_watcher_progress() -> Dict[str, Any]:
    with _WATCHER_LOCK:
        return dict(_WATCHER_PROGRESS)


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


def get_channel_live_video(channel_url: str) -> Optional[Dict[str, Any]]:
    """Checks if a YouTube channel currently has an active livestream via /live endpoint."""
    clean_url = channel_url.strip().rstrip("/")
    if "/videos" in clean_url:
        clean_url = clean_url.replace("/videos", "")
    live_target = f"{clean_url}/live"

    cmd = [
        *get_ytdlp_cmd(),
        "--no-warnings",
        "--print", "%(id)s\t%(title)s\t%(is_live)s",
        live_target
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0 and proc.stdout:
            parts = proc.stdout.strip().split("\t")
            if len(parts) >= 2:
                vid_id = parts[0].strip()
                title = parts[1].strip()
                is_live = (parts[2].strip().lower() == "true") if len(parts) > 2 else False
                if vid_id and len(vid_id) == 11 and is_live:
                    return {
                        "id": vid_id,
                        "title": title,
                        "url": f"https://www.youtube.com/watch?v={vid_id}",
                        "is_live": True
                    }
    except Exception:
        pass
    return None


def capture_live_stream_segment(live_url: str, output_path: Path, duration_sec: int = 60) -> bool:
    """Taps active live HLS m3u8 stream and buffers the trailing duration_sec seconds via FFmpeg."""
    cmd_g = [
        *get_ytdlp_cmd(),
        "-g",
        "-f", "best[ext=mp4]/best",
        live_url
    ]
    try:
        proc = subprocess.run(cmd_g, capture_output=True, text=True, timeout=18)
        if proc.returncode != 0 or not proc.stdout.strip():
            return False
        stream_url = proc.stdout.strip().splitlines()[0]

        ffmpeg_bin = get_ffmpeg_path()
        cmd_cap = [
            ffmpeg_bin, "-y",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "2",
            "-i", stream_url,
            "-t", str(duration_sec),
            "-c:v", "copy",
            "-c:a", "aac",
            str(output_path)
        ]
        p_ff = subprocess.run(cmd_cap, capture_output=True, text=True, timeout=duration_sec + 25)
        return output_path.exists() and output_path.stat().st_size > 50000
    except Exception as ex:
        push_watcher_log(f"Live HLS capture error: {ex}")
        return False


def process_live_stream_autonomous(
    live_url: str,
    title: str = "Live Stream",
    author: str = "Streamer",
    clip_duration_sec: int = 50,
    caption_style: str = "neon",
    enable_hook_badge: bool = True,
    auto_upload: bool = True
) -> List[Path]:
    """Captures rolling live window via HLS buffer, transcribes in ~3s, and renders vertical Short."""
    meta = get_video_metadata(live_url)
    vid_id = meta.get("id") or "live_stream"
    title = meta.get("title") or title
    author = meta.get("author") or author

    set_watcher_progress(
        active=True, video_id=vid_id, video_title=title,
        stage=1, total_stages=5, stage_name="Live HLS Buffer",
        step_detail=f"Tapping live stream HLS buffer ({clip_duration_sec}s rolling window)...",
        next_step="Extract audio & run Whisper Turbo",
        percent=15, is_live=True
    )
    push_watcher_log(f"🔴 LIVE STREAM DETECTED: '{title}' ({vid_id}) by @{author}. Buffering trailing {clip_duration_sec}s...")

    work_dir = WORKSPACE_DIR / f"live_{vid_id}_{int(time.time())}"
    work_dir.mkdir(parents=True, exist_ok=True)
    raw_seg = work_dir / "live_raw.mp4"

    hls_success = capture_live_stream_segment(live_url, raw_seg, duration_sec=clip_duration_sec)
    if not hls_success or not raw_seg.exists() or raw_seg.stat().st_size < 100000:
        push_watcher_log(f"Live buffer capture failed for {vid_id}. Retrying next cycle.")
        set_watcher_progress(active=False, stage=0, stage_name="Idle", step_detail="Live capture timeout. Waiting.", percent=0)
        return []

    set_watcher_progress(
        active=True, video_id=vid_id, video_title=title,
        stage=2, total_stages=5, stage_name="Live Audio Transcription",
        step_detail="Extracting live audio & generating subtitles (Whisper Turbo)...",
        next_step="Karaoke subtitle alignment",
        percent=40, is_live=True
    )
    push_watcher_log("Transcribing live segment with Whisper Turbo...")
    audio_wav = work_dir / "live_audio.wav"
    ffmpeg_bin = get_ffmpeg_path()
    subprocess.run([ffmpeg_bin, "-y", "-i", str(raw_seg), "-vn", "-ac", "1", "-ar", "16000", str(audio_wav)], capture_output=True, timeout=20)

    transcript_json = work_dir / "live_transcript.json"
    transcript = transcribe_audio_whisper(audio_wav, transcript_json)
    if not transcript or not transcript.get("segments"):
        transcript = {"segments": [{"words": [{"word": title, "start": 0.5, "end": 3.0}]}]}

    set_watcher_progress(
        active=True, video_id=vid_id, video_title=title,
        stage=3, total_stages=5, stage_name="Subtitle Styling",
        step_detail="Generating NEON karaoke subtitles & hook badge...",
        next_step="Intel QSV zero-stall hardware rendering",
        percent=65, is_live=True
    )
    words = []
    for s in transcript.get("segments", []):
        words.extend(s.get("words", []))

    ass_file = work_dir / "live_subs.ass"
    style_key = "neon" if "neon" in caption_style.lower() else "clean"
    generate_karaoke_ass(words, ass_file, clip_start_offset=0.0, style_preset=style_key)

    set_watcher_progress(
        active=True, video_id=vid_id, video_title=title,
        stage=4, total_stages=5, stage_name="Hardware GPU Render",
        step_detail="Rendering 9:16 vertical Short (Intel QSV hardware acceleration)...",
        next_step="Auto-scheduling to YouTube Studio",
        percent=85, is_live=True, current_clip=1, total_clips=1
    )
    push_watcher_log("Rendering live Short via Intel QSV...")
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:26]
    dest_name = f"LIVE_{safe_slug}_{int(time.time())}.mp4"
    READY_DIR.mkdir(parents=True, exist_ok=True)
    final_dest = READY_DIR / dest_name

    render_mode_a_short(
        source_video=raw_seg,
        ass_subtitles=ass_file,
        output_short_path=final_dest,
        flagged_profanities=[],
        split_layout=False,
        enable_tracking=False,
        hook_title=f"LIVE: {title[:24]}" if enable_hook_badge else None
    )
    push_watcher_log(f"✓ Rendered LIVE short: {final_dest.name}")

    if auto_upload and is_authenticated():
        set_watcher_progress(
            active=True, video_id=vid_id, video_title=title,
            stage=5, total_stages=5, stage_name="Auto Scheduling",
            step_detail="Pushing Short to @zelmuesports via upload queue...",
            next_step="Polling next live stream event",
            percent=95, is_live=True
        )
        try:
            results = upload_batch_private(
                max_batch_size=1,
                auto_schedule=True,
                slots_per_day=6,
                concurrency=1
            )
            push_watcher_log(f"✓ LIVE Short scheduled to YouTube Studio: {dest_name}")
        except Exception as e:
            push_watcher_log(f"Auto-upload error: {e}")

    set_watcher_progress(
        active=False, stage=0, stage_name="Idle",
        step_detail="Live Short complete. Daemon monitoring channels.",
        next_step="Scan channels", percent=100
    )
    return [final_dest]


def process_video_autonomous(
    video_url: str,
    shorts_count: int = 4,
    caption_style: str = "neon",
    enable_tracking: bool = False,
    enable_hook_badge: bool = True,
    auto_upload: bool = True
) -> List[Path]:
    """Runs end-to-end extraction, karaoke rendering, and scheduling with real-time stage progress."""
    # Stage 1: Metadata & Stream Info
    set_watcher_progress(
        active=True, video_id="", video_title="Analyzing Video",
        stage=1, total_stages=5, stage_name="Ingestion & Metadata",
        step_detail=f"Extracting video metadata & format specifications from YouTube...",
        next_step="Captions & audio transcription",
        percent=10
    )
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

    # Stage 2 to Stage 4: Protected by Arbiter (Priority 3 - VOD)
    push_watcher_log("Waiting for Compute Lock (P3) to run dialogue transcription & QSV render...")
    acquire_compute_lock("watcher", PRIORITY_VOD, f"VOD: {title[:25]}", timeout=900.0)
    try:
        # Stage 2: Transcript & Audio
        set_watcher_progress(
            active=True, video_id=vid_id, video_title=title,
            stage=2, total_stages=5, stage_name="Dialogue Transcription",
            step_detail=f"Extracting captions & running acoustic analysis on '{title[:30]}...'...",
            next_step="AI highlight candidate scoring",
            percent=30
        )
        transcript_json = work_dir / "02_transcript.json"
        transcript = None
        if transcript_json.exists():
            with open(transcript_json, "r", encoding="utf-8") as f:
                transcript = json.load(f)

        if not transcript:
            push_watcher_log(f"Fetching official captions for {vid_id}...")
            transcript = fetch_youtube_captions(video_url, transcript_json, max_duration_sec=900.0)

        if not transcript:
            push_watcher_log(f"No captions found. Running Whisper Turbo speech recognition...")
            audio_wav = work_dir / "01_audio.wav"
            extract_audio_wav(video_url, audio_wav, max_duration_sec=900.0)
            transcript = transcribe_audio_whisper(audio_wav, transcript_json)

        # Stage 3: Candidate Analysis
        set_watcher_progress(
            active=True, video_id=vid_id, video_title=title,
            stage=3, total_stages=5, stage_name="Highlight Candidate Scoring",
            step_detail=f"Scoring speech density and acoustic excitement spikes for {shorts_count} Shorts...",
            next_step="Direct stream cutting & Intel QSV rendering",
            percent=50
        )
        cand_json = work_dir / "03_candidates_mode_a.json"
        if cand_json.exists():
            with open(cand_json, "r", encoding="utf-8") as f:
                analysis = json.load(f)
        else:
            push_watcher_log(f"Evaluating transcript highlights for {shorts_count} candidate clips...")
            analysis = extract_candidates_full(
                transcript,
                mode="Mode A",
                channel_name=author,
                target_clips=shorts_count
            )
            with open(cand_json, "w", encoding="utf-8") as f:
                json.dump(analysis, f, indent=2)

        candidates = analysis.get("candidates", [])
        push_watcher_log(f"Selected {len(candidates)} high-potential candidate moments.")
        style_key = "neon" if "neon" in caption_style.lower() else ("clean" if "clean" in caption_style.lower() else "karaoke")

        rendered_files = []
        from editor import get_direct_stream_urls, download_video_section, find_profanities_in_words
        prefetched_stream_urls = get_direct_stream_urls(video_url)

        # Stage 4: Rendering Shorts (Parallel QSV Pipeline)
        total_cands = len(candidates)
        set_watcher_progress(
            active=True, video_id=vid_id, video_title=title,
            stage=4, total_stages=5, stage_name="Rendering Shorts",
            step_detail=f"Spawning parallel QSV workers for {total_cands} clips...",
            next_step="Auto-scheduling to Studio",
            percent=55, current_clip=0, total_clips=total_cands
        )

        def process_watcher_clip(c_idx: int, cand: dict):
            start_t = cand["start"]
            end_t = cand["end"]
            safe_title = cand.get("safe_title", f"GTA6_Moment_{c_idx+1}")
            dest_stem = f"{safe_title}_{c_idx+1}_{int(start_t)}s"
            final_dest = READY_DIR / f"{dest_stem}.mp4"

            if final_dest.exists() and final_dest.stat().st_size > 102400:
                return final_dest

            raw_seg = segments_dir / f"seg_raw_{c_idx}.mp4"
            push_watcher_log(f"[Worker #{c_idx+1}] Cutting section ({start_t:.1f}s - {end_t:.1f}s) via zero-disk stream cut...")
            download_video_section(video_url, start_t, end_t, raw_seg, stream_urls=prefetched_stream_urls)

            seg_words = []
            for s in transcript.get("segments", []):
                for w in s.get("words", []):
                    if start_t <= w["start"] <= end_t:
                        seg_words.append(w)

            ass_file = segments_dir / f"subs_{c_idx}.ass"
            generate_karaoke_ass(seg_words, ass_file, clip_start_offset=start_t, style_preset=style_key)

            flagged = find_profanities_in_words(seg_words)

            push_watcher_log(f"[Worker #{c_idx+1}] Rendering short with Intel QSV & viral hook badge...")
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
            raw_seg.unlink(missing_ok=True)
            for p in segments_dir.glob(f"seg_raw_{c_idx}.*"):
                p.unlink(missing_ok=True)
            return final_dest

        pool_workers = min(3, max(1, total_cands))
        with concurrent.futures.ThreadPoolExecutor(max_workers=pool_workers) as pool:
            future_map = {pool.submit(process_watcher_clip, c_idx, cand): c_idx for c_idx, cand in enumerate(candidates)}
            while any(not fut.done() for fut in future_map):
                time.sleep(1)
                done_count = sum(1 for fut in future_map if fut.done())
                render_pct = 55 + int((done_count / max(1, total_cands)) * 35)
                set_watcher_progress(
                    active=True, video_id=vid_id, video_title=title,
                    stage=4, total_stages=5, stage_name="Rendering Shorts",
                    step_detail=f"Rendering {done_count}/{total_cands} clips in parallel via Intel QSV...",
                    next_step="Auto-scheduling to Studio" if done_count == total_cands else f"Processing remaining ({total_cands - done_count})",
                    percent=render_pct, current_clip=done_count, total_clips=total_cands
                )

            for fut in future_map:
                res_dest = fut.result()
                if res_dest and res_dest.exists() and res_dest.stat().st_size > 102400:
                    rendered_files.append(res_dest)
    finally:
        release_compute_lock("watcher")

    # Stage 5: Scheduling to Studio
    if auto_upload and rendered_files and is_authenticated():
        set_watcher_progress(
            active=True, video_id=vid_id, video_title=title,
            stage=5, total_stages=5, stage_name="Auto Scheduling",
            step_detail=f"Scheduling {len(rendered_files)} new Shorts across peak monetization slots...",
            next_step="Polling next channel check",
            percent=95, current_clip=total_cands, total_clips=total_cands
        )
        push_watcher_log(f"Scheduling {len(rendered_files)} new Shorts across peak monetization slots...")
        try:
            results = upload_batch_private(
                max_batch_size=len(rendered_files),
                auto_schedule=True,
                slots_per_day=6,
                concurrency=2
            )
            push_watcher_log(f"✓ Scheduled {len(results)} Shorts to YouTube Studio (@zelmuesports)!")
        except Exception as e:
            push_watcher_log(f"Auto-upload error: {e}")

    set_watcher_progress(
        active=False, stage=0, stage_name="Idle",
        step_detail=f"Completed {len(rendered_files)} Shorts for '{title[:25]}...'. Waiting for next scan cycle.",
        next_step="Scan channels", percent=100
    )
    return rendered_files


def run_watcher_loop():
    """Main background loop executed by the autonomous watcher thread."""
    push_watcher_log("Autonomous Channel Watcher Daemon started.")
    while not _WATCHER_STOP_EVENT.is_set():
        cfg = load_watcher_config()
        if not cfg.get("enabled", False):
            set_watcher_progress(active=False, stage=0, stage_name="Paused", step_detail="Autopilot is paused. Click Start to monitor channels.", percent=0)
            time.sleep(5)
            continue

        if is_system_paused():
            set_watcher_progress(
                active=True,
                video_id="",
                video_title="",
                stage=0,
                total_stages=5,
                stage_name="System Paused (Master Switch)",
                step_detail="Autonomous channel watcher paused by operator in Mission Control.",
                next_step="Resume in Mission Control",
                percent=0
            )
            time.sleep(4)
            continue

        if not check_internet_connection():
            push_watcher_log("Internet connection dropped. Pausing watcher poll...")
            set_watcher_progress(active=False, stage=0, stage_name="Offline", step_detail="Internet connection dropped. Pausing poll.", percent=0)
            time.sleep(30)
            continue

        state = load_watcher_state()
        processed_ids = set(state.get("processed_video_ids", []))
        channels = cfg.get("channels", [])

        push_watcher_log(f"Scanning {len(channels)} target channels for new GTA 6 uploads & livestreams...")
        set_watcher_progress(
            active=True, video_id="", video_title="Channel Scanner",
            stage=1, total_stages=5, stage_name="Polling Channels",
            step_detail=f"Scanning {len(channels)} channels for new uploads & active livestreams...",
            next_step="Process new uploads",
            percent=10
        )
        new_found = 0

        for ch in channels:
            if _WATCHER_STOP_EVENT.is_set():
                break

            # 1. Check for Active Livestreams if enabled
            if cfg.get("enable_live_monitoring", True):
                live_item = get_channel_live_video(ch)
                if live_item and live_item["id"] not in processed_ids:
                    vid_id = live_item["id"]
                    push_watcher_log(f"🔴 ACTIVE LIVESTREAM DETECTED: {live_item['title']} ({live_item['url']})")
                    try:
                        process_live_stream_autonomous(
                            live_url=live_item["url"],
                            title=live_item["title"],
                            caption_style=cfg.get("caption_style", "neon"),
                            enable_hook_badge=cfg.get("enable_hook_badge", True),
                            auto_upload=cfg.get("auto_upload", True)
                        )
                        processed_ids.add(vid_id)
                        new_found += 1
                        state["processed_video_ids"] = list(processed_ids)
                        save_watcher_state(state)
                    except Exception as ex:
                        push_watcher_log(f"Error clipping livestream {vid_id}: {ex}")

            # 2. Check for Recent Videos
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
        push_watcher_log(f"Scan complete. {new_found} new item(s) processed. Next scan in {interval_sec // 60}m.")
        set_watcher_progress(
            active=False, stage=0, stage_name="Idle",
            step_detail=f"Monitoring {len(channels)} channels. Next scan in {interval_sec // 60}m.",
            next_step=f"Auto-scan in {interval_sec // 60}m",
            percent=100
        )

        for _ in range(interval_sec // 5):
            if _WATCHER_STOP_EVENT.is_set():
                break
            time.sleep(5)

    push_watcher_log("Autonomous Channel Watcher Daemon stopped.")
    set_watcher_progress(active=False, stage=0, stage_name="Stopped", step_detail="Daemon stopped.", percent=0)


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
