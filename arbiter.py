"""
Resource Arbiter & Compute Lock Manager
Enforces strict mutual exclusion for heavy compute stages (Whisper AI, FFmpeg QSV render, HLS Muxing)
across all background engines to prevent 8GB RAM saturation and GPU session crashes.
Priority: Trend Hunter (P1) > Live Stream Clipper (P2) > Channel Watcher VODs (P3)
"""
import time
import json
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional

STATE_FILE = Path("arbiter_state.json")
LOG_FILE = Path("unified_events.log")

PRIORITY_TREND = 1  # Real-time breakout trends (time-critical)
PRIORITY_LIVE = 2   # Live stream moments
PRIORITY_VOD = 3    # Channel VOD batch archive

_LOCK = threading.RLock()
_COND = threading.Condition(_LOCK)

_CURRENT_HOLDER: Optional[str] = None
_CURRENT_PRIORITY: int = 999
_CURRENT_OP: str = ""
_ACQUIRED_TS: float = 0.0

_WAIT_QUEUE: List[Dict[str, Any]] = []
_SYSTEM_PAUSED: bool = False


def is_system_paused() -> bool:
    global _SYSTEM_PAUSED
    with _LOCK:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    st = json.load(f)
                    _SYSTEM_PAUSED = bool(st.get("paused", False))
            except Exception:
                pass
        return _SYSTEM_PAUSED


def pause_all_daemons():
    global _SYSTEM_PAUSED
    with _LOCK:
        _SYSTEM_PAUSED = True
        _save_state()
        push_unified_log("SYSTEM", "⏸️ MASTER PAUSE: All background daemons instructed to pause.")


def resume_all_daemons():
    global _SYSTEM_PAUSED
    with _LOCK:
        _SYSTEM_PAUSED = False
        _save_state()
        push_unified_log("SYSTEM", "▶️ MASTER RESUME: All background daemons resumed.")


def push_unified_log(engine_tag: str, message: str):
    ts = time.strftime("%H:%M:%S")
    clean_tag = engine_tag.strip().upper()
    line = f"[{ts}] [{clean_tag}] {message}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_unified_logs(max_lines: int = 60) -> List[str]:
    if not LOG_FILE.exists():
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
            return lines[-max_lines:]
    except Exception:
        return []


def acquire_compute_lock(caller_name: str, priority: int, operation: str = "", timeout: float = 600.0) -> bool:
    """
    Acquires the global Compute Lock for heavy operations (Whisper AI, FFmpeg QSV render).
    Blocks if another caller holds the lock, prioritizing higher-priority callers (lower priority int).
    """
    global _CURRENT_HOLDER, _CURRENT_PRIORITY, _CURRENT_OP, _ACQUIRED_TS
    deadline = time.time() + timeout

    with _COND:
        entry = {"caller": caller_name, "priority": priority, "operation": operation, "queued_at": time.time()}
        _WAIT_QUEUE.append(entry)
        _save_state()

        push_unified_log("ARBITER", f"Request lock by '{caller_name}' (P{priority}: {operation}). Queue: {len(_WAIT_QUEUE)}")

        while True:
            # Check master pause
            if is_system_paused():
                push_unified_log("ARBITER", f"'{caller_name}' waiting (System Paused)...")
                time.sleep(1.0)
                if time.time() > deadline:
                    _WAIT_QUEUE[:] = [e for e in _WAIT_QUEUE if e["caller"] != caller_name]
                    _save_state()
                    return False
                continue

            # If lock is free
            if _CURRENT_HOLDER is None:
                # Find highest priority in queue (lowest int)
                highest_p = min(e["priority"] for e in _WAIT_QUEUE)
                if priority == highest_p:
                    _CURRENT_HOLDER = caller_name
                    _CURRENT_PRIORITY = priority
                    _CURRENT_OP = operation
                    _ACQUIRED_TS = time.time()
                    _WAIT_QUEUE[:] = [e for e in _WAIT_QUEUE if e["caller"] != caller_name]
                    _save_state()
                    push_unified_log("ARBITER", f"🔒 Lock GRANTED to '{caller_name}' (P{priority}: {operation}).")
                    return True

            # If lock is held, check if held for > 15 minutes (hung process safeguard)
            if _CURRENT_HOLDER is not None and (time.time() - _ACQUIRED_TS) > 900.0:
                push_unified_log("ARBITER", f"⚠️ Force releasing stale lock held by '{_CURRENT_HOLDER}' (>15m).")
                _CURRENT_HOLDER = None

            rem = deadline - time.time()
            if rem <= 0:
                _WAIT_QUEUE[:] = [e for e in _WAIT_QUEUE if e["caller"] != caller_name]
                _save_state()
                push_unified_log("ARBITER", f"Timeout waiting for lock: '{caller_name}' (P{priority}).")
                return False

            _COND.wait(timeout=min(2.0, max(0.2, rem)))


def release_compute_lock(caller_name: str):
    """Releases the compute lock and signals waiting threads."""
    global _CURRENT_HOLDER, _CURRENT_PRIORITY, _CURRENT_OP, _ACQUIRED_TS
    with _COND:
        if _CURRENT_HOLDER == caller_name:
            elapsed = time.time() - _ACQUIRED_TS
            push_unified_log("ARBITER", f"🔓 Lock RELEASED by '{caller_name}' (held {elapsed:.1f}s).")
            _CURRENT_HOLDER = None
            _CURRENT_PRIORITY = 999
            _CURRENT_OP = ""
            _save_state()
            _COND.notify_all()


def should_yield(caller_name: str, priority: int) -> bool:
    """Returns True if a higher-priority task (lower int) is waiting in the queue."""
    with _LOCK:
        if is_system_paused():
            return True
        for e in _WAIT_QUEUE:
            if e["priority"] < priority:
                return True
        return False


def get_arbiter_status() -> Dict[str, Any]:
    with _LOCK:
        return {
            "holder": _CURRENT_HOLDER,
            "priority": _CURRENT_PRIORITY,
            "operation": _CURRENT_OP,
            "held_sec": round(time.time() - _ACQUIRED_TS, 1) if _CURRENT_HOLDER else 0.0,
            "queue_len": len(_WAIT_QUEUE),
            "queue": list(_WAIT_QUEUE),
            "paused": is_system_paused()
        }


def _save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "holder": _CURRENT_HOLDER,
                "priority": _CURRENT_PRIORITY,
                "operation": _CURRENT_OP,
                "held_sec": round(time.time() - _ACQUIRED_TS, 1) if _CURRENT_HOLDER else 0.0,
                "queue_len": len(_WAIT_QUEUE),
                "paused": _SYSTEM_PAUSED,
                "updated_at": time.time()
            }, f, indent=2)
    except Exception:
        pass
