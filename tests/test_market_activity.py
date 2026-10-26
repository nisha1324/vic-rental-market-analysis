"""Market activity SQL (sql/06_market_activity.sql) and the ABS supply
download: synthetic cases with hand-worked answers, plus cross-checks against
the real tables when they have been built (skipped otherwise)."""
import pandas as pd
import pytest

from rentals import growth
from scripts import download_supply
from tests.test_growth import PROCESSED, QUARTERS, base_inputs, lgas_frame, needs_data, rent_path

BASE, LATEST = pd.Timestamp("2019-09-30"), pd.Timestamp("2025-09-30")
# LGA -> (metro, region, leases a quarter up to Sep 2019, from Dec 2024, rent then, rent now)
LGAS = {
    "Melton": (True, "North and West Metro", 100, 200, 300.0, 390.0),     # growth area
    "Melbourne": (True, "North and West Metro", 500, 600, 400.0, 500.0),  # the city
    "Knox": (True, "Eastern Metro", 300, 240, 400.0, 600.0),              # rest of Melbourne
    "Horsham": (False, "Grampians", 50, 40, 250.0, 375.0),                # regional; one quarter suppressed
}


def lga_rents() -> pd.DataFrame:
    rows = []
    for lga, (_, region, n0, n1, r0, r1) in LGAS.items():
        for q in QUARTERS:
            n = n1 if q >= pd.Timestamp("2024-12-31") else n0
            if lga == "Horsham" and q == pd.Timestamp("2025-06-30"):
                n = None
            r = r1 if q == LATEST else r0
            rows.append(("all", region, lga, "lga", q, n, r))
    lgas = pd.DataFrame(rows, columns=["dwelling", "region", "lga", "row_type", "quarter", "lettings", "median_rent"])
    return pd.concat([lgas_frame(rent_path(400, 550)), lgas], ignore_index=True)


def affordability() -> dict:
    # lga -> (affordable, share) at BASE and LATEST
    ends = {"Melton": ((400, 0.40), (750, 0.50)),      # N 1,000 -> 1,500
            "Melbourne": ((10, 0.02), (12, 0.02)),     # under 5%: left out of the decomposition
            "Knox": ((60, 0.20), (36, 0.15)),
            "Horsham": ((25, 0.50), (20, 0.50))}
    series = [("all", lga, "lga", BASE, a, s) for lga, ((a, s), _) in ends.items()]
    latest = [("all", lga, "lga", LGAS[lga][0], LATEST, a, s) for lga, (_, (a, s)) in ends.items()]
    cols = growth.COLUMNS
    return {"lga_affordability": pd.DataFrame(series, columns=list(cols["lga_affordability"])),
            "lga_affordability_latest": pd.DataFrame(latest, columns=list(cols["lga_affordability_latest"]))}


def supply() -> dict:
    quarters = pd.date_range("2018-09-30", "2025-06-30", freq="QE")
    # 10 a quarter, except 5 in Sep 2018 (main window only) and 1,000 in Sep 2024 (late window only)
    per_q = {q: 10 for q in quarters} | {pd.Timestamp("2018-09-30"): 5, pd.Timestamp("2024-09-30"): 1000}
    approvals = pd.DataFrame([(lga, q, n) for lga in LGAS for q, n in per_q.items()],
                             columns=["lga", "quarter", "approvals"])
    dwellings = pd.DataFrame({"lga": list(LGAS), "dwellings_2021": [1000, 2000, 4000, 500]})
    return {"dwelling_approvals": approvals, "census_dwellings": dwellings}


@pytest.fixture(scope="module")
def con():
    subs, _, cpi = base_inputs()
    return growth.connect(subs, lga_rents(), cpi, **affordability(), **supply())


def table(con, name: str) -> pd.DataFrame:
    return growth.query(con, f"select * from {name}")


def test_periods(con):
    p = table(con, "activity_periods").iloc[0]
    assert (p.base_q, p.latest_q) == (BASE, LATEST)
    assert (p.approvals_from, p.approvals_to) == (pd.Timestamp("2018-09-30"), pd.Timestamp("2024-06-30"))
    assert (p.late_from, p.late_to) == (pd.Timestamp("2019-09-30"), pd.Timestamp("2025-06-30"))


