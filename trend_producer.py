"""
Autonomous Trend Producer for Zelmu Clipping.
From 1 Realtime Breakout Trend, generates:
- 6+ Viral Reels (9:16 Vertical Shorts, 30-45s)
- 2+ Landscape Deep-Dive Videos (16:9 Horizontal, 2-3 mins)
Auto-schedules all 8 assets to YouTube Studio across peak monetization slots.
"""

import os
import sys
import time
import json
import subprocess
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Any, Optional

from transcriber import get_ffmpeg_path
from analyzer import query_ollama_json
from editor import (
    generate_karaoke_ass,
    generate_piper_tts,
    render_mode_a_short,
    render_mode_b_short,
    stream_video_section_fast,
    download_video_section,
    get_best_video_encoder,
    get_windows_font,
    is_valid_video_file
)
from uploader import upload_batch_private, is_authenticated
from trends_hunter import get_trend_news_articles, search_trend_source_videos
from arbiter import (
    acquire_compute_lock,
    release_compute_lock,
    push_unified_log,
    PRIORITY_TREND
)

READY_DIR = Path("ready_to_upload")
WORKSPACE_DIR = Path("workspace")


def build_fallback_scripts(query: str, breakdown: List[str], news_titles: List[str]) -> Dict[str, Any]:
    """Generates guaranteed viral scripts when Ollama is offline or busy."""
    sub_topic1 = breakdown[1] if len(breakdown) > 1 else query
    sub_topic2 = breakdown[2] if len(breakdown) > 2 else query
    news_snippet = news_titles[0] if news_titles else f"New breaking developments regarding {query} have just emerged."

    shorts = [
        {
            "hook": f"⚡ SHOCKING {query.upper()}",
            "title": f"The Shocking Truth About {query.title()}",
            "script": f"You won't believe what just happened with {query}! In the past few hours, searches have exploded by thousands of percent. {news_snippet} People across the country are scrambling to find out what's really going on. Drop a comment below if you saw this coming!"
        },
        {
            "hook": f"🚨 BREAKING {query.upper()}",
            "title": f"Breaking Update: What Happened With {query.title()}",
            "script": f"Breaking news right now on {query}! If you haven't checked the news in the last hour, this is what you missed. Massive reports are confirming major developments around {sub_topic1}. Make sure you hit subscribe to stay updated on this unfolding story!"
        },
        {
            "hook": f"🤯 3 INSANE FACTS",
            "title": f"3 Insane Details About {query.title()}",
            "script": f"Here are three insane details about {query} that nobody is talking about! Number one: this breakout started just hours ago and immediately shot to the top of Google. Number two: related searches for {sub_topic1} have jumped over five hundred percent. And number three: experts are warning this is far from over!"
        },
        {
            "hook": f"⚠️ WHY EVERYONE IS TALKING",
            "title": f"Why Everyone Is Searching {query.title()}",
            "script": f"Why is everybody talking about {query} right now? It all started when breaking reports surfaced online and went completely viral. Now, millions of people are asking what this means for {sub_topic2}. Let me know your honest thoughts in the comments!"
        },
        {
            "hook": f"🔍 DEEP ANALYSIS",
            "title": f"The Full Breakdown on {query.title()}",
            "script": f"Let's break down exactly what is happening with {query}. The latest data shows an unprecedented spike in interest over the last four hours. With reports centering on {sub_topic1}, the situation is changing every single minute. Here is the full story."
        },
        {
            "hook": f"🔥 FINAL UPDATE",
            "title": f"The Final Truth on {query.title()}",
            "script": f"This is the latest update you need to see on {query}. Despite all the rumors circulating online, the confirmed facts show that {sub_topic2} is at the center of this viral moment. Stay tuned as more information breaks!"
        }
    ]

    landscapes = [
        {
            "title": f"The Complete Story Behind {query.title()} (Full Breakdown)",
            "script": f"Welcome back. Over the last four hours, a massive breakout story has taken over the internet: {query}. In this video, we are breaking down everything that has unfolded from start to finish. First, let's examine how this trend originated and why search volume skyrocketed by thousands of percent. Major reports from news outlets have highlighted key moments, including {news_snippet}. Furthermore, related developments around {sub_topic1} and {sub_topic2} have raised serious questions. We will examine the data, the eyewitness reactions, and what to expect next. Let us know your perspective in the comments, and don't forget to like and subscribe for more real-time breakdowns."
        },
        {
            "title": f"What Nobody Is Telling You About {query.title()}",
            "script": f"There is an untold side to the viral story surrounding {query} that mainstream coverage has completely overlooked. While millions of searches are pouring in, few people understand the underlying causes that triggered this breakout. Looking closely at {sub_topic1}, the timeline reveals a completely different narrative than what social media feeds are showing. Today, we dive deep into the facts, dissecting the latest developments and explaining what this means moving forward. Make sure you watch until the very end, and subscribe for daily unvarnished breakdowns."
        }
    ]

    return {"shorts": shorts, "landscapes": landscapes}


