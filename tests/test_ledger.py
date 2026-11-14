"""Tests for the parsing rules (C_Rules) and the reconciliation guarantees.

Run: pip install -r requirements-dev.txt && pytest
"""
import math

import pandas as pd
import pytest

import ledger as lg


@pytest.mark.parametrize("raw", ["$1,200.00", "1200.00", "1,200", "1.200,00"])
def test_amounts_in_every_listed_format_read_as_1200(raw):
    assert lg.parse_amount(raw) == 1200


@pytest.mark.parametrize("raw", ["(200.00)", "-200", "", None, "abc"])
def test_negative_blank_and_text_amounts_are_unparseable(raw):
    assert math.isnan(lg.parse_amount(raw))


@pytest.mark.parametrize("raw", ["2026-09-01", "09/01/26", "September 1, 2026", "09/01/2026"])
def test_dates_in_listed_formats(raw):
    assert lg.parse_date(raw) == pd.Timestamp("2026-09-01")


def test_impossible_date_is_unparseable():
    assert pd.isna(lg.parse_date("31/02/2025"))


def test_frequency_is_case_insensitive():
    assert lg.monthly_usd(300, "usd", "  Quarterly ") == pytest.approx(100)


def test_currency_conversion():
    assert lg.monthly_usd(100, "GBP", "monthly") == pytest.approx(127)


def test_unknown_currency_is_never_a_zero_dollar_pledge():
    assert math.isnan(lg.monthly_usd(100, "XYZ", "monthly"))
    assert math.isnan(lg.monthly_usd(100, None, "monthly"))


@pytest.mark.parametrize(
    "freq,ok_days,lapsed_days",
    [("monthly", 90, 91), ("quarterly", 150, 151), ("semiannual", 240, 241), ("annual", 400, 401), ("one-time", 365, 366)],
)
def test_lapse_windows(freq, ok_days, lapsed_days):
    assert not lg.is_lapsed(freq, ok_days)
    assert lg.is_lapsed(freq, lapsed_days)


def test_no_gift_at_all_is_lapsed():
    assert lg.is_lapsed("monthly", float("nan"))


def test_every_row_is_accounted_for():
    """C_Rules: every row in both sheets is counted or listed; no row disappears."""
    raw_pledges, raw_gifts = lg.read_workbook(lg.ORIGINAL_DATA_PATH)
    result = lg.reconcile(lg.clean_pledges(raw_pledges), lg.clean_gifts(raw_gifts))
    s = lg.summarize(result, gift_rows=len(raw_gifts))
    assert s.included + s.lapsed + s.paused + s.past_end + s.unparseable == s.pledge_rows == len(raw_pledges)
    assert s.total_support > 0
