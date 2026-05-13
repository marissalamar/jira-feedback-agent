import os
import sys
from collections import Counter
from datetime import datetime, timezone

import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from scraper import (
    run_scraper, load_results, load_history, get_date_range,
    load_summary, generate_executive_summary,
    RESULTS_FILE, DAYS_WINDOW,
)
from scheduler import start_scheduler, get_next_run, update_schedule, load_log

st.set_page_config(
    page_title="Jira Product Intelligence",
    page_icon="📊",
    layout="wide"
)

# ── Executive styling ──────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* Global */
  html, body, [class*="css"] {
    font-family: 'Inter', 'Segoe UI', sans-serif;
    background-color: #f8f9fb;
    color: #1a1a2e;
  }

  /* Hide Streamlit chrome */
  #MainMenu, footer, header { visibility: hidden; }

  /* Main container */
  .block-container {
    padding: 2rem 3rem 3rem 3rem;
    max-width: 1400px;
  }

  /* Page header */
  .page-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    color: white;
    padding: 2rem 2.5rem;
    border-radius: 12px;
    margin-bottom: 1.5rem;
  }
  .page-header h1 {
    font-size: 1.8rem;
    font-weight: 700;
    margin: 0 0 0.3rem 0;
    color: white;
  }
  .page-header p {
    font-size: 0.9rem;
    opacity: 0.75;
    margin: 0;
    color: white;
  }

  /* KPI cards */
  .kpi-card {
    background: white;
    border-radius: 10px;
    padding: 1.25rem 1.5rem;
    box-shadow: 0 1px 4px rgba(0,0,0,0.07);
    border-left: 4px solid #4361ee;
    margin-bottom: 0.5rem;
  }
  .kpi-card.red { border-left-color: #e63946; }
  .kpi-card.amber { border-left-color: #f4a261; }
  .kpi-card.green { border-left-color: #2a9d8f; }
  .kpi-label {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #6b7280;
    margin-bottom: 0.25rem;
  }
  .kpi-value {
    font-size: 2rem;
    font-weight: 700;
    color: #1a1a2e;
    line-height: 1;
  }

  /* Executive summary card */
  .exec-card {
    background: white;
    border-radius: 12px;
    padding: 1.75rem 2rem;
    box-shadow: 0 1px 4px rgba(0,0,0,0.07);
    border-top: 4px solid #4361ee;
    margin-bottom: 1.5rem;
  }
  .exec-card h3 {
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #4361ee;
    margin: 0 0 0.75rem 0;
  }
  .exec-card h2 {
    font-size: 1.2rem;
    font-weight: 700;
    color: #1a1a2e;
    margin: 0 0 1rem 0;
  }

  /* Section headers */
  .section-header {
    font-size: 1rem;
    font-weight: 700;
    color: #1a1a2e;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    border-bottom: 2px solid #e5e7eb;
    padding-bottom: 0.5rem;
    margin: 1.75rem 0 1rem 0;
  }

  /* Sidebar */
  [data-testid="stSidebar"] {
    background: #1a1a2e;
    color: white;
  }
  [data-testid="stSidebar"] * {
    color: white !important;
  }
  [data-testid="stSidebar"] .stButton button {
    background: #4361ee;
    color: white;
    border: none;
    border-radius: 8px;
    font-weight: 600;
    padding: 0.6rem 1rem;
  }
  [data-testid="stSidebar"] .stButton button:hover {
    background: #3451d1;
  }

  /* Dataframe */
  [data-testid="stDataFrame"] {
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }

  /* Tabs */
  .stTabs [data-baseweb="tab-list"] {
    gap: 0.5rem;
    border-bottom: 2px solid #e5e7eb;
  }
  .stTabs [data-baseweb="tab"] {
    font-weight: 600;
    font-size: 0.85rem;
    color: #6b7280;
    padding: 0.5rem 1rem;
    border-radius: 6px 6px 0 0;
  }
  .stTabs [aria-selected="true"] {
    color: #4361ee !important;
    border-bottom: 2px solid #4361ee;
  }

  /* Warning/info banners */
  [data-testid="stAlert"] {
    border-radius: 8px;
    font-size: 0.875rem;
  }

  /* Expanders */
  [data-testid="stExpander"] {
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    background: white;
  }
</style>
""", unsafe_allow_html=True)

# ── Start the background scheduler once per process ───────────────────────────
if "scheduler_started" not in st.session_state:
    start_scheduler(hour=2, minute=0)
    st.session_state["scheduler_started"] = True
    st.session_state["sched_hour"] = 2
    st.session_state["sched_minute"] = 0

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Controls")
    refresh = st.button("🔄 Refresh Data", use_container_width=True)

    st.divider()

    if os.path.exists(RESULTS_FILE):
        mtime = os.path.getmtime(RESULTS_FILE)
        last_run = datetime.fromtimestamp(mtime).strftime("%b %d, %Y %H:%M")
        st.caption(f"Last updated: {last_run}")
    else:
        st.caption("No data yet — click Refresh Data.")

    st.divider()
    st.markdown("### 🕐 Auto-Refresh")
    next_run = get_next_run()
    if next_run:
        try:
            nr_dt = datetime.fromisoformat(next_run)
            st.success(f"Next: {nr_dt.strftime('%b %d %H:%M')} UTC")
        except Exception:
            st.success(f"Next: {next_run}")
    else:
        st.warning("Scheduler not active")

    col_h, col_m = st.columns(2)
    with col_h:
        new_hour = st.selectbox("Hour (UTC)", options=list(range(24)),
            index=st.session_state.get("sched_hour", 2), key="sched_hour_sel")
    with col_m:
        new_minute = st.selectbox("Minute", options=[0, 15, 30, 45],
            index=[0, 15, 30, 45].index(st.session_state.get("sched_minute", 0)),
            key="sched_min_sel")
    if st.button("Update Schedule", use_container_width=True):
        update_schedule(hour=new_hour, minute=new_minute)
        st.session_state["sched_hour"] = new_hour
        st.session_state["sched_minute"] = new_minute
        st.rerun()

    sched_log = load_log()
    if sched_log:
        st.divider()
        st.markdown("### 📋 Refresh Log")
        for entry in reversed(sched_log[-5:]):
            ts  = entry.get("timestamp", "")[:16]
            msg = entry.get("message", "")
            cnt = entry.get("post_count")
            status = entry.get("status", "")
            icon = {"success": "✅", "error": "❌", "running": "⏳"}.get(status, "•")
            line = f"{icon} `{ts}` — {msg}"
            if cnt is not None:
                line += f" ({cnt} posts)"
            st.caption(line)

# ── Manual refresh ─────────────────────────────────────────────────────────────
if refresh:
    progress_bar = st.progress(0, text="Starting...")
    status_text = st.empty()

    def update_progress(stage, page, posts_found, total_posts, current_title):
        if stage == "scraping":
            progress_bar.progress(5, text=f"Scraping page {page}… ({posts_found} posts in window so far)")
            status_text.caption(f"Scanning board listing — page {page}")
        elif stage == "analysis":
            if total_posts and total_posts > 0:
                pct = 10 + int((posts_found / total_posts) * 85)
            else:
                pct = 10
            progress_bar.progress(pct, text=f"Analysing new post {posts_found+1}/{total_posts} with Claude…")
            status_text.caption(f"{(current_title or '')[:80]}")
        elif stage == "summary":
            progress_bar.progress(97, text="Generating executive summary…")
            status_text.caption("Almost done — asking Claude for the executive brief…")

    with st.spinner("Running scraper and Claude analysis..."):
        results = run_scraper(progress_callback=update_progress)

    progress_bar.progress(100, text="Done!")
    status_text.empty()
    st.success(f"✅ Analysed {len(results)} posts from the last {DAYS_WINDOW} days.")
    st.rerun()

# ── Load data ──────────────────────────────────────────────────────────────────
results = load_results()
history = load_history()

if not results:
    st.markdown("""
    <div class="page-header">
      <h1>📊 Jira Community Intelligence</h1>
      <p>Product feedback analysis powered by AI</p>
    </div>
    """, unsafe_allow_html=True)
    st.info("No data yet. Click **Refresh Data** in the sidebar to begin analysis.")
    st.stop()

df = pd.DataFrame(results)
_BAD_THEMES = {"Error", "Unknown", None}
df_clean = df[~df["theme"].isin(_BAD_THEMES) & df["theme"].notna()].copy()
pending_count = len(df) - len(df_clean)

# ── Date range ─────────────────────────────────────────────────────────────────
date_from, date_to = get_date_range(results)

def fmt_date(iso: str | None) -> str:
    if not iso:
        return "unknown"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%b %d, %Y")
    except Exception:
        return iso[:10]

if date_from and date_to and date_from[:10] == date_to[:10]:
    date_label = fmt_date(date_from)
else:
    date_label = f"{fmt_date(date_from)} – {fmt_date(date_to)}"

# ── Page header ────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="page-header">
  <h1>📊 Jira Community Intelligence Dashboard</h1>
  <p>Trailing {DAYS_WINDOW}-day analysis &nbsp;·&nbsp; {date_label} &nbsp;·&nbsp; Powered by Claude AI</p>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab_dashboard, tab_history = st.tabs(["📊 Dashboard", "📈 History & Trends"])

# ─────────────────────────────────────────────
# TAB 1 — DASHBOARD
# ─────────────────────────────────────────────
with tab_dashboard:

    # ── Executive AI Summary ──────────────────────────────────────────────────
    summary = load_summary()

    st.markdown('<div class="exec-card">', unsafe_allow_html=True)
    hcol, bcol = st.columns([5, 1])
    with hcol:
        st.markdown('<h3>🤖 AI Executive Brief</h3>', unsafe_allow_html=True)
        st.markdown('<h2>Executive Summary: Jira Community Support Analysis</h2>', unsafe_allow_html=True)
    with bcol:
        regen = st.button("↻ Regenerate", use_container_width=True, key="regen_summary")

    if regen:
        with st.spinner("Generating fresh brief…"):
            summary = generate_executive_summary(load_results())
        st.rerun()

    if summary:
        gen_time = summary.get("generated_at", "")[:16].replace("T", " ")
        good_ct  = summary.get("post_count", "?")
        total_ct = summary.get("total_count", "?")
        st.caption(f"Based on {good_ct} analysed posts (of {total_ct} total) · Generated {gen_time}")
        st.markdown(summary["markdown"])
    else:
        st.info("No summary yet — click **Refresh Data** in the sidebar to generate one.")

    st.markdown('</div>', unsafe_allow_html=True)

    # ── Pending banner ────────────────────────────────────────────────────────
    if pending_count > 0:
        st.warning(
            f"⚠️ **{pending_count} posts** are queued for re-analysis. "
            f"KPIs and charts reflect the **{len(df_clean)} successfully analysed posts**. "
            "Click **Refresh Data** to process all pending posts."
        )

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    high_count = len(df_clean[df_clean["severity"] == "high"])
    neg_count  = len(df_clean[df_clean["sentiment"] == "negative"])
    neg_pct    = round(neg_count / len(df_clean) * 100) if len(df_clean) else 0
    top_theme  = df_clean["theme"].mode()[0] if not df_clean.empty else "—"

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"""
        <div class="kpi-card">
          <div class="kpi-label">Posts Analysed</div>
          <div class="kpi-value">{len(df_clean):,}</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="kpi-card red">
          <div class="kpi-label">High Severity</div>
          <div class="kpi-value">{high_count}</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div class="kpi-card amber">
          <div class="kpi-label">Negative Sentiment</div>
          <div class="kpi-value">{neg_pct}%</div>
        </div>""", unsafe_allow_html=True)
    with c4:
        st.markdown(f"""
        <div class="kpi-card green">
          <div class="kpi-label">Top Theme</div>
          <div class="kpi-value" style="font-size:1.1rem;padding-top:0.4rem">{top_theme}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Posts table ───────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Post-Level Detail</div>', unsafe_allow_html=True)

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        severity_filter = st.multiselect("Severity", options=["high", "medium", "low"],
            default=["high", "medium", "low"])
    with col_f2:
        clean_sentiments = sorted(df_clean["sentiment"].unique().tolist())
        sentiment_filter = st.multiselect("Sentiment", options=clean_sentiments, default=clean_sentiments)
    with col_f3:
        theme_search = st.text_input("Search theme or title", placeholder="e.g. automation")

    filtered = df_clean[
        df_clean["severity"].isin(severity_filter) &
        df_clean["sentiment"].isin(sentiment_filter)
    ]
    if theme_search:
        mask = (
            filtered["theme"].str.contains(theme_search, case=False, na=False) |
            filtered["title"].str.contains(theme_search, case=False, na=False)
        )
        filtered = filtered[mask]

    severity_colors  = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    sentiment_icons  = {"negative": "😟", "neutral": "😐", "positive": "😊"}

    display_cols  = ["title", "post_date", "theme", "sentiment", "severity", "summary"]
    available_cols = [c for c in display_cols if c in filtered.columns]
    display_df    = filtered[available_cols].copy()

    if "post_date" in display_df.columns:
        display_df["post_date"] = display_df["post_date"].apply(lambda x: fmt_date(x) if x else "")
    if "severity" in display_df.columns:
        display_df["severity"] = display_df["severity"].map(lambda s: f"{severity_colors.get(s,'')} {s}")
    if "sentiment" in display_df.columns:
        display_df["sentiment"] = display_df["sentiment"].map(lambda s: f"{sentiment_icons.get(s,'')} {s}")

    display_df = display_df.rename(columns={
        "title": "Title", "post_date": "Date", "theme": "Theme",
        "sentiment": "Sentiment", "severity": "Severity", "summary": "Summary"
    })

    st.dataframe(display_df, width="stretch", hide_index=True)
    st.caption(f"Showing {len(filtered):,} of {len(df_clean):,} analysed posts")

    # ── Top Themes ────────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Top Themes</div>', unsafe_allow_html=True)
    theme_counts = Counter(df_clean["theme"].tolist())
    theme_df = pd.DataFrame(theme_counts.most_common(15), columns=["Theme", "Count"])
    col_a, col_b = st.columns([2, 1])
    with col_a:
        st.bar_chart(theme_df.set_index("Theme")["Count"])
    with col_b:
        st.dataframe(theme_df, width="stretch", hide_index=True)

    # ── Severity & Sentiment ──────────────────────────────────────────────────
    st.markdown('<div class="section-header">Severity & Sentiment Breakdown</div>', unsafe_allow_html=True)
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        sev_counts = df_clean["severity"].value_counts().reindex(["high", "medium", "low"], fill_value=0)
        st.write("**Severity Distribution**")
        st.bar_chart(sev_counts)
    with col_s2:
        sent_counts = df_clean["sentiment"].value_counts().reindex(["negative", "neutral", "positive"], fill_value=0)
        st.write("**Sentiment Distribution**")
        st.bar_chart(sent_counts)

    # ── High-Severity Callout ─────────────────────────────────────────────────
    high_df = df_clean[df_clean["severity"] == "high"]
    if not high_df.empty:
        st.markdown('<div class="section-header">🔴 High-Severity Issues Requiring Attention</div>',
                    unsafe_allow_html=True)
        for _, row in high_df.iterrows():
            label = f"{row['title']}  —  {fmt_date(row.get('post_date'))}"
            with st.expander(label):
                if row.get("url"):
                    st.markdown(f"[View original post →]({row['url']})")
                st.write(f"**Theme:** {row['theme']}")
                st.write(f"**Sentiment:** {row['sentiment']}")
                st.write(f"**Summary:** {row['summary']}")


# ─────────────────────────────────────────────
# TAB 2 — HISTORY & TRENDS
# ─────────────────────────────────────────────
with tab_history:
    if not history:
        st.info("No history yet. Run the scraper at least twice to see trends.")
        st.stop()

    rows = []
    for entry in history:
        ts = entry["timestamp"]
        sc = entry.get("sentiment_counts", {})
        sv = entry.get("severity_counts", {})
        dr = entry.get("date_range", {})
        rows.append({
            "Run": ts,
            "Posts": entry.get("post_count", 0),
            "Date From": fmt_date(dr.get("from")) if dr else "",
            "Date To":   fmt_date(dr.get("to"))   if dr else "",
            "Negative":  sc.get("negative", 0),
            "Neutral":   sc.get("neutral", 0),
            "Positive":  sc.get("positive", 0),
            "High":      sv.get("high", 0),
            "Medium":    sv.get("medium", 0),
            "Low":       sv.get("low", 0),
        })
    hist_df = pd.DataFrame(rows)
    hist_df["Run"] = pd.to_datetime(hist_df["Run"])
    hist_df = hist_df.sort_values("Run")
    hist_df["Run Label"] = hist_df["Run"].dt.strftime("%m/%d %H:%M")

    st.markdown('<div class="section-header">Run History</div>', unsafe_allow_html=True)
    st.caption(f"{len(hist_df)} scraper run(s) recorded")
    display_hist = hist_df.drop(columns=["Run"]).rename(columns={"Run Label": "Timestamp"})
    st.dataframe(display_hist.set_index("Timestamp"), width="stretch")

    st.divider()

    if len(hist_df) >= 2:
        st.markdown('<div class="section-header">Sentiment Over Time</div>', unsafe_allow_html=True)
        st.line_chart(hist_df.set_index("Run Label")[["Negative", "Neutral", "Positive"]])

        st.markdown('<div class="section-header">Severity Over Time</div>', unsafe_allow_html=True)
        st.line_chart(hist_df.set_index("Run Label")[["High", "Medium", "Low"]])

        st.markdown('<div class="section-header">Theme Frequency Across All Runs</div>', unsafe_allow_html=True)
        all_themes: Counter = Counter()
        for entry in history:
            for r in entry.get("results", []):
                theme = r.get("theme", "Unknown")
                if theme != "Error":
                    all_themes[theme] += 1

        all_theme_df = pd.DataFrame(all_themes.most_common(15), columns=["Theme", "Total Mentions"])
        col_ta, col_tb = st.columns([2, 1])
        with col_ta:
            st.bar_chart(all_theme_df.set_index("Theme")["Total Mentions"])
        with col_tb:
            st.dataframe(all_theme_df, width="stretch", hide_index=True)

        st.markdown('<div class="section-header">Recurring Issues</div>', unsafe_allow_html=True)
        all_title_sets = [
            set(r["title"] for r in entry.get("results", []))
            for entry in history
        ]
        recurring = set.intersection(*all_title_sets) if all_title_sets else set()
        st.metric("Titles seen in every run", len(recurring))
        if recurring:
            with st.expander("View recurring titles"):
                for t in sorted(recurring):
                    st.write(f"- {t}")
    else:
        st.info("Run the scraper at least one more time to unlock trend charts.")
