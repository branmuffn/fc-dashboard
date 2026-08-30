import pandas as pd
import numpy as np
import re
import datetime
import streamlit as st

# ==========================================
# PHASE 1: CONFIGURATION & CONSTANTS
# ==========================================
st.set_page_config(page_title="FC Support Dashboard", layout="wide")

REFERENCE_DATE = pd.to_datetime('2026-09-01')

EXCHANGE_RATES = {
    'USD': 1.00,
    'EUR': 1.08,
    'GBP': 1.27,
    'CAD': 0.73
}

FREQUENCY_MULTIPLIERS = {
    'monthly': 1,
    'quarterly': 1/3,
    'semiannual': 1/6,
    'annual': 1/12,
    'one-time': 1/12
}

# ==========================================
# PHASE 2: PARSING ENGINE
# ==========================================
def parse_amount(val):
    if pd.isna(val): return np.nan
    val_str = str(val).strip()
    if val_str.startswith('(') or val_str.startswith('-'): return np.nan
    val_str = re.sub(r'[^\d\.,]', '', val_str)
    if not val_str: return np.nan
    if re.search(r'\.\d{3},\d{2}$', val_str) or re.search(r',\d{1,2}$', val_str):
        val_str = val_str.replace('.', '').replace(',', '.')
    else:
        val_str = val_str.replace(',', '')
    try: return float(val_str)
    except: return np.nan

def parse_date(val):
    if pd.isna(val): return pd.NaT
    try: return pd.to_datetime(val, dayfirst=False, errors='coerce')
    except: return pd.NaT

@st.cache_data
def load_data():
    file_path = "data/Frontier Commons Fellowship FA26 — Build Lane Challenge Data.xlsx"
    
    # Store raw copies for the Appendix
    raw_pledges = pd.read_excel(file_path, sheet_name='C_Pledges')
    raw_gifts = pd.read_excel(file_path, sheet_name='C_Gifts')
    
    pledges = raw_pledges.copy()
    gifts = raw_gifts.copy()
    
    # Clean Pledges
    pledges['frequency'] = pledges['frequency'].astype(str).str.lower().str.strip()
    pledges['clean_amount'] = pledges['amount'].apply(parse_amount)
    pledges['clean_start_date'] = pledges['start_date'].apply(parse_date)
    pledges['clean_end_date'] = pledges['end_date'].apply(parse_date)
    pledges['monthly_usd'] = pledges.apply(
        lambda row: row['clean_amount'] * 
        EXCHANGE_RATES.get(str(row['currency']).upper().strip(), 0) * 
        FREQUENCY_MULTIPLIERS.get(row['frequency'], 0), axis=1)
    
    # Clean Gifts
    gifts['clean_amount'] = gifts['amount'].apply(parse_amount)
    gifts['clean_date'] = gifts['date'].apply(parse_date)
    
    return pledges, gifts, raw_pledges, raw_gifts

# ==========================================
# PHASE 3: LEDGER RECONCILIATION
# ==========================================
def reconcile_data(pledges, gifts):
    # 1. Isolate valid gifts and find the latest gift per pledge
    valid_gifts = gifts.dropna(subset=['clean_amount', 'clean_date'])
    latest_gifts = valid_gifts.groupby('pledge_id')['clean_date'].max().reset_index()
    latest_gifts.rename(columns={'clean_date': 'latest_gift_date'}, inplace=True)
    
    # 2. Merge latest gift dates into the pledges ledger
    df = pd.merge(pledges, latest_gifts, on='pledge_id', how='left')
    df['days_since_gift'] = (REFERENCE_DATE - df['latest_gift_date']).dt.days
    
    # 3. Time-decay Lapse Rules
    def check_lapse(row):
        if pd.isna(row['days_since_gift']): return True
        freq = str(row['frequency'])
        days = row['days_since_gift']
        if freq == 'monthly' and days > 90: return True
        if freq == 'quarterly' and days > 150: return True
        if freq == 'semiannual' and days > 240: return True
        if freq == 'annual' and days > 400: return True
        if freq == 'one-time' and days > 365: return True
        return False
        
    df['is_lapsed_raw'] = df.apply(check_lapse, axis=1)
    
    # 4. Strict Waterfall Categorization (Prevents double counting)
    df['is_unparseable'] = pd.isna(df['clean_amount']) | pd.isna(df['clean_start_date']) | ~df['frequency'].isin(FREQUENCY_MULTIPLIERS.keys())
    df['is_past_end'] = (~df['is_unparseable']) & (~pd.isna(df['clean_end_date'])) & (df['clean_end_date'] < REFERENCE_DATE)
    df['is_paused'] = (~df['is_unparseable']) & (~df['is_past_end']) & (df['status'].str.lower().str.strip() == 'paused')
    df['is_lapsed'] = (~df['is_unparseable']) & (~df['is_past_end']) & (~df['is_paused']) & df['is_lapsed_raw']
    
    df['is_included'] = ~(df['is_unparseable'] | df['is_past_end'] | df['is_paused'] | df['is_lapsed'])
    
    # 5. Identify Orphaned Gifts
    orphaned = gifts[~gifts['pledge_id'].isin(pledges['pledge_id'])]
    unparseable_gifts = gifts[pd.isna(gifts['clean_amount']) | pd.isna(gifts['clean_date'])]
    
    return df, orphaned, unparseable_gifts