def test_groups(con):
    g = table(con, "lga_group").set_index("lga")["group"]
    assert g.to_dict() == {"Melton": "Growth areas", "Melbourne": "City of Melbourne",
                           "Knox": "Rest of Melbourne", "Horsham": "Rest of regional Victoria"}


def test_annual_leases_need_four_published_quarters(con):
    a = table(con, "annual_leases").query("row_type == 'lga'").set_index(["lga", "quarter"]).leases_12m
    assert a[("Melton", BASE)] == 400 and a[("Melton", LATEST)] == 800
    # Dec 2024 is the first quarter at the new level, so the 12 months to Sep 2025 are all new
    assert a[("Knox", pd.Timestamp("2025-06-30"))] == 300 + 3 * 240
    assert pd.isna(a[("Horsham", LATEST)])  # Jun 2025 suppressed
    assert pd.Timestamp("2018-12-31") not in a.loc["Melton"].index  # no 4 quarters behind it yet


def test_group_index(con):
    g = table(con, "group_leases").set_index(["group", "quarter"])
    assert g.loc[("Growth areas", BASE), "index_2019"] == 100
    assert g.loc[("Growth areas", LATEST), "index_2019"] == pytest.approx(200)
    # the suppressed quarter counts as 0 in the group sum: 3 x 40 against 4 x 50
    assert g.loc[("Rest of regional Victoria", LATEST), "leases_12m"] == 120
    assert g.loc[("Rest of regional Victoria", LATEST), "index_2019"] == pytest.approx(60)


def test_approval_windows_and_rate(con):
    a = table(con, "lga_approvals").set_index("lga")
    assert (a.approval_quarters == 24).all()
    assert a.loc["Melton", "approvals"] == 5 + 23 * 10
    assert a.loc["Melton", "approvals_late"] == 23 * 10 + 1000
    assert a.loc["Melton", "approval_rate"] == pytest.approx(0.235)
    assert a.loc["Knox", "approval_rate"] == pytest.approx(235 / 4000)


def test_lga_activity(con):
    a = table(con, "lga_activity").set_index("lga")
    m = a.loc["Melton"]
    assert (m.base_leases_12m, m.latest_leases_12m, m.lease_change) == (400, 800, 400)
    assert m.lease_growth == pytest.approx(1.0)
    assert m.rent_growth == pytest.approx(0.30)
    assert m.affordable_change == pytest.approx(0.10)
    assert a.loc["Knox", "lease_growth"] == pytest.approx(-0.2)
    assert pd.isna(a.loc["Horsham", "lease_growth"])


def test_share_of_gains(con):
    s = table(con, "lga_activity_share").set_index("lga")
    # gains: Melton +400, Melbourne +400; Knox's fall isn't in the denominator
    assert s.loc["Melton", "share_of_gains"] == pytest.approx(0.5)
    assert s.loc["Knox", "share_of_gains"] == pytest.approx(-240 / 800)
    assert "Horsham" not in s.index


def test_decomposition_hand_worked(con):
    d = table(con, "affordable_decomposition").set_index("lga")
    assert "Melbourne" not in d.index  # share under 5%
    m = d.loc["Melton"]
    assert (m.n0, m.n1) == pytest.approx((1000, 1500))
    # volume: 500 more leases x average share 0.45; share: +0.10 x average 1,250 leases
    assert m.volume_effect == pytest.approx(225) and m.share_effect == pytest.approx(125)
    assert (d.volume_effect + d.share_effect).values == pytest.approx(d.change_affordable.values)
    k = d.loc["Knox"]  # 60 / 0.20 = 300 -> 36 / 0.15 = 240: fewer leases and a lower share
    assert k.volume_effect == pytest.approx(-60 * 0.175) and k.share_effect == pytest.approx(-0.05 * 270)


# --- the ABS download ----------------------------------------------------------

HEADER = "DATAFLOW,MEASURE,SECTOR,WORK_TYPE,BUILDING_TYPE,REGION_TYPE,REGION,FREQ,TIME_PERIOD,OBS_VALUE\n"


def ba_csv(rows, key="1,9,1,100") -> str:
    return HEADER + "".join(f"ABS:BA_LGA2020(1.0.0),{key},LGA2020,{code},M,{month},{n}\n" for code, month, n in rows)


