"""Audit checks: synthetic cases for the logic, plus the real workbooks when
they have been downloaded (skipped otherwise)."""
from pathlib import Path

import pandas as pd
import pytest

from rentals import audit, parse

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
SUBURBS = RAW / "moving_annual_rents_by_suburb_sep2025.xlsx"
LGAS = RAW / "quarterly_median_rents_by_lga_sep2025.xlsx"
AFFORD = RAW / "affordable_lettings_by_lga_sep2024.xlsx"
TABLES = RAW / "rental_report_tables_sep2025.xlsx"
needs_data = pytest.mark.skipif(not SUBURBS.exists(), reason="run scripts/download_data.py first")


def frame(rows):
    df = pd.DataFrame(rows, columns=["dwelling", "region", "suburb", "row_type", "metro",
                                     "quarter", "lettings", "median_rent"])
    df["quarter"] = pd.to_datetime(df["quarter"])
    df["lettings"] = df["lettings"].astype("Int64")
    return df


def test_group_totals_flags_unexplained_gap():
    q = "2025-09-30"
    explained = frame([
        ("all", "R", "A", "suburb", True, q, 50, 500),
        ("all", "R", "B", "suburb", True, q, None, None),  # suppressed
        ("all", "R", "Group Total", "group_total", True, q, 58, 500),
    ])
    out = audit.group_totals(explained)
    assert out["gap_with_suppressed_suburb"] == 1 and out["gap_without_suppressed_suburb"] == 0

    unexplained = frame([
        ("all", "R", "A", "suburb", True, q, 50, 500),
        ("all", "R", "Group Total", "group_total", True, q, 58, 500),
    ])
    assert audit.group_totals(unexplained)["gap_without_suppressed_suburb"] == 1


def test_reconcile_table4_catches_wrong_value_and_rank():
    q = "2025-09-30"
    suburbs = frame([
        ("2br_flat", "R", "A", "suburb", True, q, 100, 700),
        ("2br_flat", "R", "B", "suburb", True, q, 100, 650),
        ("2br_flat", "R", "C", "suburb", True, q, 100, 720),  # higher than the listed "highest"
    ])
    t4 = pd.DataFrame([
        {"dwelling": "2br_flat", "metro": True, "side": "highest", "suburb": "A", "published_median": 700.0},
        {"dwelling": "2br_flat", "metro": True, "side": "lowest", "suburb": "B", "published_median": 640.0},
    ])
    r = audit.reconcile_table4(suburbs, t4).set_index("suburb")
    assert r.loc["A", "matches"] and not r.loc["A", "rank_ok"]
    assert not r.loc["B", "matches"]


def test_median_jumps_needs_consecutive_well_sampled_quarters():
    rows = [
        ("all", "R", "A", "suburb", True, "2025-03-31", 200, 500),
        ("all", "R", "A", "suburb", True, "2025-06-30", 200, 700),  # +40%, flagged
        ("all", "R", "A", "suburb", True, "2025-09-30", 20, 1000),  # too few leases
        ("all", "R", "B", "suburb", True, "2024-12-31", 200, 500),
        ("all", "R", "B", "suburb", True, "2025-09-30", 200, 900),  # not consecutive
    ]
    j = audit.median_jumps(frame(rows))
    assert list(j.suburb) == ["A"] and j.iloc[0].quarter == pd.Timestamp("2025-06-30")
    assert len(audit.median_jumps(frame(rows), min_lettings=10)) == 2


@pytest.fixture(scope="module")
def real():
    return {
        "suburbs": parse.parse_suburbs(SUBURBS),
        "lgas": parse.parse_lgas(LGAS),
        "aff": parse.parse_affordability(AFFORD),
        "table4": parse.parse_table4(TABLES),
        "latest": parse.parse_table14(TABLES),
        "thresholds": parse.parse_table9(TABLES),
        "revised": parse.parse_fig8(TABLES),
    }


@needs_data
def test_real_shapes(real):
    s = real["suburbs"]
    assert s.loc[s.row_type == "suburb", "suburb"].nunique() == 146
    assert s["quarter"].min() == pd.Timestamp("2000-03-31")
    assert s["quarter"].max() == pd.Timestamp("2025-09-30")
    assert real["lgas"].loc[real["lgas"].row_type == "lga", "lga"].nunique() == 79
    assert real["aff"]["quarter"].max() == pd.Timestamp("2024-09-30")
    # the two LGA tables join on name after NAME_FIXES
    aff_lgas = set(real["aff"].loc[real["aff"].row_type == "lga", "lga"])
    rent_lgas = set(real["lgas"].loc[real["lgas"].row_type == "lga", "lga"])
    assert aff_lgas == rent_lgas


@needs_data
def test_real_table4_reconciles(real):
    r = audit.reconcile_table4(real["suburbs"], real["table4"])
    assert len(r) == 49 and r["matches"].all() and r["rank_ok"].all()


@needs_data
def test_real_totals(real):
    g = audit.group_totals(real["suburbs"])
    assert g["total_below_sum"] == 0 and g["gap_without_suppressed_suburb"] == 0
    lt = audit.lga_totals(real["lgas"])
    assert lt["victoria_eq_group_totals"] == lt["quarters"]
    assert lt["victoria_below_lga_sum"] == 0 and lt["gap_without_suppressed_lga"] == 0
    at = audit.affordability_totals(real["aff"])
    assert at["victoria_eq_lga_sum"] == at["quarters"] and at["share_out_of_range"] == 0


def test_affordability_revisions_marks_newest_quarter():
    q1, q2 = pd.Timestamp("2024-06-30"), pd.Timestamp("2024-09-30")
    series = pd.DataFrame([("all", "Victoria", "victoria", q1, 10, 0.123), ("all", "Victoria", "victoria", q2, 10, 0.104),
                           ("2br", "Victoria", "victoria", q2, 5, 0.9)],
                          columns=["dwelling", "lga", "row_type", "quarter", "affordable_lettings", "affordable_share"])
    revised = pd.DataFrame({"area": ["victoria"] * 2, "quarter": [q1, q2], "affordable_share": [0.124, 0.120]})
    r = audit.affordability_revisions(series, revised).set_index("quarter")
    assert len(r) == 2  # bedroom rows are not compared
    assert r.loc[q1, "difference"] == 0.001 and not r.loc[q1, "workbook_latest_quarter"]
    assert r.loc[q2, "difference"] == 0.016 and r.loc[q2, "workbook_latest_quarter"]
    # a workbook that runs past the later report: no compared quarter is its newest
    later = pd.concat([series, series.iloc[[1]].assign(quarter=pd.Timestamp("2024-12-31"))])
    assert not audit.affordability_revisions(later, revised)["workbook_latest_quarter"].any()


@needs_data
def test_real_affordability_snapshot(real):
    s = audit.affordability_snapshot(real["latest"], real["thresholds"], real["lgas"], real["aff"])
    assert s["victoria_eq_lga_sum"] == s["dwellings"] == 5
    assert s["area_eq_table9"] == s["area_cells"] == 10
    assert s["lgas"] == 79 and not s["lgas_missing_from_series"] and not s["metro_flag_disagrees"]
    assert s["bedrooms_eq_all_series"] == s["series_lga_quarters"]
    r = audit.affordability_revisions(real["aff"], real["revised"])
    assert (r.loc[~r.workbook_latest_quarter, "difference"].abs() <= 0.001).all()
    newest = r[r.workbook_latest_quarter].set_index("area")["difference"]
    assert (newest > 0).all() and newest["victoria"] == 0.016
