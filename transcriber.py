import os
import sys
import gc
import json
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional, List

def get_ytdlp_cmd() -> List[str]:
    """Finds yt-dlp executable or falls back to python module execution."""
    base_cmd = []
    which_ytdlp = shutil.which("yt-dlp")
    if which_ytdlp:
        base_cmd = [which_ytdlp]
    else:
        venv_ytdlp = Path(sys.executable).parent / "yt-dlp.exe"
        if venv_ytdlp.exists():
            base_cmd = [str(venv_ytdlp.resolve())]
        else:
            local_ytdlp = Path("venv/Scripts/yt-dlp.exe")
            if local_ytdlp.exists():
                base_cmd = [str(local_ytdlp.resolve())]
            else:
                base_cmd = [sys.executable, "-m", "yt_dlp"]

    # Accelerate cipher extraction with local Node.js if present
    if shutil.which("node"):
        base_cmd.extend(["--js-runtimes", "node", "--remote-components", "ejs:github"])
    return base_cmd

def get_ffmpeg_path() -> Optional[Path]:
    """Finds ffmpeg executable from PATH or common Windows install locations."""
    # Check standard PATH
    which_ffmpeg = shutil.which("ffmpeg")
    if which_ffmpeg:
        return Path(which_ffmpeg).resolve()

    # Search common Windows winget / standard locations
    search_dirs = [
        Path("C:/clipping/bin"),
        Path("./bin"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages",
        Path("C:/Program Files/ffmpeg/bin"),
        Path("C:/ffmpeg/bin")
    ]
    for s_dir in search_dirs:
        if s_dir.exists():
            matches = list(s_dir.glob("**/ffmpeg.exe"))
            if matches:
                # Add directory to PATH so subprocesses find it
                bin_dir = str(matches[0].parent)
                if bin_dir not in os.environ["PATH"]:
                    os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]
                return matches[0].resolve()
    return None