def test_parse_approvals_keeps_victorian_lgas_and_renames_moreland():
    df = download_supply.parse_approvals(ba_csv([
        ("24650", "2020-07", 60), ("25250", "2020-08", 7),   # Melton; Moreland -> Merri-bek
        ("10050", "2020-07", 9), ("2", "2020-07", 999), ("29499", "2020-07", 1),  # NSW, state total, non-area
    ]), 2020)
    assert sorted(df.abs_code) == ["24650", "24700"]


def test_parse_approvals_rejects_other_series_and_months():
    with pytest.raises(ValueError, match="unexpected series"):
        download_supply.parse_approvals(ba_csv([("24650", "2020-07", 1)], key="1,9,1,110"), 2020)
    with pytest.raises(ValueError, match="outside"):
        download_supply.parse_approvals(ba_csv([("24650", "2021-07", 1)]), 2020)


def test_to_quarters_drops_incomplete_quarters():
    monthly = pd.DataFrame({"abs_code": ["24650"] * 4,
                            "month": pd.PeriodIndex(["2020-07", "2020-08", "2020-09", "2020-10"], freq="M"),
                            "approvals": [1, 2, 3, 4]})
    q = download_supply.to_quarters(monthly)
    assert q.to_dict("records") == [{"abs_code": "24650", "quarter": pd.Timestamp("2020-09-30"), "approvals": 6}]


def test_standard_names():
    assert download_supply.standard_name("Kingston (Vic.)") == "Kingston"
    assert download_supply.standard_name("Colac Otway") == "Colac-Otway"
    assert download_supply.standard_name("Melton") == "Melton"


# --- real data ---------------------------------------------------------------

@pytest.fixture(scope="module")
def real():
    if not (PROCESSED / "suburb_rents.csv").exists():
        pytest.skip("run scripts/download_data.py and scripts/build.py first")
    return growth.connect(*growth.load_inputs(), **growth.load_affordability(), **growth.load_supply())


@needs_data
def test_real_every_lga_has_supply_data(real):
    a = table(real, "lga_approvals")
    known = set(pd.read_csv(PROCESSED / "lga_rents.csv").query("row_type == 'lga'").lga)
    assert set(a.lga) == known and len(a) == 79
    assert (a.approval_quarters == 24).all() and a.dwellings_2021.notna().all()


@needs_data
def test_real_annual_leases_match_pandas(real):
    rents = pd.read_csv(PROCESSED / "lga_rents.csv", parse_dates=["quarter"])
    r = rents[(rents.dwelling == "all") & (rents.row_type == "lga")].sort_values(["lga", "quarter"])
    pandas = r.groupby("lga").lettings.rolling(4, min_periods=4).sum().reset_index(level=0)
    pandas["quarter"] = r.quarter
    a = table(real, "lga_activity").set_index("lga")
    for when, col in ((BASE, "base_leases_12m"), (LATEST, "latest_leases_12m")):
        expected = pandas[pandas.quarter == when].set_index("lga").lettings
        pd.testing.assert_series_equal(a[col].sort_index(), expected.sort_index(), check_names=False)


@needs_data
def test_real_groups_add_up_to_victoria(real):
    g = table(real, "group_leases").groupby("quarter").leases_12m.sum()
    v = table(real, "annual_leases").query("row_type == 'victoria'").set_index("quarter").leases_12m
    for q in (BASE, LATEST):
        assert 0 <= v[q] - g[q] <= 0.001 * v[q]  # only suppressed cells are missing
    assert (v[BASE], v[LATEST]) == (208281, 203821)


@needs_data
def test_real_decomposition_adds_up_and_denominators_are_close(real):
    d = table(real, "affordable_decomposition")
    assert (d.volume_effect + d.share_effect).values == pytest.approx(d.change_affordable.values)
    leases = table(real, "lga_affordability_change").query("dwelling == 'all'").set_index("lga")
    w = d[d.well_sampled].set_index("lga")
    # The share's own denominator runs a little above the rents workbook's count
    # (see sql/05). Bass Coast is the exception: 5-year medians of 1.5-1.7x since
    # 2000 and 1.8-2.0x in these two quarters, so the workbooks count it differently.
    for end, col in (("n0", "base_leases"), ("n1", "latest_leases")):
        ratio = w[end] / leases.loc[w.index, col]
        assert ratio.drop("Bass Coast").between(0.97, 1.20).all(), ratio.describe()
        assert 1.5 < ratio["Bass Coast"] < 2.0
