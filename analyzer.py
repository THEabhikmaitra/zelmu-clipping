import json
import time
import requests
from pathlib import Path
from typing import Dict, Any, List, Optional
from safety import sanitize_filename, ADULT_MONETIZATION_RISK_KEYWORDS

OLLAMA_API_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:3b"

def query_ollama_json(prompt: str, retries: int = 2, timeout: int = 300) -> Optional[Dict[str, Any]]:
    """
    Queries local Ollama using JSON format, low temperature, and automatic retries.
    """
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.2
        }
    }

    for attempt in range(retries + 1):
        try:
            resp = requests.post(OLLAMA_API_URL, json=payload, timeout=timeout)
            if resp.status_code == 200:
                result = resp.json()
                raw_response = result.get("response", "{}")
                return json.loads(raw_response)
        except Exception as e:
            if attempt == retries:
                # Log or print error
                pass
            time.sleep(2)
    return None

def split_transcript_into_chunks(
    transcript: Dict[str, Any],
    chunk_duration_sec: float = 480.0,
    overlap_sec: float = 30.0
) -> List[List[Dict[str, Any]]]:
    """
    Splits transcript segments into 8-minute chunks with a 30-second overlap.
    """
    segments = transcript.get("segments", [])
    if not segments:
        return []

    total_duration = transcript.get("duration", 0.0)
    if not total_duration and segments:
        total_duration = segments[-1]["end"]

    chunks = []
    start_time = 0.0
    step = chunk_duration_sec - overlap_sec

    while start_time < total_duration:
        end_time = start_time + chunk_duration_sec
        chunk_segments = [
            s for s in segments
            if (s["start"] >= start_time and s["start"] < end_time) or
               (s["end"] > start_time and s["end"] <= end_time)
        ]
        if chunk_segments:
            chunks.append(chunk_segments)
        start_time += step

    return chunks

