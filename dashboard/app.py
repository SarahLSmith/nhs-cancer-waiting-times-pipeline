"""Panel dashboard for the Cancer Waiting Times summary.

Run locally with:

    python -m streamlit run dashboard/app.py

It reads only the small files in ``outputs/``, so it works without the raw data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

OUTPUTS = Path(__file__).resolve().parent.parent / "outputs"
SUMMARY = OUTPUTS / "summary_icb_last_6_months.csv"
STATUS = OUTPUTS / "data_status.json"

STANDARD_NAMES = {
    "62D": "62-day (cancer treatment started within 62 days of urgent referral)",
    "31D": "31-day (first treatment started within 31 days of decision to treat)",
    "FDS": "Faster Diagnosis (diagnosed or ruled out within 28 days)",
}


@st.cache_data
def load_summary() -> pd.DataFrame:
    """Read the summary table produced by the pipeline."""
    df = pd.read_csv(SUMMARY, parse_dates=["period_start"])
    df["performance_pct"] = (df["performance"] * 100).round(1)
    return df


def main() -> None:
    st.set_page_config(page_title="Cancer waiting times by ICB", layout="wide")
    st.title("Cancer waiting times by ICB")

    if not SUMMARY.exists():
        st.error("No summary found. Run `python -m pipeline` first.")
        return

    status = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {}
    col1, col2, col3 = st.columns(3)
    col1.metric("Last pulled (UTC)", status.get("last_pulled_utc", "unknown"))
    col2.metric("Newest month", status.get("newest_month", "unknown")[:7])
    col3.metric("Provisional months", status.get("provisional_months", "unknown"))
    st.caption(
        "Provisional figures can still be revised by NHS England. "
        "ICBs are shown with their post-April 2026 names. Frimley ICB is excluded "
        "(it closed in March 2026 and its history cannot be split between the ICBs that replaced it)."
    )

    df = load_summary()
    standard = st.selectbox(
        "Standard",
        options=list(STANDARD_NAMES),
        format_func=lambda code: STANDARD_NAMES[code],
    )
    subset = df[df["standard"] == standard]
    latest = subset["period_start"].max()
    month = subset[subset["period_start"] == latest].sort_values("performance_pct")

    st.subheader(f"ICB performance, {latest:%B %Y}")
    st.caption(
        "Ranked from lowest to highest. Bars show the share of patients treated within the standard."
    )
    st.bar_chart(month.set_index("icb_name")["performance_pct"], horizontal=True)

    st.subheader("Trend over the last six months")
    pivot = subset.pivot_table(
        index="icb_name",
        columns="period_start",
        values="performance_pct",
        aggfunc="first",
    )
    pivot.columns = [c.strftime("%b %Y") for c in pivot.columns]
    st.dataframe(pivot.sort_index(), use_container_width=True)

    with st.expander("Full table"):
        st.dataframe(
            subset[
                [
                    "icb_name",
                    "period_start",
                    "total",
                    "within_standard",
                    "performance_pct",
                    "includes_provisional",
                ]
            ],
            use_container_width=True,
        )
    with st.expander("How performance is calculated"):
        st.write(
            "Performance = patients treated within the standard ÷ all patients in the measure. "
            "It is recalculated from the counts for each ICB; percentages are never averaged across ICBs."
        )


if __name__ == "__main__":
    main()