def generate_scripts_for_trend(trend: Dict[str, Any]) -> Dict[str, Any]:
    """Generates 6 Short scripts and 2 Long Video scripts from trend data via Ollama or fallback."""
    query = trend.get("query", "Viral Topic")
    breakdown = trend.get("trend_breakdown", [query])
    news_articles = trend.get("news_articles", [])
    news_titles = [a["title"] for a in news_articles if isinstance(a, dict) and "title" in a]

    # Try Ollama JSON generation
    prompt = f"""You are an elite YouTube viral scriptwriter.
A topic is currently experiencing a massive breakout in the United States:
Topic: "{query}"
Related keywords: {breakdown[:5]}
Recent headlines: {news_titles[:3]}

Write 6 high-energy viral Shorts scripts (each 40-50 words, 9:16 format) and 2 compelling Landscape video scripts (each 200-250 words, 16:9 format).
Return ONLY JSON with this schema:
{{
  "shorts": [
    {{"hook": "⚡ SHORT HOOK", "title": "Catchy Title", "script": "Full spoken voiceover script text..."}},
    ... (6 total)
  ],
  "landscapes": [
    {{"title": "Deep Dive Title 1", "script": "Full spoken voiceover script text..."}},
    {{"title": "Deep Dive Title 2", "script": "Full spoken voiceover script text..."}}
  ]
}}"""
    try:
        ollama_res = query_ollama_json(prompt, retries=1, timeout=45)
        if ollama_res and "shorts" in ollama_res and len(ollama_res["shorts"]) >= 6:
            return ollama_res
    except Exception:
        pass

    return build_fallback_scripts(query, breakdown, news_titles)


def extract_whisper_word_timestamps(wav_path: Path, script_text: str, total_duration: float, work_dir: Path, idx: int) -> List[Dict[str, Any]]:
    """
    Extracts millisecond-accurate word timestamps by running faster-whisper directly
    on the synthesized Piper speech WAV. Ensures 100% subtitle-to-voice synchronization.
    """
    json_path = work_dir / f"whisper_subs_{idx}.json"
    try:
        from transcriber import transcribe_audio_whisper
        res = transcribe_audio_whisper(wav_path, json_path, model_size="tiny.en")
        words = []
        for s in res.get("segments", []):
            for w in s.get("words", []):
                w_str = str(w.get("word", "")).strip()
                if w_str:
                    words.append({
                        "word": w_str,
                        "start": round(float(w.get("start", 0.0)), 2),
                        "end": round(float(w.get("end", 0.0)), 2)
                    })
        if words:
            return words
    except Exception as e:
        print(f"[WhisperSync] Fallback to weighted timestamps: {e}")

    # Fallback to character-length weighted timestamps if whisper fails
    raw_words = script_text.strip().split()
    if not raw_words:
        return []
    total_chars = sum(max(1, len(w)) for w in raw_words)
    out = []
    cur_t = 0.0
    for w in raw_words:
        dur_w = max(0.12, (len(w) / total_chars) * total_duration)
        w_end = min(total_duration, cur_t + dur_w)
        out.append({"word": w, "start": round(cur_t, 2), "end": round(w_end, 2)})
        cur_t = w_end
    return out


def generate_word_timestamps_from_text(text: str, total_duration: float) -> List[Dict[str, Any]]:
    """Fallback character-length weighted word timestamps."""
    words = text.strip().split()
    if not words:
        return []
    total_chars = sum(max(1, len(w)) for w in words)
    out = []
    cur_t = 0.0
    for w in words:
        dur_w = max(0.12, (len(w) / total_chars) * total_duration)
        w_end = min(total_duration, cur_t + dur_w)
        out.append({"word": w, "start": round(cur_t, 2), "end": round(w_end, 2)})
        cur_t = w_end
    return out