def get_video_metadata(url: str) -> Dict[str, Any]:
    """
    Extracts video ID, title, channel name/ID, and live status without downloading.
    """
    cmd = [
        *get_ytdlp_cmd(),
        "--print", "%(id)s\t%(title)s\t%(uploader)s\t%(channel)s\t%(uploader_id)s\t%(is_live)s\t%(was_live)s",
        "--no-warnings",
        "--skip-download",
        url
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip():
        parts = res.stdout.strip().split("\t")
        uploader = parts[2] if len(parts) > 2 and parts[2] != "NA" else ""
        channel = parts[3] if len(parts) > 3 and parts[3] != "NA" else ""
        channel_name = channel or uploader or "Creator"
        return {
            "id": parts[0] if len(parts) > 0 else "",
            "title": parts[1] if len(parts) > 1 else "",
            "channel": channel_name,
            "uploader": uploader,
            "uploader_id": parts[4] if len(parts) > 4 else "",
            "is_live": parts[5].strip().lower() == "true" if len(parts) > 5 else False,
            "was_live": parts[6].strip().lower() == "true" if len(parts) > 6 else False
        }
    return {"id": "", "title": "", "channel": "Creator", "is_live": False, "was_live": False}

def extract_audio_wav(
    url: str,
    output_wav_path: Path,
    max_duration_sec: Optional[float] = None,
    progress_callback: Optional[Any] = None
) -> Path:
    """
    Fast audio extraction:
    1. Downloads native lightweight audio stream (m4a/opus ~12MB) in 2-3s via direct HTTP.
    2. Converts to 16kHz mono WAV locally using FFmpeg in 0.5s.
    Avoids throttled real-time stream decoding.
    """
    output_wav_path = output_wav_path.resolve()
    output_wav_path.parent.mkdir(parents=True, exist_ok=True)
    
    # If audio already exists, skip
    if output_wav_path.exists() and output_wav_path.stat().st_size > 1024:
        return output_wav_path

    stem_template = str(output_wav_path.parent / f"raw_audio_{output_wav_path.stem}")

    ffmpeg_bin = str(get_ffmpeg_path() or "ffmpeg")

    cmd = [
        *get_ytdlp_cmd(),
        "--newline",
        "-f", "ba[ext=m4a]/ba/b",
        "--concurrent-fragments", "4",
        "--no-playlist",
        "-o", f"{stem_template}.%(ext)s",
        url
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    if proc.stdout:
        for line in iter(proc.stdout.readline, ""):
            line_s = line.strip()
            if line_s and progress_callback:
                progress_callback(line_s)
    proc.wait()

    # Find downloaded audio file
    downloaded = list(output_wav_path.parent.glob(f"raw_audio_{output_wav_path.stem}.*"))
    if not downloaded:
        raise RuntimeError("Fast audio stream download failed.")

    raw_file = downloaded[0]

    # Convert to 16kHz mono WAV locally at 150x speed
    t_arg = ["-t", str(int(max_duration_sec))] if max_duration_sec and max_duration_sec > 0 else []
    ff_cmd = [
        ffmpeg_bin, "-y",
        "-i", str(raw_file),
        *t_arg,
        "-ar", "16000", "-ac", "1",
        str(output_wav_path)
    ]
    res = subprocess.run(ff_cmd, capture_output=True, text=True)
    raw_file.unlink(missing_ok=True)

    if res.returncode != 0 or not output_wav_path.exists():
        raise RuntimeError(f"Local audio conversion failed:\n{res.stderr}")

    return output_wav_path

def fetch_youtube_captions(
    url: str,
    output_json_path: Path,
    max_duration_sec: Optional[float] = None,
    progress_callback: Optional[Any] = None
) -> Optional[Dict[str, Any]]:
    """
    Directly extracts YouTube's own word-timed captions (json3 format).
    Takes ~1-2 seconds for long videos with 0 GPU/CPU load.
    Returns structured transcript dict or None if captions are unavailable.
    """
    output_json_path = output_json_path.resolve()
    if output_json_path.exists() and output_json_path.stat().st_size > 100:
        try:
            with open(output_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("segments"):
                    return data
        except Exception:
            pass

    if progress_callback:
        progress_callback(0, 0, "Checking YouTube word-timed captions (Fast Mode)...")

    cmd = [
        *get_ytdlp_cmd(),
        "--dump-single-json",
        "--skip-download",
        "--no-warnings",
        url
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0 or not res.stdout.strip():
            return None
        info = json.loads(res.stdout)
    except Exception:
        return None

    duration = float(info.get("duration") or 0.0)
    auto = info.get("automatic_captions") or {}
    manual = info.get("subtitles") or {}
    lang = info.get("language") or ""

    candidates = [k for k in auto if k.endswith("-orig")]
    key = None
    group = auto
    if lang and f"{lang}-orig" in auto:
        key = f"{lang}-orig"
    elif "en-orig" in auto:
        key = "en-orig"
    elif lang and lang in auto:
        key = lang
    elif "en" in auto:
        key = "en"
    elif candidates:
        key = candidates[0]
    elif lang and lang in manual:
        key = lang
        group = manual
    elif "en" in manual:
        key = "en"
        group = manual

    track = None
    if key and key in group:
        for f in group[key]:
            if f.get("ext") == "json3" and f.get("url"):
                track = f
                break

    if not track:
        return None

    try:
        req = urllib.request.Request(track["url"], headers={"User-Agent": "Mozilla/5.0"})
        raw_data = json.loads(urllib.request.urlopen(req, timeout=15).read(40_000_000))
    except Exception:
        return None

    raw_words = []
    skipping = False
    for ev in raw_data.get("events") or []:
        segs = [x for x in ev.get("segs") or [] if (x.get("utf8") or "").strip()]
        if not segs:
            continue
        t0, dur = float(ev.get("tStartMs") or 0), float(ev.get("dDurationMs") or 0)
        timed = len(segs) > 1 or "tOffsetMs" in segs[0]
        for x in segs:
            parts = x["utf8"].split()
            for n, w in enumerate(parts):
                if skipping:
                    if w.endswith(("]", ")")):
                        skipping = False
                    continue
                if w[:1] in "[(" and not re.fullmatch(r"[\[(].*[\])]", w):
                    skipping = True
                    continue
                if re.fullmatch(r"[\[(].*[\])]", w) or w in ("[", "]", "__", ">>", "-"):
                    continue
                at = t0 + float(x.get("tOffsetMs") or 0) if timed else t0 + dur * n / max(1, len(parts))
                sec_at = round(at / 1000.0, 2)
                if max_duration_sec and sec_at > max_duration_sec:
                    continue
                raw_words.append({"start": sec_at, "text": w})

    if not raw_words:
        return None

    raw_words.sort(key=lambda w: w["start"])
    for n, w in enumerate(raw_words):
        nxt = raw_words[n + 1]["start"] if n + 1 < len(raw_words) else w["start"] + 0.4
        w["end"] = round(max(w["start"] + 0.08, min(nxt, w["start"] + 0.6)), 2)

    segments = []
    cur_words = []
    for w in raw_words:
        cur_words.append(w)
        is_break = w["text"].endswith((".", "!", "?")) or (cur_words and (w["end"] - cur_words[0]["start"]) > 5.0)
        if is_break and len(cur_words) >= 3:
            segments.append({
                "start": cur_words[0]["start"],
                "end": cur_words[-1]["end"],
                "text": " ".join([cw["text"] for cw in cur_words]),
                "words": [{
                    "word": cw["text"],
                    "start": cw["start"],
                    "end": cw["end"],
                    "probability": 1.0
                } for cw in cur_words]
            })
            cur_words = []

    if cur_words:
        segments.append({
            "start": cur_words[0]["start"],
            "end": cur_words[-1]["end"],
            "text": " ".join([cw["text"] for cw in cur_words]),
            "words": [{
                "word": cw["text"],
                "start": cw["start"],
                "end": cw["end"],
                "probability": 1.0
            } for cw in cur_words]
        })

    transcript_data = {
        "language": key[:2] if key else "en",
        "language_probability": 1.0,
        "duration": duration or (segments[-1]["end"] if segments else 0.0),
        "source": "youtube_json3",
        "segments": segments
    }

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(transcript_data, f, indent=2, ensure_ascii=False)

    if progress_callback:
        progress_callback(transcript_data["duration"], transcript_data["duration"], f"Instant YouTube captions parsed ({len(segments)} segments)")

    return transcript_data

def transcribe_audio_whisper(
    audio_path: Path,
    output_json_path: Path,
    model_size: str = "tiny.en",
    compute_type: str = "int8",
    progress_callback: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Runs faster-whisper with BatchedInference (8x threads) and int8 quantization.
    Reports real-time segment progress and immediately cleans up RAM.
    """
    audio_path = audio_path.resolve()
    output_json_path = output_json_path.resolve()
    output_json_path.parent.mkdir(parents=True, exist_ok=True)

    if output_json_path.exists() and output_json_path.stat().st_size > 100:
        with open(output_json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    from faster_whisper import WhisperModel, BatchedInferencePipeline

    if progress_callback:
        progress_callback(0, 0, f"Initializing faster-whisper model ({model_size} int8 CPU)...")

    threads = min(16, os.cpu_count() or 8)
    # Load model on CPU with int8 and max worker threads
    model = WhisperModel(model_size, device="cpu", compute_type=compute_type, cpu_threads=threads)
    batched_model = BatchedInferencePipeline(model=model)

    if progress_callback:
        progress_callback(0, 0, f"Batched model loaded in RAM ({threads} threads). Starting turbo transcription...")
    
    segments, info = batched_model.transcribe(
        str(audio_path),
        batch_size=16,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400)
    )

    transcript_data = {
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "segments": []
    }

    for segment in segments:
        seg_dict = {
            "start": round(segment.start, 2),
            "end": round(segment.end, 2),
            "text": segment.text.strip(),
            "words": []
        }
        if segment.words:
            for w in segment.words:
                seg_dict["words"].append({
                    "word": w.word.strip(),
                    "start": round(w.start, 2),
                    "end": round(w.end, 2),
                    "probability": round(w.probability, 2)
                })
        transcript_data["segments"].append(seg_dict)

        if progress_callback:
            progress_callback(segment.end, info.duration, segment.text.strip())

    # Save checkpoint immediately
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(transcript_data, f, indent=2, ensure_ascii=False)

    # Sequential RAM Cleanup: strictly delete model and force garbage collection
    del model
    gc.collect()

    return transcript_data
