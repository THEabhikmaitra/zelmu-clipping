"""
Instagram Bulk Ingestion & Repurposing Engine for Zelmu Clipping.
Fetches public Instagram Reels from @usernames or custom URL batches,
transforms descriptions into YouTube SEO metadata via Ollama,
and passes clips directly into Stage 3 Quality Review & Stage 4 Upload.
"""

import os
import sys
import re
import json
import time
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from transcriber import get_ffmpeg_path, get_ytdlp_cmd
from analyzer import query_ollama_json
from safety import is_cricket_or_broadcast_sports
from editor import (
    generate_karaoke_ass,
    render_mode_a_short,
    get_best_video_encoder,
    is_valid_video_file
)
from arbiter import push_unified_log

READY_DIR = Path("ready_to_upload")
WORKSPACE_DIR = Path("workspace")


def normalize_instagram_target(target: str) -> Tuple[str, str]:
    """
    Normalizes input string into type ('profile' or 'reel') and valid Instagram URL.
    """
    clean = target.strip()
    if clean.startswith("@"):
        uname = clean.lstrip("@").strip()
        return "profile", f"https://www.instagram.com/{uname}/reels/"
    elif clean.startswith("http://") or clean.startswith("https://"):
        if "/reel/" in clean or "/p/" in clean:
            return "reel", clean.split("?")[0].rstrip("/") + "/"
        return "profile", clean.split("?")[0].rstrip("/") + "/reels/"
    else:
        # Assumed username
        uname = clean.strip()
        return "profile", f"https://www.instagram.com/{uname}/reels/"


