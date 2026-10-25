"""Affordability SQL (sql/05_affordability.sql): synthetic cases with
hand-worked answers, plus cross-checks against the real tidy tables when they
have been built (skipped otherwise)."""
import math

import pandas as pd
import pytest

from rentals import growth
from tests.test_growth import PROCESSED, base_inputs, needs_data

BASE, WORKBOOK, LATEST = (pd.Timestamp(d) for d in ("2019-09-30", "2024-09-30", "2025-09-30"))
REGION = {"X": "Eastern Metro", "Y": "Hume", "Z": "Hume"}


def lga_rents(leases: dict) -> pd.DataFrame:
    """leases: (lga, dwelling) -> (leases at BASE, leases at LATEST, median at LATEST)."""
    rows = [("all", "Table Total", "Victoria", "victoria", q, 5000, 500.0) for q in (BASE, LATEST)]
    for (lga, dwelling), (n0, n1, median) in leases.items():
        rows += [(dwelling, REGION[lga], lga, "lga", BASE, n0, 300.0),
                 (dwelling, REGION[lga], lga, "lga", LATEST, n1, median)]
    return pd.DataFrame(rows, columns=["dwelling", "region", "lga", "row_type", "quarter", "lettings", "median_rent"])


def affordability(shares: dict) -> dict:
    """shares: lga -> (base share, latest share, metro). All bedrooms; 3br
    rows copy the 'all' figures."""
    series, latest = [], []
    for lga, (s0, s1, metro) in shares.items():
        for dwelling in ("all", "3br"):
            series.append((dwelling, lga, "lga", BASE, round(1000 * s0), s0))
            latest.append((dwelling, lga, "lga", metro, LATEST, round(1000 * s1), s1))
    for area, share in {"victoria": 0.10, "metro": 0.05, "non_metro": 0.40}.items():
        series.append(("all", area.title(), area, WORKBOOK, 100, share))
    revised = pd.DataFrame({"area": ["victoria", "metro", "non_metro", "victoria"],
                            "quarter": [WORKBOOK, WORKBOOK, WORKBOOK, LATEST],
                            "affordable_share": [0.12, 0.04, 0.42, 0.14]})  # revisions +0.02, -0.01, +0.02
    thresholds = pd.DataFrame([("3br", "Couple, 2 children", 1000.0, 450.0, "victoria", LATEST, 10, 0.2),
                               ("all", "all", None, None, "victoria", LATEST, 50, 0.1)],
                              columns=list(growth.COLUMNS["affordability_thresholds"]))
    cols = growth.COLUMNS
    return {"lga_affordability": pd.DataFrame(series, columns=list(cols["lga_affordability"])),
            "lga_affordability_latest": pd.DataFrame(latest, columns=list(cols["lga_affordability_latest"])),
            "affordability_state_revised": revised, "affordability_thresholds": thresholds}


@pytest.fixture(scope="module")
def con():
    subs, _, cpi = base_inputs()
    lgas = lga_rents({
        ("X", "all"): (100, 100, 450.0), ("Y", "all"): (200, 200, 400.0), ("Z", "all"): (1000, 1000, 500.0),
        # 3br = 3br flats + 3br houses; a suppressed (missing) count adds nothing
        ("X", "3br_flat"): (40, None, None), ("X", "3br_house"): (70, 99, 440.0),
    })
    return growth.connect(subs, lgas, cpi, **affordability({
        "X": (0.10, 0.05, True),    # small fall, wide margin: not clear
        "Y": (0.50, 0.30, False),   # big fall: clear even after the allowance
        "Z": (0.30, 0.25, False),   # clear on sampling alone, not after the allowance
    }))


def change(con, dwelling="all") -> pd.DataFrame:
    return growth.query(con, f"select * from lga_affordability_change where dwelling = '{dwelling}'").set_index("lga")


def test_quarters_and_allowance(con):
    q = growth.query(con, "select * from affordability_quarters").iloc[0]
    assert (q.base_q, q.workbook_q, q.latest_q) == (BASE, WORKBOOK, LATEST)
    # largest revision of the workbook's newest quarter, not the metro one or the later quarter
    assert growth.query(con, "select allowance from affordability_allowance").iloc[0, 0] == pytest.approx(0.02)


def test_margin_and_clear_fall_hand_worked(con):
    c = change(con)
    # Y: 1.96 * sqrt(.5*.5/200 + .3*.7/200) = 0.0940; -0.20 + 0.02 < -0.094
    assert c.loc["Y", "margin"] == pytest.approx(1.96 * math.sqrt(0.25 / 200 + 0.21 / 200))
    assert c.loc["Y", "change"] == pytest.approx(-0.20)
    assert c.loc["Y", "clear_fall"] and not c.loc["Y", "clear_rise"]
    # X: margin 0.0727 > 0.05 - 0.02
    assert c.loc["X", "margin"] == pytest.approx(1.96 * math.sqrt(0.09 / 100 + 0.0475 / 100))
    assert not c.loc["X", "clear_fall"]
    # Z: -0.05 beats the 0.039 margin, but -0.05 + 0.02 doesn't
    assert c.loc["Z", "margin"] == pytest.approx(0.0391, abs=1e-4)
    assert c.loc["Z", "change"] < -c.loc["Z", "margin"] and not c.loc["Z", "clear_fall"]


