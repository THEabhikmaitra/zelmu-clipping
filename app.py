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
    search_trend_source_videos,
    get_trend_news_articles,
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
    get_livestream_progress
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
    }
    .navbar-status-group {
        display: flex;
        align-items: center;
        gap: 0.85rem;
        margin-right: 48px; /* Room for gear icon */
    }

    /* Instant Top Tabs (beside ZELMU logo in fixed top navbar) */
    div[data-testid="stTabs"] [role="tablist"] {
        position: fixed !important;
        top: 8px !important;
        left: 175px !important;
        z-index: 1004 !important;
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
        padding: 0 16px !important;
        font-size: 0.8rem !important;
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

    /* Top Nav Gear Settings Popover (Strictly 32x32px at top-right) */
    .stElementContainer:has(div[data-testid="stPopover"]) {
        position: fixed !important;
        top: 8px !important;
        right: 14px !important;
        width: 32px !important;
        height: 32px !important;
        z-index: 1005 !important;
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
        z-index: 1005 !important;
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

    /* Clean Form Elements */
    .stTextArea textarea, .stTextInput input, .stSelectbox [data-baseweb="select"] {
        background-color: #121215 !important;
        border: 1px solid #27272a !important;
        border-radius: 6px !important;
        color: #f4f4f5 !important;
        font-size: 0.84rem !important;
    }
    .stButton > button[kind="primary"] {
        background-color: #f4f4f5 !important;
        color: #09090b !important;
        font-weight: 500 !important;
        border: 1px solid #f4f4f5 !important;
        border-radius: 6px !important;
        font-size: 0.84rem !important;
        transition: opacity 0.15s ease;
    }
    .stButton > button[kind="primary"]:hover {
        opacity: 0.9;
    }
    .stButton > button[kind="secondary"] {
        background-color: #121215 !important;
        color: #a1a1aa !important;
        border: 1px solid #27272a !important;
        border-radius: 6px !important;
        font-size: 0.8rem !important;
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
        font-size: 11.5px !important;
        color: #a1a1aa !important;
        max-height: 320px !important;
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
    }
    div[data-testid="stCode"] button[title="Copy to clipboard"]:hover,
    div[data-testid="stCode"] [data-testid="stCodeCopyButton"]:hover {
        opacity: 1 !important;
        background: #27272a !important;
        border-color: #3f3f46 !important;
    }
    .section-title {
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.06em;
        color: #71717a;
        margin-top: 1.25rem;
        margin-bottom: 0.5rem;
        text-transform: uppercase;
    }
    .sidebar-header {
        font-size: 0.68rem;
        font-weight: 600;
        letter-spacing: 0.06em;
        color: #71717a;
        text-transform: uppercase;
        margin-bottom: 0.5rem;
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

# Watermark Logo Popover (Triggered by ⚙️ Icon in Top Fixed Nav)
active_logo_path = Path("logo.png") if Path("logo.png").exists() else None

with st.popover("⚙️", help="Watermark Settings"):
    st.caption("WATERMARK OVERLAY")
    logo_file = st.file_uploader("Upload PNG/JPG", type=["png", "jpg", "jpeg"])
    if logo_file is not None:
        active_logo_path = Path("logo.png")
        with open(active_logo_path, "wb") as f:
            f.write(logo_file.read())
        st.success("Logo saved!")
        st.rerun()
    
    if Path("logo.png").exists():
        st.image("logo.png", caption="Active Watermark", width=90)
        if st.button("Remove Watermark", type="secondary", use_container_width=True):
            Path("logo.png").unlink(missing_ok=True)
            st.rerun()

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
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Produce",
    "Upload",
    "🤖 24/7 Channel Watcher (VODs)",
    "🔴 Live Stream Clipper (HLS)",
    "🎯 Trend Hunter (USA 4h)"
])

with tab1:
    col_l, col_r = st.columns([1.6, 1])

    with col_l:
        st.caption("SOURCE URLS")
        url_input = st.text_area(
            "URLs",
            height=130,
            placeholder="https://www.youtube.com/watch?v=...\nhttps://www.youtube.com/watch?v=...",
            label_visibility="collapsed"
        )

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
            enable_phonk = st.checkbox("🎵 Background Beat (Sidechain Ducking)", value=False, help="Layers trending gaming rhythm beat with automatic voice ducking")
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

with tab2:
    ready_videos = sorted(list(READY_DIR.glob("*.mp4")))
    yt_connected = is_authenticated()
    curr_client_id = get_client_id_info()
    configured_slots = list_account_slots()
    auth_slots = [s for s in configured_slots if s["is_authenticated"]]
    pool_quota = max(10000, len(auth_slots) * 10000)

    # Top Status Row
    col1, col2 = st.columns([1, 1])
    with col1:
        st.metric("Ready in Queue", f"{len(ready_videos)} clips")
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

    # Monetization & Scheduling Options
    col_sc1, col_sc2 = st.columns([1, 1])
    with col_sc1:
        auto_sched = st.checkbox(
            "🎯 Auto-Schedule High-CPM Daily Slots",
            value=True,
            help="Spaces 100s of Shorts across daily peak US/UK gaming hours to maximize CPM & retention."
        )
    with col_sc2:
        cadence_option = st.selectbox(
            "Daily Cadence",
            options=["6 Shorts / Day (High Frequency)", "3 Shorts / Day (Conservative Peak)", "12 Shorts / Day (Hyper-growth)"],
            index=0
        )
        slots_per_day = 6 if "6" in cadence_option else (12 if "12" in cadence_option else 3)

    col_cfg1, col_cfg2 = st.columns([1, 1])
    with col_cfg1:
        batch_cap = st.slider("Max Upload Queue Limit", min_value=5, max_value=250, value=min(100, max(5, len(ready_videos))), step=5)
    with col_cfg2:
        upload_concurrency = st.radio(
            "Upload Speed Optimizer",
            options=[2, 1],
            format_func=lambda x: "⚡ Turbo Parallel (2 Concurrent Streams - 2x Speed)" if x == 2 else "🐢 Sequential (1 Stream)",
            index=0,
            horizontal=True,
            help="Turbo streams 2 videos simultaneously, saturating bandwidth and overlapping Google API roundtrips."
        )

    if auto_sched and ready_videos:
        q_count = min(len(ready_videos), batch_cap)
        days_span = max(1, (q_count + slots_per_day - 1) // slots_per_day)
        st.caption(f"🗓️ **Calendar Schedule:** `{q_count}` Shorts will be scheduled across **{days_span} days** (~{slots_per_day}/day during peak US/UK hours).")

    # Upload Action Button
    upload_disabled = len(ready_videos) == 0 or not yt_connected
    upload_btn = st.button(
        f"Upload & Schedule {min(len(ready_videos), batch_cap)} Shorts to YouTube" if auto_sched else f"Upload {min(len(ready_videos), batch_cap)} Shorts to YouTube (Private)",
        type="primary",
        disabled=upload_disabled,
        use_container_width=True,
        help="Uploads clips directly to your channel with private visibility or scheduled public release"
    )

    if upload_btn:
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
                    <div class="labor-subtask">{curr_f} ({file_pct}%)</div>
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
                auto_schedule=auto_sched,
                slots_per_day=slots_per_day,
                concurrency=upload_concurrency,
                chunk_callback=on_upload_chunk,
                log_callback=on_upload_log
            )
            u_progress.progress(1.0)
            u_status.success(f"Successfully processed {len(results)} clips on YouTube!")
            if results:
                for r in results:
                    sched_note = f" (Scheduled: `{r['publish_at']}`)" if r.get("publish_at") else ""
                    st.markdown(f"- **{r['title']}**{sched_note} &rarr; [Edit in YouTube Studio]({r['studio_url']})")
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
        
        auth_slots_cnt = max(1, len([s for s in list_account_slots() if s["is_authenticated"]]))
        daily_upload_cap = auth_slots_cnt * 100
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
            st.warning(f"⚠️ High Quota Utilization: {today_uploads}/{daily_upload_cap} daily uploads used today ({upload_pct:.0f}%). Add more project slots in the pool to expand limit.")
        else:
            st.caption(f"✓ GCP Quota Status: **{today_uploads}/{daily_upload_cap} uploads today** ({upload_pct:.1f}% used). Limit: 100 uploads/day per project.")

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

with tab3:
    st.markdown("<div class='section-title'>24/7 AUTONOMOUS CHANNEL WATCHER</div>", unsafe_allow_html=True)
    watcher_cfg = load_watcher_config()
    running = is_watcher_running()

    # Status Banner
    col_w_status, col_w_action = st.columns([2, 1])
    with col_w_status:
        if running:
            st.success("🟢 **Autopilot Active:** Background daemon is monitoring channels for new GTA 6 uploads.")
        else:
            st.info("⚪ **Autopilot Idle:** Daemon is paused. Click 'Start 24/7 Autopilot' to monitor channels automatically.")

    with col_w_action:
        if running:
            if st.button("⏹️ Stop Autopilot", type="secondary", use_container_width=True):
                stop_watcher_daemon()
                watcher_cfg["enabled"] = False
                save_watcher_config(watcher_cfg)
                st.rerun()
        else:
            if st.button("▶️ Start 24/7 Autopilot", type="primary", use_container_width=True):
                # Ensure all entered channels are saved immediately before daemon starts
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
        st.caption("TARGET CHANNELS TO MONITOR (One URL per line)")
        if "txt_watcher_channels" not in st.session_state:
            st.session_state["txt_watcher_channels"] = "\n".join(watcher_cfg.get("channels", []))
        ch_input = st.text_area(
            "Monitored Channels",
            height=140,
            label_visibility="collapsed",
            help="Enter YouTube channel video URLs or handles to watch (e.g. https://www.youtube.com/@RockstarGames)",
            key="txt_watcher_channels"
        )

    with col_cfg_right:
        st.caption("AUTOPILOT SETTINGS")
        poll_int = st.select_slider(
            "Polling Interval",
            options=[15, 30, 45, 60, 120],
            value=watcher_cfg.get("check_interval_minutes", 15),
            format_func=lambda x: f"Every {x} minutes"
        )
        shorts_n = st.slider("Shorts per New Video", min_value=2, max_value=8, value=watcher_cfg.get("shorts_per_video", 4))
        auto_up = st.checkbox("🎯 Auto-Schedule to YouTube Studio", value=watcher_cfg.get("auto_upload", True), help="Automatically queues and schedules newly extracted Shorts across daily peak High-CPM slots")
        hook_bg = st.checkbox("🔥 Burn Frame-1 Viral Hook Badge", value=watcher_cfg.get("enable_hook_badge", True), help="Adds curiosity banner on frame 1 to maximize swipe-through CTR")

    if st.button("💾 Save Autopilot Configuration", use_container_width=True):
        raw_chs = st.session_state.get("txt_watcher_channels", "")
        parsed_channels = [c.strip() for c in raw_chs.splitlines() if c.strip()]
        watcher_cfg["channels"] = parsed_channels
        watcher_cfg["check_interval_minutes"] = poll_int
        watcher_cfg["shorts_per_video"] = shorts_n
        watcher_cfg["auto_upload"] = auto_up
        watcher_cfg["enable_hook_badge"] = hook_bg
        save_watcher_config(watcher_cfg)
        st.success(f"✓ Autopilot configuration saved! ({len(parsed_channels)} target channels registered)")

    # Live Real-Time Autopilot Stage & Progress Telemetry (Auto-updates every 3s)
    @st.fragment(run_every="3s")
    def render_autopilot_live_telemetry():
        prog = get_watcher_progress()
        is_run = is_watcher_running()

        pct = prog.get("percentage", 0)
        status = prog.get("status", "idle")
        stage_lbl = prog.get("stage_label", "Autopilot Idle")
        detail = prog.get("step_detail", "Ready to monitor channels.")
        next_step = prog.get("next_step", "Detecting new videos")
        vid_title = prog.get("video_title", "")
        ch_name = prog.get("channel_name", "")
        cur_clip = prog.get("current_clip", 0)
        tot_clips = prog.get("total_clips", 0)

        st.markdown("<div class='section-title'>⚡ REAL-TIME AUTOPILOT PIPELINE PROGRESS</div>", unsafe_allow_html=True)

        # Real Progress Bar
        if is_run and status not in ("idle", "waiting"):
            st.progress(min(1.0, max(0.0, pct / 100.0)), text=f"{stage_lbl} — {pct}% COMPLETE")
        elif is_run and status == "waiting":
            st.progress(1.0, text="✓ Cycle Finished — Waiting for next polling interval")
        else:
            st.progress(0.0, text="Autopilot Paused / Idle")

        # Telemetry Cards
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Current Stage", stage_lbl, delta=f"{pct}% complete" if is_run and pct > 0 else None)
        with m2:
            display_title = f"{vid_title[:24]}..." if len(vid_title) > 24 else (vid_title or "No active video")
            st.metric("Active Video", display_title, help=f"{vid_title} (@{ch_name})" if vid_title else None)
        with m3:
            clip_info = f" (Clip {cur_clip}/{tot_clips})" if tot_clips > 0 else ""
            display_detail = f"{detail[:28]}..." if len(detail) > 28 else detail
            st.metric("Current Step", display_detail, delta=clip_info if clip_info else None, help=detail)
        with m4:
            display_next = f"{next_step[:26]}..." if len(next_step) > 26 else next_step
            st.metric("Next Step", display_next, help=next_step)

        # Live Autonomous Event Stream
        st.markdown("<div class='section-title'>AUTONOMOUS EVENT STREAM (LIVE 3S REFRESH)</div>", unsafe_allow_html=True)
        w_logs = get_watcher_logs()
        if w_logs:
            st.code("\n".join(w_logs[-25:]), language="bash")
        else:
            st.caption("No watcher events recorded yet. Start autopilot to begin streaming channel checks.")

    render_autopilot_live_telemetry()

with tab4:
    st.markdown("<div class='section-title'>🔴 LIVE STREAM ROLLING BUFFER & HLS CLIPPER</div>", unsafe_allow_html=True)
    live_cfg = load_livestream_config()
    live_running = is_livestream_running()

    # Status Banner
    col_l_status, col_l_action = st.columns([2, 1])
    with col_l_status:
        if live_running:
            st.success("🟢 **Live Stream Buffer Active:** Monitoring active YouTube livestreams for rolling HLS clip capture.")
        else:
            st.info("⚪ **Live Stream Buffer Idle:** Daemon paused. Click 'Start Live Stream Clipper' to capture rolling HLS windows from live streams.")

    with col_l_action:
        if live_running:
            if st.button("⏹️ Stop Live Clipper", type="secondary", use_container_width=True, key="btn_stop_live_clipper"):
                stop_livestream_daemon()
                live_cfg["enabled"] = False
                save_livestream_config(live_cfg)
                st.rerun()
        else:
            if st.button("▶️ Start Live Stream Clipper", type="primary", use_container_width=True, key="btn_start_live_clipper"):
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
        st.caption("TARGET LIVESTREAMS OR CHANNEL LIVE HANDLES (One URL per line)")
        if "txt_live_channels" not in st.session_state:
            st.session_state["txt_live_channels"] = "\n".join(live_cfg.get("channels", []))
        live_ch_input = st.text_area(
            "Live Streams to Monitor",
            height=140,
            label_visibility="collapsed",
            help="Enter YouTube livestream URLs or channel live handles (e.g. https://www.youtube.com/@IShowSpeed/live)",
            key="txt_live_channels"
        )

    with col_lcfg_right:
        st.caption("ROLLING BUFFER & CLIPPING SETTINGS")
        slice_dur = st.select_slider(
            "Rolling Buffer Window",
            options=[180, 300, 600, 900],
            value=live_cfg.get("slice_duration_seconds", 300),
            format_func=lambda x: f"{x // 60} Minutes Buffer",
            key="sl_live_slice_dur"
        )
        shorts_per_slice = st.slider("Shorts per Live Slice", min_value=1, max_value=4, value=live_cfg.get("shorts_per_slice", 2), key="sl_live_shorts_slice")
        live_auto_up = st.checkbox("🎯 Auto-Schedule to YouTube Studio", value=live_cfg.get("auto_upload", True), key="chk_live_auto_up", help="Automatically schedules live shorts across High-CPM monetization slots")
        live_hook = st.checkbox("🔥 Burn '🔴 LIVE' Hook Badge", value=live_cfg.get("enable_hook_badge", True), key="chk_live_hook", help="Burns dynamic '🔴 LIVE HIGHLIGHT' curiosity badge into frame 1")

    if st.button("💾 Save Live Stream Configuration", use_container_width=True, key="btn_save_live_cfg"):
        raw_chs = st.session_state.get("txt_live_channels", "")
        parsed_chs = [c.strip() for c in raw_chs.splitlines() if c.strip()]
        live_cfg["channels"] = parsed_chs
        live_cfg["slice_duration_seconds"] = slice_dur
        live_cfg["shorts_per_slice"] = shorts_per_slice
        live_cfg["auto_upload"] = live_auto_up
        live_cfg["enable_hook_badge"] = live_hook
        save_livestream_config(live_cfg)
        st.success(f"✓ Live Stream configuration saved! ({len(parsed_chs)} stream targets registered)")

    # Live Real-Time Telemetry for Tab 4
    @st.fragment(run_every="3s")
    def render_livestream_live_telemetry():
        l_prog = get_livestream_progress()
        is_l_run = is_livestream_running()

        l_pct = l_prog.get("percentage", 0)
        l_status = l_prog.get("status", "idle")
        l_stage = l_prog.get("stage_label", "Live Buffer Idle")
        l_detail = l_prog.get("step_detail", "Ready to monitor active live streams.")
        l_next = l_prog.get("next_step", "Scan live streams")
        l_title = l_prog.get("stream_title", "")
        l_author = l_prog.get("channel_name", "")
        l_cur_clip = l_prog.get("current_clip", 0)
        l_tot_clips = l_prog.get("total_clips", 0)

        st.markdown("<div class='section-title'>⚡ LIVE STREAM HLS BUFFER TELEMETRY</div>", unsafe_allow_html=True)

        # Progress bar
        if is_l_run and l_status not in ("idle", "waiting"):
            st.progress(min(1.0, max(0.0, l_pct / 100.0)), text=f"{l_stage} — {l_pct}% COMPLETE")
        elif is_l_run and l_status == "waiting":
            st.progress(1.0, text="✓ Live Slice Clipped & Scheduled — Monitoring stream")
        else:
            st.progress(0.0, text="Live Buffer Paused / Idle")

        # Telemetry metrics
        lm1, lm2, lm3, lm4 = st.columns(4)
        with lm1:
            st.metric("Live Stage", l_stage, delta=f"{l_pct}% complete" if is_l_run and l_pct > 0 else None)
        with lm2:
            display_ltitle = f"{l_title[:24]}..." if len(l_title) > 24 else (l_title or "No active stream")
            st.metric("Active Stream", display_ltitle, help=f"{l_title} (@{l_author})" if l_title else None)
        with lm3:
            clip_str = f" (Clip {l_cur_clip}/{l_tot_clips})" if l_tot_clips > 0 else ""
            display_ldetail = f"{l_detail[:28]}..." if len(l_detail) > 28 else l_detail
            st.metric("Buffer Sub-Step", display_ldetail, delta=clip_str if clip_str else None, help=l_detail)
        with lm4:
            display_lnext = f"{l_next[:26]}..." if len(l_next) > 26 else l_next
            st.metric("Next Step", display_lnext, help=l_next)

        # Live Autonomous Event Stream
        st.markdown("<div class='section-title'>LIVE STREAM EVENT STREAM (LIVE 3S REFRESH)</div>", unsafe_allow_html=True)
        l_logs = get_livestream_logs()
        if l_logs:
            st.code("\n".join(l_logs[-25:]), language="bash")
        else:
            st.caption("No livestream events recorded yet. Start live buffer to begin capturing HLS streams.")

    render_livestream_live_telemetry()

with tab5:
    col_list, col_telemetry = st.columns([1.35, 1.0], gap="large")

    with col_list:
        st.markdown("<div class='section-title'>🎯 USA BREAKOUT TREND HUNTER (GOOGLE TRENDS 4H)</div>", unsafe_allow_html=True)
        st.caption("Directly tracks `https://trends.google.com/trending?geo=US&status=active&hours=4&sort=recency`. Automatically detects breakout search spikes in the United States in the last 4 hours before they saturate, generates 6+ Reels (9:16) + 2+ Landscape Videos (16:9) per trend, and schedules them directly to YouTube Studio on @zelmuesports.")

        # Trend Scanner Parameters
        st.markdown("<div class='section-title'>TREND SCANNER PARAMETERS</div>", unsafe_allow_html=True)
        p1, p2, p3, p4, p5 = st.columns([1, 1, 1.1, 1.4, 1.3])
        with p1:
            trend_geo = st.selectbox("Geo Region", ["US", "GB", "CA", "AU"], index=0, key="trend_geo")
        with p2:
            trend_hours = st.selectbox("Time Window", [4, 24, 48], index=0, format_func=lambda x: f"Past {x} Hours", key="trend_hours")
        with p3:
            trend_sort = st.selectbox("Sort By", ["recency", "search-volume"], index=0, format_func=lambda x: "Recency (Breakouts)" if x == "recency" else "Search Volume", key="trend_sort")
        with p4:
            cat_keys = list(CATEGORIES.keys())
            sel_cat_key = st.selectbox("Category", cat_keys, index=0, format_func=lambda k: CATEGORIES[k]["label"], key="trend_cat")
            sel_cat_id = CATEGORIES[sel_cat_key]["cat_id"]
            cat_default_suffix = CATEGORIES[sel_cat_key]["default_suffix"]
        with p5:
            st.write("")
            st.write("")
            btn_scan_trends = st.button("🔥 Scan Breakout Trends", use_container_width=True, type="primary")

        if btn_scan_trends or "cached_us_trends" not in st.session_state:
            with st.spinner(f"Scraping live Google Trends ({CATEGORIES[sel_cat_key]['label']}, geo={trend_geo}, hours={trend_hours})..."):
                scanned_trends = fetch_google_trends_us(geo=trend_geo, hours=trend_hours, sort=trend_sort, category_id=sel_cat_id)
                st.session_state["cached_us_trends"] = scanned_trends
                st.session_state["last_trends_scan_ts"] = datetime.datetime.now().strftime("%m/%d/%y, %I:%M %p")

        trends_data = st.session_state.get("cached_us_trends", [])
        scan_ts = st.session_state.get("last_trends_scan_ts", "")

        if trends_data:
            st.markdown(f"### Trends · {scan_ts} ({len(trends_data)} Active US Breakouts)")

            # Topic filter
            niche_col1, niche_col2 = st.columns([2, 1])
            with niche_col1:
                niche_keyword = st.text_input("Filter by Topic / Keyword (optional):", value="", placeholder="e.g. search keyword, gta, sports, viral, tech", key="trend_topic_filter")
            with niche_col2:
                video_topic_suffix = st.text_input("YouTube Search Suffix:", value=cat_default_suffix, placeholder="e.g. gameplay, moments, reaction", key="trend_yt_suffix")

            filtered_trends = trends_data
            if niche_keyword.strip():
                kw_low = niche_keyword.strip().lower()
                filtered_trends = [t for t in trends_data if kw_low in t["query"].lower()]
                st.caption(f"Showing {len(filtered_trends)} matching trends for '{niche_keyword}'")

            for idx, tr in enumerate(filtered_trends[:30]):
                with st.expander(f"#{idx+1} {tr['query'].upper()} — {tr['search_vol_display']} ({tr['started_time']})", expanded=(idx < 2)):
                    c1, c2 = st.columns([2.2, 1.8])
                    with c1:
                        st.markdown(f"**Search Volume:** `{tr['search_vol_display']}` | **Started:** `{tr['started_time']}` (🟢 Active)")
                        st.markdown(f"**Trend Breakdown (All):** *{tr['breakdown_display']}*")
                        st.markdown(f"[🔗 Google Search Link]({tr['search_link']}) | [📈 Google Trends Explore Link]({tr['explore_link']})")

                        # In the news links
                        if st.button("📰 Load Live News Links", key=f"btn_news_{idx}"):
                            news_items = get_trend_news_articles(tr['query'], max_articles=3)
                            tr["news_articles"] = news_items
                            if news_items:
                                st.write("**Top News Headlines:**")
                                for ni in news_items:
                                    st.markdown(f"- [{ni['title']}]({ni['url']}) *({ni['source']})*")
                            else:
                                st.caption("No immediate Google News articles found.")
                    with c2:
                        st.markdown("##### Content Actions")
                        if st.button(f"🚀 Produce 6 Reels + 2 Videos", key=f"btn_pkg_{idx}", type="primary", use_container_width=True):
                            with st.spinner(f"Producing 6 Reels + 2 Landscape Videos for '{tr['query']}'..."):
                                def manual_update_status(cur_q, stg, stg_name, detail, pct, s_done, v_done):
                                    set_daemon_progress(
                                        active=True,
                                        current_trend=cur_q,
                                        stage=stg,
                                        total_stages=5,
                                        stage_name=stg_name,
                                        step_detail=detail,
                                        next_step="Studio Scheduling" if stg < 5 else "Completed",
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
                                manual_update_status(tr['query'], 5, "Completed", f"Produced {pkg_res['total_rendered']} assets (6 Reels + 2 Videos)", 100, len(pkg_res.get('shorts', [])), len(pkg_res.get('landscapes', [])))
                                st.success(f"✓ Successfully produced {pkg_res['total_rendered']} assets! (6 Reels + 2 Videos).")
                                st.rerun()

                        if st.button(f"⚡ Clip in Tab 1 (Produce)", key=f"btn_clip_{idx}", use_container_width=True):
                            with st.spinner(f"Searching YouTube videos for '{tr['query']}'..."):
                                vids = search_trend_source_videos(tr['query'], max_results=3, topic_filter=video_topic_suffix)
                                if vids:
                                    top_vid = vids[0]
                                    st.session_state["txt_raw_url"] = top_vid["url"]
                                    st.success(f"Selected: {top_vid['title']} ({top_vid['url']})! Switched to Tab 1.")
                                    st.rerun()
                                else:
                                    st.warning("No recent YouTube videos found for this trend.")
        else:
            st.info("No trend data loaded. Click 'Scan Breakout Trends' above to fetch latest US breakout spikes.")

    with col_telemetry:
        st.markdown("<div class='section-title'>🤖 AUTONOMOUS DAEMON & TELEMETRY</div>", unsafe_allow_html=True)

        d_cfg = load_daemon_config()
        d_running = is_trend_daemon_running()

        if d_running:
            st.success("🟢 **Autonomous Daemon Active:** Polling US breakout trends 24/7. Auto-producing 6 Reels + 2 Videos.")
            if st.button("⏹️ Stop Trend Daemon", use_container_width=True, type="secondary", key="btn_stop_trend_daemon"):
                stop_trend_daemon()
                st.rerun()
        else:
            st.warning("⚪ **Autonomous Daemon Idle:** Start background daemon to scan and produce 24/7.")
            if st.button("🚀 Start Autonomous Trend Worker", use_container_width=True, type="primary", key="btn_start_trend_daemon"):
                start_trend_daemon()
                st.rerun()

        with st.expander("⚙️ Daemon Configuration", expanded=False):
            d_poll = st.number_input("Poll Interval (seconds)", min_value=60, max_value=3600, value=int(d_cfg.get("poll_interval_sec", 300)), step=60, key="cfg_daemon_poll")
            d_autoup = st.checkbox("Auto-Schedule to YouTube Studio", value=bool(d_cfg.get("auto_upload", True)), key="cfg_daemon_autoup")
            if st.button("💾 Save Daemon Settings", key="btn_save_daemon_cfg", use_container_width=True):
                d_cfg["poll_interval_sec"] = d_poll
                d_cfg["auto_upload"] = d_autoup
                save_daemon_config(d_cfg)
                st.success("Daemon settings saved!")

        # Independent 3-second live telemetry fragment
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

            st.markdown("<div class='section-title'>📊 LIVE PRODUCTION TELEMETRY</div>", unsafe_allow_html=True)
            if is_t_run or t_pct > 0:
                st.progress(max(0.0, min(1.0, t_pct / 100.0)), text=f"{t_stage} ({t_pct}%) — {t_detail}")
            else:
                st.progress(0.0, text="Autonomous Daemon Paused / Idle")

            tm1, tm2 = st.columns(2)
            with tm1:
                st.metric("Daemon Stage", t_stage, delta=f"{t_pct}%" if (is_t_run or t_pct > 0) else None)
            with tm2:
                disp_trend = f"{t_cur_trend[:18]}..." if len(t_cur_trend) > 18 else (t_cur_trend or "Scanning...")
                st.metric("Active Trend", disp_trend, help=t_cur_trend)

            tm3, tm4 = st.columns(2)
            with tm3:
                disp_sub = f"{t_detail[:22]}..." if len(t_detail) > 22 else t_detail
                st.metric("Sub-Step Detail", disp_sub, help=t_detail)
            with tm4:
                st.metric("Assets Produced", f"{t_shorts} Reels / {t_vids} Videos", delta=f"{t_shorts+t_vids} total" if (t_shorts+t_vids) > 0 else None)

            st.markdown("<div class='section-title'>⚡ LIVE EVENT STREAM (3S REFRESH)</div>", unsafe_allow_html=True)
            t_logs = get_daemon_logs(max_lines=40)
            if t_logs:
                st.code("\n".join(t_logs[-25:]), language="bash")
            else:
                st.caption("No autonomous trend events logged yet. Start daemon or produce to stream events.")

        render_trend_daemon_telemetry_box()

