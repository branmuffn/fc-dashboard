"""Support Ledger Reconciliation Dashboard (Streamlit UI).

Parsing, business rules and reconciliation live in ledger.py.
"""
import pandas as pd
import streamlit as st

import ledger as lg
from ledger import plural

# ==========================================
# PHASE 1: CONFIGURATION
# ==========================================
st.set_page_config(page_title="FC Support Dashboard", layout="wide")

REFERENCE_DATE_TEXT = lg.REFERENCE_DATE.strftime("%Y-%m-%d")


# ==========================================
# PHASE 2: LOAD AND CLEAN
# ==========================================
@st.cache_data
def load_data(path: str):
    # Keep raw copies for the Appendix
    raw_pledges, raw_gifts = lg.read_workbook(path)
    return lg.clean_pledges(raw_pledges), lg.clean_gifts(raw_gifts), raw_pledges, raw_gifts


# ==========================================
# PHASE 3: LEDGER RECONCILIATION
# ==========================================
df_pledges, df_gifts, raw_pledges, raw_gifts = load_data(str(lg.ORIGINAL_DATA_PATH))
result = lg.reconcile(df_pledges, df_gifts)
df, orphaned, unparseable_gifts = result.ledger, result.orphaned_gifts, result.unparseable_gifts
summary = lg.summarize(result, gift_rows=len(df_gifts))

# ==========================================
# PHASE 4: UI DASHBOARD
# ==========================================
# TIER 1: EXECUTIVE HEADER & KPIS
st.title("📊 Support Ledger Reconciliation Dashboard")
st.markdown(
    "Reconciling stated pledges against actual gift history. "
    f"**All figures as of {REFERENCE_DATE_TEXT}, in USD.**"
)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Valid Monthly Support", f"${summary.total_support:,.2f}")
col2.metric(f"Goal Progress ({lg.format_goal_short()})", f"{summary.percent_goal:.1f}%")
col3.metric("Excluded Pledges", f"{summary.excluded}")
col4.metric("Orphaned Gifts", f"{summary.orphaned_gifts}")

st.divider()

# TIER 2: AUDIT CHECKLIST
st.write("### ✅ Ledger Audit Results")
st.markdown(
    "*The methodology relies on actual gift history rather than the stated system status, "
    "which is highly unreliable.*"
)

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("**File Totals**")
    st.metric(f"Rows in {lg.PLEDGES_SHEET}", summary.pledge_rows)
    st.metric(f"Rows in {lg.GIFTS_SHEET}", summary.gift_rows)

with col2:
    st.markdown("**Pledge Breakdown**")
    st.metric("Pledges counted toward committed support", summary.included)
    st.metric("Pledges excluded as lapsed", summary.lapsed, help="Lapsed based on time-decay rules from last gift date.")
    st.metric("Pledges excluded as paused", summary.paused)
    st.metric("Pledges excluded as past end date", summary.past_end)
    st.metric("Pledge rows unparseable", summary.unparseable, help="Missing amounts, invalid formats, or unknown currencies.")

with col3:
    st.markdown("**Gift Anomalies**")
    st.metric("Gift rows unparseable", summary.unparseable_gifts, help="Gifts lacking a valid date or amount.")
    st.metric("Gift rows orphaned (pledge_id not found)", summary.orphaned_gifts, help="Gifts tied to a pledge ID not found in the master list.")

st.divider()

# TIER 3: UNREALIZED SUPPORT BREAKDOWN
st.write("### 🚨 Unrealized Support Breakdown")
goal_text = f"${lg.GOAL_MONTHLY_USD:,.0f}"
if summary.total_support < lg.GOAL_MONTHLY_USD:
    lead = f"**Why aren't we hitting the {goal_text} goal?**"
else:
    lead = f"**The {goal_text} goal is met, but support is still leaking.**"
st.markdown(
    f"{lead} Many pledges marked 'active' in the system have stopped giving. "
    "This table isolates the lost monthly revenue based on the strict exclusion rules."
)

