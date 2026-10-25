"""Growth SQL: synthetic cases with hand-worked answers, plus cross-checks
against the real tidy tables when they have been built (skipped otherwise)."""
from pathlib import Path

import pandas as pd
import pytest

from rentals import growth
from scripts import download_cpi

QUARTERS = pd.date_range("2018-12-31", "2025-09-30", freq="QE")
PROCESSED = Path(__file__).resolve().parents[1] / "data" / "processed"
needs_data = pytest.mark.skipif(not (PROCESSED / "suburb_rents.csv").exists(),
                                reason="run scripts/download_data.py and scripts/build.py first")


def rent_path(start: float, end: float) -> dict:
    """Flat at `start` until Sep 2019, then `end` from Sep 2024 on, with a
    straight line in between."""
    out = {}
    for q in QUARTERS:
        if q <= pd.Timestamp("2019-09-30"):
            out[q] = start
        elif q >= pd.Timestamp("2024-09-30"):
            out[q] = end
        else:
            out[q] = round(start + (end - start) * (q - pd.Timestamp("2019-09-30")).days / 1827)
    return out


def suburbs_frame(series: dict) -> pd.DataFrame:
    """series: (suburb, region, metro, row_type) -> (rents by quarter, lettings or {quarter: lettings})"""
    rows = []
    for (suburb, region, metro, row_type), (rents, lettings) in series.items():
        for q, r in rents.items():
            n = lettings.get(q, 500) if isinstance(lettings, dict) else lettings
            rows.append(("2br_flat", region, suburb, row_type, metro, q, n, r))
    return pd.DataFrame(rows, columns=["dwelling", "region", "suburb", "row_type", "metro",
                                       "quarter", "lettings", "median_rent"])


def lgas_frame(rents: dict) -> pd.DataFrame:
    return pd.DataFrame([("all", "Table Total", "Victoria", "victoria", q, 5000, r) for q, r in rents.items()],
                        columns=["dwelling", "region", "lga", "row_type", "quarter", "lettings", "median_rent"])


def cpi_frame(values=None) -> pd.DataFrame:
    values = values if values is not None else [100.0] * len(QUARTERS)
    return pd.DataFrame({"quarter": QUARTERS, "cpi": values})


def base_inputs(cpi=None, small_lettings=99):
    subs = suburbs_frame({
        ("A", "R1", True, "suburb"): (rent_path(400, 600), 300),
        ("B", "R1", True, "suburb"): (rent_path(400, 700), {pd.Timestamp("2019-09-30"): small_lettings}),
        ("C", "R2", False, "suburb"): (rent_path(300, 330), 150),
        ("Group Total", "R1", True, "group_total"): (rent_path(400, 640), 2000),
    })
    return subs, lgas_frame(rent_path(400, 550)), cpi_frame(cpi)


def windows(con) -> pd.DataFrame:
    return growth.query(con, "select * from windows order by ord").set_index("window")


def test_windows_end_in_latest_quarter():
    w = windows(growth.connect(*base_inputs()))
    assert list(w.index) == ["1y", "5y", "since_2019"]
    assert (w["end_q"] == pd.Timestamp("2025-09-30")).all()
    assert list(w["start_q"]) == [pd.Timestamp(d) for d in ("2024-09-30", "2020-09-30", "2019-09-30")]
    assert list(w["years"]) == [1.0, 5.0, 6.0]


def test_growth_annualised_and_real():
    # CPI rises by a fixed 2 points a quarter (not a fixed %), so the ratio of
    # 4-quarter averages differs from the ratio of the two quarters' values.
    cpi = [100 + 2 * i for i in range(len(QUARTERS))]
    con = growth.connect(*base_inputs(cpi=cpi))
    g = growth.query(con, "select * from suburb_growth where suburb = 'A'").set_index("window")
    r = g.loc["since_2019"]
    assert r["growth"] == pytest.approx(0.5)
    assert r["growth_pa"] == pytest.approx(1.5 ** (1 / 6) - 1)

    c = pd.Series(cpi, index=QUARTERS)
    avg = lambda q: c.loc[:q].tail(4).mean()  # noqa: E731
    expected_real = 1.5 / (avg("2025-09-30") / avg("2019-09-30")) - 1
    assert r["real_growth"] == pytest.approx(expected_real)
    # and not the single-quarter ratio, which is a different number here
    assert r["real_growth"] != pytest.approx(1.5 / (c["2025-09-30"] / c["2019-09-30"]) - 1, rel=1e-6)
    assert g.loc["1y", "growth"] == pytest.approx(0.0)