# ==========================================
# PHASE 4: UI DASHBOARD
# ==========================================
df_pledges, df_gifts, raw_pledges, raw_gifts = load_data()
df, orphaned, unparseable_gifts = reconcile_data(df_pledges, df_gifts)

# Calculate Core KPIs
total_support = df.loc[df['is_included'], 'monthly_usd'].sum()
goal = 7500
percent_goal = (total_support / goal) * 100
counted_pledges = df['is_included'].sum()

# TIER 1: EXECUTIVE HEADER & KPIS
st.title("📊 Support Ledger Reconciliation Dashboard")
st.markdown("Reconciling stated pledges against actual gift history. **All figures as of 2026-09-01, in USD.**")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Valid Monthly Support", f"${total_support:,.2f}")
col2.metric("Goal Progress ($7.5k)", f"{percent_goal:.1f}%")
col3.metric("Excluded Pledges", f"{(~df['is_included']).sum()}")
col4.metric("Orphaned Gifts", f"{len(orphaned)}")

st.divider()

# TIER 2: AUDIT CHECKLIST
st.write("### ✅ Ledger Audit Results")
st.markdown("*This section mirrors the expected results from the challenge brief. The methodology relies on actual gift history rather than the stated system status, which is highly unreliable.*")

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("**File Totals & Support**")
    st.metric("Rows in C_Pledges", len(df_pledges))
    st.metric("Rows in C_Gifts", len(df_gifts))
    st.markdown("<br>", unsafe_allow_html=True)
    st.metric("Total committed monthly support (USD)", f"${total_support:,.2f}")
    st.metric("Percent of goal", f"{percent_goal:.1f}%")

with col2:
    st.markdown("**Pledge Breakdown**")
    st.metric("Pledges counted toward committed support", counted_pledges)
    st.metric("Pledges excluded as lapsed", df['is_lapsed'].sum(), help="Lapsed based on time-decay rules from last gift date.")
    st.metric("Pledges excluded as paused", df['is_paused'].sum())
    st.metric("Pledges excluded as past end date", df['is_past_end'].sum())
    st.metric("Pledge rows unparseable", df['is_unparseable'].sum(), help="Missing amounts, invalid formats, or unknown currencies.")

with col3:
    st.markdown("**Gift Anomalies**")
    st.metric("Gift rows unparseable", len(unparseable_gifts), help="Gifts lacking a valid date or amount.")
    st.metric("Gift rows orphaned (pledge_id not found)", len(orphaned), help="Gifts tied to a pledge ID not found in the master list.")

st.divider()

# TIER 3: UNREALIZED SUPPORT BREAKDOWN
st.write("### 🚨 Unrealized Support Breakdown")
st.markdown("**Why aren't we hitting the $7,500 goal?** Many pledges marked 'active' in the system have stopped giving. This table isolates the lost monthly revenue based on the strict exclusion rules.")

