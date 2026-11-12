"""Parsing and reconciliation logic for the Support Ledger dashboard.

Everything here is pure pandas/Python (no Streamlit), so it can be unit tested.
app.py imports this module and only handles the UI.
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# ==========================================
# BUSINESS RULES (single source of truth)
# ==========================================
REFERENCE_DATE = pd.Timestamp("2026-09-01")
GOAL_MONTHLY_USD = 7500

# Conversion rates to USD. Any currency not listed here is unknown.
EXCHANGE_RATES = {
    "USD": 1.00,
    "EUR": 1.08,
    "GBP": 1.27,
    "CAD": 0.73,
}

# Multiplier that turns one payment into a monthly equivalent.
FREQUENCY_MULTIPLIERS = {
    "monthly": 1,
    "quarterly": 1 / 3,
    "semiannual": 1 / 6,
    "annual": 1 / 12,
    "one-time": 1 / 12,
}

# A pledge is lapsed when its last valid gift is MORE than this many days
# before REFERENCE_DATE (or when it has no valid gift at all).
LAPSE_THRESHOLD_DAYS = {
    "monthly": 90,
    "quarterly": 150,
    "semiannual": 240,
    "annual": 400,
    "one-time": 365,
}

PLEDGES_SHEET = "C_Pledges"
GIFTS_SHEET = "C_Gifts"

# Waterfall order: each pledge gets the first status that applies.
STATUS_UNPARSEABLE = "Unparseable"
STATUS_PAST_END = "Past end date"
STATUS_PAUSED = "Paused"
STATUS_LAPSED = "Lapsed"
STATUS_INCLUDED = "Included"
WATERFALL_ORDER = (STATUS_UNPARSEABLE, STATUS_PAST_END, STATUS_PAUSED, STATUS_LAPSED)

# ==========================================
# DATA FILES
# ==========================================
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
ORIGINAL_DATA_PATH = DATA_DIR / "Frontier Commons Fellowship FA26 — Build Lane Challenge Data.xlsx"


# ==========================================
# PARSERS
# ==========================================
def _clean_text(val) -> str | None:
    """Strip a cell value; return None for missing or blank cells."""
    if val is None or (not isinstance(val, str) and pd.isna(val)):
        return None
    text = str(val).strip()
    return text or None


def parse_amount(val) -> float:
    """Parse a messy amount string into a positive float, or NaN.

    Handles currency symbols, thousands separators and European decimal
    commas ("1.250,00", "25,00"). Negative or accounting-style "(200.00)"
    amounts are treated as unparseable.
    """
    text = _clean_text(val)
    if text is None:
        return float("nan")
    if text.startswith("(") or text.startswith("-"):
        return float("nan")
    text = re.sub(r"[^\d\.,]", "", text)
    if not text:
        return float("nan")
    if re.search(r"\.\d{3},\d{2}$", text) or re.search(r",\d{1,2}$", text):
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:  # e.g. "1.2.3"
        return float("nan")


def parse_date(val) -> pd.Timestamp:
    """Parse a messy date into a Timestamp, or NaT.

    Ambiguous numeric dates are read month first ("01/09/25" is 9 Jan 2025).
    When the first number cannot be a month ("20-04-2026") it is read day
    first. Impossible dates ("31/02/2025") become NaT.
    """
    if val is None or (not isinstance(val, str) and pd.isna(val)):
        return pd.NaT
    with warnings.catch_warnings():
        # The day-first fallback is intended; silence pandas' notice about it.
        warnings.filterwarnings("ignore", message="Parsing dates in", category=UserWarning)
        return pd.to_datetime(val, dayfirst=False, errors="coerce")


def normalize_label(val) -> str | None:
    """Lower-case and strip a label ("  MONTHLY " -> "monthly")."""
    text = _clean_text(val)
    return text.lower() if text else None


normalize_frequency = normalize_label


def normalize_currency(val) -> str | None:
    """Upper-case and strip a currency code (" eur" -> "EUR")."""
    text = _clean_text(val)
    return text.upper() if text else None


def exchange_rate(currency) -> float:
    """USD rate for a currency code. Unknown currencies count as 0."""
    return EXCHANGE_RATES.get(normalize_currency(currency), 0)


def monthly_usd(amount: float, currency, frequency) -> float:
    """Monthly USD equivalent of one pledge payment."""
    multiplier = FREQUENCY_MULTIPLIERS.get(normalize_frequency(frequency), 0)
    return amount * exchange_rate(currency) * multiplier


def is_lapsed(frequency, days_since_gift) -> bool:
    """True if the last valid gift is older than the frequency's lapse window.

    A pledge with no valid gift (NaN days) is lapsed. Unknown frequencies are
    never lapsed here; they are caught as unparseable instead.
    """
    if days_since_gift is None or pd.isna(days_since_gift):
        return True
    threshold = LAPSE_THRESHOLD_DAYS.get(normalize_frequency(frequency))
    return threshold is not None and days_since_gift > threshold


# ==========================================
# LOADING AND CLEANING
# ==========================================
def read_workbook(path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read the raw pledge and gift sheets exactly as stored."""
    raw_pledges = pd.read_excel(path, sheet_name=PLEDGES_SHEET)
    raw_gifts = pd.read_excel(path, sheet_name=GIFTS_SHEET)
    return raw_pledges, raw_gifts


