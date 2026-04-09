"""ai-benchmarks data explorer — Streamlit app.

Run with: .venv/bin/streamlit run explorer/app.py
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).resolve().parent.parent / "results" / "bench.sqlite"

BUCKET_ORDER = ["<1B", "<3B", "<7B", "<10B", "<15B", "<25B", "<35B", ">=35B"]

st.set_page_config(page_title="ai-benchmarks explorer", layout="wide")


@st.cache_data(ttl=30)
def load_runs() -> pd.DataFrame:
    """Load all runs joined with their LATEST judge score across all sweeps."""
    con = sqlite3.connect(DB_PATH)
    q = """
    SELECT
      r.id AS run_id, r.sweep_id, r.model, r.bucket, r.task_id, r.category,
      r.response, r.ttft_ms, r.duration_ms, r.tokens_out, r.tokens_per_sec,
      r.peak_rss_mb, r.error,
      s.score, s.criteria_json, s.reasoning AS judge_reasoning, s.judge_model
    FROM runs r
    LEFT JOIN scores s ON s.id = (
      SELECT MAX(s2.id) FROM scores s2 WHERE s2.run_id = r.id
    )
    """
    df = pd.read_sql(q, con)
    con.close()
    return df


@st.cache_data(ttl=30)
def load_sweeps() -> pd.DataFrame:
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM sweeps ORDER BY started_at DESC", con)
    con.close()
    return df


@st.cache_data(ttl=30)
def load_pairwise() -> pd.DataFrame:
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM pairwise", con)
    con.close()
    return df


def bucket_key(b: str) -> int:
    try:
        return BUCKET_ORDER.index(b)
    except ValueError:
        return 99


def parse_criteria_json(value: object) -> dict | list:
    if not isinstance(value, str):
        return {}
    if not value or value == "[]":
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, (dict, list)) else {}


# -------------------- sidebar --------------------
st.sidebar.title("🎯 ai-benchmarks")
page = st.sidebar.radio(
    "View",
    ["Leaderboards", "Task drill-down", "Model compare", "Tournaments", "Run inspector", "Sweeps", "Raw DB"],
)

runs = load_runs()
sweeps = load_sweeps()

st.sidebar.caption(f"{len(runs)} runs across {len(sweeps)} sweeps")
st.sidebar.caption(f"{runs['model'].nunique()} unique models")
st.sidebar.caption(f"{runs['task_id'].nunique()} unique tasks")

# -------------------- Leaderboards --------------------
if page == "Leaderboards":
    st.title("📊 Cross-sweep leaderboards")
    st.caption("Uses the **latest** judge score per run across ALL sweeps. Filter to drill into a specific slice.")

    col1, col2, col3 = st.columns(3)
    with col1:
        sel_bucket = st.multiselect("Buckets", sorted(runs["bucket"].dropna().unique(), key=bucket_key), default=None)
    with col2:
        sel_cat = st.multiselect("Categories", sorted(runs["category"].dropna().unique()))
    with col3:
        sel_judge = st.multiselect("Judge model", sorted(runs["judge_model"].dropna().unique()))

    df = runs.dropna(subset=["score"]).copy()
    if sel_bucket:
        df = df[df["bucket"].isin(sel_bucket)]
    if sel_cat:
        df = df[df["category"].isin(sel_cat)]
    if sel_judge:
        df = df[df["judge_model"].isin(sel_judge)]

    if df.empty:
        st.warning("No scored runs match these filters.")
        st.stop()

    agg = (
        df.groupby(["model", "bucket"])
        .agg(
            quality=("score", "mean"),
            runs=("score", "count"),
            tok_s=("tokens_per_sec", "mean"),
            ttft_ms=("ttft_ms", "mean"),
            peak_rss_gb=("peak_rss_mb", lambda x: x.mean() / 1024),
        )
        .reset_index()
    )
    agg["composite"] = (agg["quality"] / 5) * agg["tok_s"]
    agg["bucket_sort"] = agg["bucket"].apply(bucket_key)
    agg = agg.sort_values(["bucket_sort", "quality"], ascending=[True, False])

    st.subheader("Overall leaderboard")
    st.dataframe(
        agg.drop(columns=["bucket_sort"]).style.format({
            "quality": "{:.2f}", "tok_s": "{:.1f}", "ttft_ms": "{:.0f}",
            "peak_rss_gb": "{:.1f}", "composite": "{:.2f}",
        }),
        width="stretch", height=min(800, 45 + 36 * len(agg)),
    )

    st.divider()
    st.subheader("Per-bucket leaderboards (fair comparison)")
    for bucket in sorted(agg["bucket"].unique(), key=bucket_key):
        b_df = agg[agg["bucket"] == bucket].drop(columns=["bucket", "bucket_sort"])
        st.markdown(f"**{bucket}** — {len(b_df)} models")
        st.dataframe(
            b_df.style.format({
                "quality": "{:.2f}", "tok_s": "{:.1f}", "ttft_ms": "{:.0f}",
                "peak_rss_gb": "{:.1f}", "composite": "{:.2f}",
            }),
            width="stretch", hide_index=True,
        )

    st.divider()
    st.subheader("Per-category quality heatmap")
    cat_pivot = df.pivot_table(index="model", columns="category", values="score", aggfunc="mean")
    st.dataframe(cat_pivot.style.format("{:.2f}").background_gradient(axis=None, cmap="RdYlGn", vmin=1, vmax=5), width="stretch")

# -------------------- Task drill-down --------------------
elif page == "Task drill-down":
    st.title("🔍 Task drill-down")
    st.caption("Pick a task, see every model's response side-by-side with scores.")

    task_ids = sorted(runs["task_id"].dropna().unique())
    sel_task = st.selectbox("Task", task_ids)
    task_runs = runs[runs["task_id"] == sel_task].sort_values("score", ascending=False, na_position="last")

    if task_runs.empty:
        st.warning("No runs for this task.")
        st.stop()

    st.markdown(f"**Category**: `{task_runs.iloc[0]['category']}` • **Runs**: {len(task_runs)}")

    for _, r in task_runs.iterrows():
        score = r["score"] if pd.notna(r["score"]) else "—"
        badge_color = {1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢", 5: "🟢"}.get(int(r["score"]) if pd.notna(r["score"]) else 0, "⚪")
        with st.expander(
            f"{badge_color} **{r['model']}** ({r['bucket']}) — score: {score}/5 • {r['tokens_out']}tok @ {r['tokens_per_sec']:.0f}tok/s",
            expanded=False,
        ):
            col_l, col_r = st.columns([3, 2])
            with col_l:
                st.markdown("**Response:**")
                st.code(r["response"] or "(empty)", language=None, wrap_lines=True)
            with col_r:
                st.markdown("**Metrics:**")
                st.caption(f"TTFT: {r['ttft_ms']:.0f}ms  •  duration: {r['duration_ms']/1000:.1f}s")
                st.caption(f"tokens out: {r['tokens_out']}  •  peak RSS: {r['peak_rss_mb']/1024:.1f}GB")
                if r["error"]:
                    st.error(f"Error: {r['error']}")
                st.markdown("**Judge:**")
                st.caption(f"Model: `{r['judge_model']}`")
                st.caption(f"Reasoning: _{r['judge_reasoning']}_")
                parsed = parse_criteria_json(r["criteria_json"])
                criteria = parsed.get("criteria", []) if isinstance(parsed, dict) else parsed
                for c in criteria:
                    if isinstance(c, dict):
                        mark = "✅" if c.get("pass") else "❌"
                        st.caption(f"{mark} **{c.get('name', '?')}**: {c.get('note', '')}")

# -------------------- Model compare --------------------
elif page == "Model compare":
    st.title("⚔️ Model compare")
    st.caption("Pick 2+ models, see all their outputs side-by-side across tasks they've both run.")

    all_models = sorted(runs["model"].unique())
    sel_models = st.multiselect("Models (pick 2-6)", all_models, max_selections=6)

    if len(sel_models) < 2:
        st.info("Pick at least 2 models.")
        st.stop()

    sel_cat = st.multiselect("Categories (optional)", sorted(runs["category"].dropna().unique()))

    df = runs[runs["model"].isin(sel_models)].copy()
    if sel_cat:
        df = df[df["category"].isin(sel_cat)]

    # Cross-sweep data can contain multiple runs for the same model/task pair.
    # Use the latest run so the side-by-side compare has one row per model.
    compare_df = df.sort_values("run_id").drop_duplicates(["task_id", "model"], keep="last")

    # tasks where all selected models have a run
    task_counts = compare_df.groupby("task_id")["model"].nunique()
    common_tasks = task_counts[task_counts == len(sel_models)].index.tolist()

    st.caption(f"{len(common_tasks)} tasks have runs for all {len(sel_models)} selected models")

    if not common_tasks:
        st.warning("No common tasks — try fewer models or different filter.")
        st.stop()

    # summary stats
    summary = (
        compare_df[compare_df["task_id"].isin(common_tasks)]
        .dropna(subset=["score"])
        .groupby(["model", "bucket"])
        .agg(
            quality=("score", "mean"),
            tok_s=("tokens_per_sec", "mean"),
            peak_rss_gb=("peak_rss_mb", lambda x: x.mean() / 1024),
        )
        .reset_index()
    )
    summary["composite"] = (summary["quality"] / 5) * summary["tok_s"]
    st.subheader("Summary on shared task set")
    st.dataframe(
        summary.sort_values("quality", ascending=False).style.format({
            "quality": "{:.2f}", "tok_s": "{:.1f}", "peak_rss_gb": "{:.1f}", "composite": "{:.2f}",
        }),
        hide_index=True, width="stretch",
    )

    st.divider()
    sel_task = st.selectbox("Drill into a specific task", common_tasks)
    task_df = compare_df[compare_df["task_id"] == sel_task].set_index("model").reindex(sel_models)

    cols = st.columns(len(sel_models))
    for col, model in zip(cols, sel_models):
        r = task_df.loc[model]
        with col:
            score = r["score"] if pd.notna(r["score"]) else "—"
            st.markdown(f"### `{model}`")
            st.caption(f"Score: **{score}/5**  •  {r['tokens_out']}tok @ {r['tokens_per_sec']:.0f}tok/s")
            st.code(r["response"] or "(empty)", language=None, wrap_lines=True)
            if pd.notna(r["judge_reasoning"]):
                st.caption(f"_Judge: {r['judge_reasoning']}_")

# -------------------- Tournaments --------------------
elif page == "Tournaments":
    st.title("🏆 Tournaments")
    st.caption("Cross-sweep head-to-head matches using stored outputs. Run with `bench tournament --bucket \"<10B\"`.")

    con = sqlite3.connect(DB_PATH)
    try:
        trns = pd.read_sql("SELECT * FROM tournaments ORDER BY created_at DESC", con)
    except Exception:
        trns = pd.DataFrame()
    if trns.empty:
        st.info("No tournaments run yet. Try `bench tournament --bucket \"<10B\"` from the CLI.")
        con.close()
        st.stop()

    st.dataframe(trns, hide_index=True, width="stretch")

    sel_trn = st.selectbox("Pick a tournament", trns["id"].tolist())
    matches = pd.read_sql("SELECT * FROM tournament_matches WHERE tournament_id = ?", con, params=[sel_trn])
    con.close()

    if matches.empty:
        st.warning("No matches for this tournament.")
        st.stop()

    # Standings via win counts
    def _wins(m):
        w = defaultdict(int); l = defaultdict(int); t = defaultdict(int)
        for _, row in m.iterrows():
            if row["winner"] == "A":
                w[row["model_a"]] += 1; l[row["model_b"]] += 1
            elif row["winner"] == "B":
                w[row["model_b"]] += 1; l[row["model_a"]] += 1
            else:
                t[row["model_a"]] += 1; t[row["model_b"]] += 1
        return w, l, t

    from collections import defaultdict
    w, l, t = _wins(matches)
    models = sorted(set(matches["model_a"]).union(set(matches["model_b"])))

    # Bradley-Terry Elo
    try:
        from bench.pairwise import bradley_terry, to_elo
        strengths = bradley_terry([(row["model_a"], row["model_b"], row["winner"]) for _, row in matches.iterrows()])
        elo = to_elo(strengths)
    except Exception:
        elo = {m: 1000.0 for m in models}

    standings = pd.DataFrame([
        {"model": m, "Elo": round(elo.get(m, 1000), 0), "W": w[m], "L": l[m], "T": t[m]}
        for m in models
    ]).sort_values("Elo", ascending=False)

    st.subheader("Standings")
    st.dataframe(standings, hide_index=True, width="stretch")

    st.divider()
    st.subheader("Head-to-head matrix (win % of row-model vs column-model)")
    h2h = pd.DataFrame(0.0, index=models, columns=models)
    for a in models:
        for b in models:
            if a == b:
                continue
            ab = matches[(matches["model_a"] == a) & (matches["model_b"] == b)]
            ba = matches[(matches["model_a"] == b) & (matches["model_b"] == a)]
            a_wins = (ab["winner"] == "A").sum() + (ba["winner"] == "B").sum()
            b_wins = (ab["winner"] == "B").sum() + (ba["winner"] == "A").sum()
            ties = (ab["winner"] == "tie").sum() + (ba["winner"] == "tie").sum()
            total = a_wins + b_wins + ties
            h2h.loc[a, b] = (a_wins + 0.5 * ties) / total if total > 0 else 0.5
    st.dataframe(h2h.style.format("{:.2f}").background_gradient(axis=None, cmap="RdYlGn", vmin=0, vmax=1), width="stretch")

    st.divider()
    st.subheader("Match details")
    task_filter = st.multiselect("Filter by task", sorted(matches["task_id"].unique()))
    df = matches if not task_filter else matches[matches["task_id"].isin(task_filter)]
    st.dataframe(df[["task_id", "model_a", "model_b", "winner", "reasoning"]], hide_index=True, width="stretch", height=400)


# -------------------- Run inspector --------------------
elif page == "Run inspector":
    st.title("🧪 Run inspector")
    st.caption("Single-run detail view — paste a run ID or filter.")

    col1, col2, col3 = st.columns(3)
    with col1:
        sel_model = st.selectbox("Model", [""] + sorted(runs["model"].unique()))
    with col2:
        sel_cat = st.selectbox("Category", [""] + sorted(runs["category"].dropna().unique()))
    with col3:
        sel_sweep = st.selectbox("Sweep", [""] + sorted(runs["sweep_id"].dropna().unique(), reverse=True))

    df = runs.copy()
    if sel_model:
        df = df[df["model"] == sel_model]
    if sel_cat:
        df = df[df["category"] == sel_cat]
    if sel_sweep:
        df = df[df["sweep_id"] == sel_sweep]

    st.caption(f"{len(df)} runs match")

    if df.empty:
        st.stop()

    view_cols = ["run_id", "model", "task_id", "category", "score", "tokens_per_sec", "peak_rss_mb", "judge_model"]
    st.dataframe(df[view_cols], hide_index=True, width="stretch", height=400)

    sel_run = st.number_input("Run ID to inspect", min_value=int(df["run_id"].min()), max_value=int(df["run_id"].max()), value=int(df["run_id"].iloc[0]))
    row = df[df["run_id"] == sel_run]
    if not row.empty:
        r = row.iloc[0]
        st.subheader(f"Run {sel_run} — {r['model']} / {r['task_id']}")
        st.markdown(f"**Category**: {r['category']} • **Sweep**: `{r['sweep_id']}` • **Score**: {r['score']}")
        st.code(r["response"] or "(empty)", language=None, wrap_lines=True)
        criteria_json = parse_criteria_json(r["criteria_json"])
        if criteria_json:
            st.json(criteria_json)
        if r["error"]:
            st.error(r["error"])

# -------------------- Sweeps --------------------
elif page == "Sweeps":
    st.title("🗂️ Sweeps")
    st.dataframe(sweeps, hide_index=True, width="stretch")

    st.divider()
    st.subheader("Runs per sweep")
    by_sweep = runs.groupby("sweep_id").agg(
        runs=("run_id", "count"),
        models=("model", "nunique"),
        scored=("score", lambda x: x.notna().sum()),
    ).reset_index().sort_values("sweep_id", ascending=False)
    st.dataframe(by_sweep, hide_index=True, width="stretch")

# -------------------- Raw DB --------------------
elif page == "Raw DB":
    st.title("💾 Raw data")
    st.caption("Pandas DataFrames — copy, export, whatever.")
    tab1, tab2, tab3 = st.tabs(["runs", "sweeps", "pairwise"])
    with tab1:
        st.dataframe(runs, width="stretch", height=600)
        st.download_button("Download as CSV", runs.to_csv(index=False), "runs.csv", "text/csv")
    with tab2:
        st.dataframe(sweeps, width="stretch")
    with tab3:
        st.dataframe(load_pairwise(), width="stretch", height=600)
