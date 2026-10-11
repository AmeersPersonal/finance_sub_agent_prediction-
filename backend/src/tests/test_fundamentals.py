import pytest

from finance.fundamentals import beneish_m_score, financial_health, ttm
from finance.quarter_review_analysis import quarterly_review
from finance.risk_management import (
    altman_z,
    altman_z_ttm,
    atr_stop_distance,
    max_position_fraction,
)


def test_financial_health(snapshot):
    h = financial_health(snapshot.income_stmt, snapshot.balance_sheet, snapshot.cashflow, snapshot.info)
    assert h["fiscal_year_end"] == "2025-09-30"
    assert h["gross_margin_pct"] == pytest.approx(60 / 130 * 100)
    assert h["gross_margin_prior_year_pct"] == pytest.approx(45.0)
    assert h["operating_margin_pct"] == pytest.approx(30.0)
    assert h["fcf_yield_pct"] == pytest.approx(5.6)
    assert h["price_to_fcf"] == pytest.approx(500 / 28)
    assert h["ocf_to_net_income"] == pytest.approx(35 / 30)
    assert h["roic_pct"] == pytest.approx(40 * 0.8 / 120 * 100)
    assert h["debt_to_equity"] == pytest.approx(0.5)
    assert h["interest_coverage"] == pytest.approx(20.0)
    assert (h["ev_to_ebitda"], h["peg_ratio"]) == (20.0, 2.0)


def test_financial_health_tolerates_missing_statements():
    h = financial_health(None, None, None, {})
    assert h["gross_margin_pct"] is None and h["roic_pct"] is None


def test_altman_z(snapshot):
    result = altman_z(snapshot.balance_sheet, snapshot.income_stmt, 500e9)
    expected = 1.2 * 0.15 + 1.4 * 0.3 + 3.3 * 0.2 + 0.6 * (500 / 120) + 0.999 * 0.65
    assert result["z_score"] == pytest.approx(expected)
    assert result["zone"] == "safe"
    tiny_equity = altman_z(snapshot.balance_sheet, snapshot.income_stmt, 1e9)
    assert tiny_equity["zone"] == "grey"


def test_altman_z_not_for_banks_or_missing_data(snapshot):
    assert altman_z(snapshot.balance_sheet, snapshot.income_stmt, 500e9, "Financial Services") is None
    assert altman_z(None, snapshot.income_stmt, 500e9) is None


def test_altman_z_ttm_uses_latest_quarter_and_four_quarter_flows(snapshot):
    result = altman_z_ttm(snapshot.quarterly_balance, snapshot.quarterly_income, 500e9)
    ebit, revenue, assets = 41.7e9, 417e9, 210e9  # sums of the latest four quarters
    expected = (1.2 * 32 / 210 + 1.4 * 65 / 210 + 3.3 * ebit / assets + 0.6 * 500 / 125
                + 0.999 * revenue / assets)
    assert result["z_score"] == pytest.approx(expected)
    assert (result["basis"], result["balance_sheet_as_of"]) == ("ttm", "2026-06-30")
    assert altman_z(snapshot.balance_sheet, snapshot.income_stmt, 500e9)["basis"] == "annual"


def test_altman_z_ttm_needs_four_quarters(snapshot):
    three = snapshot.quarterly_income.iloc[:, :3]
    assert ttm(three, "EBIT") is None
    assert altman_z_ttm(snapshot.quarterly_balance, three, 500e9) is None
    assert altman_z_ttm(snapshot.quarterly_balance, snapshot.quarterly_income, 500e9,
                        "Financial Services") is None


def test_beneish_healthy_company_is_below_threshold(snapshot):
    result = beneish_m_score(snapshot.income_stmt, snapshot.balance_sheet, snapshot.cashflow)
    assert result["m_score"] == pytest.approx(-2.494, abs=0.01)
    assert result["above_threshold_possible_manipulation"] is False


def test_beneish_flags_receivables_outgrowing_sales(snapshot):
    balance = snapshot.balance_sheet.copy()
    balance.loc["Accounts Receivable", balance.columns[0]] = 60e9
    result = beneish_m_score(snapshot.income_stmt, balance, snapshot.cashflow)
    assert result["above_threshold_possible_manipulation"] is True


def test_beneish_needs_two_full_years(snapshot):
    assert beneish_m_score(snapshot.income_stmt.iloc[:, :1], snapshot.balance_sheet, snapshot.cashflow) is None
    assert beneish_m_score(snapshot.income_stmt, snapshot.balance_sheet, snapshot.cashflow, "Financial Services") is None


def test_quarterly_review(snapshot):
    r = quarterly_review(snapshot.quarterly_income, snapshot.earnings_history)
    assert r["latest_quarter_end"] == "2026-06-30"
    assert r["revenue_qoq_pct"] == pytest.approx(4.76, abs=0.01)
    assert r["revenue_yoy_pct"] == pytest.approx(10.0)
    assert r["gross_margin_pct_by_quarter"][0] == pytest.approx(45.45, abs=0.01)
    assert r["eps_surprise_pct_last_quarters"] == [5.0, -2.0, 3.0, 1.0]  # upcoming report skipped
    assert (r["eps_beats"], r["eps_misses"]) == (3, 1)
    assert quarterly_review(None, None) is None


def test_position_risk_helpers():
    assert atr_stop_distance(2.0, 100.0) == pytest.approx(0.04)
    assert max_position_fraction(0.01, 0.04) == pytest.approx(0.25)
    assert max_position_fraction(0.01, 0.005) == 1.0  # never more than the whole account
    with pytest.raises(ValueError):
        max_position_fraction(0.01, 0.0)