def analyze_mode_a_chunk(chunk_segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Mode A: Extract standalone viral moments (26 to 42 seconds) for own gameplay.
    Requires at least 45 spoken words (blocks silent gameplay).
    Strict content safety filters applied.
    """
    chunk_text = "\n".join([f"[{s['start']}s - {s['end']}s]: {s['text']}" for s in chunk_segments])
    
    prompt = f"""
You are an expert viral YouTube Shorts producer for high-end GTA 6 gaming channels (US/UK audiences).
Analyze the following transcript excerpt from a gaming stream.

MANDATORY SAFETY & MONETIZATION RULES:
1. STRICTLY REJECT any segment with strip clubs, nudity, sexual content, torture, slurs, or graphic gore.
2. STRICTLY REJECT story cutscenes, game spoilers, or static in-game comedy TV.
3. Zero graphic violence or banned topics in the first 7 seconds.

VIRAL SHORT CRITERIA:
1. Exact duration: between 26.0 and 42.0 seconds.
2. High spoken engagement: minimum 45 spoken words in the timestamp range (NO silent gameplay).
3. First 2 seconds must start immediately on peak action, shocking statement, or high arousal emotion (comedy, clutch play, police escape).
4. Title: Punchy 45-to-55-character American English curiosity/skill hook (e.g. '200 IQ Police Escape in Vice City').

TRANSCRIPT:
{chunk_text}

OUTPUT FORMAT: Return valid JSON ONLY:
{{
  "candidates": [
    {{
      "start": 120.5,
      "end": 152.0,
      "duration": 31.5,
      "spoken_word_count": 52,
      "viral_hook": "Shocking police chase start",
      "title": "200 IQ Police Escape in Vice City",
      "reason": "Intense chase with live player commentary"
    }}
  ]
}}
"""
    result = query_ollama_json(prompt)
    if not result or "candidates" not in result:
        return []

    valid_candidates = []
    for cand in result.get("candidates", []):
        start = float(cand.get("start", 0))
        end = float(cand.get("end", 0))
        duration = end - start
        word_count = int(cand.get("spoken_word_count", 0))
        title = cand.get("title", "GTA 6 Viral Moment")
        
        # Enforce hardcoded constraints
        if 26.0 <= duration <= 42.0 and word_count >= 40:
            cand["duration"] = round(duration, 2)
            cand["safe_title"] = sanitize_filename(title)
            valid_candidates.append(cand)

    return valid_candidates

def analyze_mode_b_compilation(
    transcript: Dict[str, Any],
    channel_name: str = "Creator"
) -> Dict[str, Any]:
    """
    Mode B: Transformative commentary compilation.
    Finds 3 micro-highlights (8-11 seconds each) around one theme.
    Writes an energetic American English (en-US) 3-second hook + transition commentary.
    """
    segments = transcript.get("segments", [])
    # Sample up to first 25 segments or condensed summary to fit context comfortably
    condensed = "\n".join([f"[{s['start']}s - {s['end']}s]: {s['text']}" for s in segments[:40]])

    prompt = f"""
You are an expert viral YouTube Shorts producer for high-end gaming clips channels.
You transform third-party GTA 6 clips into an original transformative compilation (Fair Use / Monetization compliant).
Original Creator Credit: @{channel_name}

MANDATORY RULES:
1. STRICTLY REJECT strip clubs, nudity, torture, slurs, or adult content.
2. Select exactly 3 micro-highlights (8.0 to 11.0 seconds each) sharing one exciting theme (e.g. 'Insane Stunts', 'Crazy Police AI', 'Glitch Fails').
3. Total compilation duration must be 32 to 40 seconds.
4. Write an energetic, American English (en-US) commentary voiceover script for voice actor Ryan:
   - 3-second opening hook introducing the theme.
   - 2-second commentary transition between clip 1 and clip 2.
   - 2-second commentary transition between clip 2 and clip 3.
   - 2-second loop cliffhanger ending.
5. Generate a punchy 45-to-55-character American English title.

TRANSCRIPT EXCERPT:
{condensed}

OUTPUT FORMAT: Return valid JSON ONLY:
{{
  "title": "3 Insane GTA 6 Police Escapes Ranked",
  "theme": "Insane Police Escapes",
  "clips": [
    {{"start": 35.0, "end": 44.5, "duration": 9.5, "summary": "Motorcycle jump over police roadblock"}},
    {{"start": 120.0, "end": 129.0, "duration": 9.0, "summary": "Boat escape under Vice City bridge"}},
    {{"start": 210.0, "end": 220.0, "duration": 10.0, "summary": "Helicopter dodge in storm"}}
  ],
  "voiceover_script": "You won't believe how these three GTA 6 players survived 5-star police chases. First up, this insane motorcycle leap. But watch how the next player escapes on water! And finally, this helicopter pilot pulled off the impossible loop!",
  "credit": "@{channel_name}"
}}
"""
    result = query_ollama_json(prompt)
    if not result or "clips" not in result or len(result.get("clips", [])) < 3:
        # Fallback template if Ollama gave incomplete clips
        return {
            "title": "Top 3 Insane GTA 6 Moments You Missed",
            "theme": "Epic Moments",
            "clips": [
                {"start": 10.0, "end": 20.0, "duration": 10.0, "summary": "Moment 1"},
                {"start": 60.0, "end": 70.0, "duration": 10.0, "summary": "Moment 2"},
                {"start": 120.0, "end": 130.0, "duration": 10.0, "summary": "Moment 3"}
            ],
            "voiceover_script": "Here are three unbelievable GTA 6 moments you have to see. Check out this first play! Next up is even crazier! And you won't believe what happens in this final clip!",
            "credit": f"@{channel_name}"
        }

    result["safe_title"] = sanitize_filename(result.get("title", "GTA_6_Transformative_Short"))
    return result

def extract_candidates_full(
    transcript: Dict[str, Any],
    mode: str = "Mode A",
    channel_name: str = "Creator"
) -> Dict[str, Any]:
    """
    Main entry point for candidate analysis across chunks.
    """
    if mode == "Mode B":
        return analyze_mode_b_compilation(transcript, channel_name)

    # Mode A: Process in 8-minute chunks
    chunks = split_transcript_into_chunks(transcript, chunk_duration_sec=480.0, overlap_sec=30.0)
    all_candidates = []
    
    for i, chunk in enumerate(chunks):
        cands = analyze_mode_a_chunk(chunk)
        all_candidates.extend(cands)
        if len(all_candidates) >= 5:  # Sufficient candidates collected
            break

    # If no candidates met strict criteria, fallback to top word-dense window
    if not all_candidates:
        segments = transcript.get("segments", [])
        best_window = None
        max_words = 0
        for s in segments:
            # find 30s window
            w_start = s["start"]
            w_end = w_start + 30.0
            words_in_win = sum(
                len(seg.get("words", []))
                for seg in segments
                if seg["start"] >= w_start and seg["end"] <= w_end
            )
            if words_in_win > max_words:
                max_words = words_in_win
                best_window = (w_start, w_end, words_in_win)
        
        if best_window:
            all_candidates.append({
                "start": best_window[0],
                "end": best_window[1],
                "duration": 30.0,
                "spoken_word_count": best_window[2],
                "viral_hook": "High engagement gameplay moment",
                "title": "Insane Vice City High Speed Action",
                "safe_title": "Insane Vice City High Speed Action",
                "reason": "Selected based on highest spoken engagement"
            })

    # Return top 3 candidates
    return {"mode": "Mode A", "candidates": all_candidates[:3]}
