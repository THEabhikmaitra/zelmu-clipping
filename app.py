import os
import sys
import re
import gc
import time
import json
import shutil
import hashlib
import datetime
import threading
import concurrent.futures
from pathlib import Path

# Anti-Crash: Ensure local bin (ffmpeg) and venv/Scripts (yt-dlp) are always in PATH
_base_dir = Path(__file__).resolve().parent
for _p in [_base_dir / "bin", _base_dir / "venv" / "Scripts"]:
    if _p.exists() and str(_p) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(_p) + os.pathsep + os.environ.get("PATH", "")

import streamlit as st
from streamlit.runtime.scriptrunner import StopException, RerunException

def format_elapsed(seconds: float) -> str:
    """Formats seconds into HH:MM:SS."""
    sec = max(0, int(seconds))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

import importlib
for _mod_name in ["transcriber", "editor", "analyzer", "safety", "uploader"]:
    if _mod_name in sys.modules:
        importlib.reload(sys.modules[_mod_name])

from safety import sanitize_filename, find_profanities_in_words
from transcriber import (
    get_ffmpeg_path,
    extract_audio_wav,
    transcribe_audio_whisper,
    get_video_metadata,
    fetch_youtube_captions,
    expand_source_urls
)
from analyzer import extract_candidates_full, calculate_audio_spikes, OLLAMA_API_URL, MODEL_NAME
from editor import (
    generate_karaoke_ass,
    get_direct_stream_urls,
    download_video_section,
    generate_piper_tts,
    render_mode_a_short,
    render_mode_b_short,
    check_internet_connection
)
from trends_hunter import (
    fetch_google_trends_us,
    fetch_youtube_search_breakouts,
    scan_youtube_live_breakout_trends,
    search_trend_source_videos,
    get_trend_news_articles,
    get_trend_video_coverage,
    check_trend_coverage,
    CATEGORIES
)
from trend_daemon import (
    start_trend_daemon,
    stop_trend_daemon,
    is_trend_daemon_running,
    load_daemon_config,
    save_daemon_config,
    get_daemon_progress,
    set_daemon_progress,
    get_daemon_logs,
    push_daemon_log
)
from trend_producer import produce_trend_package
from instagram_scraper import (
    scan_and_calculate_account_reels,
    start_or_resume_crawler,
    pause_crawler,
    reset_crawler,
    load_crawler_state,
    save_crawler_state,
    is_crawler_active,
    get_insta_logs,
    save_session_cookie,
    get_session_cookie
)
from campaigns_manager import (
    load_campaigns_db,
    save_campaign,
    delete_campaign,
    get_active_campaign,
    set_active_campaign,
    calculate_campaign_roi,
    generate_campaign_scripts,
    fetch_contentrewards_campaigns,
    import_contentrewards_campaign
)
from uploader import (
    upload_batch_private,
    upload_single_clip_direct,
    get_authenticated_service,
    is_authenticated,
    get_channel_info,
    get_channel_analytics,
    get_auth_url,
    get_auth_url_for_slot,
    exchange_code_for_token,
    run_local_server_auth,
    revoke_token,
    get_available_token_files,
    list_account_slots,
    add_account_slot,
    authenticate_account_slot,
    test_account_slot,
    delete_account_slot,
    reset_exhausted_slots,
    CLIENT_SECRETS_FILE,
    TOKEN_FILE,
    TOKENS_DIR,
    LOG_FILE,
    READY_DIR
)
from watcher import (
    load_watcher_config,
    save_watcher_config,
    is_watcher_running,
    start_watcher_daemon,
    stop_watcher_daemon,
    get_watcher_logs,
    get_watcher_progress
)
from livestream_buffer import (
    load_livestream_config,
    save_livestream_config,
    is_livestream_running,
    start_livestream_daemon,
    stop_livestream_daemon,
    get_livestream_logs,
    get_livestream_progress,
    check_if_stream_live
)
from arbiter import (
    pause_all_daemons,
    resume_all_daemons,
    is_system_paused,
    get_arbiter_status,
    get_unified_logs
)
from learning_engine import (
    load_learning_db,
    save_learning_db,
    load_upload_history,
    record_uploaded_video,
    sync_youtube_performance,
    get_learned_seo_boost,
    audit_quality_and_seo,
    quick_fix_seo,
    cleanup_stale_workspaces
)
from portal_stages import (
    render_pipeline_ribbon,
    render_quality_seo_stage,
    render_analytics_stage,
    render_learning_stage,
    save_sidecar_data,
    render_module_purge_matrix
)

# Ensure base directories exist
WORKSPACE_DIR = Path("workspace")
READY_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

# Page configuration
st.set_page_config(
    page_title="Zelmu Clipping",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Unslop: Linear / Vercel-inspired Minimalist Dark Design System
st.markdown("""
<style>
    /* Complete suppression of Streamlit sidebar */
    [data-testid="stSidebar"],
    [data-testid="stSidebarCollapsed"],
    [data-testid="stExpandSidebarButton"],
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapseButton"] {
        display: none !important;
        visibility: hidden !important;
        width: 0px !important;
        height: 0px !important;
        pointer-events: none !important;
    }

    /* Header container: transparent, zero height */
    header[data-testid="stHeader"] {
        background: transparent !important;
        height: 0px !important;
        pointer-events: none !important;
        z-index: 1002 !important;
    }

    /* Complete suppression of deploy button, toolbar, decorations, footer */
    [data-testid="stToolbar"],
    [data-testid="stDeployButton"],
    #MainMenu,
    [data-testid="stMainMenu"],
    div[data-testid="stStatusWidget"],
    div[data-testid="stDecoration"],
    footer,
    .stDeployButton,
    button[title="View fullscreen"] {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        width: 0 !important;
        pointer-events: none !important;
    }

    /* Fixed Top Navbar across entire viewport */
    .zelmu-navbar {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        height: 48px;
        z-index: 1000;
        background: #09090b;
        border-bottom: 1px solid #27272a;
        padding: 0 1.25rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        box-sizing: border-box;
        pointer-events: none;
    }
    .zelmu-brand {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        pointer-events: auto;
    }
    .navbar-status-group {
        display: flex;
        align-items: center;
        gap: 0.85rem;
        margin-right: 48px; /* Room for gear icon */
        pointer-events: auto;
    }

    /* Instant Top Tabs (beside ZELMU logo in fixed top navbar) */
    div[data-testid="stTabs"]:first-child > [role="tablist"],
    div[data-testid="stTabs"] [role="tablist"] {
        position: fixed !important;
        top: 8px !important;
        left: 170px !important;
        z-index: 1006 !important;
        pointer-events: auto !important;
        background: #121215 !important;
        border: 1px solid #27272a !important;
        border-radius: 6px !important;
        padding: 2px !important;
        gap: 2px !important;
        height: 32px !important;
        box-sizing: border-box !important;
        display: inline-flex !important;
        flex-direction: row !important;
        align-items: center !important;
        width: auto !important;
        border-bottom: 1px solid #27272a !important;
    }
    div[data-testid="stTabs"] [role="tab"] {
        height: 26px !important;
        padding: 0 8px !important;
        font-size: 0.72rem !important;
        font-weight: 500 !important;
        color: #71717a !important;
        border: none !important;
        border-radius: 4px !important;
        background: transparent !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        cursor: pointer !important;
        transition: all 0.15s ease !important;
        outline: none !important;
        box-shadow: none !important;
        white-space: nowrap !important;
    }
    div[data-testid="stTabs"] [role="tab"]:hover {
        color: #f4f4f5 !important;
    }
    div[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
        background: #27272a !important;
        color: #f4f4f5 !important;
        font-weight: 600 !important;
    }
    div[data-testid="stTabs"] [data-baseweb="tab-border"],
    div[data-testid="stTabs"] [data-baseweb="tab-highlight"],
    div[data-testid="stTabs"] .react-aria-SelectionIndicator,
    div[data-testid="stTabs"] [role="tablist"] div[role="presentation"] {
        display: none !important;
    }

    /* Nested Sub-Tabs inside content stay in natural flow */
    div[data-testid="stTabs"] div[data-testid="stTabs"] [role="tablist"] {
        position: static !important;
        top: auto !important;
        left: auto !important;
        z-index: 10 !important;
        width: 100% !important;
        margin: 4px 0 12px 0 !important;
        background: #18181b !important;
        border: 1px solid #27272a !important;
        border-radius: 6px !important;
        height: 28px !important;
        display: flex !important;
    }
    div[data-testid="stTabs"] div[data-testid="stTabs"] [role="tab"] {
        height: 22px !important;
        padding: 0 10px !important;
        font-size: 0.70rem !important;
    }

    /* Top Nav Gear Settings Popover (Strictly 32x32px at top-right) */
    .stElementContainer:has(div[data-testid="stPopover"]) {
        position: fixed !important;
        top: 8px !important;
        right: 14px !important;
        width: 32px !important;
        height: 32px !important;
        z-index: 1007 !important;
        margin: 0 !important;
        padding: 0 !important;
        pointer-events: auto !important;
    }
    div[data-testid="stPopover"] {
        position: fixed !important;
        top: 8px !important;
        right: 14px !important;
        width: 32px !important;
        height: 32px !important;
        min-width: 32px !important;
        max-width: 32px !important;
        z-index: 1007 !important;
        margin: 0 !important;
        padding: 0 !important;
        pointer-events: auto !important;
    }
    div[data-testid="stPopover"] > button {
        background: #121215 !important;
        border: 1px solid #27272a !important;
        border-radius: 6px !important;
        color: #a1a1aa !important;
        width: 32px !important;
        height: 32px !important;
        min-width: 32px !important;
        max-width: 32px !important;
        padding: 0 !important;
        margin: 0 !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        font-size: 0.95rem !important;
    }
    div[data-testid="stPopover"] > button:hover {
        color: #f4f4f5 !important;
        border-color: #3f3f46 !important;
        background: #18181b !important;
    }
    div[data-testid="stPopover"] > button svg {
        display: none !important;
    }
    div[data-testid="stPopoverBody"] {
        background: #121215 !important;
        border: 1px solid #27272a !important;
        border-radius: 8px !important;
        box-shadow: 0 10px 25px rgba(0,0,0,0.5) !important;
        padding: 1rem !important;
        min-width: 440px !important;
        max-width: 520px !important;
    }

    /* YouTube Top Laser Loader */
    @keyframes yt-laser-anim {
        0% { left: 0%; width: 0%; }
        35% { left: 20%; width: 45%; }
        70% { left: 60%; width: 40%; }
        100% { left: 100%; width: 0%; }
    }
    .yt-laser-bar {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: rgba(239, 68, 68, 0.15);
        z-index: 9999;
        overflow: hidden;
    }
    .yt-laser-beam {
        position: absolute;
        top: 0;
        height: 100%;
        background: linear-gradient(90deg, transparent, #ef4444, #f87171, #ffffff, #ef4444, transparent);
        box-shadow: 0 0 10px #ef4444, 0 0 4px #ffffff;
        animation: yt-laser-anim 1.4s cubic-bezier(0.4, 0, 0.2, 1) infinite;
    }

    /* Labor Illusion Glass Card */
    .labor-card {
        background: #101014;
        border: 1px solid #27272a;
        border-radius: 8px;
        padding: 1.1rem 1.25rem;
        margin-bottom: 1rem;
        box-shadow: 0 4px 16px rgba(0,0,0,0.3);
    }
    .labor-top-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 0.65rem;
    }
    .labor-stage-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
        font-size: 0.76rem;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: #f4f4f5;
    }
    .labor-pulse-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #ef4444;
        box-shadow: 0 0 8px #ef4444;
        animation: pulse-ring 1.2s infinite ease-in-out;
    }
    @keyframes pulse-ring {
        0% { transform: scale(0.9); opacity: 0.7; }
        50% { transform: scale(1.2); opacity: 1; }
        100% { transform: scale(0.9); opacity: 0.7; }
    }
    .labor-pct-num {
        font-family: ui-monospace, monospace;
        font-size: 1.1rem;
        font-weight: 700;
        color: #f4f4f5;
        letter-spacing: -0.02em;
    }
    .labor-track {
        height: 6px;
        background: #18181b;
        border-radius: 9999px;
        overflow: hidden;
        margin-bottom: 0.85rem;
        position: relative;
    }
    .labor-fill {
        height: 100%;
        background: linear-gradient(90deg, #3b82f6 0%, #60a5fa 50%, #93c5fd 100%);
        border-radius: 9999px;
        transition: width 0.3s ease;
        position: relative;
        overflow: hidden;
    }
    .labor-shimmer {
        position: absolute;
        top: 0;
        left: -100%;
        width: 100%;
        height: 100%;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.6), transparent);
        animation: labor-shimmer-anim 1.5s infinite;
    }
    @keyframes labor-shimmer-anim {
        0% { left: -100%; }
        100% { left: 150%; }
    }
    .labor-data-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 0.75rem;
        border-top: 1px solid #1c1c21;
        padding-top: 0.65rem;
    }
    .labor-data-cell {
        display: flex;
        flex-direction: column;
    }
    .labor-label {
        font-size: 0.65rem;
        font-weight: 600;
        color: #71717a;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .labor-val {
        font-family: ui-monospace, monospace;
        font-size: 0.78rem;
        font-weight: 600;
        color: #e4e4e7;
        margin-top: 2px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    /* Base Layout & Spacing */
    .block-container {
        padding-top: 64px !important;
        padding-bottom: 2rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        max-width: 1440px !important;
    }
    .zelmu-brand {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .brand-title {
        font-size: 0.95rem;
        font-weight: 700;
        color: #f4f4f5;
        letter-spacing: -0.02em;
    }
    .brand-badge {
        font-size: 0.65rem;
        font-weight: 600;
        color: #71717a;
        background: #18181b;
        border: 1px solid #27272a;
        padding: 0.15rem 0.45rem;
        border-radius: 4px;
        letter-spacing: 0.04em;
    }
    .navbar-status-group {
        display: flex;
        align-items: center;
        gap: 0.85rem;
        margin-right: 52px;
    }
    .status-item {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        font-size: 0.72rem;
        font-weight: 500;
        color: #a1a1aa;
    }
    .dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        display: inline-block;
    }
    .dot-ok { background: #22c55e; }
    .dot-warn { background: #eab308; }
    .dot-err { background: #ef4444; }

    /* Ultra-Compact High-Density Typography Scale */
    html, body, [class*="css"], .stMarkdown, p, div, span, label {
        font-size: 0.78rem !important;
        line-height: 1.4 !important;
    }

    /* Streamlit Native Headers Scale */
    h1 { font-size: 1.10rem !important; font-weight: 700 !important; margin-bottom: 0.4rem !important; }
    h2 { font-size: 0.95rem !important; font-weight: 700 !important; margin-bottom: 0.35rem !important; }
    h3 { font-size: 0.85rem !important; font-weight: 600 !important; margin-bottom: 0.3rem !important; }
    h4, h5, h6 { font-size: 0.78rem !important; font-weight: 600 !important; }

    /* Compact Metrics Scale */
    div[data-testid="stMetricValue"] {
        font-size: 1.05rem !important;
        font-weight: 700 !important;
        font-family: ui-monospace, SFMono-Regular, monospace !important;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.64rem !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.05em !important;
        color: #71717a !important;
    }
    div[data-testid="stMetricDelta"] {
        font-size: 0.64rem !important;
    }

    /* Clean Form Elements (Compact) */
    .stTextArea textarea, .stTextInput input, .stSelectbox [data-baseweb="select"] {
        background-color: #121215 !important;
        border: 1px solid #27272a !important;
        border-radius: 6px !important;
        color: #f4f4f5 !important;
        font-size: 0.78rem !important;
        padding: 4px 8px !important;
    }
    .stSelectbox div[role="listbox"] * {
        font-size: 0.76rem !important;
    }
    .stSlider [data-testid="stSliderTickBarMin"],
    .stSlider [data-testid="stSliderTickBarMax"],
    .stSlider [data-testid="stTickBarValue"] {
        font-size: 0.65rem !important;
    }

    /* Compact Action Buttons */
    .stButton > button {
        font-size: 0.76rem !important;
        padding: 2px 10px !important;
        border-radius: 5px !important;
    }
    .stButton > button[kind="primary"] {
        background-color: #f4f4f5 !important;
        color: #09090b !important;
        font-weight: 600 !important;
        border: 1px solid #f4f4f5 !important;
        font-size: 0.76rem !important;
        transition: opacity 0.15s ease;
    }
    .stButton > button[kind="primary"]:hover {
        opacity: 0.9;
    }
    .stButton > button[kind="secondary"] {
        background-color: #121215 !important;
        color: #a1a1aa !important;
        border: 1px solid #27272a !important;
        font-size: 0.74rem !important;
    }
    .stButton > button[kind="secondary"]:hover {
        border-color: #3f3f46 !important;
        color: #f4f4f5 !important;
    }

    /* Terminal Console */
    div[data-testid="stCode"] {
        background-color: #0c0c0e !important;
        border: 1px solid #27272a !important;
        border-radius: 6px !important;
        position: relative !important;
    }
    div[data-testid="stCode"] pre {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace !important;
        font-size: 10.5px !important;
        line-height: 1.35 !important;
        color: #a1a1aa !important;
        max-height: 300px !important;
        overflow-y: auto !important;
    }
    div[data-testid="stCode"] button[title="Copy to clipboard"],
    div[data-testid="stCode"] [data-testid="stCodeCopyButton"] {
        display: flex !important;
        visibility: visible !important;
        opacity: 0.85 !important;
        background: #18181b !important;
        border: 1px solid #27272a !important;
        border-radius: 4px !important;
        color: #f4f4f5 !important;
        font-size: 0.65rem !important;
    }
    div[data-testid="stCode"] button[title="Copy to clipboard"]:hover,
    div[data-testid="stCode"] [data-testid="stCodeCopyButton"]:hover {
        opacity: 1 !important;
        background: #27272a !important;
        border-color: #3f3f46 !important;
    }

    /* Section Titles & Badges */
    .section-title {
        font-size: 0.66rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.06em !important;
        color: #71717a !important;
        margin-top: 0.95rem !important;
        margin-bottom: 0.35rem !important;
        text-transform: uppercase !important;
    }
    .sidebar-header {
        font-size: 0.64rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.06em !important;
        color: #71717a !important;
        text-transform: uppercase !important;
        margin-bottom: 0.35rem !important;
    }
    .stCaption, small {
        font-size: 0.70rem !important;
        color: #71717a !important;
    }
    div[data-testid="stExpander"] details summary span {
        font-size: 0.76rem !important;
        font-weight: 600 !important;
    }
</style>
""", unsafe_allow_html=True)

def get_video_id(url: str) -> str:
    """Generates a clean filesystem-safe video identifier from URL."""
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})(?:\?|&|\/|$)", url)
    if match:
        return match.group(1)
    # Fallback to MD5 hash for arbitrary Twitch/other URLs
    return hashlib.md5(url.strip().encode("utf-8")).hexdigest()[:12]

