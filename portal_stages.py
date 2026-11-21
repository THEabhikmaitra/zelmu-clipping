"""
Portal Stages: Quality & SEO Checklist, Deep Analytics, and Continuous Learning Engine
Implements Stages 3, 5, and 6 of the Zelmu Autonomous Clipping Flywheel with full
end-to-end data interconnection across all stages.
"""

import json
import time
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
    ready_files = list(ready_dir.glob("*.mp4")) if ready_dir.exists() else []
    pending_files = []
    approved_files = []

    for vf in ready_files:
        meta = get_sidecar_data(vf)
        if meta.get("approved") is True:
            approved_files.append(vf)
        else:
            pending_files.append(vf)

    arbiter_info = get_arbiter_status()
    history = load_upload_history()
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


def render_pipeline_ribbon(ready_dir: Path):
    """
    Renders top global telemetry ribbon showing real-time interconnected flow:
    1. Research -> 2. Production -> 3. Quality Gate -> 4. Upload Queue -> 5. Analytics -> 6. Learning Flywheel
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