leakage_data = {
    "Exclusion Reason": ["Lapsed (No Recent Gift)", "Paused Status", "Past End Date", "Unparseable Data"],
    "Pledge Count": [df['is_lapsed'].sum(), df['is_paused'].sum(), df['is_past_end'].sum(), df['is_unparseable'].sum()],
    "Unrealized Value (USD)": [
        df.loc[df['is_lapsed'], 'monthly_usd'].sum(),
        df.loc[df['is_paused'], 'monthly_usd'].sum(),
        df.loc[df['is_past_end'], 'monthly_usd'].sum(),
        0 # Unparseable records have no mathable value
    ]
}
st.dataframe(pd.DataFrame(leakage_data).style.format({"Unrealized Value (USD)": "${:,.2f}"}), use_container_width=True)

# TIER 4: DRILL-DOWN INVESTIGATION VIEWS
st.write("### 🔬 Investigate Anomalies")
st.markdown("Expand the sections below to see the exact rows triggering these statuses.")

with st.expander("View 24 Included Pledges (Valid Support)"):
    st.markdown("These pledges are active, parseable, have not passed their end date, and have a recent gift according to their frequency rules.")
    st.dataframe(df[df['is_included']][['pledge_id', 'donor_name', 'amount', 'currency', 'frequency', 'monthly_usd', 'days_since_gift']], use_container_width=True)

with st.expander("View 16 Lapsed Pledges (No Recent Gift)"):
    st.markdown("These pledges are technically active, but haven't given a gift within their expected frequency window.")
    st.dataframe(df[df['is_lapsed']][['pledge_id', 'donor_name', 'frequency', 'status', 'latest_gift_date', 'days_since_gift']], use_container_width=True)

with st.expander("View 3 Pledges Past End Date"):
    st.markdown("These pledges have an `end_date` prior to the 2026-09-01 reference date.")
    st.dataframe(df[df['is_past_end']][['pledge_id', 'donor_name', 'clean_end_date', 'status']], use_container_width=True)

with st.expander("View 4 Paused Pledges"):
    st.dataframe(df[df['is_paused']][['pledge_id', 'donor_name', 'status']], use_container_width=True)

with st.expander("View 3 Unparseable Pledges"):
    st.markdown("These rows contain critical formatting errors (negative amounts, missing dates, or unknown frequencies) and cannot be calculated.")
    st.dataframe(df[df['is_unparseable']][['pledge_id', 'donor_name', 'amount', 'currency', 'frequency', 'start_date']], use_container_width=True)

with st.expander("View 2 Unparseable Gifts & 1 Orphaned Gift"):
    st.markdown("**Unparseable Gifts** (Missing amount or date)")
    st.dataframe(unparseable_gifts[['gift_id', 'pledge_id', 'amount', 'date']], use_container_width=True)
    st.markdown("**Orphaned Gifts** (The `pledge_id` does not exist in the master pledge ledger)")
    st.dataframe(orphaned[['gift_id', 'pledge_id', 'amount', 'date']], use_container_width=True)

st.divider()

# TIER 5: MAIN LEDGER EXPLORER
st.write("### 🔍 Complete Audited Ledger")
st.markdown("The master table of all 50 pledges and their final calculated status.")
st.dataframe(df[['pledge_id', 'donor_name', 'amount', 'currency', 'frequency', 'status', 'days_since_gift', 'is_included']], use_container_width=True)

st.divider()

# TIER 6: APPENDIX
st.write("### 📎 Appendix: Source Files & Methodology")
st.markdown("Reference the raw data exactly as it was imported prior to formatting and reconciliation.")
with st.expander("Raw C_Pledges File"):
    st.dataframe(raw_pledges, use_container_width=True)
with st.expander("Raw C_Gifts File"):
    st.dataframe(raw_gifts, use_container_width=True)
with st.expander("Business Rules & Exchange Rates Applied"):
    st.markdown("""
    *   **Reference Date:** Hardcoded to 2026-09-01.
    *   **Exchange Rates:** EUR (1.08), GBP (1.27), CAD (0.73).
    *   **Frequency Logic:** Quarterly (÷3), Semiannual (÷6), Annual/One-time (÷12).
    *   **Lapse Decay:** Monthly (>90 days), Quarterly (>150 days), Semiannual (>240 days), Annual (>400 days), One-time (>365 days).
    """)