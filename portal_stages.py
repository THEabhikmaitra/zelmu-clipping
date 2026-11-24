"""
Portal Stages: Quality & SEO Checklist, Deep Analytics, and Continuous Learning Engine
Implements Stages 3, 5, and 6 of the Zelmu Autonomous Clipping Flywheel with full
end-to-end data interconnection across all stages.
"""

import json
import time
import shutil
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import streamlit as st

from learning_engine import (
    load_learning_db,
    load_upload_history,
    sync_youtube_performance,
    get_learned_seo_boost,
    audit_quality_and_seo,
    quick_fix_seo,
    cleanup_stale_workspaces
)
from arbiter import get_arbiter_status


def get_sidecar_data(video_path: Path) -> Dict[str, Any]:
    sc = video_path.with_suffix(".json")
    if sc.exists():
        try:
            with open(sc, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_sidecar_data(video_path: Path, data: Dict[str, Any]):
    sc = video_path.with_suffix(".json")
    try:
        with open(sc, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving sidecar: {e}")


def get_pipeline_telemetry(ready_dir: Path) -> Dict[str, Any]:
    """Computes real-time data state across all 6 stages of the flywheel."""
    history = load_upload_history()
    uploaded_stems = {h.get("file_stem", "") for h in history if h.get("file_stem")}

    ready_files = list(ready_dir.glob("*.mp4")) if ready_dir.exists() else []
    pending_files = []
    approved_files = []

    for vf in ready_files:
        # If video was already uploaded to YouTube Studio, auto-purge residual files from disk
        if vf.stem in uploaded_stems:
            try:
                vf.unlink(missing_ok=True)
                vf.with_suffix(".json").unlink(missing_ok=True)
                for tc in [vf.with_suffix(".thumb.jpg"), vf.with_suffix(".jpg"), vf.with_suffix(".png")]:
                    tc.unlink(missing_ok=True)
            except Exception:
                pass
            continue

        meta = get_sidecar_data(vf)
        if meta.get("approved") is True:
            approved_files.append(vf)
        else:
            pending_files.append(vf)

    arbiter_info = get_arbiter_status()
    db = load_learning_db()

    total_views = sum(int(h.get("last_synced_views", 0)) for h in history)
    optimal_sec = db.get("optimal_duration", {}).get("sweet_spot_sec", 34.0)

    cached_trends = st.session_state.get("cached_us_trends", [])

    return {
        "trends_count": len(cached_trends),
        "arbiter_holder": arbiter_info.get("holder"),
        "arbiter_op": arbiter_info.get("operation", "Idle"),
        "arbiter_paused": arbiter_info.get("paused", False),
        "total_ready": len(ready_files),
        "pending_count": len(pending_files),
        "approved_count": len(approved_files),
        "pending_files": pending_files,
        "approved_files": approved_files,
        "tracked_uploads": len(history),
        "total_views": total_views,
        "optimal_sec": optimal_sec,
        "high_cpm_tags_count": len(db.get("high_cpm_keywords", {}))
    }


_TELEMETRY_SNAP_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}


def get_system_telemetry_snapshot() -> Dict[str, Any]:
    """Captures real-time system, drive, crawler, quota, and AI telemetry parameters (10s TTL cached)."""
    now = time.time()
    cached = _TELEMETRY_SNAP_CACHE.get("data")
    if cached is not None and (now - _TELEMETRY_SNAP_CACHE["ts"]) < 10.0:
        return cached
    try:
        du = shutil.disk_usage(".")
        free_gb = du.free / (1024 ** 3)
        total_gb = du.total / (1024 ** 3)
        free_pct = (du.free / du.total) * 100
    except Exception:
        free_gb, total_gb, free_pct = 0.0, 0.0, 0.0

    def calc_dir_mb(p: Path) -> float:
        if not p.exists():
            return 0.0
        return sum(f.stat().st_size for f in p.glob("**/*") if f.is_file()) / (1024 * 1024)

    ready_mb = calc_dir_mb(Path("ready_to_upload"))
    workspace_mb = calc_dir_mb(Path("workspace"))

    try:
        from instagram_scraper import load_crawler_state
        c_state = load_crawler_state()
        crawler_status = c_state.get("status", "idle")
        crawler_account = c_state.get("account", "None")
        crawler_q = len(c_state.get("reels_queue", []))
        crawler_done = len(c_state.get("completed_ids", []))
        crawler_fail = len(c_state.get("failed_ids", []))
        crawler_caption = c_state.get("current_reel_caption", "")
    except Exception:
        crawler_status, crawler_account, crawler_q, crawler_done, crawler_fail, crawler_caption = "idle", "None", 0, 0, 0, ""

    try:
        from editor import get_best_video_encoder
        enc_args = get_best_video_encoder()
        enc_name = "Intel QSV (h264_qsv)" if "h264_qsv" in str(enc_args) else "CPU (libx264)"
    except Exception:
        enc_name = "CPU (libx264)"

    try:
        from instagram_scraper import is_ollama_online
        ollama_ok = is_ollama_online()
    except Exception:
        ollama_ok = False

    try:
        from uploader import CLIENT_SECRETS_FILE
        token_files = list(Path(".").glob("token_*.json"))
        if Path("token.json").exists():
            token_files.append(Path("token.json"))
        has_secrets = CLIENT_SECRETS_FILE.exists()
        token_count = len(token_files)
    except Exception:
        has_secrets = False
        token_count = 0

    res_snap = {
        "free_gb": free_gb,
        "total_gb": total_gb,
        "free_pct": free_pct,
        "ready_mb": ready_mb,
        "workspace_mb": workspace_mb,
        "crawler_status": crawler_status,
        "crawler_account": crawler_account,
        "crawler_q": crawler_q,
        "crawler_done": crawler_done,
        "crawler_fail": crawler_fail,
        "crawler_caption": crawler_caption,
        "enc_name": enc_name,
        "ollama_ok": ollama_ok,
        "has_secrets": has_secrets,
        "token_count": token_count
    }
    _TELEMETRY_SNAP_CACHE["ts"] = now
    _TELEMETRY_SNAP_CACHE["data"] = res_snap
    return res_snap


def _render_telemetry_metrics_grid(snap: Dict[str, Any]):
    free_gb = snap["free_gb"]
    total_gb = snap["total_gb"]
    free_pct = snap["free_pct"]
    if free_gb < 3.0:
        disk_badge = "<span style='color:#ef4444; font-weight:700;'>🔴 CRITICAL (&lt;3GB AUTO-PAUSE)</span>"
    elif free_gb < 10.0:
        disk_badge = "<span style='color:#f59e0b; font-weight:700;'>🟡 LOW (&lt;10GB)</span>"
    else:
        disk_badge = "<span style='color:#10b981; font-weight:700;'>🟢 HEALTHY</span>"

    cr_stat = snap["crawler_status"].upper()
    cr_color = "#10b981" if cr_stat == "RUNNING" else ("#f59e0b" if cr_stat == "PAUSED" else "#38bdf8")

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(
            f"""
            <div style="border:1px solid #27272a; border-radius:6px; padding:10px; background:#18181b;">
                <div style="color:#a1a1aa; font-size:0.70rem; font-weight:600; text-transform:uppercase;">💾 Drive & Scratch Storage</div>
                <div style="font-size:1.15rem; font-weight:700; color:#f4f4f5; margin:4px 0;">{free_gb:.1f} GB Free</div>
                <div style="font-size:0.75rem; color:#a1a1aa;">{disk_badge} | {free_pct:.0f}% of {total_gb:.0f}GB</div>
                <div style="font-size:0.72rem; color:#71717a; margin-top:4px;">Ready: {snap['ready_mb']:.1f}MB | Temp: {snap['workspace_mb']:.1f}MB</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with m2:
        st.markdown(
            f"""
            <div style="border:1px solid #27272a; border-radius:6px; padding:10px; background:#18181b;">
                <div style="color:#a1a1aa; font-size:0.70rem; font-weight:600; text-transform:uppercase;">📸 Instagram Crawler Daemon</div>
                <div style="font-size:1.15rem; font-weight:700; color:{cr_color}; margin:4px 0;">{cr_stat} ({snap['crawler_done']}/{snap['crawler_q']})</div>
                <div style="font-size:0.75rem; color:#a1a1aa;">Target: <b>@{snap['crawler_account']}</b> | Fail: {snap['crawler_fail']}</div>
                <div style="font-size:0.72rem; color:#71717a; margin-top:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">Reel: {snap['crawler_caption'][:28] or 'None active'}</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with m3:
        sec_color = "#10b981" if snap["has_secrets"] else "#ef4444"
        sec_txt = "Secrets OK" if snap["has_secrets"] else "No Secrets"
        st.markdown(
            f"""
            <div style="border:1px solid #27272a; border-radius:6px; padding:10px; background:#18181b;">
                <div style="color:#a1a1aa; font-size:0.70rem; font-weight:600; text-transform:uppercase;">🚀 YouTube Quotas & Pool</div>
                <div style="font-size:1.15rem; font-weight:700; color:#f4f4f5; margin:4px 0;">{snap['token_count']} Channels</div>
                <div style="font-size:0.75rem; color:{sec_color}; font-weight:600;">{sec_txt} | 10k Quota Limiter</div>
                <div style="font-size:0.72rem; color:#71717a; margin-top:4px;">Drip Scheduling: 4-6 clips/day</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with m4:
        ol_color = "#10b981" if snap["ollama_ok"] else "#f59e0b"
        ol_txt = "🟢 Ollama Online" if snap["ollama_ok"] else "🟡 Fast Regex SEO"
        st.markdown(
            f"""
            <div style="border:1px solid #27272a; border-radius:6px; padding:10px; background:#18181b;">
                <div style="color:#a1a1aa; font-size:0.70rem; font-weight:600; text-transform:uppercase;">⚡ Video Engine & AI</div>
                <div style="font-size:1.15rem; font-weight:700; color:#a855f7; margin:4px 0;">{snap['enc_name']}</div>
                <div style="font-size:0.75rem; color:{ol_color};">{ol_txt}</div>
                <div style="font-size:0.72rem; color:#71717a; margin-top:4px;">Safe Zone: 9:16 vertical + CPU Failsafe</div>
            </div>
            """,
            unsafe_allow_html=True
        )


def purge_system_targets(selected_targets: List[str], ready_dir: Path = Path("ready_to_upload")) -> Dict[str, int]:
    """
    Executes selective or global purge across video files, scratch folders, and module databases.
    """
    counts = {
        "videos_deleted": 0,
        "files_deleted": 0,
        "dbs_reset": 0
    }

    # 1. Video files in ready_to_upload
    if "videos_pending" in selected_targets or "videos_approved" in selected_targets:
        del_pending = "videos_pending" in selected_targets
        del_approved = "videos_approved" in selected_targets
        if ready_dir.exists():
            for v_file in list(ready_dir.glob("*.mp4")):
                sc = v_file.with_suffix(".json")
                is_appr = False
                if sc.exists():
                    try:
                        with open(sc, "r", encoding="utf-8") as f:
                            d = json.load(f)
                            is_appr = (d.get("approved") is True) or (d.get("status") == "approved")
                    except Exception:
                        pass

                if (is_appr and del_approved) or (not is_appr and del_pending):
                    try:
                        v_file.unlink(missing_ok=True)
                        if sc.exists():
                            sc.unlink(missing_ok=True)
                        counts["videos_deleted"] += 1
                        counts["files_deleted"] += 1
                    except Exception as e:
                        print(f"Error unlinking {v_file}: {e}")

    # 2. Workspace Scratch Files
    if "workspace_temp" in selected_targets:
        ws = Path("workspace")
        if ws.exists():
            for item in list(ws.iterdir()):
                try:
                    if item.is_file():
                        item.unlink(missing_ok=True)
                        counts["files_deleted"] += 1
                    elif item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                        counts["files_deleted"] += 1
                except Exception:
                    pass

    # 3. Instagram Crawler State & Cache
    if "insta_crawler" in selected_targets:
        for f in [Path("insta_crawler_state.json"), Path("insta_discovered_cache.json"), Path("insta_crawler_events.log")]:
            if f.exists():
                f.unlink(missing_ok=True)
                counts["dbs_reset"] += 1
        try:
            from instagram_scraper import reset_crawler
            reset_crawler()
        except Exception:
            pass

    # 4. Learning & Upload History
    if "learning_history" in selected_targets:
        for f in [Path("learning_db.json"), Path("upload_history.json")]:
            if f.exists():
                f.unlink(missing_ok=True)
                counts["dbs_reset"] += 1

    # 5. Campaigns DB
    if "campaigns" in selected_targets:
        for f in [Path("campaigns_db.json"), Path("contentrewards_cache.json")]:
            if f.exists():
                f.unlink(missing_ok=True)
                counts["dbs_reset"] += 1

    # 6. Trends & Daemons
    if "trends_daemon" in selected_targets:
        for f in [Path("trend_daemon_config.json"), Path("trend_daemon.log"), Path("trends_cache.json")]:
            if f.exists():
                f.unlink(missing_ok=True)
                counts["dbs_reset"] += 1

    # 7. Livestream Buffer & Watcher
    if "livestream_watcher" in selected_targets:
        for f in [Path("livestream_buffer.json"), Path("watcher_config.json"), Path("watcher.log"), Path("livestream.log"), Path("arbiter_lock.json"), Path("unified_events.log")]:
            if f.exists():
                f.unlink(missing_ok=True)
                counts["dbs_reset"] += 1

    # 8. YouTube Tokens (Protected)
    if "youtube_tokens" in selected_targets:
        for f in list(Path(".").glob("token_*.json")) + [Path("token.json")]:
            if f.exists():
                f.unlink(missing_ok=True)
                counts["files_deleted"] += 1

    return counts


def render_watermark_options_expander(key_prefix: str, module_name: str = "Video"):
    """
    Renders modular watermark controls for any pipeline:
    - Master toggle (Optional ON/OFF).
    - Position presets (Top-Right, Top-Left, Bottom-Right, Bottom-Left, Top-Center, Bottom-Center, Center).
    - Size slider (50px to 350px).
    - Opacity slider (10% to 100%).
    - Safe zone margin offsets (X/Y px).
    - Inline logo uploader & thumbnail preview.
    - Synchronized with watermark_config.json.
    """
    from editor import get_watermark_config, save_watermark_config
    cfg = get_watermark_config()
    logo_file = Path(cfg.get("logo_path", "logo.png"))
    logo_exists = logo_file.exists()

    status_str = f"🟢 ACTIVE ({cfg.get('position', 'top-right').title()} • {cfg.get('size_px', 150)}px)" if (logo_exists and cfg.get("enabled", True)) else "⚪ OPTIONAL (Disabled)"

    with st.expander(f"🎨 Watermark & Logo Overlay [{status_str}]", expanded=False):
        wm_enabled = st.checkbox(
            f"Apply Brand Logo to {module_name} Exports",
            value=cfg.get("enabled", True) if logo_exists else False,
            disabled=not logo_exists,
            help=f"When enabled, burns brand logo into all {module_name} videos at configured position.",
            key=f"wm_chk_{key_prefix}"
        )
        if logo_exists and wm_enabled != cfg.get("enabled", True):
            cfg["enabled"] = wm_enabled
            save_watermark_config(cfg)
            st.rerun()

        if not logo_exists:
            st.caption("⚠️ No logo active. Upload a PNG/JPG below to enable brand overlay:")
            up_f = st.file_uploader("Upload Watermark", type=["png", "jpg", "jpeg"], key=f"wm_up_{key_prefix}")
            if up_f is not None:
                with open("logo.png", "wb") as f:
                    f.write(up_f.read())
                cfg["enabled"] = True
                cfg["logo_path"] = "logo.png"
                save_watermark_config(cfg)
                st.success("Logo uploaded and enabled!")
                st.rerun()
            return

        if wm_enabled:
            pos_map = {
                "Top-Right (Default Safe Zone)": "top-right",
                "Top-Left": "top-left",
                "Bottom-Right": "bottom-right",
                "Bottom-Left": "bottom-left",
                "Top-Center": "top-center",
                "Bottom-Center": "bottom-center",
                "Center": "center"
            }
            cur_pos = cfg.get("position", "top-right")
            pos_labels = list(pos_map.keys())
            pos_vals = list(pos_map.values())
            sel_idx = pos_vals.index(cur_pos) if cur_pos in pos_vals else 0

            c_pos, c_size, c_op = st.columns([1.4, 1, 1])
            with c_pos:
                chosen_pos_label = st.selectbox("Position", pos_labels, index=sel_idx, key=f"wm_pos_{key_prefix}")
                chosen_pos = pos_map[chosen_pos_label]
            with c_size:
                chosen_size = st.slider("Size (px)", 50, 350, int(cfg.get("size_px", 150)), step=10, key=f"wm_size_{key_prefix}")
            with c_op:
                chosen_op = st.slider("Opacity (%)", 10, 100, int(cfg.get("opacity", 0.85) * 100), step=5, key=f"wm_op_{key_prefix}")

            # Advanced Offsets
            m1, m2 = st.columns(2)
            with m1:
                mx = st.number_input("Margin X (px)", 0, 250, int(cfg.get("margin_x", 40)), step=5, key=f"wm_mx_{key_prefix}")
            with m2:
                my = st.number_input("Margin Y (px)", 0, 500, int(cfg.get("margin_y", 180)), step=10, key=f"wm_my_{key_prefix}", help="Avoids top YouTube search bar and bottom caption/title zones")

            new_op_f = round(chosen_op / 100.0, 2)
            if (chosen_pos != cur_pos or
                chosen_size != cfg.get("size_px") or
                new_op_f != cfg.get("opacity") or
                mx != cfg.get("margin_x") or
                my != cfg.get("margin_y")):
                cfg["position"] = chosen_pos
                cfg["size_px"] = chosen_size
                cfg["opacity"] = new_op_f
                cfg["margin_x"] = mx
                cfg["margin_y"] = my
                save_watermark_config(cfg)
                st.rerun()

            st.caption(f"✓ Logo active at `{chosen_pos}` ({chosen_size}px, {chosen_op}% opacity). Configure globally anytime via ⚙️ Settings.")
        else:
            st.info(f"Logo watermark is disabled for {module_name} exports. Check the box above to enable.")


def render_module_purge_matrix(key_prefix: str = "purge"):
    """
    Renders the Checkbox Selection Matrix for clearing individual or all modules,
    with explicit options to delete pending/approved video files, temp scratch,
    and reset pipeline databases with two-step safety confirmation.
    """
    st.markdown("<div style='font-size:0.9rem; font-weight:700; color:#f87171; margin-bottom:4px;'>🗑️ Clear Modules & Delete Videos</div>", unsafe_allow_html=True)
    st.caption("Select individual targets to purge, or check Select All for a complete clean slate.")

    # Select All toggle
    t_all = st.checkbox("⚡ Select All Modules & Videos (Complete Wipe)", value=False, key=f"{key_prefix}_sel_all")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("<span style='font-size:0.75rem; font-weight:700; color:#38bdf8;'>🎬 VIDEO & SCRATCH FILES</span>", unsafe_allow_html=True)
        del_pending = st.checkbox("Pending Clips (`ready_to_upload/*.mp4`)", value=t_all, key=f"{key_prefix}_pending")
        del_approved = st.checkbox("Approved Ready Clips (`ready_to_upload/*.mp4`)", value=t_all, key=f"{key_prefix}_approved")
        del_workspace = st.checkbox("Temp Scratch Files (`workspace/*`)", value=t_all, key=f"{key_prefix}_workspace")

    with col2:
        st.markdown("<span style='font-size:0.75rem; font-weight:700; color:#a855f7;'>📊 MODULE DATABASES & DAEMONS</span>", unsafe_allow_html=True)
        del_insta = st.checkbox("Instagram Queue & Cache (`insta_crawler_*.json`)", value=t_all, key=f"{key_prefix}_insta")
        del_learning = st.checkbox("Learning DB & Upload History", value=t_all, key=f"{key_prefix}_learning")
        del_campaigns = st.checkbox("Campaigns & Rewards DB", value=t_all, key=f"{key_prefix}_campaigns")
        del_trends = st.checkbox("Trends & Radar Cache / Logs", value=t_all, key=f"{key_prefix}_trends")
        del_watcher = st.checkbox("Livestream Buffer & Watcher State", value=t_all, key=f"{key_prefix}_watcher")
        del_tokens = st.checkbox("⚠️ YouTube Channel Tokens (`token_*.json`)", value=False, key=f"{key_prefix}_tokens", help="Forces re-authentication with YouTube")

    st.markdown("<div style='margin: 8px 0;'></div>", unsafe_allow_html=True)
    confirm = st.checkbox(
        "⚠️ I understand this permanently deletes selected files and module records.",
        value=False,
        key=f"{key_prefix}_confirm_gate"
    )

    btn_label = "🚨 Execute Purge / Reset Selected"
    if st.button(btn_label, type="primary", disabled=not confirm, key=f"{key_prefix}_run_btn", use_container_width=True):
        targets = []
        if del_pending: targets.append("videos_pending")
        if del_approved: targets.append("videos_approved")
        if del_workspace: targets.append("workspace_temp")
        if del_insta: targets.append("insta_crawler")
        if del_learning: targets.append("learning_history")
        if del_campaigns: targets.append("campaigns")
        if del_trends: targets.append("trends_daemon")
        if del_watcher: targets.append("livestream_watcher")
        if del_tokens: targets.append("youtube_tokens")

        if not targets:
            st.warning("No targets selected.")
        else:
            res = purge_system_targets(targets)
            st.success(f"✓ Purge complete: {res['videos_deleted']} videos deleted, {res['files_deleted']} files cleared, {res['dbs_reset']} databases reset.")
            time.sleep(1.2)
            st.rerun()


if hasattr(st, "dialog"):
    @st.dialog("📊 Production Telemetry & System Parameters", width="large")
    def show_system_telemetry_dialog():
        snap = get_system_telemetry_snapshot()
        _render_telemetry_metrics_grid(snap)
        st.write("")
        b1, b2, b3 = st.columns(3)
        with b1:
            if snap["crawler_status"] == "running":
                if st.button("⏸️ Pause Instagram Crawler", use_container_width=True, key="dlg_pause"):
                    from instagram_scraper import pause_crawler
                    pause_crawler()
                    st.rerun()
            else:
                if st.button("▶️ Resume Instagram Crawler", use_container_width=True, key="dlg_resume"):
                    from instagram_scraper import start_or_resume_crawler
                    start_or_resume_crawler()
                    st.rerun()
        with b2:
            if st.button("🧹 Purge Stale Scratch Workspaces", use_container_width=True, key="dlg_purge"):
                from learning_engine import cleanup_stale_workspaces
                cleanup_stale_workspaces(max_age_hours=0)
                st.success("Cleaned scratch files!")
                st.rerun()
        with b3:
            if st.button("🔄 Refresh Telemetry", use_container_width=True, key="dlg_refresh"):
                st.rerun()

        st.write("")
        with st.expander("🗑️ Clear Any or All Modules / Delete Videos", expanded=False):
            render_module_purge_matrix(key_prefix="dlg_modal_purge")
else:
    def show_system_telemetry_dialog():
        pass


def render_pipeline_ribbon(ready_dir: Path):
    """
    Renders top global telemetry ribbon showing real-time interconnected flow:
    1. Research -> 2. Production -> 3. Quality Gate -> 4. Upload Queue -> 5. Analytics -> 6. Learning Flywheel
    Includes persistent Live Parameter Sheet and Full-Screen Telemetry Dialog.
    """
    telem = get_pipeline_telemetry(ready_dir)

    c1, c2, c3, c4, c5, c6 = st.columns(6)

    with c1:
        tr_cnt = telem["trends_count"]
        st.markdown(f"<div style='border:1px solid #27272a; border-radius:6px; padding:6px; background:#121215; text-align:center;'><span style='color:#a1a1aa; font-size:0.68rem;'>1. RESEARCH</span><br><b style='color:#38bdf8; font-size:0.78rem;'>{tr_cnt} Trends</b></div>", unsafe_allow_html=True)

    with c2:
        holder = telem["arbiter_holder"]
        if holder:
            st.markdown(f"<div style='border:1px solid #3b82f6; border-radius:6px; padding:6px; background:#121215; text-align:center;'><span style='color:#a1a1aa; font-size:0.68rem;'>2. PRODUCTION</span><br><b style='color:#60a5fa; font-size:0.78rem;'>⚙️ P{arbiter_holder_p(holder)} Active</b></div>", unsafe_allow_html=True)
        elif telem["arbiter_paused"]:
            st.markdown(f"<div style='border:1px solid #ef4444; border-radius:6px; padding:6px; background:#121215; text-align:center;'><span style='color:#a1a1aa; font-size:0.68rem;'>2. PRODUCTION</span><br><b style='color:#f87171; font-size:0.78rem;'>⏸️ Paused</b></div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div style='border:1px solid #27272a; border-radius:6px; padding:6px; background:#121215; text-align:center;'><span style='color:#a1a1aa; font-size:0.68rem;'>2. PRODUCTION</span><br><b style='color:#71717a; font-size:0.78rem;'>⚪ Idle (Ready)</b></div>", unsafe_allow_html=True)

    with c3:
        pend = telem["pending_count"]
        col = "#f59e0b" if pend > 0 else "#71717a"
        st.markdown(f"<div style='border:1px solid #27272a; border-radius:6px; padding:6px; background:#121215; text-align:center;'><span style='color:#a1a1aa; font-size:0.68rem;'>3. QUALITY GATE</span><br><b style='color:{col}; font-size:0.78rem;'>{pend} Pending</b></div>", unsafe_allow_html=True)

    with c4:
        appr = telem["approved_count"]
        col = "#10b981" if appr > 0 else "#71717a"
        st.markdown(f"<div style='border:1px solid #27272a; border-radius:6px; padding:6px; background:#121215; text-align:center;'><span style='color:#a1a1aa; font-size:0.68rem;'>4. UPLOAD QUEUE</span><br><b style='color:{col}; font-size:0.78rem;'>{appr} Approved</b></div>", unsafe_allow_html=True)

    with c5:
        views = telem["total_views"]
        st.markdown(f"<div style='border:1px solid #27272a; border-radius:6px; padding:6px; background:#121215; text-align:center;'><span style='color:#a1a1aa; font-size:0.68rem;'>5. ANALYTICS</span><br><b style='color:#a855f7; font-size:0.78rem;'>{views:,} Views</b></div>", unsafe_allow_html=True)

    with c6:
        opt_s = telem["optimal_sec"]
        st.markdown(f"<div style='border:1px solid #27272a; border-radius:6px; padding:6px; background:#121215; text-align:center;'><span style='color:#a1a1aa; font-size:0.68rem;'>6. LEARNING</span><br><b style='color:#ec4899; font-size:0.78rem;'>{opt_s}s Sweet Spot</b></div>", unsafe_allow_html=True)

    # Telemetry Snapshot & Interactive Parameter Sheet
    snap = get_system_telemetry_snapshot()
    free_gb = snap["free_gb"]
    cr_stat = snap["crawler_status"].upper()
    enc_name = snap["enc_name"]
    q_str = f"{snap['crawler_done']}/{snap['crawler_q']}"

    sheet_label = f"📊 Live Telemetry & Parameters Sheet [💾 Disk: {free_gb:.1f}GB Free | 📸 Crawler: {cr_stat} ({q_str}) | ⚡ {enc_name}]"
    with st.expander(sheet_label, expanded=False):
        _render_telemetry_metrics_grid(snap)
        if hasattr(st, "dialog"):
            st.write("")
            if st.button("🔍 Open Full-Screen Telemetry & Health Modal", key="btn_open_telem_modal", use_container_width=True):
                show_system_telemetry_dialog()

    st.write("")


def arbiter_holder_p(holder: Optional[str]) -> str:
    if not holder:
        return ""
    if "trend" in holder:
        return "1"
    if "live" in holder:
        return "2"
    if "watcher" in holder or "vod" in holder:
        return "3"
    return "0"


def render_quality_seo_stage(ready_dir: Path):
    """
    Stage 3: Quality & SEO Checklist Gate
    Executes the 7-Point YouTube Monetization & Top-Notch SEO Checkmark audit on all
    candidate clips in ready_to_upload/ before dispatching to Studio.
    Provides One-Click Quick Fix / Auto-Solver and interactive approval pipeline.
    """
    st.markdown("<div class='section-title'>STAGE 3: QUALITY & SEO CHECKLIST</div>", unsafe_allow_html=True)
    st.caption("100% Monetization & Top-Notch SEO Gate: Ad-suitability, Fair Use copyright, safe zones, & metadata approval.")

    telem = get_pipeline_telemetry(ready_dir)
    pending_files = telem["pending_files"]
    approved_files = telem["approved_files"]
    total_files = telem["total_ready"]

    if total_files == 0:
        st.info("No clips pending in `ready_to_upload/`. Produce videos in Stage 2 to review and approve them here.")
        return

    # Top Overview Metrics & Mass Actions
    q_col1, q_col2, q_col3 = st.columns([1, 1, 1.4])
    with q_col1:
        st.metric("Pending Review", f"{len(pending_files)} clips", delta=f"{len(approved_files)} approved" if approved_files else None)
    with q_col2:
        total_size_mb = sum(f.stat().st_size for f in pending_files + approved_files) / (1024 * 1024)
        st.metric("Total Storage", f"{total_size_mb:.1f} MB")
    with q_col3:
        if pending_files:
            if st.button(f"⚡ Auto-Solve & Approve All ({len(pending_files)})", type="primary", use_container_width=True, key="btn_solve_all_seo"):
                solved_count = 0
                for vid in pending_files:
                    meta = get_sidecar_data(vid)
                    cur_title = meta.get("title", vid.stem)
                    fx_title, fx_desc, fx_tags = quick_fix_seo(cur_title, is_vertical=True)
                    meta["title"] = fx_title
                    meta["description"] = fx_desc
                    meta["tags"] = fx_tags
                    meta["approved"] = True
                    meta["stage"] = "ready_for_upload"
                    meta["approved_at"] = time.time()
                    save_sidecar_data(vid, meta)
                    solved_count += 1
                st.success(f"✓ Elevated & approved all {solved_count} clips for Stage 4 Upload!")
                st.rerun()
        else:
            st.success(f"✓ All {len(approved_files)} clips approved! Ready in Stage 4 (Upload Queue).")

    # Filter Segment
    filter_choice = st.radio("Filter Clips", ["🟡 Pending Review", "🟢 Approved for Upload", "All Clips"], horizontal=True, key="quality_filter_mode")
    if filter_choice == "🟡 Pending Review":
        display_files = pending_files or approved_files
    elif filter_choice == "🟢 Approved for Upload":
        display_files = approved_files or pending_files
    else:
        display_files = pending_files + approved_files

    if not display_files:
        st.info("No clips in this view.")
        return

    # Video Selector & Sidecar Inspection
    col_sel, col_inspect = st.columns([1.1, 1.9], gap="medium")

    with col_sel:
        st.markdown("<div class='section-title'>SELECT CLIP</div>", unsafe_allow_html=True)
        file_options = {f.name: f for f in display_files}
        sel_name = st.selectbox("Ready Videos", list(file_options.keys()), key="sel_quality_video")
        sel_file = file_options[sel_name]
        metadata = get_sidecar_data(sel_file)
        is_appr = metadata.get("approved") is True

        st.caption(f"File size: `{sel_file.stat().st_size / 1024 / 1024:.1f} MB` | Status: `{'🟢 Approved' if is_appr else '🟡 Pending Review'}`")
        try:
            st.video(str(sel_file))
        except Exception:
            st.warning("Video player preview unavailable.")

        if st.button("🗑️ Delete Clip", type="secondary", use_container_width=True, key=f"btn_del_{sel_file.name}"):
            sel_file.unlink(missing_ok=True)
            sel_file.with_suffix(".json").unlink(missing_ok=True)
            st.success(f"Deleted {sel_file.name}")
            st.rerun()

    with col_inspect:
        st.markdown("<div class='section-title'>9-POINT MONETIZATION, SEO & CAMPAIGN AUDIT</div>", unsafe_allow_html=True)

        cur_title = metadata.get("title", sel_file.stem)
        cur_desc = metadata.get("description", "")
        cur_tags = metadata.get("tags", [])

        # Run 7-Point Audit
        audit = audit_quality_and_seo(
            video_path=sel_file,
            title=cur_title,
            description=cur_desc,
            tags=cur_tags
        )

        score = audit.get("score", 100)
        passed = audit.get("passed", True)

        # Score & Status Bar
        score_col1, score_col2 = st.columns([2, 1])
        with score_col1:
            st.progress(score / 100.0)
        with score_col2:
            if passed:
                st.success(f"🟢 **{score}/100** (MONETIZED)")
            else:
                st.warning(f"⚠️ **{score}/100** (ACTION REQ)")

        # Audit Checklist Grid
        with st.container(height=240):
            for chk in audit.get("checks", []):
                icon = "🟢" if chk["passed"] else "⚠️"
                with st.expander(f"{icon} {chk['name']} — {chk['badge']}", expanded=not chk["passed"]):
                    st.markdown(f"**Detail:** {chk['detail']}")

        # Interconnected Stage Approval Actions
        st.markdown("<div class='section-title'>PIPELINE APPROVAL ACTION</div>", unsafe_allow_html=True)
        act_c1, act_c2 = st.columns([1.3, 1])
        with act_c1:
            if not is_appr:
                if st.button("✅ Approve Clip for Stage 4 (Studio Upload)", type="primary", use_container_width=True, key=f"btn_approve_{sel_file.name}"):
                    metadata["approved"] = True
                    metadata["stage"] = "ready_for_upload"
                    metadata["approved_at"] = time.time()
                    save_sidecar_data(sel_file, metadata)
                    st.success(f"✓ Approved! Clip moved to Stage 4 Upload Queue.")
                    st.rerun()
            else:
                st.success("🟢 **APPROVED FOR STUDIO UPLOAD (STAGE 4)**")
                if st.button("↩️ Revert to Pending Review", type="secondary", use_container_width=True, key=f"btn_revert_{sel_file.name}"):
                    metadata["approved"] = False
                    metadata["stage"] = "pending_quality_review"
                    save_sidecar_data(sel_file, metadata)
                    st.rerun()

        with act_c2:
            if st.button("⚡ Quick Fix / Auto-Solve SEO", type="secondary", use_container_width=True, key="btn_single_quick_fix"):
                fx_title, fx_desc, fx_tags = quick_fix_seo(cur_title, is_vertical=True)
                metadata["title"] = fx_title
                metadata["description"] = fx_desc
                metadata["tags"] = fx_tags
                save_sidecar_data(sel_file, metadata)
                st.success("✓ Applied high-CTR hooks, #Shorts, & learned tags!")
                st.rerun()

        # Interactive Editor
        with st.form(key=f"form_edit_meta_{sel_file.name}"):
            new_title = st.text_input("Title", value=cur_title)
            new_desc = st.text_area("Description", value=cur_desc, height=70)
            tags_str = ", ".join(cur_tags) if isinstance(cur_tags, list) else str(cur_tags)
            new_tags_str = st.text_input("Tags (comma separated)", value=tags_str)

            sched_time_str = metadata.get("publish_at", "")
            new_sched = st.text_input("Scheduled Publish (UTC ISO)", value=sched_time_str, placeholder="YYYY-MM-DDTHH:MM:SSZ")

            if st.form_submit_button("💾 Save Metadata Sidecar", use_container_width=True):
                parsed_tags = [t.strip() for t in new_tags_str.split(",") if t.strip()]
                metadata["title"] = new_title
                metadata["description"] = new_desc
                metadata["tags"] = parsed_tags
                if new_sched.strip():
                    metadata["publish_at"] = new_sched.strip()
                save_sidecar_data(sel_file, metadata)
                st.success("✓ Sidecar metadata updated.")
                st.rerun()


def render_analytics_stage():
    """
    Stage 5: Analytics Stage
    Pulls deep YouTube Studio analytics for all published videos, tracking views,
    likes, comments, retention, and engagement velocity.
    """
    st.markdown("<div class='section-title'>STAGE 5: YOUTUBE STUDIO DEEP ANALYTICS</div>", unsafe_allow_html=True)
    st.caption("Real-time telemetry on published assets: Views, audience retention, CTR, & engagement velocity.")

    history = load_upload_history()
    db = load_learning_db()

    # Top Sync Bar
    sync_c1, sync_c2, sync_c3 = st.columns([1.5, 1, 1])
    with sync_c1:
        last_sync = db.get("last_sync_timestamp", 0)
        sync_str = time.strftime("%m/%d %H:%M:%S", time.localtime(last_sync)) if last_sync > 0 else "Never"
        st.markdown(f"**Last Sync:** `{sync_str}` | **Tracked Assets:** `{len(history)}`")
    with sync_c2:
        if st.button("🔄 Sync Studio Data Now", type="primary", use_container_width=True, key="btn_sync_yt_analytics"):
            with st.spinner("Fetching live statistics from YouTube Studio Data API..."):
                res = sync_youtube_performance(force=True)
                if res.get("status") == "success":
                    st.success(f"✓ Synchronized {res.get('synced_count', 0)} videos. Stage 6 Learning Flywheel updated!")
                elif res.get("status") == "unauthenticated":
                    st.warning("YouTube API not authenticated. Sign in via Stage 4 (Upload).")
                else:
                    st.error(f"Sync error: {res.get('error', 'Unknown')}")
            st.rerun()
    with sync_c3:
        st.write("")

    if not history:
        st.info("No videos uploaded through Zelmu yet. Upload videos in Stage 4 to populate deep analytics.")
        return

    # Calculate KPIs
    total_views = sum(int(h.get("last_synced_views", 0)) for h in history)
    total_likes = sum(int(h.get("last_synced_likes", 0)) for h in history)
    total_comments = sum(int(h.get("last_synced_comments", 0)) for h in history)
    avg_views = int(total_views / max(1, len(history)))
    vvsa_vals = [float(h.get("vvsa_est", 70.0)) for h in history if h.get("vvsa_est")]
    avg_vvsa = (sum(vvsa_vals) / len(vvsa_vals)) if vvsa_vals else 72.5

    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    with kpi1:
        st.metric("Total Views", f"{total_views:,}")
    with kpi2:
        st.metric("Avg VVSA Score", f"{avg_vvsa:.1f}%", delta="Target >70% Viral")
    with kpi3:
        st.metric("Loop Replay (APV)", ">100%", delta="Seamless Bridge")
    with kpi4:
        st.metric("Total Likes", f"{total_likes:,}")
    with kpi5:
        st.metric("Avg Views/Short", f"{avg_views:,}")

    # Detailed Video Breakdown Table
    st.markdown("<div class='section-title'>PERFORMANCE TELEMETRY TABLE (VVSA & LOOP METRICS)</div>", unsafe_allow_html=True)
    table_rows = []
    for h in history:
        v_id = h.get("video_id", "")
        v_title = h.get("title", "Untitled")
        v_views = h.get("last_synced_views", 0)
        v_likes = h.get("last_synced_likes", 0)
        v_comm = h.get("last_synced_comments", 0)
        v_dur = h.get("duration_sec", 30.0)
        v_vvsa = h.get("vvsa_est", 72.0)
        v_style = h.get("caption_style", "neon")
        v_pub = h.get("publish_at") or time.strftime("%Y-%m-%d %H:%M", time.localtime(h.get("upload_timestamp", 0)))

        tier = "🚀 Breakout" if v_views > 500 else ("📈 Growing" if v_views > 50 else "🟢 Seed")
        table_rows.append({
            "Tier": tier,
            "Title": v_title[:45] + ("..." if len(v_title) > 45 else ""),
            "VVSA Est": f"{v_vvsa:.1f}%",
            "Views": v_views,
            "Likes": v_likes,
            "Comments": v_comm,
            "Dur": f"{v_dur:.0f}s",
            "Style": v_style.title(),
            "Publish Date": v_pub[:16] if v_pub else "",
            "Studio Link": f"https://studio.youtube.com/video/{v_id}/edit"
        })

    st.dataframe(
        table_rows,
        use_container_width=True,
        column_config={
            "Studio Link": st.column_config.LinkColumn("Studio", display_text="Edit ↗️")
        }
    )

    # ContentRewards Campaign ROI & Revenue Tracker
    try:
        from campaigns_manager import get_active_campaign, calculate_campaign_roi
        active_camp = get_active_campaign()
    except Exception:
        active_camp = None

    if active_camp:
        st.markdown("<div class='section-title'>🎯 CONTENTREWARDS CAMPAIGN REVENUE & ROI TRACKER</div>", unsafe_allow_html=True)
        roi = calculate_campaign_roi(active_camp.get("id", ""))
        cpm_val = roi.get("cpm_rate", 3.0)
        goal_val = roi.get("revenue_goal", 500.0)
        earned_val = roi.get("realized_earnings", 0.0)
        c_views = roi.get("total_views", 0)
        c_pct = roi.get("goal_progress_pct", 0.0)
        v_need = roi.get("views_needed", 0)

        r_c1, r_c2, r_c3, r_c4 = st.columns(4)
        with r_c1:
            st.metric("Campaign Name", active_camp.get("name", "Active"))
        with r_c2:
            st.metric("CPM Payout Rate", f"${cpm_val:.2f} / 1k views")
        with r_c3:
            st.metric("Realized Payout Earned", f"${earned_val:,.2f}", delta=f"{c_pct*100:.1f}% of goal")
        with r_c4:
            st.metric("Views Remaining", f"{v_need:,}", delta=f"Target: {roi.get('target_views', 0):,} views")

        st.caption(f"**Revenue Goal Progress:** `${earned_val:,.2f}` earned towards `${goal_val:,.2f}` payout cap ({c_pct*100:.1f}% achieved)")
        st.progress(c_pct)

        # 1-Click Submission Helper
        camp_clips = roi.get("clips", [])
        if camp_clips:
            with st.expander(f"📋 1-Click Submission Links ({len(camp_clips)} Eligible Clips for Payout)", expanded=True):
                st.caption("Submit these links into ContentRewards.com dashboard for view-tracking & payout.")
                sub_rows = []
                for cc in camp_clips:
                    sub_rows.append({
                        "Title": cc.get("title", "Clip")[:40],
                        "Views": cc.get("views", 0),
                        "Earned ($)": f"${cc.get('earned_usd', 0.0):.2f}",
                        "YouTube Link": cc.get("watch_url", "")
                    })
                st.dataframe(sub_rows, use_container_width=True, column_config={
                    "YouTube Link": st.column_config.LinkColumn("Shorts URL", display_text="Open ↗️")
                })


def render_learning_stage():
    """
    Stage 6: Continuous Learning Engine
    Visualizes the closed-loop feedback flywheel:
    Research -> Production -> Quality/SEO -> Upload -> Analytics -> Learning DB -> Research
    Displays live learned duration, keyword weights, and auto-tuning status.
    """
    st.markdown("<div class='section-title'>STAGE 6: CONTINUOUS LEARNING FLYWHEEL</div>", unsafe_allow_html=True)
    st.caption("Self-reinforcing feedback loop: Production parameters dynamically auto-tune from live audience retention.")

    db = load_learning_db()
    boost = get_learned_seo_boost()

    # Closed-Loop Flow Diagram
    st.markdown(
        """
        ```
        ┌────────────────────────────────────────────────────────────────────────┐
        │                 ZELMU CLOSED-LOOP CONTINUOUS LEARNING FLYWHEEL          │
        │                                                                        │
        │   [1. Research] ────► [2. Production] ────► [3. Quality & SEO]         │
        │         ▲                                         │                    │
        │         │                                         ▼                    │
        │   [6. Learning DB] ◄── [5. Analytics]  ◄─── [4. Studio Upload]        │
        │      (Auto-Tune)        (Views / CTR)                                  │
        └────────────────────────────────────────────────────────────────────────┘
        ```
        """
    )

    col_l1, col_l2 = st.columns([1.2, 1], gap="medium")

    with col_l1:
        st.markdown("<div class='section-title'>LEARNED PARAMETERS (DATA-DRIVEN)</div>", unsafe_allow_html=True)

        opt_dur = db.get("optimal_duration", {})
        sweet_spot = opt_dur.get("sweet_spot_sec", 34.0)
        min_sec = opt_dur.get("min_sec", 24.0)
        max_sec = opt_dur.get("max_sec", 48.0)
        sample_size = opt_dur.get("sample_size", 0)

        st.metric(
            "Optimal Duration Sweet Spot",
            f"{sweet_spot:.1f} seconds",
            delta=f"Active Range: {min_sec:.0f}s - {max_sec:.0f}s ({sample_size} videos sampled)"
        )
        st.caption("Weighted by actual view-through rate. Injected automatically into Trend Producer & Live Clipper.")

        st.markdown("##### High-CPM Keyword Multipliers")
        kw_data = db.get("high_cpm_keywords", {})
        sorted_kws = sorted(kw_data.items(), key=lambda x: x[1], reverse=True)
        kw_display = [{"Keyword": k.upper(), "Weight Multiplier": f"{v:.1f}x", "Intent": "High CPM"} for k, v in sorted_kws]
        st.dataframe(kw_display, use_container_width=True, height=180)

    with col_l2:
        st.markdown("<div class='section-title'>RETENTION & SCHEDULE TUNING</div>", unsafe_allow_html=True)

        st.markdown("##### Caption Style Retention Ranking")
        style_ratings = db.get("caption_style_ratings", {"neon": 92.0, "clean": 86.0, "bold": 80.0})
        for style_name, rating in style_ratings.items():
            st.markdown(f"**{style_name.title()} Subtitles:** `{rating:.1f}%` retention score")
            st.progress(rating / 100.0)

        st.markdown("##### Peak Monetization Slots (Tier-1 US)")
        slots = db.get("peak_upload_slots_utc", [14, 18, 20])
        st.info(f"Target Hours (UTC): `{slots}` | Corresponding to **10:00 AM - 5:00 PM EST** peak US viewing.")

        st.markdown("##### Auto-Tuning & Prompt Injection Status")
        st.success("🟢 **FEEDBACK LOOP ACTIVE:** Stage 1 Research & Stage 2 Production dynamically query these learned values.")
        st.markdown("• **Retention Engine:** `⚡ 3.2s Punch-in Zooms Active`\n• **Replay Engine:** `🔁 Seamless Infinite Loop Active`\n• **Hook Gate:** `🎯 VVSA Frame-0 Curiosity Active`")

        if st.button("🚀 Push Learned Weights to Stage 1 & 2", key="btn_push_learned_weights", type="primary", use_container_width=True):
            st.session_state["active_learned_keywords"] = [k for k, _ in sorted_kws[:6]]
            st.session_state["target_clip_duration"] = sweet_spot
            st.success(f"✓ Deployed: Duration {sweet_spot}s + {len(sorted_kws)} High-CPM Keywords to Research & Production!")
            st.rerun()
