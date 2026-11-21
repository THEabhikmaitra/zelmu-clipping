import re
from pathlib import Path
from typing import List, Dict, Tuple

# YouTube Ad-suitability & Profanity Blocklist
PROFANITY_LIST = {
    "fuck", "fucking", "fucked", "fucker", "motherfucker", "shit", "shitty", "bullshit",
    "bitch", "bitches", "asshole", "bastard", "cunt", "dick", "pussy", "nigger", "nigga",
    "faggot", "slut", "whore", "cock", "retard", "jackass"
}

# Harmful / Monetization-risk Keywords (Strip clubs, nudity, graphic gore)
ADULT_MONETIZATION_RISK_KEYWORDS = {
    "strip club", "stripper", "nudity", "naked", "sex", "blowjob", "handjob",
    "torture", "suicide", "beheading", "rape", "gore", "bloodbath", "dismember"
}

# Strict Broadcast Copyright Blocklist: Cricket & Official Sports Broadcasters
# These entities have 100% automated YouTube Content ID fingerprinting. Using real footage causes instant strikes.
CRICKET_AND_SPORTS_KEYWORDS = {
    # Cricket broad & specific terms
    "cricket", "bcci", "icc", "ipl", "wpl", "t20", "odi", "test match",
    "cricbuzz", "espncricinfo", "star sports", "willow", "hotstar", "jiocinema",
    "virat kohli", "rohit sharma", "ms dhoni", "dhoni", "bumrah", "hardik pandya",
    "babar azam", "pat cummins", "ind vs", "aus vs", "eng vs", "pak vs", "sa vs",
    "wicket", "sixes", "batsman", "bowler", "super over", "world cup", "match highlights",
    "cricket highlights", "live score", "boundary", "stumped", "century", "half century",
    "team india", "ipl 2024", "ipl 2025", "ipl 2026", "cricket world cup",
    # Major global sports broadcast copyright holders
    "uefa", "fifa", "premier league", "champions league", "nba", "nfl", "f1", "formula 1",
    "wwe", "ufc", "espn", "sky sports", "fox sports", "dazn", "bein sports", "sony liv"
}

def is_cricket_or_broadcast_sports(text: str) -> bool:
    """Detects whether text mentions cricket or strictly protected broadcast sports footage."""
    if not text:
        return False
    lower = text.lower()
    for kw in CRICKET_AND_SPORTS_KEYWORDS:
        pattern = r"\b" + re.escape(kw) + r"\b" if " " not in kw else re.escape(kw)
        if re.search(pattern, lower):
            return True
    return False

def is_profane(word: str) -> bool:
    clean = re.sub(r"[^\w]", "", word.lower())
    return clean in PROFANITY_LIST

def censor_word(word: str) -> str:
    clean = re.sub(r"[^\w]", "", word.lower())
    if clean in PROFANITY_LIST:
        if len(clean) <= 2:
            return clean[0] + "*"
        return clean[0] + ("*" * (len(clean) - 1))
    return word

def mask_text(text: str) -> str:
    words = text.split()
    censored = [censor_word(w) for w in words]
    return " ".join(censored)

def find_profanities_in_words(words: List[Dict]) -> List[Dict]:
    """
    Finds profanities from word timestamp list.
    Each item: {"word": str, "start": float, "end": float}
    """
    flagged = []
    for item in words:
        w_text = item.get("word", "")
        if is_profane(w_text):
            start = item.get("start", 0.0)
            end = max(item.get("end", start + 0.4), start + 0.4)
            flagged.append({
                "word": w_text,
                "start": round(start, 2),
                "end": round(start + 0.4, 2)  # Mute audio (volume=0) for 0.4s
            })
    return flagged

def build_audio_mute_filter(flagged_words: List[Dict]) -> str:
    """
    Builds FFmpeg volume mute filter string for flagged profanities.
    e.g. volume=enable='between(t,1.2,1.6)+between(t,5.0,5.4)':volume=0
    """
    if not flagged_words:
        return ""
    conditions = [f"between(t,{item['start']},{item['end']})" for item in flagged_words]
    combined = "+".join(conditions)
    return f"volume=enable='{combined}':volume=0"

def sanitize_filename(name: str, min_len: int = 40, max_len: int = 55) -> str:
    r"""
    Sanitizes string into viral US/UK title format safe for Windows file paths.
    Strips illegal Windows chars: \ / : * ? " < > |
    """
    # Remove illegal chars
    clean = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    # Replace multiple spaces with single space
    clean = re.sub(r"\s+", " ", clean)
    if len(clean) > max_len:
        # Trim at last word boundary
        trimmed = clean[:max_len]
        if " " in trimmed:
            clean = trimmed.rsplit(" ", 1)[0]
        else:
            clean = trimmed
    return clean or "Viral_GTA6_Moment"