def test_floor_applies_at_both_ends():
    # B has 99 leases at the start of the since-2019 window only.
    con = growth.connect(*base_inputs())
    g = growth.query(con, "select suburb, \"window\", well_sampled from suburb_growth").set_index(["suburb", "window"])
    assert not g.loc[("B", "since_2019"), "well_sampled"]
    assert g.loc[("B", "5y"), "well_sampled"]
    ranked = growth.query(con, "select suburb, rank_fastest from suburb_ranking where \"window\" = 'since_2019'")
    assert set(ranked["suburb"]) == {"A", "C"}
    assert ranked.set_index("suburb").loc["A", "rank_fastest"] == 1

    # Lower the floor and B (the fastest riser) comes in at the top.
    con = growth.connect(*base_inputs(), min_lettings=50)
    ranked = growth.query(con, "select suburb, rank_fastest from suburb_ranking where \"window\" = 'since_2019'")
    assert ranked.set_index("suburb").loc["B", "rank_fastest"] == 1


def test_growth_by_start_rent_thirds():
    con = growth.connect(*base_inputs(), min_lettings=50)  # A, B, C all ranked
    t = growth.query(con, "select * from growth_by_start_rent where \"window\" = 'since_2019' "
                          "order by rent_third").set_index("rent_third")
    assert list(t["suburbs"]) == [1, 1, 1]
    # C starts cheapest (300) and is the only regional suburb; A and B tie on 400 and split by name
    assert t.loc[1, "median_growth"] == pytest.approx(0.1) and t.loc[1, "regional_suburbs"] == 1
    assert t.loc[2, "median_growth"] == pytest.approx(0.5)   # A
    assert t.loc[3, "median_growth"] == pytest.approx(0.75)  # B


def test_region_growth_uses_group_total_and_bands():
    con = growth.connect(*base_inputs())
    r = growth.query(con, "select * from region_growth where \"window\" = 'since_2019'").set_index("region")
    assert list(r.index) == ["R1"]  # R2 has no Group Total row, so no region figure
    assert r.loc["R1", "growth"] == pytest.approx(0.6)
    assert r.loc["R1", "band"] == "Rest of Melbourne"


def test_low_point_and_recovery():
    rents = {q: 500.0 for q in QUARTERS}
    rents.update({pd.Timestamp("2020-12-31"): 450.0, pd.Timestamp("2021-03-31"): 400.0,
                  pd.Timestamp("2021-06-30"): 400.0, pd.Timestamp("2021-09-30"): 480.0})
    subs = suburbs_frame({("Group Total", "Inner Melbourne", True, "group_total"): (rents, 2000),
                          ("Group Total", "Flat", True, "group_total"): ({q: 500.0 for q in QUARTERS}, 2000)})
    con = growth.connect(subs, lgas_frame({q: 500.0 for q in QUARTERS}), cpi_frame())
    low = growth.query(con, "select * from region_low_point").set_index("region")
    assert low.loc["Inner Melbourne", "low_vs_2019"] == pytest.approx(-20.0)
    assert low.loc["Inner Melbourne", "low_quarter"] == pd.Timestamp("2021-03-31")  # earliest of the tie
    assert low.loc["Inner Melbourne", "back_above_2019"] == pd.Timestamp("2021-12-31")
    assert low.loc["Flat", "low_vs_2019"] == 0 and pd.isna(low.loc["Flat", "back_above_2019"])
    band = growth.query(con, "select region, band from region_growth").drop_duplicates().set_index("region")
    assert band.loc["Inner Melbourne", "band"] == "Inner Melbourne"


def test_state_growth_uses_quarter_cpi():
    cpi = [100 * 1.01 ** i for i in range(len(QUARTERS))]
    con = growth.connect(*base_inputs(cpi=cpi))
    s = growth.query(con, "select * from state_growth where \"window\" = 'since_2019'").iloc[0]
    c = pd.Series(cpi, index=QUARTERS)
    assert s["area"] == "victoria"
    assert s["growth"] == pytest.approx(550 / 400 - 1)
    assert s["real_growth"] == pytest.approx((550 / 400) / (c["2025-09-30"] / c["2019-09-30"]) - 1)


