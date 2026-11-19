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
from transcriber import get_ffmpeg_path, extract_audio_wav, transcribe_audio_whisper, get_video_metadata, fetch_youtube_captions
from analyzer import extract_candidates_full, calculate_audio_spikes, OLLAMA_API_URL, MODEL_NAME
from editor import (
    generate_karaoke_ass,
    download_video_section,
    generate_piper_tts,
    render_mode_a_short,
    render_mode_b_short,
    check_internet_connection
)
from uploader import (
    upload_batch_private,
    get_authenticated_service,
    is_authenticated,
    get_channel_info,
    get_channel_analytics,
    get_auth_url,
    exchange_code_for_token,
    run_local_server_auth,
    revoke_token,
    CLIENT_SECRETS_FILE,
    TOKEN_FILE,
    LOG_FILE,
    READY_DIR,
    ARCHIVE_DIR
)

# Ensure base directories exist
WORKSPACE_DIR = Path("workspace")
READY_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
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
tab1, tab2 = st.tabs(["Produce", "Upload"])

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
        if "Mode A" in mode:
            enable_yolox = st.checkbox("Dynamic Player Tracking (YOLOX-S)", value=True, help="Follows player dynamically across 16:9 frame")
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
        urls = [u.strip() for u in url_input.splitlines() if u.strip()]
        if not urls:
            st.warning("Please provide at least one valid video URL.")
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
    
                    # Checkpoint 03: Ollama Candidates Analysis (with Acoustic Peak Fusion)
                    candidates_json = work_dir / "03_candidates.json"
                    target_mode = "Mode B" if "Mode B" in mode else "Mode A"
                    
                    if not candidates_json.exists():
                        render_labor_card(
                            labor_box,
                            stage_name="Stage 3/5: AI Hook & Candidate Analysis",
                            pct=65,
                            elapsed_str=format_elapsed(time.time() - t_start),
                            current_subtask=f"Ollama {MODEL_NAME} evaluation",
                            throughput="Turbo analysis",
                            mem_stat="Local LLM"
                        )
                        push_log(f"Evaluating transcript with {MODEL_NAME} ({target_mode})...")
                        analysis = extract_candidates_full(
                            transcript,
                            mode=target_mode,
                            channel_name=active_credit,
                            audio_path=audio_wav if audio_wav.exists() else None,
                            target_clips=target_reels_count
                        )
                        with open(candidates_json, "w", encoding="utf-8") as f:
                            json.dump(analysis, f, indent=2)
                        push_log(f"AI analysis complete. Selected {len(analysis.get('candidates', []))} candidate clips.")
                    else:
                        push_log("Reusing cached 03_candidates.json")
                        with open(candidates_json, "r", encoding="utf-8") as f:
                            analysis = json.load(f)
    
                    # Checkpoint 04 & Final Render
                    segments_dir = work_dir / "04_segments"
                    segments_dir.mkdir(parents=True, exist_ok=True)
    
                    if target_mode == "Mode A":
                        candidates = analysis.get("candidates", [])
                        style_key = "neon" if "Neon" in caption_style else ("clean" if "Clean" in caption_style else "karaoke")

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
                            download_video_section(raw_url, start_t, end_t, raw_seg)

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

                            push_log(f"[Parallel Worker #{c_idx+1}] Rendering short (Intel QSV + dynamic tracking)...")
                            render_mode_a_short(
                                source_video=raw_seg,
                                ass_subtitles=ass_file,
                                output_short_path=final_dest,
                                flagged_profanities=flagged,
                                split_layout=split_cam,
                                facecam_position=cam_position.lower() if split_cam else "top-left",
                                enable_tracking=enable_yolox,
                                logo_path=active_logo_path
                            )
                            push_log(f"✓ Rendered: {final_dest.name}")
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

                            # Download micro-clips in parallel
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
                                download_video_section(raw_url, clip["start"], clip["end"], c_mp4)
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

    st.markdown("<div class='section-title'>READY CLIPS</div>", unsafe_allow_html=True)
    ready_files = sorted(list(READY_DIR.glob("*.mp4")))
    
    col_hdr1, col_hdr2 = st.columns([3, 1])
    with col_hdr1:
        if ready_files:
            st.caption(f"{len(ready_files)} clips in `{READY_DIR}`")
    with col_hdr2:
        if ready_files and st.button("Clear All", type="secondary", use_container_width=True):
            for f in ready_files:
                try:
                    f.unlink()
                except Exception:
                    pass
            st.rerun()

    if ready_files:
        cols = st.columns(3)
        for i, vid in enumerate(ready_files):
            with cols[i % 3]:
                st.caption(vid.name)
                st.video(str(vid))
                del_col1, del_col2 = st.columns([1, 1])
                with del_col1:
                    size_mb = vid.stat().st_size / (1024 * 1024)
                    st.caption(f"{size_mb:.1f} MB")
                with del_col2:
                    if st.button("Delete", key=f"del_{i}", use_container_width=True):
                        try:
                            vid.unlink()
                        except Exception:
                            pass
                        st.rerun()
    else:
        st.caption("No clips generated yet.")

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

    # Top Status Row
    col1, col2 = st.columns([1, 1])
    with col1:
        st.metric("Ready in Queue", f"{len(ready_videos)} clips")
        if len(ready_videos) > 25:
            st.caption("Batch capped at 25 (quota limit)")

    with col2:
        if not CLIENT_SECRETS_FILE.exists():
            st.error("Missing client_secrets.json in root folder.")
        elif yt_connected:
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

    # Client Secrets Uploader / Config
    with st.expander("🔑 OAuth Client Configuration / Replace Secrets", expanded=not CLIENT_SECRETS_FILE.exists()):
        if curr_client_id:
            st.caption(f"Configured Client ID: `{curr_client_id}`")
        new_secrets_file = st.file_uploader("Upload new client_secrets.json from Google Cloud Console", type=["json"], key="up_secrets_json")
        if new_secrets_file is not None:
            try:
                raw_text = new_secrets_file.read().decode("utf-8")
                json.loads(raw_text)
                with open(CLIENT_SECRETS_FILE, "w", encoding="utf-8") as f:
                    f.write(raw_text)
                revoke_token()
                st.success("client_secrets.json updated successfully!")
                st.rerun()
            except Exception as ex:
                st.error(f"Invalid JSON: {ex}")

    # If Not Authenticated, show connection options
    if CLIENT_SECRETS_FILE.exists() and not yt_connected:
        st.markdown("""
        <div style="background: rgba(234, 179, 8, 0.08); border: 1px solid rgba(234, 179, 8, 0.3); border-radius: 8px; padding: 14px; margin: 12px 0;">
            <div style="font-weight: 700; color: #fbbf24; margin-bottom: 6px;">Connect YouTube Channel</div>
            <div style="font-size: 0.85rem; color: #94a3b8; margin-bottom: 12px;">Link your account once to upload clips directly as Private Shorts. Choose either method below:</div>
        </div>
        """, unsafe_allow_html=True)

        auth_tab_auto, auth_tab_manual = st.tabs(["Method 1: One-Click Browser Login", "Method 2: Direct Link & Code"])

        with auth_tab_auto:
            st.caption("Opens Google's sign-in screen in your browser. (Auto-detects free local port)")
            if st.button("Sign In with Google (Browser)", type="primary", use_container_width=True):
                with st.spinner("Waiting for Google OAuth in your browser (60s timeout)..."):
                    try:
                        run_local_server_auth(port=8080, timeout_seconds=60)
                        st.success("Successfully authenticated!")
                        st.rerun()
                    except Exception as err:
                        st.error(f"Sign-in error: {err}")
                        if "invalid_client" in str(err) or "10048" in str(err):
                            st.info("💡 Note: Google reported Error 401 invalid_client. Ensure your OAuth 2.0 Client ID is active in Google Cloud Console.")

        with auth_tab_manual:
            try:
                auth_url = get_auth_url()
                st.markdown(f'<a href="{auth_url}" target="_blank" style="display:inline-block; background:#2563eb; color:white; padding:8px 14px; border-radius:6px; text-decoration:none; font-weight:600; margin-bottom:10px;">🔗 1. Open Google Sign-In in New Tab</a>', unsafe_allow_html=True)
                code_input = st.text_input("2. Paste Redirect URL or Code from browser address bar:", key="oauth_code_in")
                if st.button("Complete Sign-In", use_container_width=True):
                    if code_input:
                        try:
                            exchange_code_for_token(code_input)
                            st.success("Connected!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Token exchange error: {e}")
                    else:
                        st.warning("Please paste the URL or authorization code first.")
            except Exception as e:
                st.error(f"Error generating auth URL: {e}")
                st.error(f"Error generating auth URL: {e}")

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
        quota_used = total_uploads * 1600

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
            st.metric("Est. Quota Used", f"{quota_used:,} / 10,000")

        if quota_used >= 8000:
            st.warning(f"⚠️ YouTube API Quota Warning: ~{quota_used:,} units consumed today (Standard default quota limit is 10,000/day).")

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