def fetch_instagram_metadata(
    target: str,
    max_items: int = 10,
    cookies_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Extracts metadata for Instagram reels using yt-dlp.
    Guards against cricket/broadcast sports copyright risk.
    """
    t_type, target_url = normalize_instagram_target(target)
    cmd = [
        *get_ytdlp_cmd(),
        "--dump-single-json",
        "--flat-playlist",
        "--no-warnings",
        "--ignore-errors"
    ]
    if cookies_path and Path(cookies_path).exists():
        cmd.extend(["--cookies", str(Path(cookies_path).resolve())])

    if t_type == "profile":
        cmd.extend(["--playlist-end", str(max_items)])

    cmd.append(target_url)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            entries = data.get("entries", []) if "entries" in data else [data]
            reels = []
            for e in entries:
                if not e:
                    continue
                v_id = e.get("id") or e.get("webpage_url_basename")
                v_url = e.get("url") or e.get("webpage_url") or (f"https://www.instagram.com/reel/{v_id}/" if v_id else None)
                if not v_url:
                    continue
                v_desc = e.get("description") or e.get("title") or ""
                v_uploader = e.get("uploader") or e.get("channel") or ""

                # Strictly skip cricket/sports copyright risks
                if is_cricket_or_broadcast_sports(v_desc) or is_cricket_or_broadcast_sports(v_uploader):
                    print(f"[InstaScraper] Skipped copyright risk reel: '{v_desc[:40]}' by {v_uploader}")
                    continue

                reels.append({
                    "id": v_id,
                    "url": v_url,
                    "caption": v_desc,
                    "uploader": v_uploader or target.strip("@"),
                    "duration": float(e.get("duration") or 30.0)
                })
                if len(reels) >= max_items:
                    break
            return reels
    except Exception as e:
        print(f"Error fetching Instagram metadata: {e}")
    return []


def convert_caption_to_youtube_seo(caption: str, uploader: str = "") -> Dict[str, Any]:
    """
    Converts raw Instagram caption to YouTube SEO Title, Description, and Tags
    via Ollama with smart regex fallback.
    """
    # Clean hashtag spam & repetitive whitespace
    clean_text = re.sub(r'#\w+', '', caption).strip()
    clean_lines = [l.strip() for l in clean_text.splitlines() if l.strip() and not l.startswith('.')]
    lead_sentence = clean_lines[0] if clean_lines else "Unbelievable Viral Moment"
    account_handle = f"@{uploader.lstrip('@')}" if uploader else "@creator"

    # Try Ollama JSON generation
    prompt = f"""You are a YouTube Shorts SEO specialist. Convert this Instagram Reel caption into a high-CTR YouTube Short title and description:
Caption: "{lead_sentence[:120]}"
Original Creator: {account_handle}

Return ONLY JSON:
{{
  "title": "High-CTR Title under 65 chars #Shorts",
  "description": "Engaging description with credit to {account_handle}",
  "tags": ["Tag1", "Tag2", "Tag3", "Shorts"]
}}"""
    try:
        res = query_ollama_json(prompt, retries=1, timeout=18)
        if res and isinstance(res, dict) and "title" in res:
            t_raw = res.get("title", "")
            t_clean = t_raw if "#shorts" in t_raw.lower() else f"{t_raw} #Shorts"
            return {
                "title": t_clean[:70],
                "description": f"{res.get('description', '')}\n\nCredit: {account_handle}\n\n#Shorts #Trending",
                "tags": [t for t in res.get("tags", []) if isinstance(t, str)][:10] or ["Shorts", "Viral", "Trending"]
            }
    except Exception:
        pass

    # High-CTR Fallback
    base_title = lead_sentence[:50].strip()
    title = f"{base_title.title()} 🤯 #Shorts" if len(base_title) <= 50 else f"{base_title[:45].title()}... #Shorts"
    extracted_hashtags = [w.strip("#") for w in re.findall(r'#\w+', caption)[:8]]

    return {
        "title": title[:70],
        "description": f"🔥 {lead_sentence}\n\nCredit: {account_handle}\n\n#Shorts #Trending",
        "tags": extracted_hashtags + ["Shorts", "Trending", "Viral"]
    }


def download_instagram_video(
    url: str,
    output_mp4: Path,
    cookies_path: Optional[str] = None
) -> Optional[Path]:
    """Downloads an Instagram Reel MP4 directly via yt-dlp."""
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    part_mp4 = output_mp4.with_suffix(".part.mp4")

    cmd = [
        *get_ytdlp_cmd(),
        "-f", "bestvideo+bestaudio/best[ext=mp4]/best",
        "-o", str(part_mp4),
        "--no-warnings",
        "--ignore-errors"
    ]
    if cookies_path and Path(cookies_path).exists():
        cmd.extend(["--cookies", str(Path(cookies_path).resolve())])

    cmd.append(url)

    try:
        res = subprocess.run(cmd, capture_output=True, timeout=60)
        if res.returncode == 0 and is_valid_video_file(part_mp4):
            if output_mp4.exists():
                output_mp4.unlink()
            part_mp4.rename(output_mp4)
            return output_mp4
        elif part_mp4.exists():
            part_mp4.unlink()
    except Exception:
        if part_mp4.exists():
            part_mp4.unlink()
    return None


def process_instagram_reel(
    reel_info: Dict[str, Any],
    mode: str = "direct",
    cookies_path: Optional[str] = None,
    progress_callback: Optional[Any] = None
) -> Optional[Path]:
    """
    Downloads reel, converts caption to YouTube SEO sidecar,
    and formats into Stage 3 Quality Review queue:
    - 'direct': standardize to 1080x1920 MP4 with original audio.
    - 'transform': adds Whisper karaoke subtitles, 3.2s punch zoom & frame-1 hook.
    """
    def log(msg: str):
        if progress_callback:
            progress_callback(msg)
        print(f"[InstaClipper] {msg}")
        push_unified_log("INSTA", msg)

    r_id = reel_info.get("id") or str(int(time.time() * 1000))[-8:]
    r_url = reel_info.get("url")
    r_caption = reel_info.get("caption", "")
    r_uploader = reel_info.get("uploader", "creator")

    ts = int(time.time())
    work_dir = WORKSPACE_DIR / f"insta_{r_id}_{ts}"
    work_dir.mkdir(parents=True, exist_ok=True)
    READY_DIR.mkdir(parents=True, exist_ok=True)

    raw_mp4 = work_dir / "raw_reel.mp4"
    final_mp4 = READY_DIR / f"Short_Insta_{r_uploader}_{r_id}_{ts}.mp4"

    log(f"📥 Downloading Reel from @{r_uploader}: {r_url}...")
    dl_res = download_instagram_video(r_url, raw_mp4, cookies_path)
    if not dl_res or not is_valid_video_file(raw_mp4):
        log(f"⚠️ Failed to download Reel: {r_url}")
        return None

    log("🧠 Generating YouTube SEO Title & Metadata via Ollama...")
    seo_meta = convert_caption_to_youtube_seo(r_caption, r_uploader)

    ffmpeg_bin = str(get_ffmpeg_path() or "ffmpeg")

    if mode == "transform":
        log("🎬 Applying Full AI Transformation (Subtitles + 3.2s Zoom + Frame-1 Hook)...")
        # Extract audio for Whisper transcription
        audio_wav = work_dir / "audio.wav"
        subprocess.run([
            ffmpeg_bin, "-y", "-i", str(raw_mp4),
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(audio_wav)
        ], capture_output=True)

        ass_file = work_dir / "subs.ass"
        words = []
        try:
            from transcriber import get_whisper_model
            model = get_whisper_model("base")
            res = model.transcribe(str(audio_wav), word_timestamps=True)
            for seg in res.get("segments", []):
                for w in seg.get("words", []):
                    words.append({"word": w["word"], "start": w["start"], "end": w["end"]})
        except Exception as e:
            log(f"⚠️ Whisper transcription fallback: {e}")

        generate_karaoke_ass(words, ass_file, clip_start_offset=0.0, style_preset="neon")

        hook_banner = seo_meta.get("title", "").split("#")[0].strip()[:28].upper()

        render_mode_a_short(
            source_video=raw_mp4,
            ass_subtitles=ass_file,
            output_short_path=final_mp4,
            flagged_profanities=[],
            split_layout=False,
            enable_tracking=False,
            hook_title=hook_banner,
            enable_pacing_zoom=True,
            enable_anti_content_id=True,
            enable_music_ducking=False,  # NO background songs
            enable_sfx=True
        )
    else:
        log("⚡ Fast Direct Repurpose: Normalizing to 1080x1920 MP4...")
        # Standardize 9:16 layout with centered fit
        vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
        cmd = [
            ffmpeg_bin, "-y",
            "-i", str(raw_mp4),
            "-vf", vf,
            *get_best_video_encoder(),
            "-c:a", "aac", "-b:a", "128k",
            str(final_mp4)
        ]
        subprocess.run(cmd, capture_output=True)

    if not is_valid_video_file(final_mp4):
        log(f"⚠️ Processing failed for reel {r_id}")
        return None

    # Save Sidecar Metadata JSON for Stage 3 & Stage 4
    sidecar_path = final_mp4.with_suffix(".json")
    try:
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump({
                "title": seo_meta.get("title", f"Viral Moment @{r_uploader} #Shorts")[:70],
                "description": seo_meta.get("description", ""),
                "tags": seo_meta.get("tags", ["Shorts", "Viral", "Trending"]),
                "category_id": "24",  # Entertainment
                "privacy_status": "public",
                "approved": False,
                "stage": "pending_quality_review",
                "source": "instagram_clipper",
                "source_account": r_uploader,
                "source_url": r_url,
                "created_at": time.time()
            }, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving sidecar: {e}")

    log(f"✓ Successfully processed: {final_mp4.name} (Ready for Stage 3 Quality Check)")
    return final_mp4