def test_well_sampled_sums_bedroom_types(con):
    c = change(con, "3br")
    assert (c.loc["X", "base_leases"], c.loc["X", "latest_leases"]) == (110, 99)
    assert not c.loc["X", "well_sampled"]  # 99 at the latest quarter, below the 100 floor
    assert change(con).loc["X", "well_sampled"]  # exactly 100 at both ends


def test_trend_switches_source_and_flags_provisional(con):
    t = growth.query(con, "select * from affordability_trend where area = 'victoria' order by quarter")
    assert list(t.quarter) == [WORKBOOK, LATEST]  # the workbook's own WORKBOOK quarter is replaced
    assert list(t.source) == ["later report", "later report"]
    assert list(t.affordable_share) == [0.12, 0.14]
    assert list(t.provisional) == [False, True]


def test_rent_vs_threshold(con):
    r = growth.query(con, "select * from rent_vs_threshold where lga = 'X' and dwelling = '3br_house'").iloc[0]
    assert (r.affordable_rent, r.median_rent, r.gap, r.affordable_at_median) == (450, 440, -10, True)
    assert r.bedroom_affordable_share == 0.05


def test_concentration(con):
    c = growth.query(con, "select * from affordable_concentration where period = 'latest' order by position")
    assert list(c.lga) == ["Y", "Z", "X"]  # 300, 250, 50
    assert c.share_of_state.tolist() == pytest.approx([0.5, 250 / 600, 50 / 600])
    assert c.cumulative_share.iloc[-1] == pytest.approx(1.0)


def test_fast_risers_left_unmapped_are_visible(con):
    # synthetic regional suburb 'C' is in the top 10 but has no town_lga entry
    f = growth.query(con, "select * from fast_riser_lgas")
    assert list(f.suburb) == ["C"] and f.lga.isna().all()


def test_empty_affordability_tables_still_run():
    con = growth.connect(*base_inputs())
    assert growth.query(con, "select count(*) from lga_affordability_change").iloc[0, 0] == 0
    with pytest.raises(TypeError, match="unknown tables"):
        growth.connect(*base_inputs(), lga_afordability=pd.DataFrame())


# --- real data ---

@pytest.fixture(scope="module")
def real():
    return growth.connect(*growth.load_inputs(), **growth.load_affordability())


@needs_data
def test_real_quarters_match_part2(real):
    q = growth.query(real, "select * from affordability_quarters").iloc[0]
    end = growth.query(real, "select max(end_q) from windows").iloc[0, 0]
    assert q.base_q == pd.Timestamp("2019-09-30") and q.latest_q == end == pd.Timestamp("2025-09-30")


@needs_data
def test_real_every_fast_riser_town_has_an_lga(real):
    f = growth.query(real, "select * from fast_riser_lgas")
    assert len(f) > 0 and f.lga.notna().all()
    known = set(pd.read_csv(PROCESSED / "lga_rents.csv").lga)
    assert set(growth.query(real, "select lga from town_lga").lga) <= known


@needs_data
def test_real_change_matches_pandas(real):
    c = change(real).sort_index()
    a = pd.read_csv(PROCESSED / "lga_affordability.csv", parse_dates=["quarter"])
    latest = pd.read_csv(PROCESSED / "lga_affordability_latest.csv")
    rents = pd.read_csv(PROCESSED / "lga_rents.csv", parse_dates=["quarter"])
    base = a[(a.dwelling == "all") & (a.row_type == "lga") & (a.quarter == "2019-09-30")].set_index("lga")
    end = latest[(latest.dwelling == "all") & (latest.row_type == "lga")].set_index("lga")
    expected = (end.affordable_share - base.affordable_share).sort_index()
    assert len(c) == 79
    assert c["change"].values == pytest.approx(expected.values)
    n = rents[(rents.dwelling == "all") & (rents.row_type == "lga")].pivot_table(
        index="lga", columns="quarter", values="lettings")
    ws = (n[pd.Timestamp("2019-09-30")].fillna(0) >= 100) & (n[pd.Timestamp("2025-09-30")].fillna(0) >= 100)
    assert c["well_sampled"].sort_index().tolist() == ws.reindex(c.index).tolist()


@needs_data
def test_real_concentration_totals(real):
    t = growth.query(real, "select period, sum(affordable_lettings) n from affordable_concentration group by period")
    assert dict(zip(t.period, t.n)) == {"base": 8650, "latest": 7794}