def clean_pledges(raw: pd.DataFrame) -> pd.DataFrame:
    pledges = raw.copy()
    pledges["frequency"] = pledges["frequency"].map(normalize_frequency)
    pledges["clean_amount"] = pledges["amount"].map(parse_amount).astype(float)
    pledges["clean_start_date"] = pd.to_datetime(pledges["start_date"].map(parse_date))
    pledges["clean_end_date"] = pd.to_datetime(pledges["end_date"].map(parse_date))
    pledges["monthly_usd"] = [
        monthly_usd(amount, currency, frequency)
        for amount, currency, frequency in zip(
            pledges["clean_amount"], pledges["currency"], pledges["frequency"]
        )
    ]
    return pledges


def clean_gifts(raw: pd.DataFrame) -> pd.DataFrame:
    gifts = raw.copy()
    gifts["clean_amount"] = gifts["amount"].map(parse_amount).astype(float)
    gifts["clean_date"] = pd.to_datetime(gifts["date"].map(parse_date))
    return gifts


# ==========================================
# RECONCILIATION
# ==========================================
@dataclass(frozen=True)
class Reconciliation:
    ledger: pd.DataFrame  # one row per pledge, with status flags
    orphaned_gifts: pd.DataFrame  # gifts whose pledge_id is not in the pledge list
    unparseable_gifts: pd.DataFrame  # gifts missing a valid amount or date


def reconcile(
    pledges: pd.DataFrame, gifts: pd.DataFrame, reference_date: pd.Timestamp = REFERENCE_DATE
) -> Reconciliation:
    # 1. Latest valid gift per pledge
    valid_gifts = gifts.dropna(subset=["clean_amount", "clean_date"])
    latest_gifts = (
        valid_gifts.groupby("pledge_id")["clean_date"].max().rename("latest_gift_date").reset_index()
    )

    # 2. Merge into the pledge ledger
    df = pledges.merge(latest_gifts, on="pledge_id", how="left")
    df["days_since_gift"] = (reference_date - df["latest_gift_date"]).dt.days

    # 3. Time-decay lapse rule
    df["is_lapsed_raw"] = [
        is_lapsed(freq, days) for freq, days in zip(df["frequency"], df["days_since_gift"])
    ]

    # 4. Strict waterfall: a pledge is only flagged for a condition if no
    #    earlier (more severe) condition already excluded it.
    df["is_unparseable"] = (
        df["clean_amount"].isna()
        | df["clean_start_date"].isna()
        | ~df["frequency"].isin(list(FREQUENCY_MULTIPLIERS))
    )
    df["is_past_end"] = (
        ~df["is_unparseable"]
        & df["clean_end_date"].notna()
        & (df["clean_end_date"] < reference_date)
    )
    is_paused_status = df["status"].map(normalize_label).eq("paused")
    df["is_paused"] = ~df["is_unparseable"] & ~df["is_past_end"] & is_paused_status
    df["is_lapsed"] = (
        ~df["is_unparseable"] & ~df["is_past_end"] & ~df["is_paused"] & df["is_lapsed_raw"]
    )
    df["is_included"] = ~(df["is_unparseable"] | df["is_past_end"] | df["is_paused"] | df["is_lapsed"])

    df["ledger_status"] = STATUS_INCLUDED
    for flag, label in (
        ("is_lapsed", STATUS_LAPSED),
        ("is_paused", STATUS_PAUSED),
        ("is_past_end", STATUS_PAST_END),
        ("is_unparseable", STATUS_UNPARSEABLE),
    ):
        df.loc[df[flag], "ledger_status"] = label

    # 5. Gift anomalies
    orphaned = gifts[~gifts["pledge_id"].isin(pledges["pledge_id"])]
    unparseable_gifts = gifts[gifts["clean_amount"].isna() | gifts["clean_date"].isna()]

    return Reconciliation(df, orphaned, unparseable_gifts)


