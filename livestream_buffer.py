"""
Live Stream Rolling Buffer & Real-Time HLS Clipper for Zelmu Clipping.
Monitors active YouTube livestreams, captures rolling HLS stream windows,
detects live high-energy spikes, and auto-renders & schedules Shorts to YouTube Studio.
"""

import os
import sys
import time
import json
import re
import shutil
import subprocess
import threading
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Any, Optional

from transcriber import (
    get_ytdlp_cmd,
    get_ffmpeg_path,
    get_video_metadata,
    extract_audio_wav,
    transcribe_audio_whisper
)
from analyzer import extract_candidates_full, extract_top_speech_windows, detect_live_hyped_windows
from editor import generate_karaoke_ass, render_mode_a_short, check_internet_connection, is_valid_video_file
from uploader import upload_batch_private, calculate_monetization_schedule_slots, is_authenticated
from arbiter import (
    acquire_compute_lock,
    release_compute_lock,
    is_system_paused,
    push_unified_log,
    PRIORITY_LIVE
)

CONFIG_FILE = Path("livestream_config.json")
STATE_FILE = Path("livestream_state.json")
PROGRESS_FILE = Path("livestream_progress.json")
LOG_FILE = Path("livestream_events.log")
WORKSPACE_DIR = Path("workspace")
READY_DIR = Path("ready_to_upload")

DEFAULT_CONFIG = {
    "enabled": False,
    "channels": [
        "https://www.youtube.com/@IShowSpeed/live",
        "https://www.youtube.com/@RockstarGames/live"
    ],
    "check_interval_minutes": 5,
    "slice_duration_seconds": 300,  # 5-minute rolling buffer slice
    "shorts_per_slice": 2,
    "auto_upload": True,
    "caption_style": "neon",
    "enable_tracking": False,
    "enable_hook_badge": True
}

_LIVE_THREAD = None
_LIVE_STOP_EVENT = threading.Event()
_LIVE_LOGS: List[str] = []
_LIVE_LOCK = threading.Lock()

_LIVE_PROGRESS: Dict[str, Any] = {
    "status": "idle",
    "current_step": 0,
    "total_steps": 5,
    "percentage": 0,
    "stage_label": "Live Buffer Idle",
    "step_detail": "Daemon paused. Ready to monitor active live streams.",
    "next_step": "Scan live streams",
    "stream_title": "",
    "stream_id": "",
    "channel_name": "",
    "current_clip": 0,
    "total_clips": 0,
    "last_update": 0.0
}


def push_live_log(msg: str):
    import datetime
    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    entry = f"[{now_str}] {msg}"
    push_unified_log("LIVE", msg)
    with _LIVE_LOCK:
        _LIVE_LOGS.append(entry)
        if len(_LIVE_LOGS) > 200:
            _LIVE_LOGS.pop(0)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def get_livestream_logs() -> List[str]:
    with _LIVE_LOCK:
        if _LIVE_LOGS:
            return list(_LIVE_LOGS)
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
                return lines[-100:]
        except Exception:
            pass
    return []


def set_livestream_progress(
    status: str,
    current_step: int,
    total_steps: int,
    percentage: int,
    stage_label: str,
    step_detail: str,
    next_step: str,
    stream_title: str = "",
    stream_id: str = "",
    channel_name: str = "",
    current_clip: int = 0,
    total_clips: int = 0
):
    global _LIVE_PROGRESS
    with _LIVE_LOCK:
        _LIVE_PROGRESS.update({
            "status": status,
            "current_step": current_step,
            "total_steps": total_steps,
            "percentage": percentage,
            "stage_label": stage_label,
            "step_detail": step_detail,
            "next_step": next_step,
            "stream_title": stream_title or _LIVE_PROGRESS.get("stream_title", ""),
            "stream_id": stream_id or _LIVE_PROGRESS.get("stream_id", ""),
            "channel_name": channel_name or _LIVE_PROGRESS.get("channel_name", ""),
            "current_clip": current_clip,
            "total_clips": total_clips,
            "last_update": time.time()
        })
        try:
            with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                json.dump(_LIVE_PROGRESS, f, indent=2)
        except Exception:
            pass