def test_floor_sensitivity_counts():
    subs, lgas, cpi = base_inputs()
    subs = subs.assign(dwelling="3br_house")
    con = growth.connect(subs, lgas, cpi)
    s = growth.floor_sensitivity(con, floors=(50, 100, 200), top=1)
    s = s[s.dwelling == "3br_house"].set_index("floor")
    # top 1 at the default floor is A (B is excluded with 99 leases)
    assert s.loc[100, "top_kept"] == 1
    assert s.loc[50, "left_overtaken"] == 1      # B (99 leases) overtakes A
    assert s.loc[200, "left_below_floor"] == 0   # A has 300 leases at both ends
    assert s.loc[200, "suburbs"] == 1            # C (150 leases) drops out


SDMX = ("DATAFLOW,MEASURE,INDEX,TSEST,REGION,FREQ,TIME_PERIOD,OBS_VALUE\n"
        + "\n".join(f"ABS:CPI(2.0.0),1,10001,10,2,Q,{q},{v}"
                    for q, v in [("1999-Q2", 47.87), ("1999-Q1", 47.67), ("1999-Q3", 48.0)]))


def test_cpi_parse_sorts_and_checks():
    df = download_cpi.parse(SDMX)
    assert list(df["quarter"]) == [pd.Timestamp(d) for d in ("1999-03-31", "1999-06-30", "1999-09-30")]
    assert list(df["cpi"]) == [47.67, 47.87, 48.0]

    with pytest.raises(ValueError, match="not continuous"):
        download_cpi.parse(SDMX.replace("1999-Q2", "1999-Q4"))
    with pytest.raises(ValueError, match="unexpected series"):
        download_cpi.parse(SDMX.replace(",2,Q,1999-Q1", ",50,Q,1999-Q1"))


def test_cpi_refresh_refuses_changed_history(tmp_path):
    old = tmp_path / "cpi.csv"
    download_cpi.parse(SDMX).to_csv(old, index=False)
    download_cpi.check_unchanged(download_cpi.parse(SDMX), old)  # same values: fine
    with pytest.raises(SystemExit, match="changed"):
        download_cpi.check_unchanged(download_cpi.parse(SDMX.replace("48.0", "48.1")), old)


# --- real data ---------------------------------------------------------------

@pytest.fixture(scope="module")
def real():
    if not (PROCESSED / "suburb_rents.csv").exists():
        pytest.skip("run scripts/download_data.py and scripts/build.py first")
    inputs = growth.load_inputs()
    return inputs, growth.connect(*inputs)


@needs_data
def test_real_cpi_covers_every_rent_quarter(real):
    (suburbs, lgas, cpi), _ = real
    q = pd.DatetimeIndex(cpi["quarter"])
    assert q.is_monotonic_increasing
    assert len(pd.date_range(q.min(), q.max(), freq="QE").difference(q)) == 0
    # 12-month suburb medians need the 3 quarters before for the CPI average;
    # single-quarter LGA medians need only their own quarter.
    assert q.min() <= suburbs["quarter"].min() - pd.offsets.QuarterEnd(3)
    assert q.min() <= lgas["quarter"].min()
    assert q.max() >= suburbs["quarter"].max()


@needs_data
def test_real_suburb_growth_matches_pandas(real):
    """Recompute every suburb growth figure from the CSV in pandas and compare."""
    (suburbs, _, _), con = real
    g = growth.query(con, "select * from suburb_growth")
    s = suburbs[suburbs.row_type == "suburb"].set_index(["dwelling", "suburb", "quarter"])
    start = s.loc[list(zip(g.dwelling, g.suburb, g.start_q))]
    end = s.loc[list(zip(g.dwelling, g.suburb, g.end_q))]
    assert (g["growth"].values == pytest.approx(end["median_rent"].values / start["median_rent"].values - 1))
    floor_ok = (pd.concat([start["lettings"].reset_index(drop=True), end["lettings"].reset_index(drop=True)],
                          axis=1).min(axis=1) >= growth.MIN_LETTINGS)
    assert (g["well_sampled"].values == floor_ok.values).all()
    # every suburb with both medians published appears exactly once per window
    both = (suburbs[(suburbs.row_type == "suburb") & suburbs.quarter.isin([pd.Timestamp("2019-09-30"),
                                                                         pd.Timestamp("2025-09-30")])]
            .dropna(subset=["median_rent"]).groupby(["dwelling", "suburb"]).size())
    assert (g["window"] == "since_2019").sum() == (both == 2).sum()


@needs_data
def test_real_state_headline(real):
    _, con = real
    s = growth.query(con, "select * from state_growth where dwelling = 'all' and area = 'victoria' "
                          "and \"window\" = 'since_2019'").iloc[0]
    assert (s["start_rent"], s["end_rent"]) == (400, 550)
    assert s["growth"] == pytest.approx(0.375)
