import os
import sys
import gc
import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List

def get_ytdlp_cmd() -> List[str]:
    """Finds yt-dlp executable or falls back to python module execution."""
    which_ytdlp = shutil.which("yt-dlp")
    if which_ytdlp:
        return [which_ytdlp]
    venv_ytdlp = Path(sys.executable).parent / "yt-dlp.exe"
    if venv_ytdlp.exists():
        return [str(venv_ytdlp.resolve())]
    local_ytdlp = Path("venv/Scripts/yt-dlp.exe")
    if local_ytdlp.exists():
        return [str(local_ytdlp.resolve())]
    return [sys.executable, "-m", "yt_dlp"]

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
    Extracts 16kHz mono WAV audio using yt-dlp.
    Never downloads video during audio-first pass.
    Supports max_duration_sec and streams real-time stdout via progress_callback.
    """
    output_wav_path = output_wav_path.resolve()
    output_wav_path.parent.mkdir(parents=True, exist_ok=True)
    
    # If audio already exists, skip
    if output_wav_path.exists() and output_wav_path.stat().st_size > 1024:
        return output_wav_path

    # Intermediate template without extension (yt-dlp appends .wav)
    stem_template = str(output_wav_path.parent / output_wav_path.stem)

    ffmpeg_bin = get_ffmpeg_path()
    ffmpeg_loc_arg = []
    if ffmpeg_bin:
        ffmpeg_loc_arg = ["--ffmpeg-location", str(ffmpeg_bin.parent)]

    section_args = []
    if max_duration_sec and max_duration_sec > 0:
        section_args = ["--download-sections", f"*0-{int(max_duration_sec)}"]

    cmd = [
        *get_ytdlp_cmd(),
        "--newline",
        "-x",
        "--audio-format", "wav",
        "--postprocessor-args", "ffmpeg:-ar 16000 -ac 1",
        *section_args,
        *ffmpeg_loc_arg,
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

    if proc.returncode != 0 and not output_wav_path.exists():
        raise RuntimeError(f"yt-dlp audio extraction failed with exit code {proc.returncode}")

    return output_wav_path

def transcribe_audio_whisper(
    audio_path: Path,
    output_json_path: Path,
    model_size: str = "small",
    compute_type: str = "int8",
    progress_callback: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Runs faster-whisper with word-level timestamps and int8 quantization.
    Reports real-time segment progress and immediately cleans up RAM.
    """
    audio_path = audio_path.resolve()
    output_json_path = output_json_path.resolve()
    output_json_path.parent.mkdir(parents=True, exist_ok=True)

    if output_json_path.exists() and output_json_path.stat().st_size > 100:
        with open(output_json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    from faster_whisper import WhisperModel

    if progress_callback:
        progress_callback(0, 0, "Initializing faster-whisper model (int8 CPU)...")

    # Load model on CPU with int8 to prevent memory exhaustion
    model = WhisperModel(model_size, device="cpu", compute_type=compute_type)

    if progress_callback:
        progress_callback(0, 0, "Model loaded in RAM. Starting voice transcription...")
    
    segments, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500)
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