def check_system_diagnostics():
    """Verifies all external dependencies and binaries."""
    diag = {}
    
    # 1. FFmpeg
    ffmpeg_bin = get_ffmpeg_path()
    diag["ffmpeg"] = bool(ffmpeg_bin)
    diag["ffmpeg_path"] = str(ffmpeg_bin) if ffmpeg_bin else "Missing (Check C:\\clipping\\bin)"

    # 2. yt-dlp
    diag["yt_dlp"] = bool(shutil.which("yt-dlp") or Path("venv/Scripts/yt-dlp.exe").exists())

    # 3. Piper Voice Model
    voice_file = Path("en_US-ryan-high.onnx")
    diag["piper_voice"] = voice_file.exists() and voice_file.stat().st_size > 50000000

    # 4. Ollama & qwen2.5:3b
    ollama_ok = False
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        if r.status_code == 200:
            models = [m.get("name") for m in r.json().get("models", [])]
            if any("qwen2.5:3b" in m for m in models):
                ollama_ok = True
    except Exception:
        ollama_ok = False
    diag["ollama"] = ollama_ok

    # 5. YouTube API Secrets & Token
    diag["client_secrets"] = CLIENT_SECRETS_FILE.exists()
    diag["yt_auth"] = is_authenticated()

    return diag

# Top Sticky Navbar Diagnostics & Brand
diag = check_system_diagnostics()

ffmpeg_status = '<span class="dot dot-ok"></span> FFmpeg' if diag['ffmpeg'] else '<span class="dot dot-err"></span> FFmpeg'
ytdlp_status = '<span class="dot dot-ok"></span> yt-dlp' if diag['yt_dlp'] else '<span class="dot dot-err"></span> yt-dlp'
ollama_status = '<span class="dot dot-ok"></span> Ollama' if diag['ollama'] else '<span class="dot dot-warn"></span> Ollama'
if diag['yt_auth']:
    yt_auth_status = '<span class="dot dot-ok"></span> YouTube'
elif diag['client_secrets']:
    yt_auth_status = '<span class="dot dot-warn"></span> YouTube (Unlinked)'
else:
    yt_auth_status = '<span class="dot dot-err"></span> YouTube (No Secrets)'

st.markdown(f"""
<div class="zelmu-navbar">
    <div class="zelmu-brand">
        <span class="brand-title">ZELMU</span>
        <span class="brand-badge">CLIPPING</span>
    </div>
    <div class="navbar-status-group">
        <span class="status-item">{ffmpeg_status}</span>
        <span class="status-item">{ytdlp_status}</span>
        <span class="status-item">{ollama_status}</span>
        <span class="status-item">{yt_auth_status}</span>
    </div>
</div>
""", unsafe_allow_html=True)

# Watermark & Maintenance Popover (Triggered by ⚙️ Icon in Top Fixed Nav)
from editor import get_watermark_config, save_watermark_config, get_active_watermark_overlay

active_logo_path = Path("logo.png") if Path("logo.png").exists() else None

