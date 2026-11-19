import os
import sys
import re
import gc
import time
import json
import shutil
import hashlib
import datetime
from pathlib import Path

# Anti-Crash: Ensure local bin (ffmpeg) and venv/Scripts (yt-dlp) are always in PATH
_base_dir = Path(__file__).resolve().parent
for _p in [_base_dir / "bin", _base_dir / "venv" / "Scripts"]:
    if _p.exists() and str(_p) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(_p) + os.pathsep + os.environ.get("PATH", "")

import streamlit as st

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
    render_mode_b_short
)
from uploader import (
    upload_batch_private,
    get_authenticated_service,
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
    }
    div[data-testid="stCode"] pre {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace !important;
        font-size: 11.5px !important;
        color: #a1a1aa !important;
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

    # 5. YouTube API Secrets
    diag["client_secrets"] = CLIENT_SECRETS_FILE.exists()

    return diag

# Top Sticky Navbar Diagnostics & Brand
diag = check_system_diagnostics()

ffmpeg_status = '<span class="dot dot-ok"></span> FFmpeg' if diag['ffmpeg'] else '<span class="dot dot-err"></span> FFmpeg'
ytdlp_status = '<span class="dot dot-ok"></span> yt-dlp' if diag['yt_dlp'] else '<span class="dot dot-err"></span> yt-dlp'
ollama_status = '<span class="dot dot-ok"></span> Ollama' if diag['ollama'] else '<span class="dot dot-warn"></span> Ollama'
yt_auth_status = '<span class="dot dot-ok"></span> YouTube' if diag['client_secrets'] else '<span class="dot dot-warn"></span> YouTube'

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

        if "Mode A" in mode:
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

    start_btn = st.button("Produce Shorts", type="primary", use_container_width=True)

    if start_btn:
        urls = [u.strip() for u in url_input.splitlines() if u.strip()]
        if not urls:
            st.warning("Please provide at least one valid video URL.")
        else:
            labor_box = st.empty()
            status_box = st.empty()
            detail_box = st.empty()

            recent_logs = []
            def push_log(msg: str):
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                msg_clean = re.sub(r"\s+", " ", msg.strip())
                recent_logs.append(f"[{ts}] {msg_clean}")
                if len(recent_logs) > 8:
                    recent_logs.pop(0)
                detail_box.code("\n".join(recent_logs), language="bash")

            for url_idx, raw_url in enumerate(urls):
                t_start = time.time()
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

                # Checkpoint 01: Audio Extraction (yt-dlp 16kHz mono WAV)
                audio_wav = work_dir / "01_audio.wav"
                if not audio_wav.exists() or audio_wav.stat().st_size < 1024:
                    push_log("Starting audio-first stream extraction via yt-dlp...")
                    
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
                            throughput="16kHz mono WAV",
                            mem_stat="Active"
                        )
                        push_log(line)

                    extract_audio_wav(raw_url, audio_wav, max_duration_sec=max_scan_sec, progress_callback=on_audio_extract_progress)
                    push_log(f"Audio extracted successfully: {audio_wav.name}")
                else:
                    push_log("Reusing cached 01_audio.wav")

                # Checkpoint 02: Instant YouTube Captions or Faster-Whisper Fallback
                transcript_json = work_dir / "02_transcript.json"
                if not transcript_json.exists():
                    push_log("Checking for YouTube word-timed captions (Fast Mode)...")
                    transcript = fetch_youtube_captions(raw_url, transcript_json, max_duration_sec=max_scan_sec)
                    if transcript:
                        elapsed_str = format_elapsed(time.time() - t_start)
                        render_labor_card(
                            labor_box,
                            stage_name="Stage 2/5: Word-Timed Captions (⚡ Instant YT)",
                            pct=100,
                            elapsed_str=elapsed_str,
                            current_subtask="YouTube json3 word-level subtitles",
                            throughput="Zero CPU / ~1s",
                            mem_stat="Fast Mode"
                        )
                        push_log(f"⚡ Instant YouTube word-timed captions parsed ({len(transcript.get('segments', []))} segments)")
                    else:
                        push_log("YouTube captions unavailable. Initializing Faster-Whisper (int8 CPU)...")
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
                else:
                    push_log("Reusing cached 02_transcript.json")
                    with open(transcript_json, "r", encoding="utf-8") as f:
                        transcript = json.load(f)

                # Checkpoint 03: Ollama Candidates Analysis (with Acoustic Peak Fusion)
                candidates_json = work_dir / "03_candidates.json"
                target_mode = "Mode B" if "Mode B" in mode else "Mode A"
                
                if not candidates_json.exists():
                    render_labor_card(
                        labor_box,
                        stage_name="Stage 3/5: AI Hook & Acoustic Spike Analysis",
                        pct=65,
                        elapsed_str=format_elapsed(time.time() - t_start),
                        current_subtask=f"Ollama {MODEL_NAME} + 2-4kHz audio energy analysis",
                        throughput="Acoustic peak fusion",
                        mem_stat="Local LLM"
                    )
                    push_log(f"Scanning acoustic energy spikes & evaluating transcript with {MODEL_NAME} ({target_mode})...")
                    analysis = extract_candidates_full(transcript, mode=target_mode, channel_name=active_credit, audio_path=audio_wav)
                    with open(candidates_json, "w", encoding="utf-8") as f:
                        json.dump(analysis, f, indent=2)
                    push_log("AI & acoustic analysis complete. Selected candidate clips.")
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

                    for c_idx, cand in enumerate(candidates):
                        start_t = cand["start"]
                        end_t = cand["end"]
                        safe_title = cand.get("safe_title", f"GTA6_Moment_{c_idx+1}")
                        final_dest = READY_DIR / f"{safe_title}.mp4"

                        if final_dest.exists() and final_dest.stat().st_size > 102400:
                            push_log(f"Short '{safe_title}' already exists.")
                            continue

                        # Section download with live stdout
                        raw_seg = segments_dir / f"seg_raw_{c_idx}.mp4"
                        push_log(f"Downloading clip {c_idx+1}/{len(candidates)} ({start_t}s - {end_t}s)...")
                        def on_clip_dl(line: str):
                            elapsed_s = format_elapsed(time.time() - t_start)
                            render_labor_card(
                                labor_box,
                                stage_name=f"Stage 4/5: Downloading Clip {c_idx+1}/{len(candidates)}",
                                pct=75,
                                elapsed_str=elapsed_s,
                                current_subtask=f"Downloading section: {start_t}s - {end_t}s",
                                throughput="yt-dlp segment",
                                mem_stat="Buffered"
                            )
                            push_log(line)
                        download_video_section(raw_url, start_t, end_t, raw_seg, progress_callback=on_clip_dl)

                        # Words in this timestamp
                        seg_words = []
                        for s in transcript.get("segments", []):
                            for w in s.get("words", []):
                                if start_t <= w["start"] <= end_t:
                                    seg_words.append(w)

                        # Generate .ass subtitles with center safe-zone karaoke
                        ass_file = segments_dir / f"subs_{c_idx}.ass"
                        push_log(f"Generating center safe-zone {style_key.upper()} subtitles (.ass)...")
                        generate_karaoke_ass(seg_words, ass_file, clip_start_offset=start_t, style_preset=style_key)

                        # Profanities for audio muting
                        flagged = find_profanities_in_words(seg_words)
                        if flagged:
                            push_log(f"Masking {len(flagged)} profanity timestamp(s) with audio muting.")

                        # Render with micro-pacing zooms + optional logo watermark
                        render_labor_card(
                            labor_box,
                            stage_name=f"Stage 4/5: Rendering Clip {c_idx+1}/{len(candidates)}",
                            pct=int(80 + (c_idx / max(1, len(candidates))) * 18),
                            elapsed_str=format_elapsed(time.time() - t_start),
                            current_subtask="FFmpeg 9:16 vertical crop + safe-zone captions",
                            throughput="Micro-pacing zooms",
                            mem_stat="2-Thread CPU"
                        )
                        push_log("FFmpeg rendering 9:16 vertical crop + micro-pacing zooms...")
                        render_mode_a_short(
                            source_video=raw_seg,
                            ass_subtitles=ass_file,
                            output_short_path=final_dest,
                            flagged_profanities=flagged,
                            split_layout=split_cam,
                            facecam_position=cam_position.lower(),
                            logo_path=active_logo_path
                        )
                        push_log(f"Rendered: {final_dest.name}")

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

                        # Download micro-clips with live progress
                        downloaded_clips = []
                        for m_idx, clip in enumerate(clips_info):
                            c_mp4 = segments_dir / f"micro_clip_{m_idx}.mp4"
                            push_log(f"Downloading micro-highlight {m_idx+1}/3 ({clip['start']}s - {clip['end']}s)...")
                            def on_mclip_dl(line: str):
                                elapsed_s = format_elapsed(time.time() - t_start)
                                render_labor_card(
                                    labor_box,
                                    stage_name=f"Stage 4/5: Downloading Highlight {m_idx+1}/3",
                                    pct=75 + (m_idx * 5),
                                    elapsed_str=elapsed_s,
                                    current_subtask="yt-dlp micro-clip download",
                                    throughput="Fast segment",
                                    mem_stat="Buffered"
                                )
                                push_log(line)
                            download_video_section(raw_url, clip["start"], clip["end"], c_mp4, progress_callback=on_mclip_dl)
                            downloaded_clips.append(c_mp4)

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

