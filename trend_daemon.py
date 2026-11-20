"""
24/7 Autonomous Trend Daemon for Zelmu Clipping.
Continuously polls:
https://trends.google.com/trending?geo=US&status=active&hours=4&sort=recency
When a new breakout trend is detected, automatically triggers:
1 Trend -> 6+ Reels (9:16) + 2+ Landscape Videos (16:9) -> YouTube Studio auto-scheduling.
"""

import os
import sys
import time
import json
import threading
from pathlib import Path
from typing import Dict, Any, List

from trends_hunter import fetch_google_trends_us
from trend_producer import produce_trend_package
from editor import check_internet_connection

CONFIG_FILE = Path("trend_daemon_config.json")
STATE_FILE = Path("trend_daemon_state.json")
PROGRESS_FILE = Path("trend_daemon_progress.json")
LOG_FILE = Path("trend_daemon_events.log")

DEFAULT_CONFIG = {
    "enabled": False,
    "geo": "US",
    "hours": 4,
    "sort": "recency",
    "min_search_vol": 1000,
    "check_interval_minutes": 15,
    "auto_upload": True,
    "topic_filter": ""
}

_DAEMON_THREAD = None
_STOP_EVENT = threading.Event()


def load_daemon_config() -> Dict[str, Any]:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                res = DEFAULT_CONFIG.copy()
                res.update(cfg)
                return res
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_daemon_config(cfg: Dict[str, Any]):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def load_daemon_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"processed_trends": [], "last_check_ts": 0, "total_produced": 0}


def save_daemon_state(state: Dict[str, Any]):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def push_daemon_log(msg: str):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_daemon_logs(max_lines: int = 50) -> List[str]:
    if not LOG_FILE.exists():
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
            return lines[-max_lines:]
    except Exception:
        return []


def set_daemon_progress(
    active: bool,
    current_trend: str = "",
    stage: int = 0,
    total_stages: int = 5,
    stage_name: str = "Idle",
    step_detail: str = "Monitoring Google Trends...",
    next_step: str = "Polling next breakout",
    percent: int = 0,
    shorts_done: int = 0,
    videos_done: int = 0
):
    data = {
        "active": active,
        "current_trend": current_trend,
        "stage": stage,
        "total_stages": total_stages,
        "stage_name": stage_name,
        "step_detail": step_detail,
        "next_step": next_step,
        "percent": percent,
        "shorts_done": shorts_done,
        "videos_done": videos_done,
        "updated_at": time.time()
    }
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def get_daemon_progress() -> Dict[str, Any]:
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "active": False,
        "current_trend": "",
        "stage": 0,
        "total_stages": 5,
        "stage_name": "Idle",
        "step_detail": "Daemon not started",
        "next_step": "Waiting for start",
        "percent": 0,
        "shorts_done": 0,
        "videos_done": 0
    }


def daemon_loop():
    push_daemon_log("🚀 24/7 Autonomous Google Trends Daemon initialized.")
    while not _STOP_EVENT.is_set():
        cfg = load_daemon_config()
        if not cfg.get("enabled", False):
            set_daemon_progress(active=False, stage_name="Stopped", step_detail="Daemon disabled in configuration")
            time.sleep(3)
            continue

        if not check_internet_connection():
            push_daemon_log("⚠️ Internet connection dropped. Waiting 10s...")
            time.sleep(10)
            continue

        geo = cfg.get("geo", "US")
        hours = cfg.get("hours", 4)
        sort = cfg.get("sort", "recency")
        min_vol = cfg.get("min_search_vol", 1000)
        auto_up = cfg.get("auto_upload", True)

        state = load_daemon_state()
        processed = set(state.get("processed_trends", []))

        push_daemon_log(f"🔎 Scanning Google Trends (geo={geo}, hours={hours}, sort={sort})...")
        set_daemon_progress(
            active=True,
            stage=1,
            total_stages=5,
            stage_name="Scanning Trends",
            step_detail=f"Querying Google Trends (Past {hours}h, {geo}, {sort})...",
            next_step="Evaluating breakout velocity",
            percent=15
        )

        trends = fetch_google_trends_us(geo=geo, hours=hours, sort=sort)
        target_trend = None

        for t in trends:
            q = t.get("query", "").strip()
            vol = t.get("search_vol", 0)
            if q and q not in processed and vol >= min_vol:
                target_trend = t
                break

        if target_trend:
            t_query = target_trend["query"]
            t_vol = target_trend.get("search_vol_fmt", "High")
            t_growth = target_trend.get("growth_pct", "")
            push_daemon_log(f"🔥 NEW BREAKOUT DETECTED: '{t_query}' ({t_vol} {t_growth})")

            set_daemon_progress(
                active=True,
                current_trend=t_query,
                stage=2,
                total_stages=5,
                stage_name="Producing 8 Assets",
                step_detail=f"Producing 6 Reels + 2 Landscape Videos for '{t_query}'...",
                next_step="Studio Monetization Scheduling",
                percent=40
            )

            try:
                res = produce_trend_package(
                    target_trend,
                    auto_upload=auto_up,
                    progress_callback=lambda m: push_daemon_log(f"[{t_query}] {m}")
                )

                # Record in state
                processed.add(t_query)
                state["processed_trends"] = list(processed)[-100:]  # keep last 100
                state["total_produced"] = state.get("total_produced", 0) + res.get("total_rendered", 0)
                state["last_check_ts"] = time.time()
                save_daemon_state(state)

                push_daemon_log(f"✅ SUCCESSFULLY COMPLETED '{t_query}': 6 Reels + 2 Videos published to Studio.")
                set_daemon_progress(
                    active=True,
                    current_trend=t_query,
                    stage=5,
                    total_stages=5,
                    stage_name="Completed",
                    step_detail=f"Published package for '{t_query}'. Sleeping until next check.",
                    next_step="Next polling cycle",
                    percent=100,
                    shorts_done=6,
                    videos_done=2
                )
            except Exception as e:
                push_daemon_log(f"❌ Error producing package for '{t_query}': {e}")
        else:
            push_daemon_log("✓ No new qualifying breakout trends. Sleeping...")
            set_daemon_progress(
                active=True,
                stage=1,
                total_stages=5,
                stage_name="Sleeping / Idle",
                step_detail=f"Monitoring active. All current trends already processed. Next check in {cfg.get('check_interval_minutes', 15)}m.",
                next_step="Next polling check",
                percent=100
            )

        interval_sec = cfg.get("check_interval_minutes", 15) * 60
        for _ in range(int(interval_sec)):
            if _STOP_EVENT.is_set():
                break
            time.sleep(1)


def start_trend_daemon():
    global _DAEMON_THREAD, _STOP_EVENT
    if _DAEMON_THREAD and _DAEMON_THREAD.is_alive():
        return
    cfg = load_daemon_config()
    cfg["enabled"] = True
    save_daemon_config(cfg)
    _STOP_EVENT.clear()
    _DAEMON_THREAD = threading.Thread(target=daemon_loop, daemon=True)
    _DAEMON_THREAD.start()


def stop_trend_daemon():
    global _STOP_EVENT
    cfg = load_daemon_config()
    cfg["enabled"] = False
    save_daemon_config(cfg)
    _STOP_EVENT.set()
    set_daemon_progress(active=False, stage_name="Stopped", step_detail="Daemon manually stopped by user.")


def is_trend_daemon_running() -> bool:
    global _DAEMON_THREAD
    return _DAEMON_THREAD is not None and _DAEMON_THREAD.is_alive()
