"""
ContentRewards Campaign Hub & Clipping Manager for Zelmu Flywheel.
Enables campaign-driven clipping based on:
- Campaign Brief & Description
- Target Audience & Target Country Geo
- CPM Payout Rate ($ / 1k views) & Revenue Goal ($)
- Mandatory Hashtags & Sponsor Links
- Flexible Source Footage (YouTube VOD, Channel, or Local MP4)
- Live Realized Earnings & 1-Click Submission Tracker
"""

import os
import sys
import json
import time
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from analyzer import query_ollama_json
from safety import is_cricket_or_broadcast_sports
from arbiter import push_unified_log

CAMPAIGNS_DB_FILE = Path("campaigns_db.json")
UPLOAD_HISTORY_FILE = Path("upload_history.json")


def load_campaigns_db() -> Dict[str, Any]:
    """Loads campaigns database from disk."""
    if CAMPAIGNS_DB_FILE.exists():
        try:
            with open(CAMPAIGNS_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "active_campaign_id": "",
        "campaigns": {}
    }


def save_campaigns_db(data: Dict[str, Any]):
    """Persists campaigns database to disk."""
    try:
        with open(CAMPAIGNS_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving campaigns db: {e}")


def get_active_campaign() -> Optional[Dict[str, Any]]:
    """Returns currently selected active campaign dict."""
    db = load_campaigns_db()
    c_id = db.get("active_campaign_id")
    if c_id and c_id in db.get("campaigns", {}):
        return db["campaigns"][c_id]
    # Return first campaign if any exists
    campaigns = db.get("campaigns", {})
    if campaigns:
        first_id = list(campaigns.keys())[0]
        db["active_campaign_id"] = first_id
        save_campaigns_db(db)
        return campaigns[first_id]
    return None


def set_active_campaign(campaign_id: str):
    """Sets active campaign ID."""
    db = load_campaigns_db()
    if campaign_id in db.get("campaigns", {}):
        db["active_campaign_id"] = campaign_id
        save_campaigns_db(db)


def save_campaign(campaign: Dict[str, Any]) -> str:
    """Creates or updates a campaign."""
    db = load_campaigns_db()
    c_id = campaign.get("id")
    if not c_id:
        name_clean = "".join(c if c.isalnum() else "_" for c in campaign.get("name", "Campaign")).strip("_")[:20]
        c_id = f"cmp_{name_clean.lower()}_{int(time.time())}"
        campaign["id"] = c_id

    # Compute target views goal if CPM and revenue goal provided
    cpm = float(campaign.get("cpm_rate", 3.0))
    revenue_goal = float(campaign.get("revenue_goal", 500.0))
    target_views = int((revenue_goal / max(0.1, cpm)) * 1000)
    campaign["target_views"] = target_views
    campaign["updated_at"] = time.time()

    db.setdefault("campaigns", {})[c_id] = campaign
    if not db.get("active_campaign_id"):
        db["active_campaign_id"] = c_id
    save_campaigns_db(db)
    push_unified_log("CAMPAIGN", f"Saved campaign '{campaign.get('name')}' (CPM: ${cpm:.2f}, Goal: ${revenue_goal:.0f})")
    return c_id


def delete_campaign(campaign_id: str):
    """Deletes campaign by ID."""
    db = load_campaigns_db()
    if campaign_id in db.get("campaigns", {}):
        del db["campaigns"][campaign_id]
        if db.get("active_campaign_id") == campaign_id:
            rem = list(db.get("campaigns", {}).keys())
            db["active_campaign_id"] = rem[0] if rem else ""
        save_campaigns_db(db)


def calculate_campaign_roi(campaign_id: str) -> Dict[str, Any]:
    """
    Computes real-time ROI, realized earnings, goal progress, and tracked clips
    from YouTube upload history for a specific campaign.
    """
    db = load_campaigns_db()
    campaign = db.get("campaigns", {}).get(campaign_id)
    if not campaign:
        return {
            "campaign_name": "None",
            "total_clips": 0,
            "total_views": 0,
            "total_likes": 0,
            "realized_earnings": 0.0,
            "revenue_goal": 500.0,
            "goal_progress_pct": 0.0,
            "views_needed": 0,
            "clips": []
        }

    cpm = float(campaign.get("cpm_rate", 3.0))
    goal = float(campaign.get("revenue_goal", 500.0))
    target_views = int((goal / max(0.1, cpm)) * 1000)

    # Scan upload_history.json for clips tagged with this campaign
    history = []
    if UPLOAD_HISTORY_FILE.exists():
        try:
            with open(UPLOAD_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            pass

    campaign_clips = []
    total_views = 0
    total_likes = 0

    c_name_lower = campaign.get("name", "").lower()
    c_tags = [t.lower().strip("#") for t in campaign.get("mandatory_hashtags", "").split() if t.strip()]

    for item in history:
        # Match by explicit campaign_id, source, or campaign hashtags in title/tags
        match = False
        if item.get("campaign_id") == campaign_id:
            match = True
        elif c_name_lower and c_name_lower in item.get("title", "").lower():
            match = True
        elif any(t in " ".join(item.get("tags", [])).lower() for t in c_tags):
            match = True

        if match:
            v_views = int(item.get("last_synced_views", 0))
            v_likes = int(item.get("last_synced_likes", 0))
            total_views += v_views
            total_likes += v_likes
            earned = round((v_views / 1000.0) * cpm, 2)
            campaign_clips.append({
                "video_id": item.get("video_id"),
                "title": item.get("title", "Clip"),
                "views": v_views,
                "likes": v_likes,
                "earned_usd": earned,
                "publish_at": item.get("publish_at", ""),
                "watch_url": f"https://www.youtube.com/shorts/{item.get('video_id')}"
            })

    realized_earnings = round((total_views / 1000.0) * cpm, 2)
    progress_pct = min(1.0, realized_earnings / max(1.0, goal))
    views_needed = max(0, target_views - total_views)

    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign.get("name", "Campaign"),
        "cpm_rate": cpm,
        "revenue_goal": goal,
        "target_views": target_views,
        "total_clips": len(campaign_clips),
        "total_views": total_views,
        "total_likes": total_likes,
        "realized_earnings": realized_earnings,
        "goal_progress_pct": progress_pct,
        "views_needed": views_needed,
        "clips": campaign_clips
    }


def generate_campaign_scripts(
    campaign: Dict[str, Any],
    source_title: str = "",
    transcript_snippet: str = ""
) -> List[Dict[str, Any]]:
    """
    Dynamically generates 6 high-retention Shorts scripts tailored to:
    - Campaign Brief & Description
    - Target Audience & Target Country
    - Mandatory Hashtags & Sponsor Hook
    """
    c_name = campaign.get("name", "Sponsor Campaign")
    brief = campaign.get("description_brief", "Promote brand via engaging moments")
    audience = campaign.get("target_audience", "Gamers / Tech Enthusiasts")
    country = campaign.get("target_country", "United States (US)")
    hashtags = campaign.get("mandatory_hashtags", "#Shorts")
    sponsor_link = campaign.get("sponsor_link", "")

    prompt = f"""You are an elite YouTube Shorts producer crafting clips for a paid sponsor campaign on ContentRewards.
Campaign Name: "{c_name}"
Campaign Brief: "{brief}"
Target Audience: {audience}
Target Country: {country}
Mandatory Hashtags: {hashtags}
Source Video Title: "{source_title}"
Source Footage Snippet: "{transcript_snippet[:400]}"

Generate 6 viral Shorts scripts (each 40-50 words, target 24-34s duration) that seamlessly integrate the campaign message for the {audience} demographic in {country}.
MANDATORY RULES:
1. Frame 0 Hook: No greetings. Start immediately with curiosity/tension.
2. Seamless Loop: Final sentence must grammatically connect into opening hook.
3. Include organic mention of sponsor context.

Return ONLY JSON:
{{
  "shorts": [
    {{
      "hook": "⚡ SHORT HOOK",
      "title": "High-CTR Title under 65 chars {hashtags}",
      "script": "Spoken script ending with loop bridge...",
      "description": "Engaging description including {sponsor_link} {hashtags}"
    }},
    ... (6 total)
  ]
}}"""

    try:
        res = query_ollama_json(prompt, retries=1, timeout=25)
        if res and isinstance(res, dict) and "shorts" in res and len(res["shorts"]) >= 3:
            return res["shorts"][:6]
    except Exception:
        pass

    # High-CTR Dynamic Fallback
    tag_clean = " ".join(hashtags.split()[:3])
    lead_q = source_title or c_name
    return [
        {
            "hook": f"⚡ UNREAL {c_name.upper()}",
            "title": f"The Crazy Truth About {lead_q[:40]} {tag_clean}"[:70],
            "script": f"Nobody expected this from {c_name}! For everyone following this in {country}, the verified facts prove this changes everything for {audience}, and the craziest part of the whole story is that...",
            "description": f"🔥 {lead_q}\n\nCheck out: {sponsor_link}\n\n{hashtags}"
        },
        {
            "hook": f"🚨 BREAKING {c_name.upper()}",
            "title": f"Stop Scrolling If You Missed This {tag_clean}"[:70],
            "script": f"Stop scrolling if you haven't seen the latest update from {c_name}! The community is buzzing with excitement over these new developments, and the real reason everyone is talking is...",
            "description": f"🚨 Breaking update on {c_name}.\n\nOfficial Link: {sponsor_link}\n\n{hashtags}"
        },
        {
            "hook": f"🤯 3 INSANE DETAILS",
            "title": f"3 Insane Details You Missed {tag_clean}"[:70],
            "script": f"Here are three details about {c_name} you completely missed! Number one: response times doubled this week. Number two: community interest exploded. And number three: the only thing left to ask is...",
            "description": f"🤯 3 details breakdown.\n\nSponsor Link: {sponsor_link}\n\n{hashtags}"
        },
        {
            "hook": f"⚠️ WHY EVERYONE IS TALKING",
            "title": f"Why Everyone Is Searching {c_name} {tag_clean}"[:70],
            "script": f"Why is everyone in {country} suddenly talking about {c_name}? It all started when reports surfaced online and caught {audience} completely by surprise, which explains why...",
            "description": f"⚠️ Full context breakdown.\n\nLink: {sponsor_link}\n\n{hashtags}"
        },
        {
            "hook": f"🔍 DEEP DIVE",
            "title": f"The Secret Behind {c_name} {tag_clean}"[:70],
            "script": f"Here is the secret behind {c_name} nobody is admitting! Verified data proves that interest surged overnight, and if you look closely at the numbers...",
            "description": f"🔍 Deep analysis.\n\nCheck out: {sponsor_link}\n\n{hashtags}"
        },
        {
            "hook": f"🔥 FINAL VERDICT",
            "title": f"This Changes Everything For {audience} {tag_clean}"[:70],
            "script": f"This changes everything for {audience}! The official announcement from {c_name} is finally out, and if you still doubt how big this is...",
            "description": f"🔥 Final verdict on {c_name}.\n\nGet started: {sponsor_link}\n\n{hashtags}"
        }
    ]