with tab2:
    ready_videos = sorted(list(READY_DIR.glob("*.mp4")))
    
    col1, col2 = st.columns([1, 1])
    with col1:
        st.metric("Ready in Queue", f"{len(ready_videos)} clips")
        if len(ready_videos) > 25:
            st.caption("Batch capped at 25 (quota limit)")

    with col2:
        if not CLIENT_SECRETS_FILE.exists():
            st.error("Missing client_secrets.json.")
        else:
            if st.button("Verify Auth", use_container_width=True):
                with st.spinner("Connecting..."):
                    try:
                        yt = get_authenticated_service()
                        resp = yt.channels().list(mine=True, part="snippet").execute()
                        items = resp.get("items", [])
                        channel_title = items[0]["snippet"]["title"] if items else "Connected Account"
                        st.success(f"Channel: {channel_title}")
                    except Exception as err:
                        st.error(f"OAuth error: {err}")

    upload_btn = st.button(
        "Upload to YouTube (Private)",
        type="primary",
        disabled=len(ready_videos) == 0 or not CLIENT_SECRETS_FILE.exists(),
        use_container_width=True
    )

    if upload_btn:
        u_progress = st.progress(0.0)
        u_status = st.empty()

        def update_ui(current, total, filename):
            u_progress.progress((current - 1) / max(1, total))
            u_status.info(f"Preparing [{current}/{total}]: {filename}...")

        def update_chunk(current, total, filename, pct):
            overall = ((current - 1) + (pct / 100.0)) / max(1, total)
            u_progress.progress(min(1.0, max(0.0, overall)))
            u_status.info(f"Uploading [{current}/{total}]: {filename} ({pct}%)")

        try:
            results = upload_batch_private(
                max_batch_size=25,
                progress_callback=update_ui,
                chunk_callback=update_chunk
            )
            u_status.success(f"Uploaded {len(results)} videos as Private.")
            st.rerun()
        except Exception as e:
            u_status.error(f"Upload failed: {str(e)}")

    st.markdown("<div class='section-title'>UPLOAD HISTORY</div>", unsafe_allow_html=True)
    if LOG_FILE.exists():
        import pandas as pd
        df = pd.read_csv(LOG_FILE)
        st.dataframe(df, use_container_width=True)
    else:
        st.caption("No upload history recorded yet.")