with st.popover("⚙️", help="Settings & Module Maintenance"):
    pop_tab1, pop_tab2 = st.tabs(["🎨 Watermark", "🗑️ Purge Modules & Videos"])
    with pop_tab1:
        st.markdown("<div class='section-title'>GLOBAL WATERMARK & LOGO OVERLAY</div>", unsafe_allow_html=True)
        wm_cfg = get_watermark_config()
        logo_exists = Path("logo.png").exists()

        # 1. Master Optional Toggle
        wm_master_enabled = st.toggle(
            "Enable Logo Watermark for All Video Pipelines",
            value=wm_cfg.get("enabled", True) if logo_exists else False,
            disabled=not logo_exists,
            help="Toggles logo overlay across Instagram Clipper, Trend Factory, VOD Watcher, and Live Buffer.",
            key="wm_master_toggle_gear"
        )
        if logo_exists and wm_master_enabled != wm_cfg.get("enabled", True):
            wm_cfg["enabled"] = wm_master_enabled
            save_watermark_config(wm_cfg)
            st.rerun()

        # 2. Upload / Replace Logo File
        logo_uploader_label = "Replace Watermark (PNG/JPG)" if logo_exists else "Upload Watermark (PNG/JPG)"
        logo_file = st.file_uploader(logo_uploader_label, type=["png", "jpg", "jpeg"], key="wm_uploader_gear")
        if logo_file is not None:
            active_logo_path = Path("logo.png")
            with open(active_logo_path, "wb") as f:
                f.write(logo_file.read())
            wm_cfg["logo_path"] = "logo.png"
            wm_cfg["enabled"] = True
            save_watermark_config(wm_cfg)
            st.success("Logo saved and enabled!")
            st.rerun()

        if logo_exists:
            if wm_master_enabled:
                # 3. Position Preset
                pos_map = {
                    "Top-Right (Default Safe Zone)": "top-right",
                    "Top-Left": "top-left",
                    "Bottom-Right": "bottom-right",
                    "Bottom-Left": "bottom-left",
                    "Top-Center": "top-center",
                    "Bottom-Center": "bottom-center",
                    "Center": "center"
                }
                cur_pos_key = wm_cfg.get("position", "top-right")
                labels = list(pos_map.keys())
                vals = list(pos_map.values())
                cur_idx = vals.index(cur_pos_key) if cur_pos_key in vals else 0
                chosen_pos_label = st.selectbox("Position on Video", labels, index=cur_idx, key="wm_pos_gear")
                chosen_pos = pos_map[chosen_pos_label]

                # 4. Size & Opacity
                w_col1, w_col2 = st.columns(2)
                with w_col1:
                    chosen_size = st.slider("Logo Size (Width px)", 50, 350, int(wm_cfg.get("size_px", 150)), step=10, key="wm_size_gear")
                with w_col2:
                    chosen_opacity = st.slider("Opacity (%)", 10, 100, int(wm_cfg.get("opacity", 0.85) * 100), step=5, key="wm_opacity_gear")

                # 5. Advanced Safe Zone Margins
                with st.expander("🛠️ Advanced Margins (Safe Zone Offsets)", expanded=False):
                    m_col1, m_col2 = st.columns(2)
                    with m_col1:
                        chosen_mx = st.number_input("Margin X (px)", 0, 250, int(wm_cfg.get("margin_x", 40)), step=5, key="wm_mx_gear")
                    with m_col2:
                        chosen_my = st.number_input("Margin Y (px)", 0, 500, int(wm_cfg.get("margin_y", 180)), step=10, key="wm_my_gear", help="Keeps logo out of YouTube Shorts top header and bottom captions")

                # Auto-persist when parameters change
                new_opacity_f = round(chosen_opacity / 100.0, 2)
                if (chosen_pos != cur_pos_key or
                    chosen_size != wm_cfg.get("size_px") or
                    new_opacity_f != wm_cfg.get("opacity") or
                    chosen_mx != wm_cfg.get("margin_x") or
                    chosen_my != wm_cfg.get("margin_y")):
                    wm_cfg["position"] = chosen_pos
                    wm_cfg["size_px"] = chosen_size
                    wm_cfg["opacity"] = new_opacity_f
                    wm_cfg["margin_x"] = chosen_mx
                    wm_cfg["margin_y"] = chosen_my
                    save_watermark_config(wm_cfg)
                    st.rerun()

                # 6. Live 9:16 Mock Visual Preview
                import base64
                try:
                    with open("logo.png", "rb") as f:
                        b64_img = base64.b64encode(f.read()).decode("utf-8")
                    img_src = f"data:image/png;base64,{b64_img}"
                    pw, ph = 112, 199  # ~9:16 aspect ratio preview card
                    ratio = pw / 1080.0
                    prev_w = max(14, int(chosen_size * ratio))
                    prev_mx = int(chosen_mx * ratio)
                    prev_my = int(chosen_my * ratio)

                    if chosen_pos == "top-left":
                        p_style = f"top: {prev_my}px; left: {prev_mx}px;"
                    elif chosen_pos == "bottom-right":
                        p_style = f"bottom: {prev_my}px; right: {prev_mx}px;"
                    elif chosen_pos == "bottom-left":
                        p_style = f"bottom: {prev_my}px; left: {prev_mx}px;"
                    elif chosen_pos == "top-center":
                        p_style = f"top: {prev_my}px; left: 50%; transform: translateX(-50%);"
                    elif chosen_pos == "bottom-center":
                        p_style = f"bottom: {prev_my}px; left: 50%; transform: translateX(-50%);"
                    elif chosen_pos == "center":
                        p_style = f"top: 50%; left: 50%; transform: translate(-50%, -50%);"
                    else:  # top-right
                        p_style = f"top: {prev_my}px; right: {prev_mx}px;"

                    st.markdown(f"""
                    <div style="margin: 0.6rem 0; display: flex; flex-direction: column; align-items: center;">
                        <span style="font-size: 0.65rem; color: #71717a; text-transform: uppercase; font-weight: 600; letter-spacing: 0.05em; margin-bottom: 4px;">Live 9:16 Canvas Preview</span>
                        <div style="position: relative; width: {pw}px; height: {ph}px; background: #0c0c0e; border: 1px solid #3f3f46; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 16px rgba(0,0,0,0.6);">
                            <div style="position: absolute; top: 8px; left: 6px; right: 6px; height: 10px; background: rgba(255,255,255,0.06); border-radius: 2px;"></div>
                            <div style="position: absolute; bottom: 12px; left: 6px; right: 6px; height: 14px; background: rgba(255,255,255,0.05); border-radius: 2px;"></div>
                            <img src="{img_src}" style="position: absolute; {p_style} width: {prev_w}px; height: auto; opacity: {new_opacity_f}; pointer-events: none;" />
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                except Exception:
                    pass

            else:
                st.info("Watermark is toggled OFF. Videos will export cleanly without logo overlay.")

            if st.button("Delete Watermark File", type="secondary", use_container_width=True, key="wm_btn_remove_gear"):
                Path("logo.png").unlink(missing_ok=True)
                wm_cfg["enabled"] = False
                save_watermark_config(wm_cfg)
                st.rerun()
        else:
            st.caption("Upload a PNG or JPG to enable branded watermark overlay on all generated Shorts.")

    with pop_tab2:
        render_module_purge_matrix(key_prefix="top_gear_purge")

def render_labor_card(
    placeholder,
    stage_name: str,
    pct: int,
    elapsed_str: str,
    current_subtask: str,
    throughput: str = "Active",
    mem_stat: str = "Healthy"
):
    """Renders high-trust Labor Illusion UI card with real-time stats and YouTube top laser beam."""
    pct_clamped = min(100, max(0, pct))
    html = f"""
    <div class="yt-laser-bar"><div class="yt-laser-beam"></div></div>
    <div class="labor-card">
        <div class="labor-top-row">
            <div class="labor-stage-badge">
                <span class="labor-pulse-dot"></span>
                <span>{stage_name}</span>
            </div>
            <div class="labor-pct-num">{pct_clamped}%</div>
        </div>
        <div class="labor-track">
            <div class="labor-fill" style="width: {pct_clamped}%;">
                <div class="labor-shimmer"></div>
            </div>
        </div>
        <div class="labor-data-grid">
            <div class="labor-data-cell">
                <span class="labor-label">ELAPSED</span>
                <span class="labor-val">{elapsed_str}</span>
            </div>
            <div class="labor-data-cell">
                <span class="labor-label">SUBTASK</span>
                <span class="labor-val">{current_subtask}</span>
            </div>
            <div class="labor-data-cell">
                <span class="labor-label">THROUGHPUT</span>
                <span class="labor-val">{throughput}</span>
            </div>
            <div class="labor-data-cell">
                <span class="labor-label">STATUS</span>
                <span class="labor-val">{mem_stat}</span>
            </div>
        </div>
    </div>
    """
    placeholder.markdown(html, unsafe_allow_html=True)

# Instant Client-Side Tabs (Positioned inside Top Fixed Navbar beside logo)

def render_mission_control():
    # 1. Master System Control Row
    st.markdown("<div class='section-title'>MISSION CONTROL</div>", unsafe_allow_html=True)
    st.caption("Hardware mutex & fleet status.")

    paused = is_system_paused()
    col_p1, col_p2, col_p3 = st.columns([2.5, 1.2, 1.2])
    with col_p1:
        if paused:
            st.error("⏸️ **PAUSED:** Background engines suspended.")
        else:
            st.success("🟢 **ACTIVE:** P1 Trend > P2 Live > P3 VOD.")
    with col_p2:
        if paused:
            if st.button("▶️ RESUME", type="primary", use_container_width=True, key="mc_btn_resume"):
                resume_all_daemons()
                st.rerun()
        else:
            if st.button("⏸️ PAUSE", type="secondary", use_container_width=True, key="mc_btn_pause"):
                pause_all_daemons()
                st.rerun()
    with col_p3:
        if st.button("🔄 Refresh", use_container_width=True, key="mc_btn_refresh"):
            st.rerun()

    st.markdown("---")

    # 2. Engine Control Grid (3 Cards)
    st.markdown("<div class='section-title'>FLEET</div>", unsafe_allow_html=True)
    ec1, ec2, ec3 = st.columns(3, gap="medium")

    # Card 1: Trend Hunter (P1)
    with ec1:
        t_running = is_trend_daemon_running()
        t_prog = get_daemon_progress()
        st.markdown("### 🎯 Trend (P1)")
        st.caption("US news & search spikes.")
        if t_running:
            st.markdown("Status: 🟢 **Running**")
            st.markdown(f"**Stage:** `{t_prog.get('stage_name', 'Active')}`")
            st.markdown(f"**Trend:** *{t_prog.get('current_trend') or 'Scanning'}*")
            if st.button("⏹️ Stop", use_container_width=True, key="mc_stop_trend"):
                stop_trend_daemon()
                st.rerun()
        else:
            st.markdown("Status: ⚪ **Stopped**")
            st.caption("Offline.")
            if st.button("▶️ Start", type="primary", use_container_width=True, key="mc_start_trend"):
                start_trend_daemon()
                st.rerun()

    # Card 2: Live Stream Clipper (P2)
    with ec2:
        l_running = is_livestream_running()
        l_prog = get_livestream_progress()
        st.markdown("### 🔴 Live (P2)")
        st.caption("YouTube livestreams.")
        if l_running:
            st.markdown("Status: 🟢 **Running**")
            st.markdown(f"**Stage:** `{l_prog.get('stage_label', 'Active')}`")
            st.markdown(f"**Stream:** *{l_prog.get('stream_title') or 'Scanning'}*")
            if st.button("⏹️ Stop", use_container_width=True, key="mc_stop_live"):
                stop_livestream_daemon()
                st.rerun()
        else:
            st.markdown("Status: ⚪ **Stopped**")
            st.caption("Offline.")
            if st.button("▶️ Start", type="primary", use_container_width=True, key="mc_start_live"):
                start_livestream_daemon()
                st.rerun()

    # Card 3: Channel Watcher (P3)
    with ec3:
        w_running = is_watcher_running()
        w_prog = get_watcher_progress()
        st.markdown("### 🤖 VOD (P3)")
        st.caption("Channel VOD archives.")
        if w_running:
            st.markdown("Status: 🟢 **Running**")
            st.markdown(f"**Stage:** `{w_prog.get('stage_name', 'Active')}`")
            st.markdown(f"**Video:** *{w_prog.get('video_title') or 'Scanning'}*")
            if st.button("⏹️ Stop", use_container_width=True, key="mc_stop_vod"):
                stop_watcher_daemon()
                st.rerun()
        else:
            st.markdown("Status: ⚪ **Stopped**")
            st.caption("Offline.")
            if st.button("▶️ Start", type="primary", use_container_width=True, key="mc_start_vod"):
                start_watcher_daemon()
                st.rerun()

    st.markdown("---")

    # 3. Two-Column Deck: Live Consolidated Log Stream + Compute Arbiter Lock Status
    col_logs, col_arbiter = st.columns([1.7, 1.0], gap="large")

    with col_arbiter:
        st.markdown("<div class='section-title'>ARBITER</div>", unsafe_allow_html=True)
        @st.fragment(run_every="3s")
        def render_mc_arbiter_deck():
            arb = get_arbiter_status()
            holder = arb.get("holder")
            p_val = arb.get("priority", 999)
            op = arb.get("operation") or "Idle / Ready"
            held = arb.get("held_sec", 0.0)
            q_len = arb.get("queue_len", 0)

            m1, m2 = st.columns(2)
            with m1:
                st.metric("Lock Holder", holder or "None (Free)", delta=f"P{p_val}" if holder else "Free")
            with m2:
                st.metric("Operation", f"{op[:18]}..." if len(op) > 18 else op, delta=f"{held}s held" if holder else None)

            st.markdown(f"**Queue:** `{q_len}` waiting")
            if arb.get("queue"):
                for q_item in arb["queue"]:
                    st.caption(f"⏳ **P{q_item['priority']}**: {q_item['caller']} — *{q_item['operation']}*")
            else:
                st.caption("Queue empty.")

        render_mc_arbiter_deck()

    with col_logs:
        st.markdown("<div class='section-title'>EVENTS</div>", unsafe_allow_html=True)
        @st.fragment(run_every="3s")
        def render_mc_unified_log_box():
            logs = get_unified_logs(max_lines=45)
            if logs:
                st.code("\n".join(logs[-30:]), language="bash")
            else:
                st.caption("No events.")

        render_mc_unified_log_box()


def render_manual_clipper():
    col_l, col_r = st.columns([1.6, 1])

    with col_l:
        st.caption("SOURCE URLS")
        initial_urls = st.session_state.get("manual_source_urls", "")
        url_input = st.text_area(
            "URLs",
            value=initial_urls,
            height=130,
            placeholder="https://www.youtube.com/watch?v=...\nhttps://www.youtube.com/watch?v=...",
            label_visibility="collapsed",
            key="area_manual_source_urls"
        )
        if initial_urls:
            st.caption(f"🔗 Target received from Stage 1 Research")

    with col_r:
        st.caption("MODE & CONFIG")
        mode = st.radio(
            "Mode",
            ["Mode A (Highlight + Karaoke)", "Mode B (Transformative + Voiceover)"],
            label_visibility="collapsed"
        )
        channel_credit = ""
        split_cam = False
        cam_position = "Top-Left"
        caption_style = "GTA Neon (Cyan/Pink)"

        enable_yolox = False
        enable_hook_badge = True
        enable_anti_cid = True
        enable_sfx = True
        enable_phonk = False

        if "Mode A" in mode:
            enable_yolox = st.checkbox("Dynamic Player Tracking (YOLOX-S)", value=True, help="Follows player dynamically across 16:9 frame")
            enable_hook_badge = st.checkbox("🔥 Frame-1 Viral Hook Badge", value=True, help="Burns dynamic curiosity banner into Frame 1 (first 1.2s) to maximize YouTube Shorts swipe-through rate")
            enable_anti_cid = st.checkbox("🛡️ Anti-Content-ID Protection", value=True, help="0.3% dynamic scale/acoustic jitter to prevent duplicate match and protect monetization")
            enable_sfx = st.checkbox("💥 SFX Punch-In Transitions", value=True, help="Injects audio impact/whoosh transitions on hook and key beats")
            st.caption("🛡️ **Copyright Audio Shield:** Background songs permanently disabled to guarantee 100% Green Dollar monetization & zero Content ID claims.")
            enable_phonk = False
            split_cam = st.checkbox("Facecam split (9:16)", value=False)
            if split_cam:
                cam_position = st.selectbox(
                    "Facecam Position",
                    ["Top-Left", "Top-Right", "Bottom-Left", "Bottom-Right"],
                    index=0
                )
            caption_style = st.selectbox(
                "Caption Style",
                ["GTA Neon (Cyan/Pink)", "Gold Karaoke (Yellow/White)", "Clean White"],
                index=0
            )
        else:
            channel_credit = st.text_input("Credit", placeholder="@handle (auto-detected if blank)", label_visibility="collapsed")

        target_reels_count = st.slider(
            "Shorts to Extract per Video",
            min_value=2,
            max_value=12,
            value=4,
            help="Choose how many viral Reels/Shorts to extract from each video"
        )

        scan_window = st.selectbox(
            "Duration Cap",
            [
                "First 15 Minutes (Fast scan)",
                "First 30 Minutes (Balanced)",
                "Full Video (Deep scan)"
            ],
            index=0,
            label_visibility="collapsed"
        )
        max_scan_sec = None
        if "First 15" in scan_window:
            max_scan_sec = 900.0
        elif "First 30" in scan_window:
            max_scan_sec = 1800.0

        from portal_stages import render_watermark_options_expander
        render_watermark_options_expander("manual", "Manual Clipper")

    # Internet Disconnect Pause / Resume Banner
    if st.session_state.get("pipeline_paused"):
        online = check_internet_connection()
        conn_badge = "🟢 Internet Active" if online else "🔴 Offline (Reconnect network)"
        st.markdown(f"""
        <div style="background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.4); border-radius: 8px; padding: 14px; margin: 12px 0;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div style="font-weight: 700; color: #f87171; font-size: 1.05rem;">⏸️ Pipeline Paused: Internet Disconnected</div>
                <div style="font-size: 0.85rem; font-weight: 600; color: {'#4ade80' if online else '#f87171'};">{conn_badge}</div>
            </div>
            <div style="font-size: 0.85rem; color: #cbd5e1; margin-top: 6px;">
                Network connection dropped during video download. All metadata, audio, and transcript checkpoints are safely cached on disk.
            </div>
        </div>
        """, unsafe_allow_html=True)
        col_res1, col_res2 = st.columns([2, 1])
        with col_res1:
            if st.button("🔄 Resume Pipeline (Try Again)", type="primary", use_container_width=True, key="resume_top_btn"):
                st.session_state["pipeline_paused"] = False
                st.session_state["trigger_produce"] = True
                st.rerun()
        with col_res2:
            if st.button("Dismiss / Clear", use_container_width=True, key="clear_pause_top"):
                st.session_state["pipeline_paused"] = False
                st.rerun()

    start_btn = st.button("Produce Shorts", type="primary", use_container_width=True)
    should_run = start_btn or st.session_state.pop("trigger_produce", False)

    if should_run:
        urls = expand_source_urls(url_input)
        if not urls:
            st.warning("Please provide at least one valid video URL or playlist link.")
        else:
            labor_box = st.empty()
            status_box = st.empty()
            detail_box = st.empty()

            full_logs = []
            log_lock = threading.Lock()
            def push_log(msg: str):
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                msg_clean = re.sub(r"\s+", " ", msg.strip())
                with log_lock:
                    full_logs.append(f"[{ts}] {msg_clean}")
                    try:
                        detail_box.code("\n".join(full_logs), language="bash")
                    except Exception:
                        pass

            for url_idx, raw_url in enumerate(urls):
                t_start = time.time()
                try:
                    render_labor_card(
                        labor_box,
                        stage_name="Stage 0/5: Querying Video Metadata",
                        pct=5,
                        elapsed_str=format_elapsed(0),
                        current_subtask=f"Connecting to {raw_url[:30]}...",
                        throughput="Network fetch",
                        mem_stat="Ready"
                    )
                    push_log(f"Extracting video metadata from {raw_url}...")

                    meta = get_video_metadata(raw_url)
                    vid_id = meta.get("id") or get_video_id(raw_url)
                    uploader_name = meta.get("channel") or meta.get("uploader") or "Creator"
                    detected_handle = f"@{uploader_name}" if not uploader_name.startswith("@") else uploader_name
                    active_credit = channel_credit.strip() if channel_credit.strip() else detected_handle
                    is_live = meta.get("is_live", False)
                    was_live = meta.get("was_live", False)
    
                    if is_live:
                        status_box.error(f"HALTED: '{meta.get('title', vid_id)}' is currently live.")
                        push_log("ERROR: Video is currently live stream. Halted.")
                        continue
                    elif was_live:
                        status_box.info("Video is an ended live stream (VOD).")
                        push_log("Video is archived VOD stream.")
    
                    work_dir = WORKSPACE_DIR / vid_id
                    work_dir.mkdir(parents=True, exist_ok=True)
    
                    # Save 00_meta.json
                    meta_json = work_dir / "00_meta.json"
                    with open(meta_json, "w", encoding="utf-8") as f:
                        json.dump(meta, f, indent=2)
                    
                    push_log(f"Channel: {detected_handle} | Video ID: {vid_id}")
    
                    # Checkpoint 01: Instant YouTube Word-Timed Captions (Zero-Audio Fast Path)
                    transcript_json = work_dir / "02_transcript.json"
                    transcript = None
                    if transcript_json.exists() and transcript_json.stat().st_size > 100:
                        push_log("Reusing cached 02_transcript.json")
                        with open(transcript_json, "r", encoding="utf-8") as f:
                            transcript = json.load(f)
    
                    if not transcript:
                        push_log("Checking for instant YouTube word-timed captions (Fast Path)...")
                        render_labor_card(
                            labor_box,
                            stage_name="Stage 1/5: Word-Timed Captions (⚡ Fast Path)",
                            pct=25,
                            elapsed_str=format_elapsed(time.time() - t_start),
                            current_subtask="Querying YouTube json3 subtitles...",
                            throughput="Direct API fetch",
                            mem_stat="Zero CPU"
                        )
                        transcript = fetch_youtube_captions(raw_url, transcript_json, max_duration_sec=max_scan_sec)
                        if transcript:
                            elapsed_str = format_elapsed(time.time() - t_start)
                            render_labor_card(
                                labor_box,
                                stage_name="Stage 1/5: Word-Timed Captions (⚡ Instant YT)",
                                pct=100,
                                elapsed_str=elapsed_str,
                                current_subtask="YouTube json3 word-level subtitles",
                                throughput="Zero CPU / Instant",
                                mem_stat="Fast Path"
                            )
                            push_log(f"⚡ Instant YouTube word-timed captions parsed ({len(transcript.get('segments', []))} segments). Skipping 15m audio download!")
    
                    # Checkpoint 02: Fallback Audio Extraction + Faster-Whisper (ONLY if YouTube captions were absent)
                    audio_wav = work_dir / "01_audio.wav"
                    if not transcript:
                        push_log("YouTube captions unavailable. Fast extracting audio for Whisper...")
                        def on_audio_extract_progress(line: str):
                            elapsed_s = format_elapsed(time.time() - t_start)
                            dl_pct = 20
                            m = re.search(r"(\d+(?:\.\d+)?)%", line)
                            if m:
                                dl_pct = int(float(m.group(1)))
                            render_labor_card(
                                labor_box,
                                stage_name="Stage 1/5: Audio Extraction",
                                pct=dl_pct,
                                elapsed_str=elapsed_s,
                                current_subtask="yt-dlp stream extraction",
                                throughput="Fast m4a stream",
                                mem_stat="Active"
                            )
                            push_log(line)
    
                        extract_audio_wav(raw_url, audio_wav, max_duration_sec=max_scan_sec, progress_callback=on_audio_extract_progress)
                        push_log(f"Audio extracted successfully: {audio_wav.name}")
    
                        push_log("Initializing Faster-Whisper (int8 CPU)...")
                        def on_whisper_progress(curr, total, snippet):
                            pct = min(100, int((curr / max(1.0, total)) * 100)) if total > 0 else 0
                            elapsed_str = format_elapsed(time.time() - t_start)
                            render_labor_card(
                                labor_box,
                                stage_name="Stage 2/5: Voice Transcription",
                                pct=pct,
                                elapsed_str=elapsed_str,
                                current_subtask=f'"{snippet[:28]}..."' if snippet else "Transcribing...",
                                throughput=f"{format_elapsed(curr)} / {format_elapsed(total)}",
                                mem_stat="int8 CPU"
                            )
                            push_log(f"Whisper: {snippet}")
    
                        transcript = transcribe_audio_whisper(audio_wav, transcript_json, progress_callback=on_whisper_progress)
                        push_log("Transcription complete. Saved to 02_transcript.json")
    
                    # Checkpoint 03: Candidate Analysis (Mode-Isolated Cache)
                    target_mode = "Mode B" if "Mode B" in mode else "Mode A"
                    mode_slug = "mode_b" if target_mode == "Mode B" else "mode_a"
                    candidates_json = work_dir / f"03_candidates_{mode_slug}.json"
                    
                    # Backward-compatibility check for legacy un-suffixed cache
                    analysis = None
                    if not candidates_json.exists():
                        legacy_json = work_dir / "03_candidates.json"
                        if legacy_json.exists():
                            try:
                                with open(legacy_json, "r", encoding="utf-8") as f:
                                    cached_cand = json.load(f)
                                if cached_cand.get("mode") == target_mode:
                                    analysis = cached_cand
                                    with open(candidates_json, "w", encoding="utf-8") as f:
                                        json.dump(analysis, f, indent=2)
                            except Exception:
                                analysis = None

                    if not candidates_json.exists() or analysis is None:
                        render_labor_card(
                            labor_box,
                            stage_name="Stage 3/5: AI Hook & Candidate Analysis",
                            pct=65,
                            elapsed_str=format_elapsed(time.time() - t_start),
                            current_subtask=f"Analyzing {target_mode} candidates...",
                            throughput="Turbo analysis",
                            mem_stat="Active"
                        )
                        push_log(f"Evaluating highlights for {target_mode}...")
                        analysis = extract_candidates_full(
                            transcript,
                            mode=target_mode,
                            channel_name=active_credit,
                            audio_path=audio_wav if audio_wav.exists() else None,
                            target_clips=target_reels_count
                        )
                        with open(candidates_json, "w", encoding="utf-8") as f:
                            json.dump(analysis, f, indent=2)
                        cand_count = len(analysis.get("candidates", [])) if target_mode == "Mode A" else len(analysis.get("clips", []))
                        push_log(f"AI analysis complete. Selected {cand_count} {target_mode} clip(s).")
                    else:
                        push_log(f"Reusing cached 03_candidates_{mode_slug}.json")
    
                    # Checkpoint 04 & Final Render
                    segments_dir = work_dir / "04_segments"
                    segments_dir.mkdir(parents=True, exist_ok=True)
    
                    if target_mode == "Mode A":
                        candidates = analysis.get("candidates", [])
                        style_key = "neon" if "Neon" in caption_style else ("clean" if "Clean" in caption_style else "karaoke")

                        # Prefetch direct stream URLs once for all parallel workers (avoids redundant yt-dlp calls)
                        push_log("Prefetching direct HTTP stream URLs (Zero-Disk pipeline)...")
                        prefetched_stream_urls = get_direct_stream_urls(raw_url)

                        def process_mode_a_candidate(c_idx: int, cand: dict):
                            start_t = cand["start"]
                            end_t = cand["end"]
                            safe_title = cand.get("safe_title", f"GTA6_Moment_{c_idx+1}")
                            dest_stem = f"{safe_title}_{c_idx+1}_{int(start_t)}s" if not safe_title.endswith(f"_{int(start_t)}s") else safe_title
                            final_dest = READY_DIR / f"{dest_stem}.mp4"

                            if final_dest.exists() and final_dest.stat().st_size > 102400:
                                push_log(f"Short '{safe_title}' already exists.")
                                return final_dest

                            raw_seg = segments_dir / f"seg_raw_{c_idx}.mp4"
                            push_log(f"[Parallel Worker #{c_idx+1}] Downloading section ({start_t}s - {end_t}s)...")
                            download_video_section(raw_url, start_t, end_t, raw_seg, stream_urls=prefetched_stream_urls)

                            # Words in this timestamp
                            seg_words = []
                            for s in transcript.get("segments", []):
                                for w in s.get("words", []):
                                    if start_t <= w["start"] <= end_t:
                                        seg_words.append(w)

                            # Generate .ass subtitles with center safe-zone karaoke
                            ass_file = segments_dir / f"subs_{c_idx}.ass"
                            push_log(f"[Parallel Worker #{c_idx+1}] Generating {style_key.upper()} subtitles (.ass)...")
                            generate_karaoke_ass(seg_words, ass_file, clip_start_offset=start_t, style_preset=style_key)

                            # Profanities for audio muting
                            flagged = find_profanities_in_words(seg_words)
                            if flagged:
                                push_log(f"[Parallel Worker #{c_idx+1}] Masking {len(flagged)} profanity timestamp(s).")

                            render_mode_desc = "Intel QSV + dynamic tracking" if enable_yolox else "Intel QSV center crop"
                            push_log(f"[Parallel Worker #{c_idx+1}] Rendering short ({render_mode_desc})...")
                            render_mode_a_short(
                                source_video=raw_seg,
                                ass_subtitles=ass_file,
                                output_short_path=final_dest,
                                flagged_profanities=flagged,
                                split_layout=split_cam,
                                facecam_position=cam_position.lower() if split_cam else "top-left",
                                enable_tracking=enable_yolox,
                                logo_path=active_logo_path,
                                hook_title=cand.get("title", "GTA 6 MOMENT") if enable_hook_badge else None,
                                enable_anti_content_id=enable_anti_cid,
                                enable_music_ducking=enable_phonk,
                                enable_sfx=enable_sfx
                            )
                            push_log(f"✓ Rendered: {final_dest.name}")
                            
                            # Popular creator metadata optimization for title, description, tags
                            clean_creator = active_credit.lstrip("@").strip()
                            is_creator_valid = bool(clean_creator and clean_creator.lower() not in ["creator", "streamer", "unknown", "live", "none", ""])
                            cand_title = cand.get("title", final_dest.stem.replace("_", " "))
                            if is_creator_valid and clean_creator.lower() not in cand_title.lower():
                                clip_title = f"{clean_creator}: {cand_title}"
                            else:
                                clip_title = cand_title
                            if len(clip_title) > 65:
                                clip_title = clip_title[:62].rstrip() + "..."
                            final_mode_a_title = f"{clip_title} #Shorts" if "#shorts" not in clip_title.lower() else clip_title

                            clean_tag_creator = re.sub(r'[^a-zA-Z0-9]', '', clean_creator)
                            creator_tags = [
                                clean_creator,
                                f"{clean_creator} clips",
                                f"{clean_creator} highlights",
                                f"{clean_creator} moments",
                                f"{clean_creator} funny",
                                f"{clean_creator} live"
                            ] if is_creator_valid else []
                            full_tags = creator_tags + ["Shorts", "Trending", "Gaming", "Viral"]

                            desc_lines = [
                                f"🔥 {clip_title}",
                                "",
                                f"Original Creator: {active_credit}" if is_creator_valid else "",
                                f"Source Video: {meta.get('title', '')}" if meta.get('title') else "",
                                "",
                                f"Best moments and top clips from {clean_creator}!" if is_creator_valid else "",
                                "Subscribe to @zelmuesports for daily gaming highlights & viral moments!",
                                "",
                                f"#Shorts " + (f"#{clean_tag_creator} #{clean_tag_creator}Clips #{clean_tag_creator}Moments " if is_creator_valid else "") + "#Gaming #Viral #Trending"
                            ]
                            clean_desc = "\n".join([l for l in desc_lines if l is not None])

                            save_sidecar_data(final_dest, {
                                "title": final_mode_a_title,
                                "description": clean_desc,
                                "tags": full_tags,
                                "creator": clean_creator if is_creator_valid else "",
                                "channel_name": active_credit if is_creator_valid else "",
                                "source_title": meta.get("title", ""),
                                "category_id": "20",
                                "stage": "pending_quality_review",
                                "approved": False,
                                "source": "manual_clipper",
                                "created_at": time.time()
                            })
                            # Auto-purge raw cuts immediately to eliminate SSD I/O drag
                            raw_seg.unlink(missing_ok=True)
                            for p in segments_dir.glob(f"seg_raw_{c_idx}.*"):
                                p.unlink(missing_ok=True)
                            return final_dest

                        render_labor_card(
                            labor_box,
                            stage_name=f"Stage 4/5: Parallel Processing ({len(candidates)} Shorts)",
                            pct=75,
                            elapsed_str=format_elapsed(time.time() - t_start),
                            current_subtask=f"Spawning parallel download & render workers (max 5)",
                            throughput="ThreadPoolExecutor",
                            mem_stat="Parallel Pool"
                        )

                        pool_size = min(5, max(1, len(candidates)))
                        completed_shorts = 0
                        with concurrent.futures.ThreadPoolExecutor(max_workers=pool_size) as pool:
                            future_map = {pool.submit(process_mode_a_candidate, c_idx, cand): c_idx for c_idx, cand in enumerate(candidates)}
                            while any(not fut.done() for fut in future_map):
                                time.sleep(1)
                                done_count = sum(1 for fut in future_map if fut.done())
                                pct_val = int(75 + (done_count / max(1, len(candidates))) * 23)
                                render_labor_card(
                                    labor_box,
                                    stage_name=f"Stage 4/5: Parallel Rendering ({done_count}/{len(candidates)} Finished)",
                                    pct=pct_val,
                                    elapsed_str=format_elapsed(time.time() - t_start),
                                    current_subtask=f"Encoding {len(candidates)} shorts (Intel QSV + YOLOX)...",
                                    throughput="Multi-worker active",
                                    mem_stat="Encoding"
                                )
                                with log_lock:
                                    try:
                                        detail_box.code("\n".join(full_logs), language="bash")
                                    except Exception:
                                        pass

                            for fut in future_map:
                                fut.result()

                    else:
                        # Mode B Transformative Compilation
                        clips_info = analysis.get("clips", [])
                        script = analysis.get("voiceover_script", "")
                        comp_title = analysis.get("safe_title", "GTA6_Viral_Compilation")
                        final_dest = READY_DIR / f"{comp_title}.mp4"

                        if not final_dest.exists() or final_dest.stat().st_size < 102400:
                            # Generate Piper Narration
                            narration_wav = work_dir / "05_narration.wav"
                            if not narration_wav.exists():
                                push_log("Synthesizing energetic Ryan TTS voiceover via Piper...")
                                generate_piper_tts(script, narration_wav)

                            # Download micro-clips in parallel using prefetched stream URLs
                            prefetched_stream_urls = get_direct_stream_urls(raw_url)
                            render_labor_card(
                                labor_box,
                                stage_name=f"Stage 4/5: Parallel Downloading {len(clips_info)} Highlights",
                                pct=75,
                                elapsed_str=format_elapsed(time.time() - t_start),
                                current_subtask="yt-dlp parallel segments",
                                throughput="Parallel pool",
                                mem_stat="Buffered"
                            )
                            downloaded_clips = [None] * len(clips_info)
                            def dl_micro(m_idx, clip):
                                c_mp4 = segments_dir / f"micro_clip_{m_idx}.mp4"
                                push_log(f"Downloading highlight #{m_idx+1} ({clip['start']}s - {clip['end']}s)...")
                                download_video_section(raw_url, clip["start"], clip["end"], c_mp4, stream_urls=prefetched_stream_urls)
                                return m_idx, c_mp4

                            pool_size = min(3, max(1, len(clips_info)))
                            with concurrent.futures.ThreadPoolExecutor(max_workers=pool_size) as pool:
                                futs = [pool.submit(dl_micro, m_idx, clip) for m_idx, clip in enumerate(clips_info)]
                                for fut in concurrent.futures.as_completed(futs):
                                    idx, c_path = fut.result()
                                    downloaded_clips[idx] = c_path

                            # Render Framed Template + Audio Ducking + optional logo watermark
                            render_labor_card(
                                labor_box,
                                stage_name="Stage 4/5: Assembling Branded Compilation",
                                pct=92,
                                elapsed_str=format_elapsed(time.time() - t_start),
                                current_subtask="FFmpeg framing + audio ducking + badges",
                                throughput="Micro-pacing zooms",
                                mem_stat="2-Thread CPU"
                            )
                            push_log("FFmpeg rendering 9:16 branded template with audio ducking and credit badge...")
                            render_mode_b_short(
                                clip_videos=downloaded_clips,
                                narration_audio=narration_wav,
                                output_short_path=final_dest,
                                hook_title=analysis.get("theme", "GTA 6 HIGHLIGHTS"),
                                channel_credit=active_credit,
                                logo_path=active_logo_path
                            )
                            push_log(f"Rendered: {final_dest.name}")

                            # Popular creator metadata optimization for compilation Mode B
                            clean_creator_b = active_credit.lstrip("@").strip()
                            is_creator_b_valid = bool(clean_creator_b and clean_creator_b.lower() not in ["creator", "streamer", "unknown", "live", "none", ""])
                            comp_theme = analysis.get("theme", final_dest.stem.replace("_", " "))
                            if is_creator_b_valid and clean_creator_b.lower() not in comp_theme.lower():
                                comp_title = f"{clean_creator_b}: {comp_theme}"
                            else:
                                comp_title = comp_theme
                            if len(comp_title) > 65:
                                comp_title = comp_title[:62].rstrip() + "..."
                            final_mode_b_title = f"{comp_title} #Shorts" if "#shorts" not in comp_title.lower() else comp_title

                            clean_tag_creator_b = re.sub(r'[^a-zA-Z0-9]', '', clean_creator_b)
                            creator_b_tags = [
                                clean_creator_b,
                                f"{clean_creator_b} compilation",
                                f"{clean_creator_b} clips",
                                f"{clean_creator_b} moments",
                                f"{clean_creator_b} best of"
                            ] if is_creator_b_valid else []
                            full_b_tags = creator_b_tags + ["GTA6", "Shorts", "Trending", "Gaming", "Viral"]

                            desc_b_lines = [
                                f"🔥 {comp_title}",
                                "",
                                f"Featuring gameplay & highlights from: {active_credit}" if is_creator_b_valid else "",
                                f"Source Video: {meta.get('title', '')}" if meta.get('title') else "",
                                "",
                                f"Transformative compilation with analytical commentary on {clean_creator_b} moments." if is_creator_b_valid else "Transformative commentary compilation.",
                                "Subscribe to @zelmuesports for daily gaming compilations & viral highlights!",
                                "",
                                f"#Shorts " + (f"#{clean_tag_creator_b} #{clean_tag_creator_b}Clips " if is_creator_b_valid else "") + "#Gaming #GTA6 #Trending #Viral"
                            ]
                            clean_b_desc = "\n".join([l for l in desc_b_lines if l is not None])

                            save_sidecar_data(final_dest, {
                                "title": final_mode_b_title,
                                "description": clean_b_desc,
                                "tags": full_b_tags,
                                "creator": clean_creator_b if is_creator_b_valid else "",
                                "channel_name": active_credit if is_creator_b_valid else "",
                                "source_title": meta.get("title", ""),
                                "category_id": "20",
                                "stage": "pending_quality_review",
                                "approved": False,
                                "source": "manual_clipper_mode_b",
                                "created_at": time.time()
                            })
                            for c_path in downloaded_clips:
                                if c_path and Path(c_path).exists():
                                    Path(c_path).unlink(missing_ok=True)
                        else:
                            push_log(f"Transformative Short '{comp_title}' already exists.")
                except (StopException, RerunException):
                    raise
                except ConnectionError as ce:
                    st.session_state["pipeline_paused"] = True
                    push_log(f"⚠️ PAUSED: Internet connection dropped ({ce}). Checkpoints safe.")
                    render_labor_card(
                        labor_box,
                        stage_name="⏸️ Pipeline Paused: Internet Disconnected",
                        pct=50,
                        elapsed_str=format_elapsed(time.time() - t_start),
                        current_subtask="Connection lost. Waiting for internet. Checkpoints saved.",
                        throughput="0 kb/s (Paused)",
                        mem_stat="Checkpoints Safe"
                    )
                    status_box.error("⏸️ Pipeline Paused: Internet disconnected. Reconnect network and click 'Resume / Try Again'.")
                    break
                except Exception as ex:
                    err_str = str(ex)
                    if "getaddrinfo failed" in err_str or "Failed to resolve" in err_str or not check_internet_connection():
                        st.session_state["pipeline_paused"] = True
                        push_log("⚠️ PAUSED: Internet disconnected. Checkpoints safe.")
                        render_labor_card(
                            labor_box,
                            stage_name="⏸️ Pipeline Paused: Internet Disconnected",
                            pct=50,
                            elapsed_str=format_elapsed(time.time() - t_start),
                            current_subtask="Connection lost. Checkpoints saved.",
                            throughput="0 kb/s (Paused)",
                            mem_stat="Checkpoints Safe"
                        )
                        status_box.error("⏸️ Pipeline Paused: Internet disconnected. Click 'Resume / Try Again' once reconnected.")
                    else:
                        push_log(f"ERROR: {err_str}")
                        status_box.error(f"Error: {err_str}")
                    break

            render_labor_card(
                labor_box,
                stage_name="Stage 5/5: Pipeline Complete",
                pct=100,
                elapsed_str=format_elapsed(time.time() - t_start),
                current_subtask="All clips rendered in ./ready_to_upload/",
                throughput="Render complete",
                mem_stat="All systems OK"
            )
            status_box.success("Complete: batch processed.")

            if full_logs:
                col_log1, col_log2 = st.columns([1, 1])
                with col_log1:
                    st.download_button(
                        "📥 Download Full Execution Log (.txt)",
                        data="\n".join(full_logs),
                        file_name=f"zelmu_execution_{int(time.time())}.txt",
                        mime="text/plain",
                        use_container_width=True
                    )
                with col_log2:
                    with st.expander("📋 View & Select Full Raw Log"):
                        st.text_area("Full Log", value="\n".join(full_logs), height=240, label_visibility="collapsed")

    st.markdown("<div class='section-title'>🎬 STUDIO PREVIEW & INSTANT PUBLISH</div>", unsafe_allow_html=True)

    # Auto-stop other videos when one plays (HTML/JS hook)
    st.components.v1.html("""
    <script>
    const setupAutoStop = () => {
        const vids = window.parent.document.querySelectorAll('video');
        vids.forEach(v => {
            if (!v._autoStopHooked) {
                v._autoStopHooked = true;
                v.addEventListener('play', () => {
                    const all = window.parent.document.querySelectorAll('video');
                    all.forEach(other => {
                        if (other !== v && !other.paused) {
                            other.pause();
                        }
                    });
                });
            }
        });
    };
    setupAutoStop();
    const mo = new MutationObserver(setupAutoStop);
    mo.observe(window.parent.document.body, { childList: true, subtree: true });
    </script>
    """, height=0, width=0)

    ready_files = sorted(list(READY_DIR.glob("*.mp4")))
    
    col_hdr1, col_hdr2 = st.columns([3, 1])
    with col_hdr1:
        if ready_files:
            st.caption(f"📁 **{len(ready_files)} Ready Shorts** in `{READY_DIR}` | ⚡ Hardware accelerated (Intel QSV)")
    with col_hdr2:
        if ready_files and st.button("🗑️ Clear All", type="secondary", use_container_width=True):
            for f in ready_files:
                try:
                    f.unlink()
                except Exception:
                    pass
            st.rerun()

    if ready_files:
        # 2 cards per row for better readability & controls
        cols = st.columns(2)
        for i, vid in enumerate(ready_files):
            with cols[i % 2]:
                with st.container(border=True):
                    size_mb = vid.stat().st_size / (1024 * 1024)
                    
                    # Top Title & Specs
                    st.markdown(f"**Clip #{i+1}: `{vid.name}`**")
                    st.video(str(vid))
                    
                    # Specs Bar
                    spec_c1, spec_c2, spec_c3 = st.columns([1, 1, 1])
                    with spec_c1:
                        st.caption(f"📦 **Size:** `{size_mb:.1f} MB`")
                    with spec_c2:
                        st.caption("📐 **Aspect:** `9:16`")
                    with spec_c3:
                        st.caption("⚡ **Codec:** `H.264 QSV`")

                    # Editable YouTube Settings
                    raw_stem = vid.stem.replace("_", " ")
                    default_title = f"{raw_stem[:70]} #GTA6 #Shorts"
                    e_title = st.text_input("📝 YouTube Title:", value=default_title, key=f"yt_title_{i}")
                    
                    with st.expander("⚙️ Editable YouTube Settings & Tags", expanded=False):
                        e_desc = st.text_area(
                            "Description:",
                            value=f"Insane GTA 6 gameplay highlight moment. Subscribed for daily high-energy clips.\n\n#GTA6 #GrandTheftAuto6 #Shorts #Gaming",
                            key=f"yt_desc_{i}",
                            height=75
                        )
                        e_mode = st.selectbox(
                            "Visibility & Publish Mode:",
                            options=["Schedule (Next Peak CPM Slot) 🗓️", "Instant Public 🚀", "Private Draft 🔒"],
                            key=f"yt_mode_{i}"
                        )
                        e_tags = st.text_input("Tags:", value="GTA6, GTA 6, GTA Shorts, Gaming", key=f"yt_tags_{i}")

                    # Action buttons
                    btn_c1, btn_c2 = st.columns([2.5, 1])
                    with btn_c1:
                        btn_label = "🗓️ Schedule Clip" if "Schedule" in e_mode else ("🚀 Publish Now" if "Instant" in e_mode else "🔒 Save Private")
                        if st.button(btn_label, key=f"btn_up_{i}", type="primary", use_container_width=True):
                            with st.spinner("Uploading to YouTube..."):
                                try:
                                    p_mode = "scheduled" if "Schedule" in e_mode else ("public" if "Instant" in e_mode else "private")
                                    tag_list = [t.strip() for t in e_tags.split(",") if t.strip()]
                                    res = upload_single_clip_direct(
                                        file_path=vid,
                                        title=e_title,
                                        description=e_desc,
                                        tags=tag_list,
                                        privacy_mode=p_mode
                                    )
                                    st.success(f"✓ Uploaded! [Edit in YouTube Studio ↗]({res['studio_url']})")
                                    time.sleep(1.0)
                                    st.rerun()
                                except Exception as u_err:
                                    st.error(f"Upload failed: {u_err}")
                    with btn_c2:
                        if st.button("🗑️ Delete", key=f"del_{i}", use_container_width=True):
                            try:
                                vid.unlink()
                            except Exception:
                                pass
                            st.rerun()
    else:
        st.caption("No clips generated yet. Paste a YouTube URL above and click 'Produce Shorts' to generate clips.")

def get_client_id_info():
    """Reads configured OAuth client_id safely."""
    if not CLIENT_SECRETS_FILE.exists():
        return None
    try:
        with open(CLIENT_SECRETS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = data.get("installed") or data.get("web") or {}
        return cfg.get("client_id", "Unknown")
    except Exception:
        return "Invalid JSON"


def render_upload_stage():
    ready_videos = sorted(list(READY_DIR.glob("*.mp4")))
    yt_connected = is_authenticated()
    curr_client_id = get_client_id_info()
    configured_slots = list_account_slots()
    auth_slots = [s for s in configured_slots if s["is_authenticated"]]
    pool_quota = max(10000, len(auth_slots) * 10000)

    def is_clip_approved(p: Path) -> bool:
        sc = p.with_suffix(".json")
        if sc.exists():
            try:
                with open(sc, "r", encoding="utf-8") as f:
                    return json.load(f).get("approved") is True
            except Exception:
                pass
        return False

    approved_videos = [f for f in ready_videos if is_clip_approved(f)]
    pending_videos = [f for f in ready_videos if not is_clip_approved(f)]

    # Top Status Row
    col1, col2 = st.columns([1, 1])
    with col1:
        st.metric("Ready to Upload (Approved)", f"{len(approved_videos)} clips", delta=f"{len(pending_videos)} awaiting Stage 3" if pending_videos else None)
        if pending_videos:
            st.caption(f"⚠️ {len(pending_videos)} clips awaiting Stage 3 Quality Review.")
            if st.button("⚡ Fast-Track: Approve All Pending Clips", key="btn_ft_appr", type="secondary"):
                for pv in pending_videos:
                    meta = {}
                    sc = pv.with_suffix(".json")
                    if sc.exists():
                        try:
                            with open(sc, "r", encoding="utf-8") as f:
                                meta = json.load(f)
                        except Exception:
                            pass
                    meta["approved"] = True
                    meta["stage"] = "ready_for_upload"
                    save_sidecar_data(pv, meta)
                st.success(f"✓ Approved all {len(pending_videos)} clips for upload!")
                st.rerun()
        if len(auth_slots) > 1:
            st.caption(f"⚡ Multi-Project Quota: {len(auth_slots) * 100} uploads/day across {len(auth_slots)} projects")
        elif len(ready_videos) > 100:
            st.caption("Standard GCP quota: 100 uploads/day (10,000 queries/day)")

    with col2:
        if not CLIENT_SECRETS_FILE.exists() and not configured_slots:
            st.error("Missing client_secrets.json in root folder.")
        elif yt_connected or auth_slots:
            an = get_channel_analytics()
            title = an.get("title", "Connected Account")
            subs = an.get("subscribers", 0)
            views = an.get("views", 0)
            st.success(f"Linked: **{title}** ({subs:,} subs | {views:,} views)")
            if st.button("Disconnect / Switch Account", use_container_width=True):
                revoke_token()
                st.rerun()
        else:
            st.warning("YouTube Not Linked")

    if len(auth_slots) > 1:
        st.info(f"🔄 **Multi-Project Quota Pool Active:** {len(auth_slots)} authorized GCP project slots connected ({pool_quota:,} total daily units). Auto-rotates to next project slot when daily 10k quota limits are reached, maintaining continuous uploads to **@zelmuesports**.")

    # Item 3: Multi-Project Account Pool (Scale Beyond 10k Daily Quota)
    with st.expander("🔑 Multi-Project Account Pool (Scale Beyond 10k Daily Quota)", expanded=len(configured_slots) > 1):
        st.markdown("""
        <div style="background: rgba(37, 99, 235, 0.08); border: 1px solid rgba(37, 99, 235, 0.25); border-radius: 8px; padding: 12px 14px; margin-bottom: 14px;">
            <div style="font-weight: 700; color: #60a5fa; margin-bottom: 4px;">Scale Beyond 10k Daily YouTube Upload Quota</div>
            <div style="font-size: 0.84rem; color: #94a3b8; line-height: 1.45;">
                Every standard Google Cloud project receives <b>100 Video Uploads/day</b> and <b>10,000 queries/day</b>.
                By adding additional GCP projects authorized against <b>@zelmuesports</b> and dropping their <code>client_secrets_*.json</code> files here,
                the uploader seamlessly rotates across slots on quota limits (100 + 100 + 100 = 300+ uploads/day) without interrupting your queue.
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Multi-Project Capacity Dashboard
        total_slots_cnt = max(1, len(configured_slots))
        auth_slots_cnt = max(1, len(auth_slots))
        max_daily_shorts = total_slots_cnt * 100
        active_daily_shorts = auth_slots_cnt * 100
        total_units_pool = total_slots_cnt * 10000
        active_units_pool = auth_slots_cnt * 10000

        dash_c1, dash_c2, dash_c3, dash_c4 = st.columns(4)
        with dash_c1:
            st.metric("Total Slots Configured", f"{total_slots_cnt} Projects", help="Total GCP project slots registered in local pool.")
        with dash_c2:
            st.metric(
                "Max Daily Upload Capacity",
                f"{max_daily_shorts} Shorts/day",
                delta=f"{active_daily_shorts} active" if total_slots_cnt != auth_slots_cnt else None,
                help="GCP YouTube Data API limit: 100 Video Uploads per day per project."
            )
        with dash_c3:
            st.metric(
                "Total Daily Queries Pool",
                f"{total_units_pool:,} queries",
                delta=f"{active_units_pool:,} active" if total_slots_cnt != auth_slots_cnt else None,
                help="10,000 queries per day per project slot. Auto-rotates sequentially when quota hits."
            )
        with dash_c4:
            st.metric("Target Channel", "@zelmuesports", help="All project slots upload to @zelmuesports.")

        st.markdown("---")

        # 3-Step Quick Setup Guide
        with st.expander("⚡ How to Create Multiple Projects in 2 Minutes", expanded=False):
            st.markdown("""
            <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(59, 130, 246, 0.35); border-radius: 8px; padding: 16px; margin-bottom: 8px;">
                <div style="font-weight: 700; color: #60a5fa; font-size: 0.95rem; margin-bottom: 12px;">🚀 3-Step Multi-Project Setup (Bypass Quota Limits Instantly)</div>
                <div style="display: flex; flex-direction: column; gap: 12px; font-size: 0.88rem; color: #e2e8f0; line-height: 1.5;">
                    <div><b>1. Create Project in Google Cloud Console:</b><br>
                    Go to <a href="https://console.cloud.google.com/projectcreate" target="_blank" style="color: #38bdf8; text-decoration: underline;">Google Cloud Console &gt; Create Project ↗</a> and give it a name (e.g. <code>Zelmu-Pool-2</code>, <code>Zelmu-Pool-3</code>).</div>
                    <div><b>2. Enable YouTube Data API v3 &amp; Create OAuth Client ID:</b><br>
                    Navigate to <b>APIs &amp; Services &gt; Library</b> &rarr; search and <b>Enable YouTube Data API v3</b>.<br>
                    Then go to <b>APIs &amp; Services &gt; Credentials &rarr; Create Credentials &rarr; OAuth client ID</b> (Application type: <b>Desktop app</b>).</div>
                    <div><b>3. Download &amp; Drop JSON Here:</b><br>
                    Click <b>Download JSON</b> for your new client secret (e.g. <code>client_secret_*.json</code>) and drop it into the batch uploader below. Click <b>Sign In</b> on the new slot to connect <b>@zelmuesports</b>. Repeat to add as many projects as you need!</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("##### ➕ Batch Add Project Slots (`client_secrets_*.json`)")
        new_slot_files = st.file_uploader(
            "Drop multiple client_secrets_*.json files here (Project 2, Project 3, etc.)",
            type=["json"],
            accept_multiple_files=True,
            key="up_slot_secrets_pool_json",
            help="Drag & drop multiple Google Cloud OAuth client secret JSON files all at once."
        )
        if new_slot_files:
            added_slots = []
            for f in new_slot_files:
                try:
                    raw_bytes = f.read()
                    added = add_account_slot(raw_bytes, custom_name=f.name)
                    added_slots.append(added)
                except Exception as ex:
                    st.error(f"Error adding {f.name}: {ex}")
            if added_slots:
                st.success(f"✓ Added {len(added_slots)} project slot(s) successfully! Authorize each slot below.")
                time.sleep(0.5)
                st.rerun()

        st.markdown("##### ⚙️ Pool Operations & Verification")
        pool_btn_c1, pool_btn_c2 = st.columns([1, 1])
        with pool_btn_c1:
            if st.button("🧪 Test All Slots", key="btn_test_all_slots", use_container_width=True):
                if not configured_slots:
                    st.info("No project slots to test.")
                else:
                    with st.spinner("Testing connectivity for all project slots..."):
                        all_ok = True
                        for s in configured_slots:
                            t_res = test_account_slot(s["slot_id"])
                            if t_res.get("valid"):
                                st.toast(f"Slot '{s['name']}': ✅ Healthy ({t_res.get('channel_title', '')})", icon="✅")
                            else:
                                all_ok = False
                                st.error(f"Slot '{s['name']}': ❌ {t_res.get('error')}")
                        if all_ok:
                            st.success(f"✓ All {len(configured_slots)} slots verified healthy and connected to target channel!")
        with pool_btn_c2:
            if st.button("🔄 Reset Daily Quota Hit Flags", key="btn_reset_quota_flags", use_container_width=True):
                reset_exhausted_slots()
                st.success("✓ Daily quota exhaustion flags reset for all slots!")
                time.sleep(0.4)
                st.rerun()

        st.markdown("##### 📋 Configured Project Slots & Rotation Status")
        if not configured_slots:
            st.caption("No account slots configured yet.")
        else:
            for s_idx, slot in enumerate(configured_slots):
                with st.container():
                    sc1, sc2, sc3 = st.columns([2.5, 2.2, 2.3])
                    with sc1:
                        st.markdown(f"**{slot['name']}**")
                        st.caption(f"Project ID: `{slot['project_id']}` | Client: `...{slot['client_id'][-14:] if len(slot['client_id']) > 14 else slot['client_id']}`")
                    with sc2:
                        if slot["is_authenticated"]:
                            st.markdown(
                                f"<div style='font-size:0.85rem; color:#22c55e; font-weight:600;'>● Connected & Verified</div>"
                                f"<div style='font-size:0.8rem; color:#94a3b8;'>Channel: <b>{slot['channel_handle']}</b></div>",
                                unsafe_allow_html=True
                            )
                        elif slot.get("quota_exceeded"):
                            st.markdown("<div style='font-size:0.85rem; color:#f59e0b; font-weight:600;'>⚠️ 10k Quota Hit Today</div>", unsafe_allow_html=True)
                        else:
                            st.markdown("<div style='font-size:0.85rem; color:#ef4444; font-weight:600;'>○ Needs Sign-In</div>", unsafe_allow_html=True)
                    with sc3:
                        if not slot["is_authenticated"]:
                            with st.popover(f"Sign In ({slot['slot_id']})", use_container_width=True):
                                st.caption(f"Authorize Google account for {slot['name']}:")
                                if st.button("Launch Browser Sign-In", key=f"btn_auth_pop_{slot['slot_id']}", use_container_width=True):
                                    with st.spinner("Waiting for Google OAuth in browser..."):
                                        try:
                                            authenticate_account_slot(slot["slot_id"])
                                            st.success("Successfully authenticated!")
                                            st.rerun()
                                        except Exception as err:
                                            st.error(f"Sign-in failed: {err}")
                                try:
                                    slot_url = get_auth_url_for_slot(slot["slot_id"])
                                    st.markdown(f'<a href="{slot_url}" target="_blank" style="display:inline-block; font-size:0.8rem; margin:6px 0;">🔗 Open Google Sign-In Tab</a>', unsafe_allow_html=True)
                                    code_val = st.text_input("Paste redirect code / URL:", key=f"slot_code_in_{slot['slot_id']}")
                                    if st.button("Exchange Code", key=f"btn_code_ex_{slot['slot_id']}"):
                                        if code_val:
                                            authenticate_account_slot(slot["slot_id"], code=code_val)
                                            st.success("Connected!")
                                            st.rerun()
                                except Exception:
                                    pass
                        else:
                            tc1, tc2 = st.columns([1, 1])
                            with tc1:
                                if st.button("🧪 Test Slot", key=f"btn_test_slot_{slot['slot_id']}", use_container_width=True):
                                    test_res = test_account_slot(slot["slot_id"])
                                    if test_res.get("valid"):
                                        st.toast(f"Slot '{slot['name']}' ready: {test_res['channel_title']} ({test_res['channel_handle']})", icon="✅")
                                    else:
                                        st.error(f"Slot verification failed: {test_res.get('error')}")
                            with tc2:
                                if slot["slot_id"] != "default":
                                    if st.button("🗑️ Remove", key=f"btn_del_slot_{slot['slot_id']}", use_container_width=True):
                                        delete_account_slot(slot["slot_id"])
                                        st.rerun()
                                else:
                                    if st.button("Disconnect", key=f"btn_disc_slot_{slot['slot_id']}", use_container_width=True):
                                        revoke_token()
                                        st.rerun()
                    st.divider()

    # Monetization, Cadence & Visibility Controls
    col_sc1, col_sc2, col_sc3 = st.columns([1.2, 1.1, 1.0])
    with col_sc1:
        cadence_option = st.selectbox(
            "Schedule Cadence",
            options=["6 Shorts / Day (High Frequency)", "3 Shorts / Day (Conservative Peak)", "12 Shorts / Day (Hyper-growth)"],
            index=0,
            help="For Scheduled Publish: spreads clips across daily peak US/UK monetization windows."
        )
        slots_per_day = 6 if "6" in cadence_option else (12 if "12" in cadence_option else 3)
    with col_sc2:
        instant_privacy = st.selectbox(
            "Instant Visibility",
            options=["public", "private", "unlisted"],
            index=0,
            format_func=lambda x: f"🌐 {x.upper()} (Live Now)" if x == "public" else (f"🔒 {x.upper()} (Draft)" if x == "private" else f"🔗 {x.upper()} (Unlisted)"),
            help="For Instant Publish: controls video visibility immediately upon upload."
        )
    with col_sc3:
        upload_concurrency = st.selectbox(
            "Concurrency",
            options=[2, 1],
            format_func=lambda x: f"⚡ {x} Parallel" if x == 2 else f"🐢 {x} Sequential",
            index=0,
            help="Turbo streams 2 videos simultaneously to maximize upload bandwidth."
        )

    batch_cap = st.slider("Max Upload Queue Limit", min_value=5, max_value=250, value=min(100, max(5, len(ready_videos))), step=5)

    target_upload_list = approved_videos if approved_videos else ready_videos
    upload_disabled = len(target_upload_list) == 0 or not yt_connected
    clip_count = min(len(target_upload_list), batch_cap)

    if ready_videos:
        days_span = max(1, (clip_count + slots_per_day - 1) // slots_per_day)
        st.caption(f"🗓️ **Scheduled Horizon:** Spans `{clip_count}` clips across **{days_span} days** (~{slots_per_day}/day during peak US EST hours). | ⚡ **Instant Horizon:** Publishes `{clip_count}` clips immediately live as `{instant_privacy.upper()}`.")

    # Two Primary Action Buttons: 1 for Instant Publish, 2 for Scheduled Publish
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        btn_instant = st.button(
            f"⚡ Instant Publish ({clip_count} Clips)",
            type="primary",
            disabled=upload_disabled,
            use_container_width=True,
            help=f"Publishes {clip_count} clips immediately to YouTube as {instant_privacy.upper()} without calendar delays."
        )
    with btn_col2:
        btn_schedule = st.button(
            f"🗓️ Scheduled Publish ({clip_count} Clips)",
            type="secondary",
            disabled=upload_disabled,
            use_container_width=True,
            help=f"Uploads and spaces {clip_count} clips across peak monetization slots (~{slots_per_day}/day)."
        )

    if btn_instant or btn_schedule:
        run_auto_sched = bool(btn_schedule)
        target_privacy = "private" if run_auto_sched else instant_privacy
        mode_label = f"🗓️ Scheduled ({slots_per_day}/day)" if run_auto_sched else f"⚡ Instant Publish ({target_privacy.upper()})"

        u_labor_box = st.empty()
        u_progress = st.progress(0.0)
        u_status = st.empty()
        u_log_box = st.empty()

        upload_logs = []
        t_batch_start = time.time()

        def on_upload_log(msg: str):
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            formatted = f"[{timestamp}] {msg}"
            upload_logs.append(formatted)
            try:
                u_log_box.code("\n".join(upload_logs[-12:]), language="bash")
            except Exception:
                pass

        def on_upload_chunk(t: dict):
            try:
                u_progress.progress(min(1.0, max(0.0, t.get("overall_pct", 0) / 100.0)))

                eta_s = t.get("eta_sec", 0.0)
                eta_str = f"{int(eta_s // 60):02d}:{int(eta_s % 60):02d}"
                elapsed_str = format_elapsed(time.time() - t_batch_start)
                active_stream_str = f"{t.get('active_workers', 1)} Stream(s) Active"

                speed_mbs = t.get("speed_MBs", 0.0)
                speed_mbps = t.get("speed_mbps", 0.0)
                bytes_mb = t.get("overall_bytes_mb", 0.0)
                total_mb = t.get("total_batch_mb", 0.0)
                curr_f = t.get("current_file", "Processing")
                file_pct = t.get("file_pct", 0)
                done_c = t.get("completed_count", 0)
                tot_c = t.get("total_count", 1)
                ov_pct = t.get("overall_pct", 0)

                labor_html = f"""
                <div class="labor-card" style="margin-bottom: 0.85rem;">
                    <div class="labor-top-row">
                        <div class="labor-stage">
                            <span class="labor-dot"></span>
                            <span>YouTube Upload Center &bull; [{done_c}/{tot_c} Completed] &bull; {active_stream_str}</span>
                        </div>
                        <div class="labor-pct">{ov_pct}%</div>
                    </div>
                    <div class="labor-subtask">{curr_f} ({file_pct}%) &bull; <b>{mode_label}</b></div>
                    <div class="labor-data-grid">
                        <div class="labor-data-cell">
                            <span class="labor-label">Transfer Speed</span>
                            <span class="labor-val" style="color: #22c55e;">{speed_mbs:.2f} MB/s ({speed_mbps:.1f} Mbps)</span>
                        </div>
                        <div class="labor-data-cell">
                            <span class="labor-label">Transferred</span>
                            <span class="labor-val">{bytes_mb:.1f} / {total_mb:.1f} MB</span>
                        </div>
                        <div class="labor-data-cell">
                            <span class="labor-label">Elapsed / ETA</span>
                            <span class="labor-val">{elapsed_str} / {eta_str}</span>
                        </div>
                        <div class="labor-data-cell">
                            <span class="labor-label">Batch Queue</span>
                            <span class="labor-val">{done_c} of {tot_c} Done</span>
                        </div>
                    </div>
                </div>
                """
                u_labor_box.markdown(labor_html, unsafe_allow_html=True)
            except Exception:
                pass

        try:
            results = upload_batch_private(
                max_batch_size=batch_cap,
                auto_schedule=run_auto_sched,
                slots_per_day=slots_per_day,
                concurrency=upload_concurrency,
                privacy_mode=target_privacy,
                files_subset=target_upload_list[:batch_cap],
                chunk_callback=on_upload_chunk,
                log_callback=on_upload_log
            )
            u_progress.progress(1.0)
            successful = [r for r in results if isinstance(r, dict) and not r.get("error") and r.get("video_id")]
            errors = [r for r in results if isinstance(r, dict) and r.get("error")]

            if successful:
                u_status.success(f"✓ Successfully processed {len(successful)} clips on YouTube ({mode_label})!")
                for r in successful:
                    v_title = r.get("title") or "YouTube Clip"
                    v_url = r.get("studio_url") or (f"https://studio.youtube.com/video/{r.get('video_id')}/edit" if r.get("video_id") else "https://studio.youtube.com")
                    sched_note = f" (Scheduled: `{r.get('publish_at')}`)" if r.get("publish_at") else f" ({r.get('privacy_status', target_privacy).upper()})"
                    st.markdown(f"- **{v_title}**{sched_note} &rarr; [Edit in YouTube Studio]({v_url})")

            if errors:
                seen_errors = set()
                for err_r in errors:
                    msg = err_r.get("error", "Upload interrupted")
                    if msg not in seen_errors:
                        seen_errors.add(msg)
                        st.warning(f"{msg}")

            if not successful and not errors:
                u_status.info("No clips were processed.")

            if st.button("Refresh Queue", key="refresh_after_up"):
                st.rerun()
        except Exception as e:
            u_status.error(f"Upload failed: {str(e)}")

    st.markdown("<div class='section-title'>UPLOAD HISTORY & DATA ANALYTICS</div>", unsafe_allow_html=True)
    if LOG_FILE.exists():
        import pandas as pd
        df = pd.read_csv(LOG_FILE)

        for col in ["File_Size_MB", "Upload_Sec", "Speed_MBps"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        total_uploads = len(df)
        total_mb = df["File_Size_MB"].sum() if "File_Size_MB" in df.columns else 0.0
        avg_speed = df["Speed_MBps"].mean() if "Speed_MBps" in df.columns else 0.0
        # Calculate daily uploads (today) matching GCP Quota metric
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        today_uploads = len(df[df["Timestamp"].astype(str).str.startswith(today_str)]) if "Timestamp" in df.columns else total_uploads
        
        auth_slots = [s for s in list_account_slots() if s["is_authenticated"]]
        daily_upload_cap = max(1, len(auth_slots)) * 100
        upload_pct = (today_uploads / daily_upload_cap) * 100.0 if daily_upload_cap > 0 else 0.0

        # Telemetry Data Grid
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        with m_col1:
            st.metric("Total Shorts Uploaded", f"{total_uploads} clips")
        with m_col2:
            if total_mb >= 1024:
                st.metric("Data Transferred", f"{total_mb / 1024:.2f} GB")
            else:
                st.metric("Data Transferred", f"{total_mb:.1f} MB")
        with m_col3:
            st.metric("Avg Upload Speed", f"{avg_speed:.1f} Mbps")
        with m_col4:
            st.metric("Daily Upload Quota", f"{today_uploads} / {daily_upload_cap} clips", delta=f"{upload_pct:.1f}% used")

        if today_uploads >= int(daily_upload_cap * 0.9):
            st.warning(f"⚠️ High Quota Utilization: {today_uploads}/{daily_upload_cap} daily uploads used today ({upload_pct:.0f}% across {len(auth_slots)} project slot(s)). Add more project slots in the pool to expand limit.")
        else:
            st.caption(f"✓ GCP Quota Status: **{today_uploads}/{daily_upload_cap} uploads today across {len(auth_slots)} project slot(s)** ({upload_pct:.1f}% used). Limit: 100 uploads/day per GCP project.")

        st.dataframe(
            df,
            column_config={
                "Studio_URL": st.column_config.LinkColumn("YouTube Studio", display_text="Edit in Studio ↗"),
                "Scheduled_Time": st.column_config.TextColumn("Scheduled Release"),
                "Speed_MBps": st.column_config.NumberColumn("Transfer Speed", format="%.1f Mbps"),
                "File_Size_MB": st.column_config.NumberColumn("File Size", format="%.1f MB"),
                "Upload_Sec": st.column_config.NumberColumn("Duration", format="%.1f s"),
            },
            hide_index=True,
            use_container_width=True
        )

        col_csv1, col_csv2 = st.columns([1, 1])
        with col_csv1:
            csv_bytes = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Export Upload Report (.csv)",
                data=csv_bytes,
                file_name=f"zelmu_upload_report_{int(time.time())}.csv",
                mime="text/csv",
                use_container_width=True
            )
        with col_csv2:
            if st.button("Clear Upload History", type="secondary", use_container_width=True):
                try:
                    LOG_FILE.unlink()
                except Exception:
                    pass
                st.rerun()
    else:
        st.caption("No upload history recorded yet.")
    st.markdown("<div class='section-title'>STORAGE MAINTENANCE</div>", unsafe_allow_html=True)
    if st.button("🧹 Purge Stale Workspace Temp Dirs (>7d)", type="secondary", key="btn_clean_ws_storage"):
        cleaned = cleanup_stale_workspaces()
        st.success(f"✓ Cleaned {cleaned} stale intermediate folders.")


def render_vod_watcher():
    st.markdown("<div class='section-title'>VOD CLIPPER</div>", unsafe_allow_html=True)
    watcher_cfg = load_watcher_config()
    running = is_watcher_running()

    # Status Banner
    col_w_status, col_w_action = st.columns([2, 1])
    with col_w_status:
        if running:
            st.success("🟢 **Active:** Monitoring uploads.")
        else:
            st.info("⚪ **Idle:** Watcher paused.")

    with col_w_action:
        if running:
            if st.button("⏹️ Stop", type="secondary", use_container_width=True):
                stop_watcher_daemon()
                watcher_cfg["enabled"] = False
                save_watcher_config(watcher_cfg)
                st.rerun()
        else:
            if st.button("▶️ Start Watcher", type="primary", use_container_width=True):
                raw_chs = st.session_state.get("txt_watcher_channels", "")
                if raw_chs.strip():
                    watcher_cfg["channels"] = [c.strip() for c in raw_chs.splitlines() if c.strip()]
                watcher_cfg["enabled"] = True
                save_watcher_config(watcher_cfg)
                start_watcher_daemon()
                st.rerun()

    st.markdown("---")

    # Config Grid
    col_cfg_left, col_cfg_right = st.columns([1.5, 1])

    with col_cfg_left:
        st.caption("CHANNELS (1/line)")
        if "txt_watcher_channels" not in st.session_state:
            st.session_state["txt_watcher_channels"] = "\n".join(watcher_cfg.get("channels", []))
        ch_input = st.text_area(
            "Monitored Channels",
            height=140,
            label_visibility="collapsed",
            placeholder="https://www.youtube.com/@Channel",
            key="txt_watcher_channels"
        )

    with col_cfg_right:
        st.caption("SETTINGS")
        poll_int = st.select_slider(
            "Interval",
            options=[15, 30, 45, 60, 120],
            value=watcher_cfg.get("check_interval_minutes", 15),
            format_func=lambda x: f"{x} min"
        )
        shorts_n = st.slider("Shorts/Video", min_value=2, max_value=8, value=watcher_cfg.get("shorts_per_video", 4))
        auto_up = st.checkbox("Auto-Schedule (Studio)", value=watcher_cfg.get("auto_upload", True))
        hook_bg = st.checkbox("Burn Hook Badge", value=watcher_cfg.get("enable_hook_badge", True))

    if st.button("💾 Save Settings", use_container_width=True):
        raw_chs = st.session_state.get("txt_watcher_channels", "")
        parsed_channels = [c.strip() for c in raw_chs.splitlines() if c.strip()]
        watcher_cfg["channels"] = parsed_channels
        watcher_cfg["check_interval_minutes"] = poll_int
        watcher_cfg["shorts_per_video"] = shorts_n
        watcher_cfg["auto_upload"] = auto_up
        watcher_cfg["enable_hook_badge"] = hook_bg
        save_watcher_config(watcher_cfg)
        st.success("✓ Saved")

    from portal_stages import render_watermark_options_expander
    render_watermark_options_expander("vod", "VOD Watcher")

    # Live Real-Time Autopilot Stage & Progress Telemetry (Auto-updates every 3s)
    @st.fragment(run_every="3s")
    def render_autopilot_live_telemetry():
        prog = get_watcher_progress()
        is_run = is_watcher_running()

        pct = prog.get("percentage", 0)
        status = prog.get("status", "idle")
        stage_lbl = prog.get("stage_label", "Idle")
        detail = prog.get("step_detail", "Ready.")
        next_step = prog.get("next_step", "Scan uploads")
        vid_title = prog.get("video_title", "")
        ch_name = prog.get("channel_name", "")
        cur_clip = prog.get("current_clip", 0)
        tot_clips = prog.get("total_clips", 0)

        st.markdown("<div class='section-title'>PROGRESS</div>", unsafe_allow_html=True)

        if is_run and status not in ("idle", "waiting"):
            st.progress(min(1.0, max(0.0, pct / 100.0)), text=f"{stage_lbl} — {pct}%")
        elif is_run and status == "waiting":
            st.progress(1.0, text="✓ Cycle Finished")
        else:
            st.progress(0.0, text="Paused / Idle")

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Stage", stage_lbl, delta=f"{pct}%" if is_run and pct > 0 else None)
        with m2:
            display_title = f"{vid_title[:20]}..." if len(vid_title) > 20 else (vid_title or "None")
            st.metric("Video", display_title)
        with m3:
            clip_info = f" ({cur_clip}/{tot_clips})" if tot_clips > 0 else ""
            display_detail = f"{detail[:22]}..." if len(detail) > 22 else detail
            st.metric("Sub-Step", display_detail, delta=clip_info if clip_info else None)
        with m4:
            display_next = f"{next_step[:20]}..." if len(next_step) > 20 else next_step
            st.metric("Next", display_next)

        st.markdown("<div class='section-title'>EVENTS</div>", unsafe_allow_html=True)
        w_logs = get_watcher_logs()
        if w_logs:
            st.code("\n".join(w_logs[-25:]), language="bash")
        else:
            st.caption("No events.")

    render_autopilot_live_telemetry()


def render_live_buffer():
    st.markdown("<div class='section-title'>LIVE CLIPPER</div>", unsafe_allow_html=True)
    live_cfg = load_livestream_config()
    live_running = is_livestream_running()

    # Status Banner
    col_l_status, col_l_action = st.columns([2, 1])
    with col_l_status:
        if live_running:
            st.success("🟢 **Active:** Rolling HLS capture.")
        else:
            st.info("⚪ **Idle:** Clipper paused.")

    with col_l_action:
        if live_running:
            if st.button("⏹️ Stop", type="secondary", use_container_width=True, key="btn_stop_live_clipper"):
                stop_livestream_daemon()
                live_cfg["enabled"] = False
                save_livestream_config(live_cfg)
                st.rerun()
        else:
            if st.button("▶️ Start Clipper", type="primary", use_container_width=True, key="btn_start_live_clipper"):
                raw_chs = st.session_state.get("txt_live_channels", "")
                if raw_chs.strip():
                    live_cfg["channels"] = [c.strip() for c in raw_chs.splitlines() if c.strip()]
                live_cfg["enabled"] = True
                save_livestream_config(live_cfg)
                start_livestream_daemon()
                st.rerun()

    st.markdown("---")

    # Config Grid
    col_lcfg_left, col_lcfg_right = st.columns([1.5, 1])

    with col_lcfg_left:
        st.caption("CHANNELS (1/line)")
        if "txt_live_channels" not in st.session_state:
            st.session_state["txt_live_channels"] = "\n".join(live_cfg.get("channels", []))
        live_ch_input = st.text_area(
            "Live Streams to Monitor",
            height=140,
            label_visibility="collapsed",
            placeholder="https://www.youtube.com/@Channel/live",
            key="txt_live_channels"
        )

    with col_lcfg_right:
        st.caption("SETTINGS")
        slice_dur = st.select_slider(
            "Buffer Window",
            options=[180, 300, 600, 900],
            value=live_cfg.get("slice_duration_seconds", 300),
            format_func=lambda x: f"{x // 60} min",
            key="sl_live_slice_dur"
        )
        shorts_per_slice = st.slider("Shorts/Slice", min_value=1, max_value=4, value=live_cfg.get("shorts_per_slice", 2), key="sl_live_shorts_slice")
        live_auto_up = st.checkbox("Auto-Schedule (Studio)", value=live_cfg.get("auto_upload", True), key="chk_live_auto_up")
        live_hook = st.checkbox("Burn Live Badge", value=live_cfg.get("enable_hook_badge", True), key="chk_live_hook")

    if st.button("💾 Save Settings", use_container_width=True, key="btn_save_live_cfg"):
        raw_chs = st.session_state.get("txt_live_channels", "")
        parsed_chs = [c.strip() for c in raw_chs.splitlines() if c.strip()]
        live_cfg["channels"] = parsed_chs
        live_cfg["slice_duration_seconds"] = slice_dur
        live_cfg["shorts_per_slice"] = shorts_per_slice
        live_cfg["auto_upload"] = live_auto_up
        live_cfg["enable_hook_badge"] = live_hook
        save_livestream_config(live_cfg)
        st.success("✓ Saved")

    from portal_stages import render_watermark_options_expander
    render_watermark_options_expander("live", "Live Buffer Clipper")

    # Live Real-Time Telemetry for Tab 4
    @st.fragment(run_every="3s")
    def render_livestream_live_telemetry():
        l_prog = get_livestream_progress()
        is_l_run = is_livestream_running()

        l_pct = l_prog.get("percentage", 0)
        l_status = l_prog.get("status", "idle")
        l_stage = l_prog.get("stage_label", "Idle")
        l_detail = l_prog.get("step_detail", "Ready.")
        l_next = l_prog.get("next_step", "Scan streams")
        l_title = l_prog.get("stream_title", "")
        l_author = l_prog.get("channel_name", "")
        l_cur_clip = l_prog.get("current_clip", 0)
        l_tot_clips = l_prog.get("total_clips", 0)

        st.markdown("<div class='section-title'>TELEMETRY</div>", unsafe_allow_html=True)

        if is_l_run and l_status not in ("idle", "waiting"):
            st.progress(min(1.0, max(0.0, l_pct / 100.0)), text=f"{l_stage} — {l_pct}%")
        elif is_l_run and l_status == "waiting":
            st.progress(1.0, text="✓ Clipped & Scheduled")
        else:
            st.progress(0.0, text="Paused / Idle")

        lm1, lm2, lm3, lm4 = st.columns(4)
        with lm1:
            st.metric("Stage", l_stage, delta=f"{l_pct}%" if is_l_run and l_pct > 0 else None)
        with lm2:
            display_ltitle = f"{l_title[:20]}..." if len(l_title) > 20 else (l_title or "None")
            st.metric("Stream", display_ltitle)
        with lm3:
            clip_str = f" ({l_cur_clip}/{l_tot_clips})" if l_tot_clips > 0 else ""
            display_ldetail = f"{l_detail[:22]}..." if len(l_detail) > 22 else l_detail
            st.metric("Sub-Step", display_ldetail, delta=clip_str if clip_str else None)
        with lm4:
            display_lnext = f"{l_next[:20]}..." if len(l_next) > 20 else l_next
            st.metric("Next", display_lnext)

        st.markdown("<div class='section-title'>EVENTS</div>", unsafe_allow_html=True)
        l_logs = get_livestream_logs()
        if l_logs:
            st.code("\n".join(l_logs[-25:]), language="bash")
        else:
            st.caption("No events.")

    render_livestream_live_telemetry()


def render_trend_hunter():
    st.markdown("<div class='section-title'>TREND HUNTER</div>", unsafe_allow_html=True)
    st.caption("Pre-Peak US Trends & Real-Time YouTube Search Autocomplete Radar → 8 Pure 9:16 Shorts.")

    # Trend Scanner Parameters
    st.markdown("<div class='section-title'>SCANNER</div>", unsafe_allow_html=True)
    p0, p1, p2, p3, p4, p5 = st.columns([1.3, 0.8, 0.9, 1.1, 1.3, 1.0])
    with p0:
        radar_feed = st.selectbox(
            "Radar Source",
            ["Google Pre-Peak 4h", "YouTube Autocomplete Live", "Combined Dual Radar"],
            index=0,
            key="trend_feed_src"
        )
    with p1:
        trend_geo = st.selectbox("Geo", ["US", "GB", "CA", "AU"], index=0, key="trend_geo")
    with p2:
        trend_hours = st.selectbox("Window", [4, 24, 48], index=0, format_func=lambda x: f"Past {x}h", key="trend_hours")
    with p3:
        trend_sort = st.selectbox("Sort", ["recency", "search-volume"], index=0, format_func=lambda x: "Recency (Newest First)" if x == "recency" else "Search Volume", key="trend_sort")
    with p4:
        cat_keys = list(CATEGORIES.keys())
        sel_cat_key = st.selectbox("Category", cat_keys, index=0, format_func=lambda k: CATEGORIES[k]["label"], key="trend_cat")
        sel_cat_id = CATEGORIES[sel_cat_key]["cat_id"]
        cat_default_suffix = CATEGORIES[sel_cat_key]["default_suffix"]
    with p5:
        st.write("")
        st.write("")
        btn_scan_trends = st.button("🔥 Scan", use_container_width=True, type="primary")

    if btn_scan_trends or "cached_us_trends" not in st.session_state:
        with st.spinner(f"Scraping trends ({radar_feed}, {trend_geo})..."):
            if radar_feed == "YouTube Autocomplete Live":
                scanned_trends = scan_youtube_live_breakout_trends(geo=trend_geo)
            elif radar_feed == "Combined Dual Radar":
                g_trends = fetch_google_trends_us(geo=trend_geo, hours=trend_hours, sort=trend_sort, category_id=sel_cat_id)
                yt_trends = scan_youtube_live_breakout_trends(geo=trend_geo)
                scanned_trends = yt_trends + g_trends
            else:
                scanned_trends = fetch_google_trends_us(geo=trend_geo, hours=trend_hours, sort=trend_sort, category_id=sel_cat_id)
            st.session_state["cached_us_trends"] = scanned_trends
            st.session_state["last_trends_scan_ts"] = datetime.datetime.now().strftime("%m/%d/%y, %I:%M %p")

    trends_data = st.session_state.get("cached_us_trends", [])
    scan_ts = st.session_state.get("last_trends_scan_ts", "")

    if trends_data:
        cov_index = get_trend_video_coverage()
        for tr in trends_data:
            tr["_cov"] = check_trend_coverage(tr["query"], cov_index)

        done_cnt = sum(1 for t in trends_data if t.get("_cov", {}).get("status") in ["uploaded", "ready"])
        uploaded_cnt = sum(1 for t in trends_data if t.get("_cov", {}).get("status") == "uploaded")
        st.markdown(f"### Trends · {scan_ts} ({len(trends_data)} Active · **{done_cnt} Covered [{uploaded_cnt} Published]**)")

        niche_col1, niche_col2, niche_col3 = st.columns([1.5, 1.2, 1.3])
        with niche_col1:
            niche_keyword = st.text_input("Filter Topic:", placeholder="keyword...", key="trend_topic_filter")
        with niche_col2:
            status_filter = st.selectbox(
                "Video Status:",
                ["All Trends", "⚪ Fresh Only (Not Done)", "✅ Done / Ready Only"],
                index=0,
                key="trend_status_filter"
            )
        with niche_col3:
            video_topic_suffix = st.text_input("Suffix:", value=cat_default_suffix, placeholder="e.g. gameplay", key="trend_yt_suffix")

        filtered_trends = trends_data
        if niche_keyword.strip():
            kw_low = niche_keyword.strip().lower()
            filtered_trends = [t for t in filtered_trends if kw_low in t["query"].lower()]
            st.caption(f"{len(filtered_trends)} matching '{niche_keyword}'")

        if status_filter == "⚪ Fresh Only (Not Done)":
            filtered_trends = [t for t in filtered_trends if t.get("_cov", {}).get("status") == "fresh"]
        elif status_filter == "✅ Done / Ready Only":
            filtered_trends = [t for t in filtered_trends if t.get("_cov", {}).get("status") in ["uploaded", "ready"]]

        # Explicitly sort: recent trends first by default
        if trend_sort == "recency":
            filtered_trends = sorted(filtered_trends, key=lambda t: t.get("started_ts", 0), reverse=True)
        elif trend_sort == "search-volume":
            filtered_trends = sorted(filtered_trends, key=lambda t: t.get("search_vol", 0), reverse=True)

        with st.container(height=650):
            for idx, tr in enumerate(filtered_trends[:30]):
                cov = tr.get("_cov") or check_trend_coverage(tr["query"], cov_index)
                cov_status = cov.get("status", "fresh")
                cov_badge = cov.get("badge", "")

                if cov_status == "uploaded":
                    prefix = f"✅ DONE ({cov['uploaded_count']}) · "
                elif cov_status == "ready":
                    prefix = f"📦 READY ({cov['ready_count']}) · "
                else:
                    prefix = "⚪ "

                header = f"{prefix}#{idx+1} {tr['query'].upper()} — ⏱️ {tr['started_time']} ({tr['search_vol_display']})"

                with st.expander(header, expanded=(idx < 2 and cov_status == "fresh")):
                    if cov_status == "uploaded":
                        st.success(f"✅ **Video Produced & Published ({cov['uploaded_count']} live):** Already covered on YouTube Studio! ({cov['ready_count']} additional in ready queue)")
                    elif cov_status == "ready":
                        st.info(f"📦 **Video Produced ({cov['ready_count']} clips ready):** {cov['ready_shorts']} Shorts + {cov['ready_landscapes']} Videos generated in `ready_to_upload/`.")

                    c1, c2 = st.columns([2.2, 1.8])
                    with c1:
                        st.markdown(f"**Vol:** `{tr['search_vol_display']}` | **Started:** `{tr['started_time']}` (🟢 Active)")
                        st.markdown(f"**Breakdown:** *{tr['breakdown_display']}*")
                        st.markdown(f"[🔗 Search]({tr['search_link']}) | [📈 Explore]({tr['explore_link']})")

                        if st.button("📰 Load News", key=f"btn_news_{idx}"):
                            news_items = get_trend_news_articles(tr['query'], max_articles=3)
                            tr["news_articles"] = news_items
                            if news_items:
                                st.write("**Top News:**")
                                for ni in news_items:
                                    st.markdown(f"- [{ni['title']}]({ni['url']}) *({ni['source']})*")
                            else:
                                st.caption("No news articles.")

                        if st.button("🔴 Live YouTube Search Queries", key=f"btn_yt_suggest_{idx}"):
                            yt_breakouts = fetch_youtube_search_breakouts(tr['query'], max_items=6)
                            tr["yt_breakouts"] = yt_breakouts
                            if yt_breakouts:
                                st.write("**Realtime YouTube Autocomplete Breakouts:**")
                                for yb in yt_breakouts:
                                    st.markdown(f"- 🔍 `{yb}`")
                            else:
                                st.caption("No direct YouTube suggest variants.")
                    with c2:
                        st.markdown("##### Actions")
                        action_btn_label = "🔄 Re-Produce & Publish" if cov_status == "uploaded" else ("⚡ Produce More Clips" if cov_status == "ready" else "🚀 Produce & Publish")
                        action_btn_type = "secondary" if cov_status in ["uploaded", "ready"] else "primary"

                        if st.button(action_btn_label, key=f"btn_pkg_{idx}", type=action_btn_type, use_container_width=True):
                            with st.spinner(f"Producing '{tr['query']}'..."):
                                def manual_update_status(cur_q, stg, stg_name, detail, pct, s_done, v_done):
                                    set_daemon_progress(
                                        active=True,
                                        current_trend=cur_q,
                                        stage=stg,
                                        total_stages=5,
                                        stage_name=stg_name,
                                        step_detail=detail,
                                        next_step="Instant Public Publishing" if stg < 5 else "Completed",
                                        percent=pct,
                                        shorts_done=s_done,
                                        videos_done=v_done
                                    )
                                pkg_res = produce_trend_package(
                                    tr,
                                    auto_upload=is_authenticated(),
                                    progress_callback=lambda m: push_daemon_log(f"[{tr['query']}] {m}"),
                                    status_callback=manual_update_status
                                )
                                manual_update_status(tr['query'], 5, "Completed", f"Published {pkg_res['total_rendered']} assets", 100, len(pkg_res.get('shorts', [])), len(pkg_res.get('landscapes', [])))
                                st.success(f"✓ Published {pkg_res['total_rendered']} assets (Public)!")
                                st.rerun()

                        if st.button(f"🎬 Send to Manual Clipper (Stage 2)", key=f"btn_clip_{idx}", use_container_width=True):
                            with st.spinner(f"Searching YouTube..."):
                                vids = search_trend_source_videos(tr['query'], max_results=3, topic_filter=video_topic_suffix)
                                if vids:
                                    top_vid = vids[0]
                                    st.session_state["manual_source_urls"] = top_vid["url"]
                                    st.session_state["txt_raw_url"] = top_vid["url"]
                                    st.success(f"✓ Sent '{top_vid['title']}' to Stage 2 (Manual Clipper)!")
                                    st.rerun()
                                else:
                                    st.warning("No YouTube videos found.")

                        if st.button(f"⚡ Send to Trend Factory (Stage 2)", key=f"btn_send_factory_{idx}", use_container_width=True):
                            st.session_state["target_trend_query"] = tr["query"]
                            st.success(f"✓ Selected '{tr['query']}' for Stage 2 Trend Factory!")
                            st.rerun()
    else:
        st.info("No trends. Click 'Scan' above.")


def render_trend_factory():
    st.markdown("<div class='section-title'>DAEMON & TELEMETRY</div>", unsafe_allow_html=True)

    target_q = st.session_state.get("target_trend_query", "")
    if target_q:
        st.info(f"🎯 **Target Trend from Stage 1:** `{target_q}`")
        t_c1, t_c2 = st.columns([1.5, 1])
        with t_c1:
            if st.button(f"⚡ Produce 8 Tier-1 US Shorts for '{target_q}' Now", type="primary", use_container_width=True, key="btn_run_target_trend"):
                with st.spinner(f"Producing 8 Tier-1 Shorts for '{target_q}'..."):
                    cached = st.session_state.get("cached_us_trends", [])
                    match = next((t for t in cached if t["query"] == target_q), {"query": target_q, "trend_breakdown": [target_q]})
                    pkg_res = produce_trend_package(match, auto_upload=False)
                    if pkg_res:
                        st.success(f"✓ Produced {pkg_res.get('total_rendered', 0)} assets! Ready in Stage 3 Quality Gate.")
                        st.rerun()
        with t_c2:
            if st.button("✕ Clear Target", key="btn_clear_target_q"):
                del st.session_state["target_trend_query"]
                st.rerun()

    d_cfg = load_daemon_config()
    d_running = is_trend_daemon_running()

    if d_running:
        st.success("🟢 **Active:** 24/7 US Trends → Public.")
        if st.button("⏹️ Stop", use_container_width=True, type="secondary", key="btn_stop_trend_daemon"):
            stop_trend_daemon()
            st.rerun()
    else:
        st.warning("⚪ **Idle:** Daemon stopped.")
        if st.button("▶️ Start Daemon", use_container_width=True, type="primary", key="btn_start_trend_daemon"):
            start_trend_daemon()
            st.rerun()

    with st.expander("⚙️ Daemon Config", expanded=False):
        d_poll = st.number_input("Poll (sec)", min_value=60, max_value=3600, value=int(d_cfg.get("poll_interval_sec", 300)), step=60, key="cfg_daemon_poll")
        d_autoup = st.checkbox("Publish Public", value=bool(d_cfg.get("auto_upload", True)), key="cfg_daemon_autoup")
        if st.button("💾 Save", key="btn_save_daemon_cfg", use_container_width=True):
            d_cfg["poll_interval_sec"] = d_poll
            d_cfg["auto_upload"] = d_autoup
            save_daemon_config(d_cfg)
            st.success("Saved")

    from portal_stages import render_watermark_options_expander
    render_watermark_options_expander("trend_factory", "Trend Factory")

    @st.fragment(run_every="3s")
    def render_trend_daemon_telemetry_box():
        t_prog = get_daemon_progress()
        is_t_run = is_trend_daemon_running()
        t_pct = int(t_prog.get("percent", 0))
        t_stage = t_prog.get("stage_name", "Idle")
        t_cur_trend = t_prog.get("current_trend", "")
        t_detail = t_prog.get("step_detail", "Idle")
        t_shorts = t_prog.get("shorts_done", 0)
        t_vids = t_prog.get("videos_done", 0)

        st.markdown("<div class='section-title'>TELEMETRY</div>", unsafe_allow_html=True)
        if is_t_run or t_pct > 0:
            st.progress(max(0.0, min(1.0, t_pct / 100.0)), text=f"{t_stage} ({t_pct}%) — {t_detail}")
        else:
            st.progress(0.0, text="Paused / Idle")

        tm1, tm2 = st.columns(2)
        with tm1:
            st.metric("Stage", t_stage, delta=f"{t_pct}%" if (is_t_run or t_pct > 0) else None)
        with tm2:
            disp_trend = f"{t_cur_trend[:18]}..." if len(t_cur_trend) > 18 else (t_cur_trend or "Scanning...")
            st.metric("Trend", disp_trend, help=t_cur_trend)

        tm3, tm4 = st.columns(2)
        with tm3:
            disp_sub = f"{t_detail[:22]}..." if len(t_detail) > 22 else t_detail
            st.metric("Sub-Step", disp_sub, help=t_detail)
        with tm4:
            st.metric("Assets", f"{t_shorts} Reels / {t_vids} Vids", delta=f"{t_shorts+t_vids} total" if (t_shorts+t_vids) > 0 else None)

        st.markdown("<div class='section-title'>EVENTS</div>", unsafe_allow_html=True)
        t_logs = get_daemon_logs(max_lines=40)
        if t_logs:
            st.code("\n".join(t_logs[-25:]), language="bash")
        else:
            st.caption("No events.")

    render_trend_daemon_telemetry_box()


def render_live_radar():
    st.markdown("<div class='section-title'>LIVE RADAR</div>", unsafe_allow_html=True)
    st.caption("Live Broadcasting Scanner: monitors target channels for real-time streams.")
    l_cfg = load_livestream_config()
    channels = l_cfg.get("channels", [])
    if st.button("📡 Probe All Channels Now", type="primary", key="btn_probe_radar"):
        with st.spinner("Probing channels..."):
            for ch in channels:
                info = check_if_stream_live(ch)
                if info and info.get("is_live"):
                    st.success(f"🔴 LIVE: **{info.get('title')}** ({info.get('channel')})")
                else:
                    st.info(f"⚪ Offline: {ch}")
    st.markdown("##### Monitored Channels")
    for ch in channels:
        st.markdown(f"- 📺 [{ch}]({ch})")


def render_vod_radar():
    st.markdown("<div class='section-title'>VOD RADAR</div>", unsafe_allow_html=True)
    st.caption("Creator Channel Surveillance: monitors latest uploads for autonomous clipping.")
    w_cfg = load_watcher_config()
    channels = w_cfg.get("channels", [])
    st.markdown(f"**Target Channels ({len(channels)}):**")
    for idx, ch in enumerate(channels):
        c_v1, c_v2 = st.columns([3, 1.2])
        with c_v1:
            st.markdown(f"- 📹 [{ch}]({ch})")
        with c_v2:
            if st.button("🎬 Clip in Stage 2", key=f"btn_send_vod_{idx}", use_container_width=True):
                st.session_state["manual_source_urls"] = ch
                st.success(f"✓ Channel sent to Stage 2 Manual Clipper!")
                st.rerun()


def render_learned_topics():
    st.markdown("<div class='section-title'>LEARNED TOPIC INTELLIGENCE</div>", unsafe_allow_html=True)
    st.caption("Closed-Loop Data Engine: High-CPM topics and tags discovered from actual viewership.")
    boost = get_learned_seo_boost()
    opt_dur = boost.get("target_duration_sec", 34.0)
    dur_rng = boost.get("duration_range", (24.0, 48.0))
    tags_list = ", ".join(boost.get("high_cpm_tags", []))
    utc_hours = str(boost.get("peak_utc_hours", [14, 18, 20]))

    st.info(f"Data-Driven Optimal Duration: **{opt_dur}s** (Range: {dur_rng[0]}s - {dur_rng[1]}s)")
    st.markdown(f"**Top High-CPM Tags:** `{tags_list}`")
    st.markdown(f"**Peak Viewing Windows (UTC):** `{utc_hours}` (10 AM - 5 PM US EST)")

    if boost.get("boost_keywords"):
        top_kw = boost["boost_keywords"][0]

        def _apply_top_learned_kw(kw=top_kw):
            st.session_state["trend_topic_filter"] = kw
            st.session_state["applied_top_kw"] = kw

        st.button(
            f"🎯 Apply Top Learned Keyword ('{top_kw}') to Stage 1 Research Filter",
            key="btn_apply_learned_kw",
            type="primary",
            on_click=_apply_top_learned_kw
        )
        if st.session_state.get("applied_top_kw"):
            st.success(f"✓ Research filtered by '{st.session_state['applied_top_kw']}'! Switch to 'Trends Hunter' tab.")


def render_instagram_clipper():
    st.markdown("<div class='section-title'>STAGE 2: INSTAGRAM BULK INGESTION & CLIPPER</div>", unsafe_allow_html=True)
    st.caption("Auto-calculates all reels from target @account, downloads 1-by-1 sequentially without breaking, with full Pause & Resume capability.")

    # 1. Session & Account Discovery Row
    top_c1, top_c2 = st.columns([1.5, 1.2], gap="medium")

    with top_c1:
        target_uname = st.text_input(
            "Target Instagram Account (@username or Profile URL)",
            placeholder="@gta6.only or https://www.instagram.com/username/",
            key="insta_target_uname"
        )
        st.caption("💡 Supports @username, profile link, or comma/newline-separated direct Reel URLs.")
        scan_limit = st.slider("Scan Search Depth (Max Reels)", min_value=5, max_value=150, value=50, step=5, key="insta_scan_limit")

        scan_btn = st.button("🔍 Auto-Calculate All Reels on Account", type="secondary", use_container_width=True, key="btn_scan_insta")

    with top_c2:
        st.markdown("<div class='section-title'>SESSION & ANTI-BOT SHIELD</div>", unsafe_allow_html=True)
        saved_sess = get_session_cookie()
        sess_input = st.text_input(
            "Instagram Session ID (sessionid cookie)",
            value=saved_sess,
            type="password",
            placeholder="Paste sessionid cookie to bypass rate-limits",
            key="insta_session_input"
        )
        if st.button("💾 Save SessionID", key="btn_save_sess", use_container_width=True):
            save_session_cookie(sess_input)
            st.success("✓ SessionID saved locally! Rate-limits unlocked.")

        st.caption("🛡️ **Auto-Protection:** Broadcast cricket/sports reels are filtered out automatically. Background songs permanently banned.")

    # Auto-Calculate Action
    if scan_btn and target_uname.strip():
        active_sess = sess_input.strip() or saved_sess
        if sess_input.strip() and sess_input.strip() != saved_sess:
            save_session_cookie(sess_input.strip())
        with st.spinner(f"Connecting to Instagram & calculating all reels for '{target_uname}'..."):
            calc_data = scan_and_calculate_account_reels(
                target=target_uname.strip(),
                session_id=active_sess,
                limit=scan_limit
            )
            st.session_state["insta_calc_data"] = calc_data

    # Pre-load cached discovery from subagent if not yet calculated in current session
    if "insta_calc_data" not in st.session_state:
        c_p = Path("insta_discovered_cache.json")
        if c_p.exists():
            try:
                with open(c_p, "r", encoding="utf-8") as f:
                    c_dict = json.load(f)
                    req_key = target_uname.strip().lstrip("@") if target_uname.strip() else "gta6.only"
                    if req_key in c_dict:
                        st.session_state["insta_calc_data"] = c_dict[req_key]
            except Exception:
                pass

    # Display Discovery Card or Actionable Error Guidance
    calc_data = st.session_state.get("insta_calc_data")
    if calc_data and calc_data.get("reels"):
        reels_list = calc_data.get("reels", [])
        total_p = calc_data.get("total_account_posts", len(reels_list))
        filt_s = calc_data.get("filtered_sports_count", 0)
        f_count = calc_data.get("follower_count")
        f_str = f" | • <b>Followers:</b> <b style='color:#38bdf8;'>{f_count:,}</b>" if f_count else ""
        fn_str = f" ({calc_data.get('full_name')})" if calc_data.get("full_name") and calc_data.get("full_name") != calc_data.get("account") else ""

        st.markdown(
            f"""
            <div style="border:1px solid #0284c7; background:#082f49; border-radius:8px; padding:12px; margin-bottom:12px;">
                <b style="color:#38bdf8; font-size:1.0rem;">📊 Account Discovery: @{calc_data.get('account')}{fn_str}</b><br>
                <span style="color:#e0f2fe; font-size:0.85rem;">
                    • <b>Total Account Posts:</b> {total_p} | 
                    • <b>Discovered Video Reels:</b> <b style="color:#4ade80;">{len(reels_list)}</b>{f_str} | 
                    • <b>Cricket/Sports Filtered:</b> <b style="color:#fbbf24;">{filt_s} excluded</b>
                </span>
            </div>
            """,
            unsafe_allow_html=True
        )
    elif calc_data and not calc_data.get("reels"):
        acc_name = calc_data.get('account', target_uname)
        st.warning(
            f"⚠️ **Could not calculate reels for @{acc_name} without authentication.**\n\n"
            f"Instagram rate-limits unauthenticated profile requests (HTTP 429). "
            f"To unlock full account scanning:\n"
            f"1. Open [instagram.com](https://www.instagram.com) in your browser.\n"
            f"2. Press **F12** -> **Application** -> **Cookies** -> `https://www.instagram.com`.\n"
            f"3. Copy the value of the `sessionid` cookie.\n"
            f"4. Paste it in the **Instagram Session ID** field on the right and click **Save SessionID**.\n\n"
            f"*(Alternatively: paste individual Reel URLs directly into the target input box separated by commas or newlines.)*"
        )


    from portal_stages import render_watermark_options_expander
    render_watermark_options_expander("insta", "Instagram Clipper")

    # 2. Crawler State & Live Sequential Progress
    st.markdown("<div class='section-title'>1-BY-1 SEQUENTIAL INGESTION DASHBOARD</div>", unsafe_allow_html=True)

    @st.fragment(run_every=3 if is_crawler_active() else None)
    def render_live_crawler_dashboard():
        c_state = load_crawler_state()
        crawler_status = c_state.get("status", "idle")
        crawler_active = is_crawler_active()

        # Self-healing: if status says running but background thread died, mark as paused
        if crawler_status == "running" and not crawler_active:
            crawler_status = "paused"
            c_state["status"] = "paused"
            save_crawler_state(c_state)

        total_q = c_state.get("total_count", 0)
        completed_q = len(c_state.get("completed_ids", []))
        failed_q = len(c_state.get("failed_ids", []))
        curr_cap = c_state.get("current_reel_caption", "None")

        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        with kpi1:
            status_badges = {
                "running": "🟢 RUNNING (1-by-1)",
                "paused": "⏸️ PAUSED (Click Resume)",
                "completed": "🏁 COMPLETED",
                "idle": "⚪ IDLE"
            }
            st.metric("Crawler Status", status_badges.get(crawler_status, "⚪ IDLE"))
        with kpi2:
            st.metric("Progress", f"{completed_q} / {total_q} Completed")
        with kpi3:
            st.metric("Active Account", f"@{c_state.get('account', 'None')}")
        with kpi4:
            st.metric("Failed / Skipped", f"{failed_q}")

        prog_pct = (completed_q / max(1, total_q)) if total_q > 0 else 0.0
        st.progress(prog_pct)

        if crawler_status == "running":
            st.info(f"⏳ Currently downloading & processing: **'{curr_cap}'**...")

        # Live Log Console
        with st.expander("Live Sequential Ingestion Logs", expanded=(crawler_status == "running")):
            insta_logs = get_insta_logs(30)
            st.code("\n".join(insta_logs) if insta_logs else "No events logged yet.", language="log")

        if completed_q > 0:
            st.success(f"✓ {completed_q} clips ready in `ready_to_upload/` with YouTube SEO sidecars!")
            st.markdown(
                "👉 **Switch to Stage 3 (Quality & SEO Checklist)** to review monetization checks or approve for Studio upload."
            )

    render_live_crawler_dashboard()

    c_state = load_crawler_state()
    crawler_status = c_state.get("status", "idle")
    if crawler_status == "running" and not is_crawler_active():
        crawler_status = "paused"

    # Workflow Mode Selector
    proc_mode = st.radio(
        "Repurposing Workflow",
        [
            "⚡ Direct Repurpose (Fast 1080x1920 Clean Fit + Ollama SEO)",
            "🎬 Full AI Transform (Whisper Karaoke Subtitles + 3.2s Punch Zoom + Hook Banner)"
        ],
        index=0 if c_state.get("mode", "direct") == "direct" else 1,
        horizontal=True,
        key="insta_proc_mode_ctrl"
    )
    mode_val = "transform" if "Full AI" in proc_mode else "direct"

    # Control Action Buttons (Start / Resume / Pause / Reset)
    btn_c1, btn_c2, btn_c3, btn_c4 = st.columns(4)

    with btn_c1:
        if crawler_status == "paused":
            if st.button("▶️ Resume Ingestion", type="primary", use_container_width=True, key="btn_resume_crawler"):
                start_or_resume_crawler(account=c_state.get("account", ""), mode=mode_val)
                st.success("✓ Resumed crawler from exact checkpoint!")
                st.rerun()
        elif crawler_status != "running":
            reels_to_start = (calc_data.get("reels", []) if calc_data else []) or c_state.get("reels_queue", [])
            acc_to_start = (calc_data.get("account") if calc_data else "") or c_state.get("account", "") or target_uname.strip().lstrip("@")
            can_start = bool(reels_to_start and acc_to_start)

            if st.button(f"▶️ Start Ingest ({len(reels_to_start)} Reels)", type="primary", disabled=not can_start, use_container_width=True, key="btn_start_crawler"):
                start_or_resume_crawler(account=acc_to_start, reels=reels_to_start, mode=mode_val)
                st.success(f"✓ Started 1-by-1 ingestion for @{acc_to_start}!")
                st.rerun()
        else:
            st.button("▶️ Ingesting Active...", disabled=True, use_container_width=True)

    with btn_c2:
        if crawler_status == "running":
            if st.button("⏸️ Pause Ingestion", type="secondary", use_container_width=True, key="btn_pause_crawler"):
                pause_crawler()
                st.warning("⏸️ Ingestion paused. State saved!")
                st.rerun()
        else:
            st.button("⏸️ Pause", disabled=True, use_container_width=True)

    with btn_c3:
        if st.button("🔄 Reset Queue / Clear", type="secondary", use_container_width=True, key="btn_reset_crawler"):
            reset_crawler()
            st.session_state["insta_calc_data"] = None
            st.info("Queue and progress reset.")
            st.rerun()

    with btn_c4:
        if st.button("🔄 Refresh Status", use_container_width=True, key="btn_refresh_crawler_status"):
            st.rerun()


def render_campaign_clipper():
    st.markdown("<div class='section-title'>STAGE 2: CONTENTREWARDS CAMPAIGN CLIPPER</div>", unsafe_allow_html=True)
    st.caption("Auto-pull live campaigns from ContentRewards.com marketplace, adopt campaign goals & KPIs, and auto-produce brand-compliant Shorts.")

    # 1. ContentRewards Live Marketplace Pull Bar
    st.markdown("<div class='section-title'>🌐 CONTENTREWARDS LIVE MARKETPLACE (LIVE PULL)</div>", unsafe_allow_html=True)

    col_pull1, col_pull2 = st.columns([1.3, 1.7], gap="medium")
    with col_pull1:
        if st.button("🔄 Pull Live Campaigns from ContentRewards.com", type="primary", use_container_width=True, key="btn_pull_cr"):
            with st.spinner("Connecting to ContentRewards.com/c/discover & extracting active campaigns..."):
                pulled = fetch_contentrewards_campaigns(limit=50, force_refresh=True)
                if pulled:
                    st.success(f"✓ Successfully pulled {len(pulled)} live campaigns from ContentRewards.com!")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("Failed to fetch campaigns. Please verify network connectivity.")

    pulled_campaigns = fetch_contentrewards_campaigns(limit=50, force_refresh=False)

    with col_pull2:
        if pulled_campaigns:
            st.caption(f"✓ **{len(pulled_campaigns)} Live Campaigns Discovered** on ContentRewards.com. Select any campaign below to adopt its goals, payout rate & KPIs.")
        else:
            st.caption("Click 'Pull Live Campaigns' to discover active payout campaigns from ContentRewards.com.")

    # Campaign Selector / Adoption Row
    if pulled_campaigns:
        camp_display_map = {
            f"{c['name']} | ${c['cpm_rate']:.2f}/1K | Budget: {c['budget_total']} | {', '.join(c.get('platforms', ['Shorts']))}": c
            for c in pulled_campaigns
        }
        selected_display = st.selectbox(
            "Select Live Campaign from ContentRewards Marketplace",
            list(camp_display_map.keys()),
            key="sel_live_cr_camp"
        )
        selected_c_item = camp_display_map[selected_display]

        col_adopt1, col_adopt2 = st.columns([1.2, 1.8])
        with col_adopt1:
            if st.button(f"⚡ Pull & Adopt '{selected_c_item['name'][:22]}' Goals", type="primary", use_container_width=True, key=f"btn_adopt_{selected_c_item['id']}"):
                with st.spinner(f"Pulling brief, guidelines & assets for '{selected_c_item['name']}'..."):
                    adopted = import_contentrewards_campaign(selected_c_item["url"])
                    st.success(f"✓ Adopted '{adopted['name']}'! CPM: ${adopted['cpm_rate']:.2f}, Goal: ${adopted['revenue_goal']:,.0f}")
                    time.sleep(0.5)
                    st.rerun()
        with col_adopt2:
            st.markdown(f"🔗 [Inspect on ContentRewards.com ↗]({selected_c_item['url']}) &bull; **Platforms:** `{', '.join(selected_c_item.get('platforms', []))}` &bull; **Spend:** `{selected_c_item.get('budget_spent', '$0')} / {selected_c_item.get('budget_total', '$0')}`")

    st.divider()

    camp_db = load_campaigns_db()
    campaigns = camp_db.get("campaigns", {})
    active_camp = get_active_campaign()

    # Top Campaign Selector & Creator
    top_c1, top_c2 = st.columns([1.6, 1.2], gap="medium")

    with top_c1:
        camp_options = {c["name"]: cid for cid, c in campaigns.items()} if campaigns else {}
        if camp_options:
            cur_active_name = active_camp.get("name") if active_camp else list(camp_options.keys())[0]
            selected_camp_name = st.selectbox("Select Active Working Campaign", list(camp_options.keys()), index=list(camp_options.keys()).index(cur_active_name) if cur_active_name in camp_options else 0, key="sel_active_campaign")
            if selected_camp_name and camp_options[selected_camp_name] != camp_db.get("active_campaign_id"):
                set_active_campaign(camp_options[selected_camp_name])
                st.rerun()

        with st.expander("➕ Or Create Custom / Offline Campaign Profile", expanded=(not camp_options)):
            with st.form("form_new_campaign"):
                new_c_name = st.text_input("Campaign Name", placeholder="e.g. DraftKings Podcast Clipper")
                n_col1, n_col2 = st.columns(2)
                with n_col1:
                    new_cpm = st.number_input("Payout Rate ($ / 1,000 views)", min_value=0.5, max_value=50.0, value=3.5, step=0.5)
                    new_country = st.selectbox("Target Country / Geo", ["United States (US)", "United Kingdom (UK)", "Canada (CA)", "Australia (AU)", "Global / Worldwide"], index=0)
                with n_col2:
                    new_goal = st.number_input("Revenue Payout Cap / Goal ($)", min_value=50.0, max_value=10000.0, value=500.0, step=50.0)
                    new_audience = st.selectbox("Target Audience", ["Gamers & Esports", "Tech & AI Enthusiasts", "Crypto & Finance", "Pop Culture & Comedy", "Sports & Fitness", "General Viral"], index=0)

                new_brief = st.text_area("Campaign Brief & Instructions", placeholder="e.g. Highlight shocking podcast moments, debates, and tech updates. Mention sponsor code in comments.")
                new_tags = st.text_input("Mandatory Hashtags", placeholder="#DraftKings #Sponsor #Shorts")
                new_link = st.text_input("Sponsor Link / Promo Code", placeholder="https://draftkings.com/promo/zelmu (Code: ZELMU)")
                new_src = st.text_input("Default Source Footage URL", placeholder="https://www.youtube.com/watch?v=... or local MP4 path")

                if st.form_submit_button("💾 Save Campaign Profile", type="primary", use_container_width=True):
                    if new_c_name.strip():
                        new_id = save_campaign({
                            "name": new_c_name.strip(),
                            "cpm_rate": new_cpm,
                            "revenue_goal": new_goal,
                            "target_country": new_country,
                            "target_audience": new_audience,
                            "description_brief": new_brief,
                            "mandatory_hashtags": new_tags,
                            "sponsor_link": new_link,
                            "source_footage_url": new_src,
                            "status": "active"
                        })
                        st.success(f"✓ Campaign '{new_c_name}' created and set as active!")
                        st.rerun()

    with top_c2:
        if active_camp:
            st.markdown("<div class='section-title'>CAMPAIGN KPI GOALS</div>", unsafe_allow_html=True)
            cpm_r = float(active_camp.get("cpm_rate", 1.0))
            rev_g = float(active_camp.get("revenue_goal", 500.0))
            t_views = int((rev_g / max(0.1, cpm_r)) * 1000)

            st.metric("Revenue Cap / Goal", f"${rev_g:,.2f}", delta=f"${cpm_r:.2f} CPM")
            st.metric("Target Views Needed (KPI)", f"{t_views:,} views")
            st.caption(f"**Audience:** {active_camp.get('target_audience', 'General')} | **Geo:** {active_camp.get('target_country', 'US')}")
            st.caption(f"**Hashtags:** `{active_camp.get('mandatory_hashtags', '#Shorts')}`")

            if st.button("🗑️ Remove Campaign", type="secondary", use_container_width=True, key=f"btn_del_camp_{active_camp.get('id')}"):
                delete_campaign(active_camp.get("id"))
                st.warning("Campaign removed.")
                st.rerun()

    if not active_camp:
        st.info("No active campaign configured. Select a campaign from the live marketplace above to adopt its goals.")
        return

    # Full Campaign Brief, Instructions & Guidelines
    with st.expander("📋 Full Campaign Brief, Instructions & Deliverables", expanded=True):
        st.markdown(f"**Campaign:** `{active_camp.get('name')}` &bull; [Inspect Live on ContentRewards ↗]({active_camp.get('sponsor_link', 'https://contentrewards.com')})")
        full_desc = active_camp.get("description_brief", "No detailed description provided.")
        st.info(full_desc)

    from portal_stages import render_watermark_options_expander
    render_watermark_options_expander("campaign", "Campaign Clipper")

    # Campaign Clipping Engine
    st.markdown("<div class='section-title'>⚡ 1-CLICK CAMPAIGN CLIPPING GENERATOR</div>", unsafe_allow_html=True)
    c_src_url = st.text_input("Source Video / Podcast URL for this Campaign", value=active_camp.get("source_footage_url", ""), placeholder="https://www.youtube.com/watch?v=... or Channel URL", key="camp_src_url_input")

    proc_c1, proc_c2 = st.columns([1.5, 1])
    with proc_c1:
        st.info(f"🎯 **Campaign Brief Active:** Generating 6 Shorts matching `{active_camp.get('target_audience')}` audience in `{active_camp.get('target_country')}` with `{active_camp.get('mandatory_hashtags')}`.")
    with proc_c2:
        if st.button("🚀 Generate 6 Campaign Shorts", type="primary", use_container_width=True, key="btn_gen_camp_shorts"):
            if not c_src_url.strip():
                st.error("Please provide a valid source video URL.")
                return

            p_box = st.empty()
            p_bar = st.progress(0.0)
            p_box.info("🧠 Analyzing campaign brief, target audience, and generating AI scripts...")

            scripts = generate_campaign_scripts(active_camp, source_title=active_camp.get("name", "Campaign"))
            p_bar.progress(0.25)
            p_box.info(f"✓ Generated {len(scripts)} scripts. Sourcing visual footage...")

            work_dir = Path("workspace") / f"camp_{int(time.time())}"
            work_dir.mkdir(parents=True, exist_ok=True)
            raw_vid = work_dir / "raw_source.mp4"

            try:
                from editor import download_video_section
                download_video_section(c_src_url.strip(), start_sec=30.0, end_sec=85.0, output_mp4_path=raw_vid)
            except Exception:
                pass

            from trend_producer import create_solid_color_broll
            if not raw_vid.exists() or raw_vid.stat().st_size < 100000:
                raw_vid = create_solid_color_broll(work_dir / "broll.mp4", duration=45.0, is_vertical=True)

            p_bar.progress(0.50)
            p_box.info("🎬 Rendering 6 campaign-branded vertical Shorts with karaoke captions & 3.2s zoom...")

            from editor import generate_piper_tts, generate_karaoke_ass, render_mode_a_short
            from trend_producer import extract_whisper_word_timestamps, get_audio_duration

            ready_dir = Path("ready_to_upload")
            ready_dir.mkdir(parents=True, exist_ok=True)
            camp_id = active_camp.get("id")
            ts = int(time.time())

            produced_clips = []
            for idx, sc in enumerate(scripts):
                s_title = sc.get("title", f"Campaign Clip {idx+1}")
                s_hook = sc.get("hook", "⚡ SPONSOR ALERT")
                s_script = sc.get("script", "")

                wav_p = work_dir / f"tts_{idx}.wav"
                generate_piper_tts(s_script, wav_p)
                dur = get_audio_duration(wav_p)

                words = extract_whisper_word_timestamps(wav_p, s_script, dur, work_dir, idx)
                ass_p = work_dir / f"subs_{idx}.ass"
                generate_karaoke_ass(words, ass_p, style_preset="neon")

                final_mp4 = ready_dir / f"Short_Camp_{camp_id}_{idx+1}_{ts}.mp4"

                broll_offset = (idx * 9) % 40
                cut_vis = work_dir / f"vis_{idx}.mp4"
                subprocess.run([
                    "ffmpeg", "-y",
                    "-ss", f"{broll_offset:.1f}",
                    "-stream_loop", "-1",
                    "-i", str(raw_vid),
                    "-i", str(wav_p),
                    "-t", f"{dur:.2f}",
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    str(cut_vis)
                ], capture_output=True)

                render_mode_a_short(
                    source_video=cut_vis,
                    ass_subtitles=ass_p,
                    output_short_path=final_mp4,
                    flagged_profanities=[],
                    split_layout=False,
                    enable_tracking=False,
                    hook_title=s_hook,
                    enable_pacing_zoom=True,
                    enable_anti_content_id=True,
                    enable_music_ducking=False,
                    enable_sfx=True
                )

                if final_mp4.exists():
                    produced_clips.append(final_mp4)
                    sidecar_p = final_mp4.with_suffix(".json")
                    with open(sidecar_p, "w", encoding="utf-8") as sf:
                        json.dump({
                            "title": s_title[:70],
                            "description": sc.get("description", f"🔥 Sponsored breakdown\n\n{active_camp.get('mandatory_hashtags')}"),
                            "tags": [t.strip("#") for t in active_camp.get("mandatory_hashtags", "").split() if t.strip()] + ["Shorts", "Trending"],
                            "category_id": "24",
                            "privacy_status": "public",
                            "approved": False,
                            "stage": "pending_quality_review",
                            "source": "contentrewards_campaign",
                            "campaign_id": camp_id,
                            "campaign_name": active_camp.get("name"),
                            "cpm_rate": active_camp.get("cpm_rate"),
                            "created_at": time.time()
                        }, sf, indent=2, ensure_ascii=False)

                p_bar.progress(0.50 + ((idx+1) / len(scripts)) * 0.50)

            p_box.success(f"✓ Successfully generated {len(produced_clips)} Campaign Shorts! All passed to Stage 3 Quality Review.")
            for cp in produced_clips:
                st.markdown(f"- 📦 `{cp.name}` &rarr; **Ready for Stage 3 Quality Check**")
            if st.button("➡️ Review in Stage 3 Quality Check", type="primary", key="btn_go_to_stage3_from_camp"):
                st.rerun()


# Instant Client-Side Tabs (Positioned inside Top Fixed Navbar beside logo)
tab_mc, tab_research, tab_prod, tab_quality, tab_upload, tab_analytics, tab_learning = st.tabs([
    "🎛️ Mission",
    "1. 🔍 Research",
    "2. ⚙️ Production",
    "3. ✅ Quality & SEO",
    "4. 🚀 Upload",
    "5. 📊 Analytics",
    "6. 🧠 Learning"
])

render_pipeline_ribbon(READY_DIR)

with tab_mc:
    render_mission_control()

with tab_research:
    sub_res1, sub_res2, sub_res3, sub_res4 = st.tabs([
        "🎯 Trends Hunter",
        "🔴 Live Radar",
        "🤖 VOD Radar",
        "💡 Learned Topics"
    ])
    with sub_res1:
        render_trend_hunter()
    with sub_res2:
        render_live_radar()
    with sub_res3:
        render_vod_radar()
    with sub_res4:
        render_learned_topics()

with tab_prod:
    sub_p1, sub_p2, sub_p3, sub_p4, sub_p5, sub_p6 = st.tabs([
        "⚡ Trend Factory (P1)",
        "🔴 Live Buffer (P2)",
        "🤖 VOD Watcher (P3)",
        "🎬 Manual Clipper",
        "📸 Insta Clipper",
        "🎯 Campaign Clipper (ContentRewards)"
    ])
    with sub_p1:
        render_trend_factory()
    with sub_p2:
        render_live_buffer()
    with sub_p3:
        render_vod_watcher()
    with sub_p4:
        render_manual_clipper()
    with sub_p5:
        render_instagram_clipper()
    with sub_p6:
        render_campaign_clipper()

with tab_quality:
    render_quality_seo_stage(READY_DIR)

with tab_upload:
    render_upload_stage()

with tab_analytics:
    render_analytics_stage()

with tab_learning:
    render_learning_stage()
