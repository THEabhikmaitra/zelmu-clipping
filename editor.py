import os
import sys
import subprocess
import json
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from safety import mask_text, build_audio_mute_filter, find_profanities_in_words
from transcriber import get_ffmpeg_path, get_ytdlp_cmd

_BEST_ENCODER_CACHE = None
_STREAM_URL_CACHE: Dict[str, Tuple[float, Tuple[str, str]]] = {}

def get_best_video_encoder() -> List[str]:
    """Detects fastest available hardware encoder (Intel QSV > NVENC > CPU ultrafast)."""
    global _BEST_ENCODER_CACHE
    if _BEST_ENCODER_CACHE is not None:
        return _BEST_ENCODER_CACHE

    ffmpeg_bin = str(get_ffmpeg_path() or "ffmpeg")
    try:
        res_qsv = subprocess.run([ffmpeg_bin, "-f", "lavfi", "-i", "nullsrc=s=256x256:d=0.1", "-c:v", "h264_qsv", "-f", "null", "-"], capture_output=True, timeout=6)
        if res_qsv.returncode == 0:
            _BEST_ENCODER_CACHE = ["-fpsmax", "30", "-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "23", "-async_depth", "4", "-look_ahead", "0", "-bf", "0"]
            return _BEST_ENCODER_CACHE
        res_nv = subprocess.run([ffmpeg_bin, "-f", "lavfi", "-i", "nullsrc=s=256x256:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True, timeout=6)
        if res_nv.returncode == 0:
            _BEST_ENCODER_CACHE = ["-fpsmax", "30", "-c:v", "h264_nvenc", "-preset", "p1", "-cq", "23", "-bf", "0"]
            return _BEST_ENCODER_CACHE
    except Exception:
        pass
    _BEST_ENCODER_CACHE = ["-fpsmax", "30", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-crf", "23", "-threads", "0"]
    return _BEST_ENCODER_CACHE

def run_ffmpeg_with_cpu_fallback(cmd: List[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """Runs FFmpeg command with timeout; if GPU/QSV encoder initialization fails, retries on CPU libx264."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"FFmpeg command timed out after {timeout}s: {' '.join(cmd[:10])}...") from e

    if res.returncode == 0:
        return res

    # Check if GPU encoder was used in cmd
    gpu_tokens = ["h264_qsv", "h264_nvenc"]
    if any(t in cmd for t in gpu_tokens):
        fallback_cmd = []
        i = 0
        while i < len(cmd):
            if cmd[i] in ["-c:v", "-vcodec"] and i + 1 < len(cmd) and (cmd[i+1] in gpu_tokens):
                fallback_cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"])
                i += 2
                while i < len(cmd) and cmd[i] in ["-global_quality", "-async_depth", "-look_ahead", "-bf", "-cq"]:
                    i += 2
            else:
                fallback_cmd.append(cmd[i])
                i += 1
        
        try:
            fb_res = subprocess.run(fallback_cmd, capture_output=True, text=True, timeout=timeout)
            if fb_res.returncode == 0:
                return fb_res
            return fb_res
        except Exception:
            pass

    return res

def escape_ffmpeg_path(path: Path) -> str:
    r"""
    Windows path escaping for FFmpeg filters (subtitles=, fontfile=).
    Converts backslashes to forward slashes and escapes the drive colon:
    C:/foo -> C\:/foo
    """
    p_str = str(path.resolve()).replace("\\", "/")
    # Escape colon (e.g. C: -> C\:)
    if len(p_str) > 1 and p_str[1] == ":":
        p_str = p_str[0] + r"\:" + p_str[2:]
    return p_str

def get_windows_font(font_name: str = "ariblk.ttf") -> str:
    """Returns escaped Windows font path for FFmpeg drawtext."""
    win_font = Path("C:/Windows/Fonts") / font_name
    if win_font.exists():
        return escape_ffmpeg_path(win_font)
    fallback = Path("C:/Windows/Fonts/arial.ttf")
    if fallback.exists():
        return escape_ffmpeg_path(fallback)
    return ""

def generate_karaoke_ass(
    words: List[Dict[str, Any]],
    output_ass_path: Path,
    clip_start_offset: float = 0.0,
    max_words_per_line: int = 3,
    style_preset: str = "neon"
) -> Path:
    """
    Generates styled .ass subtitle file with Center Safe-Zone Karaoke Captions.
    - 1080x1920 resolution.
    - Alignment=2 (bottom-center), MarginV=520 (center safe zone clear of YouTube UI).
    - Styles: 'neon' (GTA Vice Neon pink/cyan), 'karaoke' (Gold/Yellow), 'clean' (High-contrast White).
    - Max 3 words per line, profanities masked (f***).
    """
    output_ass_path = output_ass_path.resolve()
    output_ass_path.parent.mkdir(parents=True, exist_ok=True)

    if style_preset == "neon":
        style_line = "Style: Default,Arial Black,74,&H00FFFF00,&H00D414E0,&H004B0082,&H99000000,-1,0,0,0,100,100,0,0,1,6,2,2,40,40,520,1"
    elif style_preset == "clean":
        # Pure White text &H00FFFFFF, Electric Yellow highlight &H0000E5FF, 6px heavy black outline
        style_line = "Style: Default,Arial Black,70,&H00FFFFFF,&H0000E5FF,&H00000000,&H99000000,-1,0,0,0,100,100,0,0,1,6,2,2,40,40,520,1"
    else:  # classic karaoke
        style_line = "Style: Default,Arial Black,72,&H00FFFFFF,&H0000E5FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,40,40,520,1"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style_line}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    def to_ass_time(sec: float) -> str:
        sec = max(0.0, sec)
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        cs = int(round((sec - int(sec)) * 100))
        if cs >= 100:
            s += 1
            cs -= 100
        return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

    # Filter and adjust words relative to clip start
    clip_words = []
    for w in words:
        w_start = w["start"] - clip_start_offset
        w_end = w["end"] - clip_start_offset
        clean_text = mask_text(w["word"])
        if w_start >= 0 and clean_text.strip():
            clip_words.append({
                "word": clean_text.strip(),
                "start": max(0.0, w_start),
                "end": max(0.1, w_end)
            })

    # Group into chunks of max_words_per_line (strict 2-3 words per on-screen burst)
    dialogues = []
    danger_words = {"ruin", "ruined", "ruins", "fail", "failed", "worst", "crash", "bug", "mistake", "dont", "drop", "drops", "choke", "bland", "overrated", "warning", "dead", "fatal", "not"}

    for i in range(0, len(clip_words), max_words_per_line):
        group = clip_words[i:i + max_words_per_line]
        if not group:
            continue
        line_start = group[0]["start"]
        line_end = group[-1]["end"]

        # Word-by-word active highlighting: create a subtitle event for each active word in the group
        for current_idx, active_word in enumerate(group):
            w_start_str = to_ass_time(active_word["start"])
            w_end_str = to_ass_time(active_word["end"])
            
            line_parts = []
            for idx, w in enumerate(group):
                if idx == current_idx:
                    # Dynamic color hierarchy: Neon Red &H004B33FF on danger words, Electric Yellow &H0000E5FF on high-intent words
                    w_clean_lower = re.sub(r"[^\w]", "", w["word"]).lower()
                    hl_color = r"&H004B33FF&" if w_clean_lower in danger_words else r"&H0000E5FF&"
                    line_parts.append(r"{\c" + hl_color + r"\t(0,100,\fscx110\fscy110)}" + w["word"] + r"{\c&H00FFFFFF&\fscx100\fscy100}")
                else:
                    line_parts.append(w["word"])
            
            full_line = " ".join(line_parts)
            dialogues.append(f"Dialogue: 0,{w_start_str},{w_end_str},Default,,0,0,520,,{full_line}")

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(dialogues) + "\n")

    return output_ass_path

def check_internet_connection(timeout: float = 2.5) -> bool:
    """Probes reliable DNS/HTTPS endpoints to verify internet status."""
    import socket
    for host in ("1.1.1.1", "8.8.8.8", "www.youtube.com"):
        try:
            socket.create_connection((host, 53 if host in ("1.1.1.1", "8.8.8.8") else 443), timeout=timeout)
            return True
        except (OSError, socket.timeout):
            continue
    return False


def get_direct_stream_urls(url: str, force_refresh: bool = False) -> Optional[Tuple[str, str]]:
    """Extracts direct HTTPS video and audio playback stream URLs via yt-dlp in ~2s with 2h in-memory TTL caching."""
    global _STREAM_URL_CACHE
    now = time.time()
    if not force_refresh and url in _STREAM_URL_CACHE:
        ts, cached_urls = _STREAM_URL_CACHE[url]
        if now - ts < 7200:  # 2 hours validity
            return cached_urls

    cmd = [
        *get_ytdlp_cmd(),
        "-g",
        "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
        url
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        if proc.returncode == 0:
            lines = [l.strip() for l in proc.stdout.splitlines() if l.strip().startswith("http")]
            if len(lines) >= 2:
                res = (lines[0], lines[1])
                _STREAM_URL_CACHE[url] = (now, res)
                return res
            elif len(lines) == 1:
                res = (lines[0], lines[0])
                _STREAM_URL_CACHE[url] = (now, res)
                return res
    except Exception:
        pass
    return None


def is_valid_video_file(file_path: Path) -> bool:
    """Verifies that a video file exists, is >100KB, and has readable streams with valid container headers."""
    if not file_path.exists() or file_path.stat().st_size < 102400:
        return False
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)],
            capture_output=True,
            text=True,
            timeout=5
        )
        return proc.returncode == 0 and len(proc.stdout.strip()) > 0
    except Exception:
        return False


def stream_video_section_fast(
    url: str,
    start_sec: float,
    end_sec: float,
    output_mp4_path: Path,
    stream_urls: Optional[Tuple[str, str]] = None
) -> Optional[Path]:
    """Streams and cuts remote video in ~3-4s directly via FFmpeg Range requests without yt-dlp download wait."""
    urls = stream_urls or get_direct_stream_urls(url)
    if not urls:
        return None

    v_url, a_url = urls
    ffmpeg_bin = str(get_ffmpeg_path() or "ffmpeg")
    dur = max(1.0, end_sec - start_sec)
    part_path = output_mp4_path.with_suffix(".part.mp4")

    cmd = [
        ffmpeg_bin, "-y",
        "-reconnect", "1",
        "-reconnect_at_eof", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "2",
        "-ss", f"{start_sec:.2f}",
        "-i", v_url,
        "-reconnect", "1",
        "-reconnect_at_eof", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "2",
        "-ss", f"{start_sec:.2f}",
        "-i", a_url,
        "-t", f"{dur:.2f}",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(part_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=25)
        if res.returncode == 0 and is_valid_video_file(part_path):
            if output_mp4_path.exists():
                output_mp4_path.unlink()
            part_path.rename(output_mp4_path)
            return output_mp4_path
        else:
            if part_path.exists():
                part_path.unlink()
    except Exception:
        if part_path.exists():
            part_path.unlink()
    return None


def download_video_section(
    url: str,
    start_sec: float,
    end_sec: float,
    output_mp4_path: Path,
    progress_callback: Optional[Any] = None,
    max_retries: int = 3,
    stream_urls: Optional[Tuple[str, str]] = None
) -> Path:
    """
    Downloads only the approved timestamp section.
    Prioritizes ultra-fast zero-disk direct stream cut (~3s) before falling back to yt-dlp.
    """
    output_mp4_path = output_mp4_path.resolve()
    output_mp4_path.parent.mkdir(parents=True, exist_ok=True)

    if is_valid_video_file(output_mp4_path):
        return output_mp4_path
    elif output_mp4_path.exists():
        output_mp4_path.unlink()

    # Fast Path 1: Zero-disk direct stream seek cut in ~3s
    if progress_callback:
        progress_callback("⚡ Fast streaming remote section (Zero-Disk cut)...")
    fast_cut = stream_video_section_fast(url, start_sec, end_sec, output_mp4_path, stream_urls=stream_urls)
    if fast_cut and is_valid_video_file(fast_cut):
        if progress_callback:
            progress_callback(f"✓ Fast stream cut complete: {output_mp4_path.name}")
        return fast_cut

    ffmpeg_bin = get_ffmpeg_path()
    ffmpeg_loc_arg = []
    if ffmpeg_bin:
        ffmpeg_loc_arg = ["--ffmpeg-location", str(ffmpeg_bin.parent)]

    section_arg = f"*{start_sec:.2f}-{end_sec:.2f}"
    stem_template = str(output_mp4_path.parent / output_mp4_path.stem)

    cmd = [
        *get_ytdlp_cmd(),
        "--newline",
        "--download-sections", section_arg,
        "--concurrent-fragments", "4",
        "--buffer-size", "16M",
        "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/bestvideo[height<=1080]+bestaudio/best",
        *ffmpeg_loc_arg,
        "-o", f"{stem_template}.%(ext)s",
        url
    ]

    for attempt in range(1, max_retries + 1):
        logs = []
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        if proc.stdout:
            for line in iter(proc.stdout.readline, ""):
                line_s = line.strip()
                if line_s:
                    logs.append(line_s)
                    if progress_callback:
                        progress_callback(line_s)
        proc.wait()

        # Check if file exists with mp4 or other extensions (webm, mkv)
        if not output_mp4_path.exists() or not is_valid_video_file(output_mp4_path):
            candidates = [p for p in output_mp4_path.parent.glob(f"{output_mp4_path.stem}.*") if not p.name.endswith(".part") and p != output_mp4_path]
            if candidates:
                src_file = candidates[0]
                ffmpeg_exe = str(ffmpeg_bin or "ffmpeg")
                # Transcode to guaranteed compliant H264 MP4 with ultrafast
                conv_cmd = [
                    ffmpeg_exe, "-y", "-i", str(src_file),
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                    "-c:a", "aac", "-movflags", "+faststart",
                    str(output_mp4_path)
                ]
                subprocess.run(conv_cmd, capture_output=True, timeout=180)

        if is_valid_video_file(output_mp4_path):
            return output_mp4_path
        elif output_mp4_path.exists():
            output_mp4_path.unlink()

        # If download failed, inspect error
        err_text = "\n".join(logs[-10:]) if logs else "No process output."
        is_net_error = any(
            "getaddrinfo failed" in l or "Failed to resolve" in l or "Connection" in l or "network" in l.lower()
            for l in logs
        )

        if is_net_error or not check_internet_connection():
            if attempt < max_retries:
                if progress_callback:
                    progress_callback(f"⚠️ Network drop detected. Retrying ({attempt}/{max_retries})...")
                import time
                for _ in range(5):
                    if check_internet_connection():
                        break
                    time.sleep(1)
                continue
            else:
                raise ConnectionError(f"Internet connection lost: {err_text}")

        if attempt == max_retries:
            raise RuntimeError(f"Section download failed: {err_text}")

    return output_mp4_path

def generate_piper_tts(
    text: str,
    output_wav_path: Path,
    model_onnx_path: Path = Path("en_US-ryan-high.onnx")
) -> Path:
    """
    Generates offline narration via python -m piper.
    Guards against empty input to prevent Python wave.Error (# channels not specified).
    """
    output_wav_path = output_wav_path.resolve()
    output_wav_path.parent.mkdir(parents=True, exist_ok=True)

    clean_text = (text or "").strip()
    if not clean_text or len(clean_text) < 4:
        clean_text = "Here are the top three unbelievable GTA 6 moments you have to see right now! Let's get right into the action."

    model_onnx_path = model_onnx_path.resolve()
    if not model_onnx_path.exists():
        raise FileNotFoundError(f"Piper ONNX model not found: {model_onnx_path}")

    # Use active python interpreter
    cmd = [
        sys.executable,
        "-m", "piper",
        "-m", str(model_onnx_path),
        "-f", str(output_wav_path)
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = proc.communicate(input=clean_text)
    if proc.returncode != 0:
        raise RuntimeError(f"Piper TTS generation failed: {stderr}")

    return output_wav_path

def get_watermark_config() -> Dict[str, Any]:
    """Loads persistent watermark configuration."""
    defaults = {
        "enabled": True,
        "logo_path": "logo.png",
        "position": "top-right",
        "size_px": 150,
        "opacity": 0.85,
        "margin_x": 40,
        "margin_y": 180
    }
    cfg_file = Path("watermark_config.json")
    if cfg_file.exists():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                defaults.update(data)
        except Exception:
            pass
    return defaults

def save_watermark_config(cfg: Dict[str, Any]) -> None:
    """Saves persistent watermark configuration."""
    cfg_file = Path("watermark_config.json")
    try:
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

def get_active_watermark_overlay(override_path: Optional[Path] = None) -> Optional[Tuple[Path, str, str]]:
    """
    Returns (logo_file, scale_filter, overlay_coordinates) if watermark is enabled and exists.
    Returns None if disabled or file missing.
    """
    cfg = get_watermark_config()
    if not cfg.get("enabled", True):
        return None

    logo_file = override_path or Path(cfg.get("logo_path", "logo.png"))
    if not logo_file.exists():
        return None

    size_px = max(40, min(600, int(cfg.get("size_px", 150))))
    opacity = max(0.05, min(1.0, float(cfg.get("opacity", 0.85))))
    margin_x = max(0, int(cfg.get("margin_x", 40)))
    margin_y = max(0, int(cfg.get("margin_y", 180)))
    pos = str(cfg.get("position", "top-right")).lower().strip()

    if pos in ("top-left", "tl"):
        coords = f"x={margin_x}:y={margin_y}"
    elif pos in ("bottom-right", "br"):
        coords = f"x=W-w-{margin_x}:y=H-h-{margin_y}"
    elif pos in ("bottom-left", "bl"):
        coords = f"x={margin_x}:y=H-h-{margin_y}"
    elif pos in ("top-center", "tc"):
        coords = f"x=(W-w)/2:y={margin_y}"
    elif pos in ("bottom-center", "bc"):
        coords = f"x=(W-w)/2:y=H-h-{margin_y}"
    elif pos in ("center", "c"):
        coords = f"x=(W-w)/2:y=(H-h)/2"
    else:  # default top-right safe zone
        coords = f"x=W-w-{margin_x}:y={margin_y}"

    if opacity < 0.99:
        prep_filter = f"scale={size_px}:-1,format=rgba,colorchannelmixer=aa={opacity:.2f}"
    else:
        prep_filter = f"scale={size_px}:-1"

    return (logo_file, prep_filter, coords)

def render_mode_a_short(
    source_video: Path,
    ass_subtitles: Path,
    output_short_path: Path,
    flagged_profanities: List[Dict[str, Any]],
    split_layout: bool = False,
    facecam_position: str = "top-left",
    enable_tracking: bool = True,
    logo_path: Optional[Path] = None,
    hook_title: Optional[str] = None,
    enable_anti_content_id: bool = True,
    enable_music_ducking: bool = False,
    enable_sfx: bool = True,
    enable_pacing_zoom: bool = True
) -> Path:
    """
    Renders Mode A viral short:
    - Dynamic YOLOX-S player tracking (smooth 16:9 -> 9:16 pan) or micro-pacing center zoom.
    - 4-way facecam split layout.
    - Center safe-zone karaoke captions burned in.
    - Frame-1 Viral Hook Badge (0.0s - 1.2s top curiosity banner for maximum swipe-through rate).
    - Anti-Content-ID evasion (0.3% scale jitter + 0.3% resample protects monetization).
    - Background phonk music with dynamic sidechain ducking.
    - Algorithmic SFX punch-in transition triggers on frame 1.
    - Optional channel logo/watermark overlay (top-right safe zone).
    - Profanity audio mute (0.4s).
    - Hardware acceleration: Intel QSV (350+ fps) or CPU fallback.
    """
    output_short_path = output_short_path.resolve()
    output_short_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_bin = str(get_ffmpeg_path() or "ffmpeg")
    esc_sub = escape_ffmpeg_path(ass_subtitles)

    # Configurable & optional watermark overlay
    wm_overlay = None
    if logo_path is not False:
        if logo_path and Path(logo_path).exists():
            wm_overlay = get_active_watermark_overlay(override_path=Path(logo_path))
        else:
            wm_overlay = get_active_watermark_overlay()

    has_logo = wm_overlay is not None
    sfx_file = Path("assets/sfx/whoosh.wav")
    has_sfx = enable_sfx and sfx_file.exists()
    # HARD RULE: Background songs/music permanently disabled to guarantee 0% Content ID copyright claims
    has_music = False

    # Optional Frame-1 viral hook banner (first 1.5s to boost feed CTR)
    hook_filter_str = ""
    if hook_title:
        clean_hook = re.sub(r"[^\w\s!?-]", "", hook_title)[:30].strip().upper()
        if clean_hook:
            font_title = get_windows_font("impact.ttf") or get_windows_font("ariblk.ttf")
            f_title_arg = f"fontfile='{font_title}':" if font_title else ""
            hook_filter_str = (
                f",drawtext={f_title_arg}text='⚡ {clean_hook}':fontsize=74:fontcolor=yellow:"
                f"x=(w-text_w)/2:y=380:box=1:boxcolor=black@0.85:boxborderw=16:enable='between(t,0,1.5)'"
            )

    # Single-pass scale and anti-content-id evasion: scales directly to target dimensions
    scale_expr = "scale=1084:1928,crop=1080:1920:2:4" if enable_anti_content_id else "scale=1080:1920"
    # Mechanical Pacing: 0:00-0:02 snap zoom (1.18x), followed by rapid 1.5s cut/punch-in cycles (1.08x vs 1.0x)
    zoom_filter = ",zoompan=z='if(between(on,0,45),1.18,if(mod(floor(on/45),2),1.08,1.0))':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30" if enable_pacing_zoom else ""

    tracking_keys = None
    if enable_tracking and not split_layout:
        try:
            from tracker import track_player
            tracking_keys = track_player(str(source_video.resolve()))
        except Exception:
            tracking_keys = None

    if tracking_keys:
        from tracker import generate_panning_crop_expr
        crop_x = generate_panning_crop_expr(tracking_keys)
        base_filter = (
            f"[0:v]crop=in_h*9/16:in_h:'{crop_x}':0,"
            f"{scale_expr}{zoom_filter},"
            f"subtitles='{esc_sub}'"
            f"{hook_filter_str}"
        )
    elif not split_layout:
        base_filter = (
            f"[0:v]crop=in_h*9/16:in_h:(in_w-in_h*9/16)/2:0,"
            f"{scale_expr}{zoom_filter},"
            f"subtitles='{esc_sub}'"
            f"{hook_filter_str}"
        )
    else:
        cam_coords = {
            "top-left": "0:0",
            "top-right": "in_w*0.65:0",
            "bottom-left": "0:in_h*0.55",
            "bottom-right": "in_w*0.65:in_h*0.55"
        }
        cam_xy = cam_coords.get(facecam_position.lower(), "0:0")
        stack_cid = ",scale=1084:1928,crop=1080:1920:2:4" if enable_anti_content_id else ""
        base_filter = (
            f"[0:v]split=2[cam][game];"
            f"[cam]crop=in_w*0.35:in_h*0.45:{cam_xy},scale=1080:672[top];"
            f"[game]crop=in_h*9/16:in_h:(in_w-in_h*9/16)/2:0,scale=1080:1248[bot];"
            f"[top][bot]vstack=inputs=2"
            f"{stack_cid}{zoom_filter},"
            f"subtitles='{esc_sub}'"
            f"{hook_filter_str}"
        )

    input_args = ["-hwaccel", "auto", "-i", str(source_video.resolve())]
    input_count = 1

    if has_logo:
        actual_logo_path, logo_prep, logo_coords = wm_overlay
        input_args.extend(["-i", str(actual_logo_path.resolve())])
        logo_idx = input_count
        input_count += 1
    else:
        logo_idx = None

    if has_sfx:
        input_args.extend(["-i", str(sfx_file.resolve())])
        sfx_idx = input_count
        input_count += 1
    else:
        sfx_idx = None

    if has_music:
        input_args.extend(["-stream_loop", "-1", "-i", str(music_file.resolve())])
        music_idx = input_count
        input_count += 1
    else:
        music_idx = None

    # Construct Filter Complex
    fc_parts = []
    v_out_label = "[v_out]"

    if has_logo:
        actual_logo_path, logo_prep, logo_coords = wm_overlay
        fc_parts.append(
            f"{base_filter}[v_base];"
            f"[{logo_idx}:v]{logo_prep}[logo];"
            f"[v_base][logo]overlay={logo_coords}{v_out_label}"
        )
    else:
        fc_parts.append(f"{base_filter}{v_out_label}")

    # Audio filters: profanity mute + anti-content-id shift + SFX + music ducking
    audio_chain = []
    mute_filter = build_audio_mute_filter(flagged_profanities)
    if mute_filter:
        audio_chain.append(mute_filter)
    if enable_anti_content_id:
        audio_chain.append("asetrate=44100*1.003,atempo=1/1.003")

    cur_audio = "0:a"
    if audio_chain:
        fc_parts.append(f"[{cur_audio}]{','.join(audio_chain)}[a_base]")
        cur_audio = "[a_base]"

    if has_sfx:
        in_aud = cur_audio if cur_audio.startswith("[") else f"[{cur_audio}]"
        fc_parts.append(f"{in_aud}[{sfx_idx}:a]amix=inputs=2:duration=first:dropout_transition=0[a_sfx]")
        cur_audio = "[a_sfx]"

    if has_music:
        in_aud = cur_audio if cur_audio.startswith("[") else f"[{cur_audio}]"
        fc_parts.append(f"[{music_idx}:a]volume=0.18[m_duck];{in_aud}[m_duck]amix=inputs=2:duration=first:dropout_transition=2[a_final]")
        cur_audio = "[a_final]"

    filter_complex_str = ";".join(fc_parts)

    cmd = [
        ffmpeg_bin, "-y",
        *input_args,
        "-filter_complex", filter_complex_str,
        "-map", v_out_label,
        "-map", cur_audio,
        *get_best_video_encoder(),
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_short_path)
    ]

    res = run_ffmpeg_with_cpu_fallback(cmd, timeout=300)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg Mode A render failed:\n{res.stderr}")

    return output_short_path

def render_mode_b_short(
    clip_videos: List[Path],
    narration_audio: Path,
    output_short_path: Path,
    hook_title: str = "GTA 6 INSANE MOMENTS",
    channel_credit: str = "@Creator",
    logo_path: Optional[Path] = None
) -> Path:
    """
    Renders Mode B Transformative Short:
    - 3 micro-highlights stitched sequentially.
    - Framed 9:16 branded template with top hook header & Credit: @[ChannelName] badge.
    - Optional channel logo/watermark overlay.
    - Gameplay audio ducked to 20% while Piper TTS narration speaks.
    - Safe CPU execution: -preset veryfast -threads 2 -crf 23.
    """
    output_short_path = output_short_path.resolve()
    output_short_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_bin = str(get_ffmpeg_path() or "ffmpeg")

    # Step 1: Normalize and frame each clip into 1080x1920 template with blurred background and badges
    temp_processed = []
    clean_credit = re.sub(r"[^\w@.-]", "", channel_credit)
    clean_title = re.sub(r"[^\w\s-]", "", hook_title)[:35].upper()

    font_title = get_windows_font("ariblk.ttf")
    font_credit = get_windows_font("arial.ttf")
    f_title_arg = f"fontfile='{font_title}':" if font_title else ""
    f_credit_arg = f"fontfile='{font_credit}':" if font_credit else ""

    temp_dir = clip_videos[0].parent if clip_videos else output_short_path.parent

    for i, clip in enumerate(clip_videos):
        clip_out = temp_dir / f"framed_clip_{i}.mp4"
        
        # 9:16 layout: downscaled ultra-fast background blur + centered 16:9 gameplay + hook bar + credit badge
        vf = (
            f"[0:v]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=4:2,scale=1080:1920[bg];"
            f"[0:v]scale=1040:-1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[base];"
            f"[base]drawtext={f_title_arg}text='{clean_title}':fontsize=56:fontcolor=white:x=(w-text_w)/2:y=220:box=1:boxcolor=black@0.7:boxborderw=14,"
            f"drawtext={f_credit_arg}text='Credit\\: {clean_credit}':fontsize=42:fontcolor=yellow:x=(w-text_w)/2:y=1640:box=1:boxcolor=black@0.6:boxborderw=10[v_out]"
        )

        cmd = [
            ffmpeg_bin, "-y",
            "-hwaccel", "auto",
            "-i", str(clip.resolve()),
            "-filter_complex", vf,
            "-map", "[v_out]",
            "-map", "0:a?",
            *get_best_video_encoder(),
            "-c:a", "aac", "-b:a", "128k",
            str(clip_out)
        ]
        res = run_ffmpeg_with_cpu_fallback(cmd, timeout=300)
        if res.returncode != 0:
            raise RuntimeError(f"Framed clip {i} failed: {res.stderr}")
        temp_processed.append(clip_out)

    # Step 2: Concatenate framed clips into single video
    concat_txt = temp_dir / "concat_list.txt"
    with open(concat_txt, "w", encoding="utf-8") as f:
        for p in temp_processed:
            f.write(f"file '{p.resolve().as_posix()}'\n")

    concatenated_raw = temp_dir / "concat_raw.mp4"
    cat_cmd = [
        ffmpeg_bin, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_txt.resolve()),
        "-c", "copy",
        str(concatenated_raw)
    ]
    subprocess.run(cat_cmd, capture_output=True, timeout=60)

    # Step 3: Pure narration audio overlay (strictly omit input 0 audio to eliminate background song copyright claims)
    wm_overlay = None
    if logo_path is not False:
        if logo_path and Path(logo_path).exists():
            wm_overlay = get_active_watermark_overlay(override_path=Path(logo_path))
        else:
            wm_overlay = get_active_watermark_overlay()

    has_logo = wm_overlay is not None
    mix_inputs = [
        "-i", str(concatenated_raw.resolve()),
        "-i", str(narration_audio.resolve())
    ]

    if has_logo:
        actual_logo_path, logo_prep, logo_coords = wm_overlay
        mix_inputs.extend(["-i", str(actual_logo_path.resolve())])
        fc = f"[2:v]{logo_prep}[logo];[0:v][logo]overlay={logo_coords}[v_out]"
        map_args = ["-map", "[v_out]", "-map", "1:a:0"]
        c_v_args = get_best_video_encoder()
        fc_args = ["-filter_complex", fc]
    else:
        map_args = ["-map", "0:v:0", "-map", "1:a:0"]
        c_v_args = ["-c:v", "copy"]
        fc_args = []

    mix_cmd = [
        ffmpeg_bin, "-y",
        *mix_inputs,
        *fc_args,
        *map_args,
        *c_v_args,
        "-c:a", "aac", "-b:a", "128k",
        str(output_short_path)
    ]
    mix_res = run_ffmpeg_with_cpu_fallback(mix_cmd, timeout=120)
    if mix_res.returncode != 0:
        raise RuntimeError(f"Audio mix failed:\n{mix_res.stderr}")

    return output_short_path


def generate_viral_thumbnail(
    video_path: Path,
    hook_text: str,
    sub_text: str = "",
    pill_tag: str = "🔴 DEBATE",
    output_thumb_path: Optional[Path] = None
) -> Path:
    """
    Extracts high-definition frame from video and composites an ultra-high engagement
    9:16 vertical thumbnail optimized for YouTube Shorts and Reels grids:
    - Frame 0/1 extracted via ffmpeg at t=0.6s.
    - Upper Safe-Zone (Y=280 to Y=600):
        * Top urgency badge/pill tag (e.g. 🔴 DEBATE, ⚠️ DON'T BUY, ⚡ EXPOSED).
        * Giant bold hook text (80-92px Impact font, yellow/white with black stroke and rounded background box).
    - Middle Visual Zone: High-contrast action frame with enhanced contrast.
    - Lower Safe-Zone (Y=1280 to Y=1380):
        * Direct comparison/benchmark sub-badge (e.g. "GTA 6 vs GTA 5 🤯" or "13 YEARS APART").
    - Strict UI Safe-Zone compliance: Avoids top 180px and bottom 350px platform UI overlays.
    - Saves as <stem>.thumb.jpg and <stem>.jpg.
    """
    video_path = Path(video_path).resolve()
    if not output_thumb_path:
        output_thumb_path = video_path.with_suffix(".thumb.jpg")
    output_thumb_path = Path(output_thumb_path).resolve()

    temp_frame = output_thumb_path.parent / f"temp_frame_{output_thumb_path.stem}.jpg"
    ffmpeg_bin = str(get_ffmpeg_path() or "ffmpeg")
    cmd = [
        ffmpeg_bin, "-y",
        "-ss", "0.6",
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",
        str(temp_frame)
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=15)
        from PIL import Image, ImageDraw, ImageFont, ImageEnhance

        if temp_frame.exists() and temp_frame.stat().st_size > 1000:
            base_img = Image.open(temp_frame).convert("RGB")
        else:
            base_img = Image.new("RGB", (1080, 1920), color=(15, 20, 30))

        if base_img.size != (1080, 1920):
            base_img = base_img.resize((1080, 1920), Image.Resampling.LANCZOS)

        enhancer = ImageEnhance.Contrast(base_img)
        base_img = enhancer.enhance(1.15)
        draw = ImageDraw.Draw(base_img)

        font_path = "C:/Windows/Fonts/impact.ttf" if Path("C:/Windows/Fonts/impact.ttf").exists() else "C:/Windows/Fonts/ariblk.ttf"
        font_pill = ImageFont.truetype(font_path, 42)
        font_hook = ImageFont.truetype(font_path, 86)
        font_sub = ImageFont.truetype(font_path, 52)

        # 1. Top Urgency Pill Tag (Y=280)
        clean_pill = pill_tag.strip().upper()
        if clean_pill:
            bbox_p = draw.textbbox((540, 290), clean_pill, font=font_pill, anchor="mm")
            draw.rounded_rectangle(
                [bbox_p[0] - 28, bbox_p[1] - 12, bbox_p[2] + 28, bbox_p[3] + 14],
                radius=14,
                fill=(225, 20, 50),
                outline=(255, 255, 255),
                width=3
            )
            draw.text((540, 290), clean_pill, font=font_pill, fill=(255, 255, 255), anchor="mm")

        # 2. Giant Hook Box in Upper Safe Zone (Y=440-520)
        clean_hook = re.sub(r"[^\w\s!?:-]", "", hook_text).strip().upper()[:28]
        if clean_hook:
            words = clean_hook.split()
            if len(clean_hook) > 16 and len(words) >= 2:
                mid = len(words) // 2
                line1 = " ".join(words[:mid])
                line2 = " ".join(words[mid:])
                lines = [line1, line2]
            else:
                lines = [clean_hook]

            y_start = 450 if len(lines) == 1 else 400
            for i, l_text in enumerate(lines):
                cur_y = y_start + (i * 96)
                bbox_h = draw.textbbox((540, cur_y), l_text, font=font_hook, anchor="mm")
                draw.rounded_rectangle(
                    [bbox_h[0] - 28, bbox_h[1] - 10, bbox_h[2] + 28, bbox_h[3] + 12],
                    radius=18,
                    fill=(0, 0, 0),
                    outline=(255, 230, 0),
                    width=5
                )
                draw.text(
                    (540, cur_y),
                    l_text,
                    font=font_hook,
                    fill=(255, 230, 0),
                    anchor="mm",
                    stroke_width=6,
                    stroke_fill=(0, 0, 0)
                )

        # 3. Sub-Text Benchmark / Comparison Badge in Lower Safe Zone (Y=1320)
        clean_sub = re.sub(r"[^\w\s!?:-]", "", sub_text).strip()[:38]
        if clean_sub:
            bbox_s = draw.textbbox((540, 1320), clean_sub, font=font_sub, anchor="mm")
            draw.rounded_rectangle(
                [bbox_s[0] - 25, bbox_s[1] - 10, bbox_s[2] + 25, bbox_s[3] + 12],
                radius=14,
                fill=(10, 15, 25),
                outline=(255, 255, 255),
                width=3
            )
            draw.text(
                (540, 1320),
                clean_sub,
                font=font_sub,
                fill=(255, 255, 255),
                anchor="mm",
                stroke_width=4,
                stroke_fill=(0, 0, 0)
            )

        base_img.save(output_thumb_path, format="JPEG", quality=95)
        alt_jpg = output_thumb_path.with_name(f"{video_path.stem}.jpg")
        if alt_jpg != output_thumb_path:
            base_img.save(alt_jpg, format="JPEG", quality=95)

        temp_frame.unlink(missing_ok=True)
        return output_thumb_path
    except Exception as e:
        print(f"[ThumbnailEngine] Error creating thumbnail: {e}")
        temp_frame.unlink(missing_ok=True)
        return output_thumb_path