@dataclass(frozen=True)
class Summary:
    pledge_rows: int
    gift_rows: int
    included: int
    lapsed: int
    paused: int
    past_end: int
    unparseable: int
    unparseable_gifts: int
    orphaned_gifts: int
    total_support: float
    lapsed_value: float
    paused_value: float
    past_end_value: float
    goal: float = GOAL_MONTHLY_USD

    @property
    def excluded(self) -> int:
        return self.lapsed + self.paused + self.past_end + self.unparseable

    @property
    def percent_goal(self) -> float:
        return self.total_support / self.goal * 100


def summarize(result: Reconciliation, gift_rows: int, goal: float = GOAL_MONTHLY_USD) -> Summary:
    df = result.ledger

    def value(flag: str) -> float:
        return float(df.loc[df[flag], "monthly_usd"].sum())

    return Summary(
        pledge_rows=len(df),
        gift_rows=gift_rows,
        included=int(df["is_included"].sum()),
        lapsed=int(df["is_lapsed"].sum()),
        paused=int(df["is_paused"].sum()),
        past_end=int(df["is_past_end"].sum()),
        unparseable=int(df["is_unparseable"].sum()),
        unparseable_gifts=len(result.unparseable_gifts),
        orphaned_gifts=len(result.orphaned_gifts),
        total_support=value("is_included"),
        lapsed_value=value("is_lapsed"),
        paused_value=value("is_paused"),
        past_end_value=value("is_past_end"),
        goal=goal,
    )


# ==========================================
# TEXT HELPERS
# ==========================================
def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    """plural(1, "Pledge") -> "1 Pledge"; plural(3, "Pledge") -> "3 Pledges"."""
    word = singular if count == 1 else (plural_form or singular + "s")
    return f"{count} {word}"


def format_goal_short(goal: float = GOAL_MONTHLY_USD) -> str:
    """7500 -> "$7.5k"."""
    return f"${goal / 1000:g}k"


def _frequency_label(freq: str) -> str:
    return freq[:1].upper() + freq[1:]


def methodology_markdown() -> str:
    """The business rules as Markdown bullets, generated from the constants."""
    reference = REFERENCE_DATE.strftime("%Y-%m-%d")
    rates = ", ".join(
        f"{code} ({rate:.2f})" for code, rate in EXCHANGE_RATES.items() if code != "USD"
    )

    divisors: dict[int, list[str]] = {}
    for freq, multiplier in FREQUENCY_MULTIPLIERS.items():
        divisors.setdefault(round(1 / multiplier), []).append(_frequency_label(freq))
    frequency_logic = ", ".join(
        f"{'/'.join(names)} (÷{divisor})" for divisor, names in divisors.items() if divisor != 1
    )

    lapse = ", ".join(
        f"{_frequency_label(freq)} (>{days} days)" for freq, days in LAPSE_THRESHOLD_DAYS.items()
    )
    waterfall = " → ".join(WATERFALL_ORDER + (STATUS_INCLUDED,))

    return "\n".join(
        [
            f"- **Reference date:** {reference}. All figures are as of this date, in USD.",
            f"- **Monthly goal:** ${GOAL_MONTHLY_USD:,.0f}.",
            f"- **Exchange rates to USD:** {rates}.",
            f"- **Frequency logic:** {frequency_logic}.",
            f"- **Lapse decay (days since last valid gift):** {lapse}. "
            "A pledge with no valid gift is lapsed.",
            f"- **Waterfall:** {waterfall}. Each pledge gets the first status that applies, "
            "so nothing is excluded twice.",
        ]
    )