leakage_data = {
    "Exclusion Reason": ["Lapsed (No Recent Gift)", "Paused Status", "Past End Date", "Unparseable Data"],
    "Pledge Count": [summary.lapsed, summary.paused, summary.past_end, summary.unparseable],
    "Unrealized Value (USD)": [
        summary.lapsed_value,
        summary.paused_value,
        summary.past_end_value,
        0,  # Unparseable records have no mathable value
    ],
}
st.dataframe(pd.DataFrame(leakage_data).style.format({"Unrealized Value (USD)": "${:,.2f}"}), width="stretch")

# TIER 4: DRILL-DOWN INVESTIGATION VIEWS
st.write("### 🔬 Investigate Anomalies")
st.markdown("Expand the sections below to see the exact rows triggering these statuses.")

with st.expander(f"View {plural(summary.included, 'Included Pledge')} (Valid Support)"):
    st.markdown("These pledges are active, parseable, have not passed their end date, and have a recent gift according to their frequency rules.")
    st.dataframe(df[df['is_included']][['pledge_id', 'donor_name', 'amount', 'currency', 'frequency', 'monthly_usd', 'days_since_gift']], width="stretch")

with st.expander(f"View {plural(summary.lapsed, 'Lapsed Pledge')} (No Recent Gift)"):
    st.markdown("These pledges are technically active, but haven't given a gift within their expected frequency window.")
    st.dataframe(df[df['is_lapsed']][['pledge_id', 'donor_name', 'frequency', 'status', 'latest_gift_date', 'days_since_gift']], width="stretch")

with st.expander(f"View {plural(summary.past_end, 'Pledge')} Past End Date"):
    st.markdown(f"These pledges have an `end_date` prior to the {REFERENCE_DATE_TEXT} reference date.")
    st.dataframe(df[df['is_past_end']][['pledge_id', 'donor_name', 'clean_end_date', 'status']], width="stretch")

with st.expander(f"View {plural(summary.paused, 'Paused Pledge')}"):
    st.dataframe(df[df['is_paused']][['pledge_id', 'donor_name', 'status']], width="stretch")

with st.expander(f"View {plural(summary.unparseable, 'Unparseable Pledge')}"):
    st.markdown("These rows contain critical formatting errors (negative amounts, missing dates, unknown frequencies, or unknown currencies) and cannot be calculated.")
    st.dataframe(df[df['is_unparseable']][['pledge_id', 'donor_name', 'amount', 'currency', 'frequency', 'start_date']], width="stretch")

with st.expander(
    f"View {plural(summary.unparseable_gifts, 'Unparseable Gift')} & {plural(summary.orphaned_gifts, 'Orphaned Gift')}"
):
    st.markdown("**Unparseable Gifts** (Missing amount or date)")
    st.dataframe(unparseable_gifts[['gift_id', 'pledge_id', 'amount', 'date']], width="stretch")
    st.markdown("**Orphaned Gifts** (The `pledge_id` does not exist in the master pledge ledger)")
    st.dataframe(orphaned[['gift_id', 'pledge_id', 'amount', 'date']], width="stretch")

st.divider()

# TIER 5: MAIN LEDGER EXPLORER
st.write("### 🔍 Complete Audited Ledger")
st.markdown(f"The master table of all {summary.pledge_rows} pledges and their final calculated status.")
st.dataframe(df[['pledge_id', 'donor_name', 'amount', 'currency', 'frequency', 'status', 'days_since_gift', 'is_included']], width="stretch")

st.divider()

# TIER 6: APPENDIX
st.write("### 📎 Appendix: Source Files & Methodology")
st.markdown("Reference the raw data exactly as it was imported prior to formatting and reconciliation.")
with st.expander(f"Raw {lg.PLEDGES_SHEET} File"):
    st.dataframe(raw_pledges, width="stretch")
with st.expander(f"Raw {lg.GIFTS_SHEET} File"):
    st.dataframe(raw_gifts, width="stretch")
with st.expander("Business Rules & Exchange Rates Applied"):
    st.markdown(lg.methodology_markdown())