def get_livestream_progress() -> Dict[str, Any]:
    global _LIVE_PROGRESS
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    with _LIVE_LOCK:
        return dict(_LIVE_PROGRESS)


def load_livestream_config() -> Dict[str, Any]:
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


def save_livestream_config(cfg: Dict[str, Any]):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def load_livestream_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"processed_slices": [], "last_check_timestamp": 0}
    return {"processed_slices": [], "last_check_timestamp": 0}


def save_livestream_state(state: Dict[str, Any]):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def normalize_livestream_url(target: str) -> str:
    clean = target.strip()
    if not clean:
        return ""
    if clean.startswith("@"):
        clean = f"https://www.youtube.com/{clean}"
    elif not clean.startswith("http"):
        clean = f"https://www.youtube.com/{clean}"
    if not clean.endswith("/live") and "/watch" not in clean:
        clean = clean.rstrip("/") + "/live"
    return clean


def check_if_stream_live(target_url: str) -> Optional[Dict[str, Any]]:
    """Probes if a channel or URL is currently live broadcasting in ~2-3s."""
    clean_url = normalize_livestream_url(target_url)
    if not clean_url:
        return None

    cmd = [
        *get_ytdlp_cmd(),
        "--print", "%(is_live)s\t%(id)s\t%(title)s\t%(channel)s",
        "--no-warnings",
        clean_url
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0 and proc.stdout.strip():
            parts = proc.stdout.strip().split("\t")
            if len(parts) >= 3:
                is_live_str = parts[0].strip().lower()
                if is_live_str in ("true", "1"):
                    return {
                        "is_live": True,
                        "id": parts[1].strip(),
                        "title": parts[2].strip(),
                        "channel": parts[3].strip() if len(parts) > 3 else "Live Creator",
                        "url": f"https://www.youtube.com/watch?v={parts[1].strip()}"
                    }
    except Exception as e:
        push_live_log(f"Live probe error ({target_url}): {e}")
    return None


def get_live_hls_urls(stream_watch_url: str) -> Dict[str, Optional[str]]:
    """
    Extracts direct video and audio HLS manifests from active YouTube live stream.
    Returns dict: {"video": video_url, "audio": audio_url}
    """
    cmd = [
        *get_ytdlp_cmd(),
        "-g",
        "--no-warnings",
        stream_watch_url
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0 and proc.stdout:
            lines = [l.strip() for l in proc.stdout.splitlines() if l.strip().startswith("http")]
            if len(lines) >= 2:
                return {"video": lines[0], "audio": lines[1]}
            elif len(lines) == 1:
                return {"video": lines[0], "audio": None}
    except Exception as e:
        push_live_log(f"HLS manifest error ({stream_watch_url}): {e}")
    return {"video": None, "audio": None}


def get_live_hls_url(stream_watch_url: str) -> Optional[str]:
    """Extracts direct HLS manifest .m3u8 from active YouTube live stream."""
    urls = get_live_hls_urls(stream_watch_url)
    return urls.get("video")


def capture_rolling_hls_slice(stream_input: Any, output_path: Path, duration_sec: int = 300) -> Optional[Path]:
    """Captures a rolling N-second slice from live HLS manifests with full video and audio synchronization."""
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = output_path.with_suffix(".part.mp4")

    if isinstance(stream_input, dict):
        v_url = stream_input.get("video")
        a_url = stream_input.get("audio")
    else:
        v_url = str(stream_input)
        a_url = None

    if not v_url:
        return None

    ffmpeg_bin = str(get_ffmpeg_path() or "ffmpeg")
    if a_url:
        cmd = [
            ffmpeg_bin, "-y",
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "3",
            "-i", v_url,
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "3",
            "-i", a_url,
            "-t", str(duration_sec),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "19",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(part_path)
        ]
    else:
        cmd = [
            ffmpeg_bin, "-y",
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "3",
            "-i", v_url,
            "-t", str(duration_sec),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "19",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(part_path)
        ]

    try:
        res = subprocess.run(cmd, capture_output=True, timeout=duration_sec + 60)
        if res.returncode == 0 and is_valid_video_file(part_path):
            if output_path.exists():
                output_path.unlink()
            part_path.rename(output_path)
            return output_path
        else:
            if part_path.exists():
                part_path.unlink()
    except Exception as e:
        push_live_log(f"HLS capture exception: {e}")
        if part_path.exists():
            part_path.unlink()
    return None


def process_livestream_slice(
    stream_info: Dict[str, Any],
    slice_duration: int = 300,
    shorts_count: int = 2,
    caption_style: str = "neon",
    enable_tracking: bool = False,
    enable_hook_badge: bool = True,
    auto_upload: bool = True
) -> List[Path]:
    """Captures rolling HLS slice, runs speech/spike analysis, and renders vertical Shorts."""
    vid_id = stream_info["id"]
    title = stream_info["title"]
    author = stream_info["channel"]
    stream_url = stream_info["url"]

    slice_ts = int(time.time())
    work_dir = WORKSPACE_DIR / f"live_{vid_id}_{slice_ts}"
    work_dir.mkdir(parents=True, exist_ok=True)
    segments_dir = work_dir / "04_segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    READY_DIR.mkdir(parents=True, exist_ok=True)

    # Stage 1: Capture HLS stream slice
    set_livestream_progress(
        status="buffering",
        current_step=1,
        total_steps=5,
        percentage=10,
        stage_label="Stage 1/5: Capturing Live HLS",
        step_detail=f"Buffering {slice_duration}s rolling HLS window from '{title}'...",
        next_step="Stage 2/5: Audio Extraction & Whisper Transcription",
        stream_title=title,
        stream_id=vid_id,
        channel_name=author
    )
    push_live_log(f"🔴 [Stage 1/5] Extracting HLS stream for '{title}' (@{author})...")

    hls_urls = get_live_hls_urls(stream_url)
    if not hls_urls or not hls_urls.get("video"):
        push_live_log("Failed to acquire HLS manifest.")
        return []

    slice_mp4 = work_dir / "live_slice.mp4"
    captured = capture_rolling_hls_slice(hls_urls, slice_mp4, duration_sec=slice_duration)
    if not captured or not is_valid_video_file(captured):
        push_live_log("HLS capture failed or produced invalid container.")
        return []

    push_live_log(f"✓ [Stage 1/5] Captured {slice_duration}s live slice ({slice_mp4.stat().st_size / 1024 / 1024:.1f} MB).")

    # Stage 2 to Stage 4: Heavy Compute (Whisper AI + Intel QSV) protected by Arbiter Compute Lock
    push_live_log("Waiting for Compute Lock (P2) to run Whisper AI & QSV Render...")
    if not acquire_compute_lock("livestream_buffer", PRIORITY_LIVE, f"Live: {title[:25]}", timeout=600.0):
        push_live_log("Failed to acquire Compute Lock (timeout or system paused). Skipping slice.")
        return
    try:
        # Stage 2: Audio & Transcription
        set_livestream_progress(
            status="transcribing",
            current_step=2,
            total_steps=5,
            percentage=30,
            stage_label="Stage 2/5: Live Audio AI",
            step_detail="Extracting live audio & running Whisper turbo transcription...",
            next_step="Stage 3/5: Spike Detection & Viral Moment Extraction"
        )
        push_live_log("🎙️ [Stage 2/5] Running Whisper turbo transcription on live audio slice...")
        audio_wav = work_dir / "01_audio.wav"
        transcript_json = work_dir / "02_transcript.json"

        ffmpeg_bin = str(get_ffmpeg_path() or "ffmpeg")
        res_wav = subprocess.run([
            ffmpeg_bin, "-y", "-i", str(slice_mp4),
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(audio_wav)
        ], capture_output=True, text=True)

        # Safeguard: if audio extraction failed, create ambient placeholder audio to prevent crash
        if not audio_wav.exists() or audio_wav.stat().st_size < 1000:
            push_live_log("⚠️ Live slice had no audio stream. Generating ambient placeholder audio.")
            subprocess.run([
                ffmpeg_bin, "-y",
                "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                "-t", f"{slice_duration}",
                str(audio_wav)
            ], capture_output=True)

        transcript = transcribe_audio_whisper(audio_wav, transcript_json)
        if not transcript or not transcript.get("segments"):
            push_live_log("No speech detected in live slice. Using acoustic energy fallback...")

        # Stage 3: Candidate Spike Detection
        # Stage 3: Candidate Spike & Hyped Area Detection (Acoustic RMS + 2-4kHz Shouts + Speech Velocity)
        set_livestream_progress(
            status="analyzing",
            current_step=3,
            total_steps=5,
            percentage=45,
            stage_label="Stage 3/5: Hyped Area Detection",
            step_detail=f"Scanning audio RMS & speech velocity for top {shorts_count} hyped areas...",
            next_step="Stage 4/5: Vertical Short Hardware Render"
        )
        push_live_log(f"⚡ [Stage 3/5] Detecting top {shorts_count} hyped areas (acoustic RMS energy + speech velocity)...")

        windows = detect_live_hyped_windows(
            audio_path=audio_wav if audio_wav.exists() else None,
            transcript=transcript,
            target_clips=shorts_count,
            min_duration=26.0,
            max_duration=42.0,
            stream_title=title,
            channel_name=author,
            total_duration=float(slice_duration)
        )
        if not windows:
            windows = [{"start": 0.0, "end": 35.0, "title": f"{author} - Insane Live Moment", "hype_score": 75}]

        for idx, w in enumerate(windows):
            push_live_log(f"🔥 [Stage 3/5] Hyped Area #{idx+1}: {w['start']:.1f}s - {w['end']:.1f}s ({w['duration']:.1f}s, Hype: {w.get('hype_score', 0)}%) -> '{w.get('title')}'")

        style_key = "neon" if "neon" in caption_style.lower() else ("clean" if "clean" in caption_style.lower() else "karaoke")

        # Stage 4: Parallel QSV Rendering
        candidates = windows[:shorts_count]
        from editor import find_profanities_in_words

        def process_live_short(c_idx: int, win: dict):
            start_t = win["start"]
            end_t = win["end"]
            clip_title = win.get("title", f"Live_Moment_{c_idx+1}")
            clean_name = f"Live_{author}_{slice_ts}_{c_idx+1}"
            final_dest = READY_DIR / f"{clean_name}.mp4"

            if final_dest.exists() and final_dest.stat().st_size > 102400:
                return final_dest

            raw_seg = segments_dir / f"live_seg_{c_idx}.mp4"
            dur = max(1.0, end_t - start_t)
            subprocess.run([
                ffmpeg_bin, "-y",
                "-ss", f"{start_t:.2f}",
                "-i", str(slice_mp4),
                "-t", f"{dur:.2f}",
                "-c", "copy",
                str(raw_seg)
            ], capture_output=True)

            if not is_valid_video_file(raw_seg):
                return None

            seg_words = []
            for s in transcript.get("segments", []):
                for w in s.get("words", []):
                    if start_t <= w["start"] <= end_t:
                        seg_words.append(w)

            ass_file = segments_dir / f"live_subs_{c_idx}.ass"
            generate_karaoke_ass(seg_words, ass_file, clip_start_offset=start_t, style_preset=style_key)

            flagged = find_profanities_in_words(seg_words)

            render_mode_a_short(
                source_video=raw_seg,
                ass_subtitles=ass_file,
                output_short_path=final_dest,
                flagged_profanities=flagged,
                split_layout=False,
                enable_tracking=enable_tracking,
                hook_title="🔴 LIVE HIGHLIGHT" if enable_hook_badge else None
            )
            push_live_log(f"✓ [Stage 4/5] Rendered Live Short: {final_dest.name} (Hype {win.get('hype_score', 0)}%)")
            raw_seg.unlink(missing_ok=True)
            for p in segments_dir.glob(f"live_seg_{c_idx}.*"):
                p.unlink(missing_ok=True)

            # Generate sidecar metadata JSON for YouTube Studio (Live-specific)
            sidecar_p = final_dest.with_suffix(".json")
            try:
                clean_tag_author = re.sub(r'[^a-zA-Z0-9]', '', author)
                with open(sidecar_p, "w", encoding="utf-8") as sf:
                    json.dump({
                        "title": f"{clip_title} #Shorts",
                        "description": (
                            f"🔴 {clip_title}\n\n"
                            f"Best live streaming highlights from {author}!\n"
                            f"Stream: {title}\n\n"
                            f"Subscribe to @zelmuesports for non-stop live gaming moments & clips!\n\n"
                            f"#Shorts #{clean_tag_author} #LiveStream #Highlights #Gaming"
                        ),
                        "tags": ["Shorts", author, "LiveStream", "Highlights", "Gaming", "Viral"],
                        "category_id": "20",  # Gaming
                        "privacy_status": "private"
                    }, sf, indent=2)
            except Exception:
                pass

            return final_dest

        pool_workers = min(3, max(1, len(candidates)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=pool_workers) as pool:
            future_map = {pool.submit(process_live_short, c_idx, win): c_idx for c_idx, win in enumerate(candidates)}
            while any(not fut.done() for fut in future_map):
                time.sleep(1)
                done_count = sum(1 for fut in future_map if fut.done())
                rnd_pct = 50 + int((done_count / max(1, len(candidates))) * 35)
                set_livestream_progress(
                    status="rendering",
                    current_step=4,
                    total_steps=5,
                    percentage=rnd_pct,
                    stage_label=f"Stage 4/5: Parallel QSV Rendering ({done_count}/{len(candidates)})",
                    step_detail=f"Rendering {done_count}/{len(candidates)} live clips via Intel QSV...",
                    next_step="Stage 5/5: Auto-Schedule to Studio",
                    current_clip=done_count,
                    total_clips=len(candidates)
                )
            for fut in future_map:
                res_dest = fut.result()
                if res_dest and res_dest.exists() and res_dest.stat().st_size > 102400:
                    rendered_files.append(res_dest)
    finally:
        release_compute_lock("livestream_buffer")

    # Stage 5: Upload / Schedule
    if auto_upload and rendered_files and is_authenticated():
        set_livestream_progress(
            status="uploading",
            current_step=5,
            total_steps=5,
            percentage=92,
            stage_label="Stage 5/5: YouTube Scheduling",
            step_detail=f"Scheduling {len(rendered_files)} live Shorts across monetization slots on @zelmuesports...",
            next_step="Completion"
        )
        push_live_log(f"📤 [Stage 5/5] Scheduling {len(rendered_files)} Live Shorts to YouTube Studio...")
        try:
            results = upload_batch_private(
                max_batch_size=len(rendered_files),
                auto_schedule=True,
                slots_per_day=6,
                concurrency=2,
                privacy_mode="private",
                files_subset=rendered_files,
                log_callback=push_live_log
            )
            push_live_log(f"✓ [Stage 5/5] Successfully scheduled {len(results)} Live Shorts!")
        except Exception as e:
            push_live_log(f"Auto-upload error: {e}")

    set_livestream_progress(
        status="waiting",
        current_step=5,
        total_steps=5,
        percentage=100,
        stage_label="Live Buffer Complete",
        step_detail=f"Successfully clipped {len(rendered_files)} Shorts from live stream '{title}'!",
        next_step="Standby for next live stream polling cycle"
    )

    # Clean intermediate live slice files to prevent disk leaks
    try:
        shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        pass

    return rendered_files


def run_livestream_loop():
    """Main background loop executed by the Live Stream Buffer daemon thread."""
    push_live_log("Live Stream Rolling Buffer Daemon started.")
    set_livestream_progress(
        status="scanning",
        current_step=0,
        total_steps=5,
        percentage=0,
        stage_label="Scanning Active Livestreams",
        step_detail="Daemon started. Checking target channels for active live broadcasts...",
        next_step="Capture rolling HLS buffer"
    )

    while not _LIVE_STOP_EVENT.is_set():
        cfg = load_livestream_config()
        if not cfg.get("enabled", False):
            set_livestream_progress(
                status="idle",
                current_step=0,
                total_steps=5,
                percentage=0,
                stage_label="Live Buffer Paused",
                step_detail="Live Stream Buffer daemon is paused. Click 'Start Live Stream Buffer'.",
                next_step="Start Live Daemon"
            )
            time.sleep(5)
            continue

        if is_system_paused():
            set_livestream_progress(
                status="paused",
                current_step=0,
                total_steps=5,
                percentage=0,
                stage_label="System Paused (Master Switch)",
                step_detail="All autonomous engines paused by operator in Mission Control.",
                next_step="Resume in Mission Control"
            )
            time.sleep(4)
            continue

        if not check_internet_connection():
            push_live_log("Internet connection dropped. Pausing live buffer daemon...")
            time.sleep(30)
            continue

        channels = cfg.get("channels", [])
        state = load_livestream_state()
        processed_slices = set(state.get("processed_slices", []))

        push_live_log(f"Checking {len(channels)} channel(s) for active livestreams...")
        set_livestream_progress(
            status="scanning",
            current_step=0,
            total_steps=5,
            percentage=5,
            stage_label="Scanning Livestreams",
            step_detail=f"Probing {len(channels)} target channels for live broadcasts...",
            next_step="Capture HLS slice"
        )

        active_found = 0
        for ch in channels:
            if _LIVE_STOP_EVENT.is_set():
                break
            live_info = check_if_stream_live(ch)
            if live_info and live_info.get("is_live"):
                push_live_log(f"🔴 ACTIVE LIVESTREAM DETECTED: {live_info['title']} ({live_info['url']}) by @{live_info['channel']}")
                slice_dur = cfg.get("slice_duration_seconds", 300)
                last_caps = state.setdefault("last_capture_ts", {})
                last_ts = float(last_caps.get(live_info["id"], 0.0))
                if (time.time() - last_ts) < (slice_dur - 15):
                    push_live_log(f"Slice within active window ({int(time.time() - last_ts)}s < {slice_dur - 15}s). Skipping to prevent duplicate.")
                    continue

                slice_key = f"{live_info['id']}_{int(time.time() // 600)}"  # 1 slice per 10 mins window
                if slice_key not in processed_slices:
                    try:
                        process_livestream_slice(
                            stream_info=live_info,
                            slice_duration=slice_dur,
                            shorts_count=cfg.get("shorts_per_slice", 2),
                            caption_style=cfg.get("caption_style", "neon"),
                            enable_tracking=cfg.get("enable_tracking", False),
                            enable_hook_badge=cfg.get("enable_hook_badge", True),
                            auto_upload=cfg.get("auto_upload", True)
                        )
                        processed_slices.add(slice_key)
                        state["processed_slices"] = list(processed_slices)
                        last_caps[live_info["id"]] = time.time()
                        state["last_capture_ts"] = last_caps
                        save_livestream_state(state)
                        active_found += 1
                    except Exception as ex:
                        push_live_log(f"Error processing live stream {live_info['id']}: {ex}")
            else:
                push_live_log(f"⚪ No active livestream on {ch}")

        interval_sec = max(60, int(cfg.get("check_interval_minutes", 5)) * 60)
        push_live_log(f"Live poll complete. {active_found} active slice(s) processed. Next scan in {interval_sec // 60}m.")
        set_livestream_progress(
            status="waiting",
            current_step=5,
            total_steps=5,
            percentage=100,
            stage_label="Waiting Next Live Check",
            step_detail=f"Live poll complete ({active_found} active streams clipped). Next check in {interval_sec // 60}m.",
            next_step="Scan live streams"
        )

        for _ in range(interval_sec // 5):
            if _LIVE_STOP_EVENT.is_set():
                break
            time.sleep(5)

    push_live_log("Live Stream Rolling Buffer Daemon stopped.")
    set_livestream_progress(
        status="idle",
        current_step=0,
        total_steps=5,
        percentage=0,
        stage_label="Live Buffer Stopped",
        step_detail="Daemon stopped by operator.",
        next_step="Start Live Daemon"
    )


def start_livestream_daemon():
    """Starts the background live stream buffer daemon thread."""
    global _LIVE_THREAD, _LIVE_STOP_EVENT
    if _LIVE_THREAD is not None and _LIVE_THREAD.is_alive():
        return False
    _LIVE_STOP_EVENT.clear()
    _LIVE_THREAD = threading.Thread(target=run_livestream_loop, daemon=True)
    _LIVE_THREAD.start()
    return True


def stop_livestream_daemon():
    """Signals the background live stream buffer daemon to stop."""
    global _LIVE_STOP_EVENT
    _LIVE_STOP_EVENT.set()
    return True


def is_livestream_running() -> bool:
    global _LIVE_THREAD
    return _LIVE_THREAD is not None and _LIVE_THREAD.is_alive()