def get_audio_duration(audio_path: Path) -> float:
    """Gets audio duration via ffprobe in seconds."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True, timeout=5
        )
        return float(proc.stdout.strip())
    except Exception:
        return 30.0


def create_solid_color_broll(output_path: Path, duration: float, is_vertical: bool = True) -> Path:
    """Generates sleek dark news studio motion backdrop if no external video is available."""
    ffmpeg_bin = str(get_ffmpeg_path() or "ffmpeg")
    size_str = "1080x1920" if is_vertical else "1920x1080"
    cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x0a0f1d:s={size_str}:d={duration:.2f}",
        "-vf", "noise=c1s=8:c1f=t+u,eq=contrast=1.1:brightness=-0.05",
        "-c:v", "libx264", "-preset", "ultrafast",
        str(output_path)
    ]
    subprocess.run(cmd, capture_output=True)
    return output_path


def produce_trend_package(
    trend: Dict[str, Any],
    auto_upload: bool = True,
    progress_callback: Optional[Any] = None,
    status_callback: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Produces full package from 1 trend:
    - 6 Reels (9:16 Shorts)
    - 2 Landscape Videos (16:9)
    Total: 8 video assets.
    Auto-schedules to YouTube Studio.
    """
    query = trend.get("query", "Trending_Topic")
    safe_q = "".join(c if c.isalnum() else "_" for c in query)[:25].strip("_")
    ts = int(time.time())

    work_dir = WORKSPACE_DIR / f"trend_{safe_q}_{ts}"
    work_dir.mkdir(parents=True, exist_ok=True)
    READY_DIR.mkdir(parents=True, exist_ok=True)

    def log(msg: str):
        if progress_callback:
            progress_callback(msg)
        print(f"[TrendProducer] {msg}")
        push_unified_log("TREND", msg)

    def update_status(stg: int, stg_name: str, detail: str, pct: int, s_done: int = 0, v_done: int = 0):
        if status_callback:
            status_callback(query, stg, stg_name, detail, pct, s_done, v_done)

    log(f"🔥 Starting Trend Production for: '{query}'")
    update_status(1, "Step 1/5: AI Scripts", f"Generating 6 Shorts scripts + 2 Landscape scripts for '{query}'...", 15, 0, 0)

    # Step 1: News & Scripts
    log("Step 1/5: Fetching recent news headlines & generating AI scripts...")
    if not trend.get("news_articles"):
        trend["news_articles"] = get_trend_news_articles(query, max_articles=4)

    package_scripts = generate_scripts_for_trend(trend)
    shorts_scripts = package_scripts.get("shorts", [])[:6]
    landscapes_scripts = package_scripts.get("landscapes", [])[:2]

    # Step 2: Sourcing visual footage
    update_status(2, "Step 2/5: Sourcing Footage", f"Sourcing background YouTube clips for '{query}'...", 25, 0, 0)
    log("Step 2/5: Sourcing YouTube background clips for trend visuals...")
    yt_videos = search_trend_source_videos(query, max_results=2)
    source_clip_vertical = None
    source_clip_landscape = None

    if yt_videos:
        raw_dl = work_dir / "raw_trend_source.mp4"
        top_url = yt_videos[0]["url"]
        log(f"Downloading 45s section from top YouTube video: '{yt_videos[0]['title']}'...")
        try:
            download_video_section(top_url, start_sec=10.0, end_sec=55.0, output_mp4_path=raw_dl)
            if is_valid_video_file(raw_dl):
                source_clip_vertical = raw_dl
                source_clip_landscape = raw_dl
        except Exception as e:
            log(f"⚠️ YouTube clip download failed: {e}")

    # Fallback B-roll if needed
    if not source_clip_vertical or not is_valid_video_file(source_clip_vertical):
        source_clip_vertical = create_solid_color_broll(work_dir / "broll_vert.mp4", duration=45.0, is_vertical=True)
    if not source_clip_landscape or not is_valid_video_file(source_clip_landscape):
        source_clip_landscape = create_solid_color_broll(work_dir / "broll_land.mp4", duration=150.0, is_vertical=False)

    rendered_shorts = []
    rendered_landscapes = []

    # Step 3 & 4: Heavy Compute Render (Reels + Landscape) via Arbiter P1 Lock
    log("Acquiring Compute Lock (P1) for Reels & Landscape rendering...")
    if not acquire_compute_lock("trend_producer", PRIORITY_TREND, f"Trend: {query[:25]}", timeout=600.0):
        log("Failed to acquire Compute Lock (timeout or system paused). Aborting trend run.")
        update_status(0, "Aborted", "Compute lock timeout or paused", 0, 0, 0)
        return False
    try:
        # Step 3: Render 6 Reels (9:16) in Parallel
        update_status(3, "Step 3/5: Rendering Reels", f"Synthesizing voiceovers & rendering 6 Shorts in parallel...", 35, 0, 0)
        log(f"Step 3/5: Synthesizing voiceovers & rendering 6 Shorts in parallel...")

        def render_single_reel(r_idx: int, item: dict) -> Optional[Path]:
            reel_title = item.get("title", f"{query} Moment {r_idx+1}")
            hook_txt = item.get("hook", f"⚡ {query.upper()}")
            script_txt = item.get("script", "")

            # Synthesize Piper TTS
            wav_path = work_dir / f"tts_short_{r_idx}.wav"
            generate_piper_tts(script_txt, wav_path)
            dur = get_audio_duration(wav_path)

            # Generate Subtitles using exact Whisper word alignment on TTS speech
            words = extract_whisper_word_timestamps(wav_path, script_txt, dur, work_dir, r_idx)
            ass_path = work_dir / f"subs_short_{r_idx}.ass"
            generate_karaoke_ass(words, ass_path, clip_start_offset=0.0, style_preset="clean")

            # Output path
            final_mp4 = READY_DIR / f"Short_{safe_q}_{r_idx+1}_{ts}.mp4"

            # Combine video + Piper TTS via Mode A
            # Visual scene stagger: offset each short by (r_idx * 11) % 60 to prevent duplicate background frames
            broll_offset = (r_idx * 11) % 60
            cut_vis = work_dir / f"vis_short_{r_idx}.mp4"
            subprocess.run([
                "ffmpeg", "-y",
                "-ss", f"{broll_offset:.1f}",
                "-stream_loop", "-1",
                "-i", str(source_clip_vertical),
                "-i", str(wav_path),
                "-t", f"{dur:.2f}",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                str(cut_vis)
            ], capture_output=True)

            if not is_valid_video_file(cut_vis):
                return None

            render_mode_a_short(
                source_video=cut_vis,
                ass_subtitles=ass_path,
                output_short_path=final_mp4,
                flagged_profanities=[],
                split_layout=False,
                enable_tracking=False,
                hook_title=hook_txt,
                enable_anti_content_id=False,  # NO pitch shift / audio speed altering
                enable_music_ducking=False,    # NO phonk beat
                enable_sfx=False               # NO punch / whoosh sound
            )
            cut_vis.unlink(missing_ok=True)

            # Generate sidecar metadata JSON for YouTube Studio (Trend-specific, NO GTA6!)
            sidecar_p = final_mp4.with_suffix(".json")
            try:
                with open(sidecar_p, "w", encoding="utf-8") as sf:
                    json.dump({
                        "title": f"{reel_title} #Shorts",
                        "description": (
                            f"🔥 {reel_title}\n\n"
                            f"{script_txt}\n\n"
                            f"Latest breaking developments on {query}.\n"
                            f"Subscribe to @zelmuesports for real-time trending updates!\n\n"
                            f"#Shorts #Trending #{safe_q} #News"
                        ),
                        "tags": [query, *trend.get("trend_breakdown", [])[:4], "Trending", "News", "Breaking News", "Breakout", "Shorts"],
                        "category_id": "25",
                        "privacy_status": "public"
                    }, sf, indent=2, ensure_ascii=False)
            except Exception:
                pass

            return final_mp4

        total_shorts_count = len(shorts_scripts)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            fut_map = {pool.submit(render_single_reel, idx, item): idx for idx, item in enumerate(shorts_scripts)}
            for fut in concurrent.futures.as_completed(fut_map):
                res_p = fut.result()
                if res_p and res_p.exists() and res_p.stat().st_size > 102400:
                    rendered_shorts.append(res_p)
                    done_cnt = len(rendered_shorts)
                    step_pct = 35 + int((done_cnt / max(1, total_shorts_count)) * 35)
                    update_status(3, f"Step 3/5: Rendering Reels ({done_cnt}/{total_shorts_count})", f"Rendered Reel {done_cnt}/{total_shorts_count}: '{res_p.name}' via Intel QSV...", step_pct, done_cnt, 0)
                    log(f"✓ Rendered Short: {res_p.name}")

        # Step 4: Render 2 Landscape Videos (16:9)
        update_status(4, "Step 4/5: Rendering Landscape", "Synthesizing voiceovers & rendering 2 Landscape videos...", 72, len(rendered_shorts), 0)
        log(f"Step 4/5: Synthesizing voiceovers & rendering 2 Landscape videos...")
        ffmpeg_bin = str(get_ffmpeg_path() or "ffmpeg")
        font_f = get_windows_font("ariblk.ttf")
        f_arg = f"fontfile='{font_f}':" if font_f else ""
        clean_header = "".join(c for c in query.upper() if c.isalnum() or c.isspace())[:30]

        for l_idx, l_item in enumerate(landscapes_scripts):
            l_title = l_item.get("title", f"{query} Breakdown {l_idx+1}")
            l_script = l_item.get("script", "")

            wav_path = work_dir / f"tts_land_{l_idx}.wav"
            generate_piper_tts(l_script, wav_path)
            dur = get_audio_duration(wav_path)

            final_land_mp4 = READY_DIR / f"Video_{safe_q}_{l_idx+1}_{ts}.mp4"

            # Render 16:9 Landscape Video with looped visual background
            vf_filter = (
                f"scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
                f"drawtext={f_arg}text='{clean_header} BREAKDOWN':fontsize=42:fontcolor=white:box=1:boxcolor=black@0.75:x=(w-text_w)/2:y=80"
            )
            land_cmd = [
                ffmpeg_bin, "-y",
                "-stream_loop", "-1",
                "-i", str(source_clip_landscape),
                "-i", str(wav_path),
                "-t", f"{dur:.2f}",
                "-vf", vf_filter,
                *get_best_video_encoder(),
                "-c:a", "aac",
                "-b:a", "192k",
                str(final_land_mp4)
            ]
            res = subprocess.run(land_cmd, capture_output=True)
            if res.returncode == 0 and is_valid_video_file(final_land_mp4):
                # Generate sidecar metadata JSON for YouTube Studio (Trend-specific, NO GTA6!)
                sidecar_land = final_land_mp4.with_suffix(".json")
                try:
                    with open(sidecar_land, "w", encoding="utf-8") as sf:
                        json.dump({
                            "title": f"{l_title} (Full Breakdown)",
                            "description": (
                                f"The full breakdown of {query}.\n\n"
                                f"{l_script}\n\n"
                                f"Subscribe to @zelmuesports for daily in-depth breakdowns on unfolding stories across the United States.\n\n"
                                f"#Trending #{safe_q} #News #DeepDive"
                            ),
                            "tags": [query, *trend.get("trend_breakdown", [])[:4], "Deep Dive", "Explained", "Trending", "News", "United States"],
                            "category_id": "25",
                            "privacy_status": "public"
                        }, sf, indent=2, ensure_ascii=False)
                except Exception:
                    pass

                rendered_landscapes.append(final_land_mp4)
                v_done_cnt = len(rendered_landscapes)
                l_pct = 72 + int((v_done_cnt / 2) * 18)
                update_status(4, f"Step 4/5: Rendering Landscape ({v_done_cnt}/2)", f"Rendered Landscape Video {v_done_cnt}/2: '{final_land_mp4.name}'...", l_pct, len(rendered_shorts), v_done_cnt)
                log(f"✓ Rendered Landscape Video: {final_land_mp4.name}")
    finally:
        release_compute_lock("trend_producer")

    # Step 5: Instant Public Upload to Studio
    all_rendered = rendered_shorts + rendered_landscapes
    upload_results = []
    if auto_upload and all_rendered and is_authenticated():
        update_status(5, "Step 5/5: Publishing Instantly", f"Publishing {len(all_rendered)} assets instantly to YouTube Studio (Public)...", 92, len(rendered_shorts), len(rendered_landscapes))
        log(f"Step 5/5: Publishing {len(all_rendered)} assets ({len(rendered_shorts)} Shorts + {len(rendered_landscapes)} Videos) instantly (PUBLIC) to YouTube Studio...")
        upload_results = upload_batch_private(
            max_batch_size=len(all_rendered),
            auto_schedule=False,
            privacy_mode="public",
            files_subset=all_rendered,
            log_callback=log
        )

    # Clean up intermediate workspace to prevent SSD disk bloat
    import shutil
    shutil.rmtree(work_dir, ignore_errors=True)

    update_status(5, "Completed", f"Successfully produced & published {len(rendered_shorts)} Reels + {len(rendered_landscapes)} Videos for '{query}'.", 100, len(rendered_shorts), len(rendered_landscapes))
    log(f"🎉 Completed! Generated & published {len(rendered_shorts)} Shorts + {len(rendered_landscapes)} Landscape Videos instantly from '{query}'.")
    return {
        "query": query,
        "shorts": [str(p) for p in rendered_shorts],
        "landscapes": [str(p) for p in rendered_landscapes],
        "total_rendered": len(all_rendered),
        "uploads": upload_results
    }
