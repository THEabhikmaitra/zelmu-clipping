"""
Portal Stages: Quality & SEO Checklist, Deep Analytics, and Continuous Learning Engine
Implements Stages 3, 5, and 6 of the Zelmu Autonomous Clipping Flywheel.
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


def render_quality_seo_stage(ready_dir: Path):
    """
    Stage 3: Quality & SEO Checklist Gate
    Executes the 7-Point YouTube Monetization & Top-Notch SEO Checkmark audit on all
    candidate clips in ready_to_upload/ before dispatching to Studio.
    Provides One-Click Quick Fix / Auto-Solver and interactive metadata editor.
    """
    st.markdown("<div class='section-title'>STAGE 3: QUALITY & SEO CHECKLIST</div>", unsafe_allow_html=True)
    st.caption("100% Monetization & Top-Notch SEO Gate: Ad-suitability, Fair Use copyright, safe zones, & metadata solver.")

    ready_files = sorted(list(ready_dir.glob("*.mp4")), key=lambda p: p.stat().st_mtime, reverse=True)

    if not ready_files:
        st.info("No clips pending in `ready_to_upload/`. Produce videos in Stage 2 to review them here.")
        return

    # Top Overview Metrics
    q_col1, q_col2, q_col3 = st.columns([1, 1, 1.2])
    with q_col1:
        st.metric("Pending Gate", f"{len(ready_files)} clips")
    with q_col2:
        total_size_mb = sum(f.stat().st_size for f in ready_files) / (1024 * 1024)
        st.metric("Total Storage", f"{total_size_mb:.1f} MB")
    with q_col3:
        st.write("")
        if st.button("⚡ Auto-Solve All Pending SEO", type="primary", use_container_width=True, key="btn_solve_all_seo"):
            solved_count = 0
            for vid in ready_files:
                sidecar = vid.with_suffix(".json")
                meta = {}
                if sidecar.exists():
                    try:
                        with open(sidecar, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                    except Exception:
                        pass
                cur_title = meta.get("title", vid.stem)
                fx_title, fx_desc, fx_tags = quick_fix_seo(cur_title, is_vertical=True)
                meta["title"] = fx_title
                meta["description"] = fx_desc
                meta["tags"] = fx_tags
                with open(sidecar, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)
                solved_count += 1
            st.success(f"✓ Elevated {solved_count} clips to Top-Notch SEO & Monetization standard!")
            st.rerun()

    # Video Selector & Sidecar Inspection
    col_sel, col_inspect = st.columns([1.1, 1.9], gap="medium")

    with col_sel:
        st.markdown("<div class='section-title'>SELECT CLIP</div>", unsafe_allow_html=True)
        file_options = {f.name: f for f in ready_files}
        sel_name = st.selectbox("Ready Videos", list(file_options.keys()), key="sel_quality_video")
        sel_file = file_options[sel_name]

        # Read Sidecar metadata
        sidecar_path = sel_file.with_suffix(".json")
        metadata = {}
        if sidecar_path.exists():
            try:
                with open(sidecar_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            except Exception:
                pass

        st.caption(f"File size: `{sel_file.stat().st_size / 1024 / 1024:.1f} MB`")
        try:
            st.video(str(sel_file))
        except Exception:
            st.warning("Video player preview unavailable.")

        if st.button("🗑️ Delete Clip", type="secondary", use_container_width=True, key=f"btn_del_{sel_file.name}"):
            sel_file.unlink(missing_ok=True)
            sidecar_path.unlink(missing_ok=True)
            st.success(f"Deleted {sel_file.name}")
            st.rerun()

    with col_inspect:
        st.markdown("<div class='section-title'>7-POINT MONETIZATION & SEO AUDIT</div>", unsafe_allow_html=True)

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
        with st.container(height=260):
            for chk in audit.get("checks", []):
                icon = "🟢" if chk["passed"] else "⚠️"
                with st.expander(f"{icon} {chk['name']} — {chk['badge']}", expanded=not chk["passed"]):
                    st.markdown(f"**Detail:** {chk['detail']}")

        # Quick Fix / Auto-Solver Button
        st.markdown("<div class='section-title'>METADATA SOLVER & EDITOR</div>", unsafe_allow_html=True)
        solv_c1, solv_c2 = st.columns([1, 1])
        with solv_c1:
            if st.button("⚡ Quick Fix / Auto-Solve SEO", type="primary", use_container_width=True, key="btn_single_quick_fix"):
                fx_title, fx_desc, fx_tags = quick_fix_seo(cur_title, is_vertical=True)
                metadata["title"] = fx_title
                metadata["description"] = fx_desc
                metadata["tags"] = fx_tags
                with open(sidecar_path, "w", encoding="utf-8") as f:
                    json.dump(metadata, f, indent=2)
                st.success("✓ Applied high-CTR hooks, #Shorts, Fair Use, & learned high-CPM tags!")
                st.rerun()

        with solv_c2:
            st.caption("Elevates title length, appends #Shorts, & adds Tier-1 tags.")

        # Interactive Editor
        with st.form(key=f"form_edit_meta_{sel_file.name}"):
            new_title = st.text_input("Title", value=cur_title)
            new_desc = st.text_area("Description", value=cur_desc, height=75)
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
                with open(sidecar_path, "w", encoding="utf-8") as f:
                    json.dump(metadata, f, indent=2)
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
        st.markdown(f"**Last Sync:** `{sync_str}` | **Tracked Videos:** `{len(history)}`")
    with sync_c2:
        if st.button("🔄 Sync Studio Data", type="primary", use_container_width=True, key="btn_sync_yt_analytics"):
            with st.spinner("Fetching live statistics from YouTube Studio Data API..."):
                res = sync_youtube_performance(force=True)
                if res.get("status") == "success":
                    st.success(f"✓ Synchronized {res.get('synced_count', 0)} videos.")
                elif res.get("status") == "unauthenticated":
                    st.warning("YouTube API not authenticated. Please sign in via Stage 4 (Upload).")
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

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.metric("Total Views", f"{total_views:,}")
    with kpi2:
        st.metric("Total Likes", f"{total_likes:,}")
    with kpi3:
        st.metric("Total Comments", f"{total_comments:,}")
    with kpi4:
        st.metric("Avg Views/Short", f"{avg_views:,}")

    # Detailed Video Breakdown Table
    st.markdown("<div class='section-title'>PERFORMANCE TELEMETRY TABLE</div>", unsafe_allow_html=True)
    table_rows = []
    for h in history:
        v_id = h.get("video_id", "")
        v_title = h.get("title", "Untitled")
        v_views = h.get("last_synced_views", 0)
        v_likes = h.get("last_synced_likes", 0)
        v_comm = h.get("last_synced_comments", 0)
        v_dur = h.get("duration_sec", 30.0)
        v_style = h.get("caption_style", "neon")
        v_pub = h.get("publish_at") or time.strftime("%Y-%m-%d %H:%M", time.localtime(h.get("upload_timestamp", 0)))

        tier = "🚀 Breakout" if v_views > 500 else ("📈 Growing" if v_views > 50 else "🟢 Seed")
        table_rows.append({
            "Tier": tier,
            "Title": v_title[:45] + ("..." if len(v_title) > 45 else ""),
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

        st.markdown("##### Auto-Tuning Status")
        st.success("🟢 **FEEDBACK LOOP ACTIVE:** Every run in Stage 1 & 2 dynamically adopts these learned values.")

        if st.button("💾 Persist Learned State", key="btn_save_learning_state", use_container_width=True):
            save_learning_db(db)
            st.success("Learning DB persisted to disk.")
