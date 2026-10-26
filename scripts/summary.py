"""Part 5: the headline numbers behind the README's TL;DR, in one generated
file. Runs sql/*.sql in DuckDB (the same tables as Parts 2-4) and writes
results/SUMMARY.md.

    python scripts/build.py
    python scripts/summary.py

tests/test_summary.py checks that every number in the README's TL;DR is one
of these figures, and that each figure also appears in the Part report it
comes from, so the summary can't drift from the analysis.
"""
from dataclasses import dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from rentals import growth  # noqa: E402
from scripts.growth import md, money  # noqa: E402

RESULTS = ROOT / "results"
SUMMARY = RESULTS / "SUMMARY.md"


@dataclass
class Key:
    part: int
    finding: str
    figures: list[str]  # each one appears verbatim in `report`
    report: str


def pct(x: float) -> str:
    return f"{100 * x:+.1f}%"


def share(x: float) -> str:
    return f"{100 * x:.1f}%"


def rank_corr(x: pd.Series, y: pd.Series) -> str:
    return f"{x.rank().corr(y.rank()):.2f}"


def key_numbers(con) -> list[Key]:
    q = lambda sql: growth.query(con, sql)  # noqa: E731
    keys = []

    # --- Part 2: rents ---
    st = q("select * from state_growth where dwelling = 'all'").set_index(["area", "window"])
    vic, vic_1y = st.loc[("victoria", "since_2019")], st.loc[("victoria", "1y")]
    keys.append(Key(2, "Victoria, median weekly rent of new leases, Sep 2019 → Sep 2025 (nominal, real)",
                    [money(vic.start_rent), money(vic.end_rent), pct(vic.growth), pct(vic.real_growth)],
                    "GROWTH.md"))
    keys.append(Key(2, "Victoria, the last year (Sep 2024 → Sep 2025, nominal, real)",
                    [pct(vic_1y.growth), pct(vic_1y.real_growth)], "GROWTH.md"))
    keys.append(Key(2, "Regional Victoria and Metro Melbourne since Sep 2019",
                    [pct(st.loc[("non_metro", "since_2019")].growth), pct(st.loc[("metro", "since_2019")].growth)],
                    "GROWTH.md"))
    rg = q("select * from region_growth where dwelling = 'all' and \"window\" = 'since_2019' "
           "order by growth desc, region")
    fast, slow = rg.iloc[0], rg.iloc[-1]
    keys.append(Key(2, f"Fastest region since Sep 2019 ({fast.region}); slowest ({slow.region}, nominal, real)",
                    [pct(fast.growth), pct(slow.growth), pct(slow.real_growth)], "GROWTH.md"))

    # --- Part 3: affordability ---
    beds = q("select * from affordability_by_bedroom").set_index(["area", "dwelling"])
    keys.append(Key(3, "Share of new leases affordable to a lower-income household, Sep 2019 → Sep 2025: "
                    "Victoria, Metro Melbourne, Regional Victoria",
                    [f"{share(beds.loc[(a, 'all')].base_share)} → {share(beds.loc[(a, 'all')].latest_share)}"
                     for a in ("victoria", "metro", "non_metro")], "AFFORDABILITY.md"))
    two = beds.loc[("non_metro", "2br")]
    keys.append(Key(3, "Regional Victoria, 2-bedroom leases affordable to a single parent, Sep 2019 → Sep 2025",
                    [f"{share(two.base_share)} → {share(two.latest_share)}"], "AFFORDABILITY.md"))
    one = beds.loc[("victoria", "1br")]
    flat = q("select end_rent from state_growth where dwelling = '1br_flat' and area = 'victoria' "
             "and \"window\" = '1y'").iloc[0, 0]
    keys.append(Key(3, "1-bedroom leases affordable to a single on JobSeeker, Sep 2025; the median 1-bedroom "
                    "flat against the affordable rent",
                    [share(one.latest_share), money(flat), money(one.affordable_rent)], "AFFORDABILITY.md"))
    ch = q("select * from lga_affordability_change where dwelling = 'all' and well_sampled")
    by = ch.groupby("metro").agg(n=("lga", "size"), falls=("clear_fall", "sum"))
    keys.append(Key(3, "Well-sampled LGAs with a clear fall in the affordable share: regional, metro",
                    [f"{int(by.loc[False, 'falls'])} of {int(by.loc[False, 'n'])}",
                     f"{int(by.loc[True, 'falls'])} of {int(by.loc[True, 'n'])}"], "AFFORDABILITY.md"))
    fr = q("select * from fast_riser_lgas").drop_duplicates("lga")
    keys.append(Key(3, "LGAs of Part 2's top-10 fastest-rising regional towns with a clear fall",
                    [f"{int(fr.clear_fall.sum())} of {len(fr)}"], "AFFORDABILITY.md"))
    rel = q("select * from lga_rent_and_affordability")
    keys.append(Key(3, "Rank correlation, LGA rent growth vs change in affordable share (all well-sampled LGAs)",
                    [rank_corr(rel.rent_growth, rel.change)], "AFFORDABILITY.md"))
    conc = q("select * from affordable_concentration where position = 2").set_index("period")
    keys.append(Key(3, "Share of Victoria's affordable new leases in the top 2 LGAs (Wyndham, Melton), "
                    "Sep 2019 and Sep 2025",
                    [share(conc.loc["base"].cumulative_share), share(conc.loc["latest"].cumulative_share)],
                    "AFFORDABILITY.md"))

    # --- Part 4: market activity ---
    p = q("select * from activity_periods").iloc[0]
    tot = q("select row_type, quarter, leases_12m from annual_leases where row_type = 'victoria'") \
        .set_index("quarter").leases_12m
    keys.append(Key(4, "New leases in Victoria, 12 months to Sep 2019 → Sep 2025",
                    [f"{tot[p.base_q]:,.0f}", f"{tot[p.latest_q]:,.0f}", pct(tot[p.latest_q] / tot[p.base_q] - 1)],
                    "MARKET_ACTIVITY.md"))
    act = q("select * from lga_activity")
    keys.append(Key(4, "LGAs that signed fewer new leases", [
        f"{int((act.lease_change < 0).sum())} of {int(act.lease_change.notna().sum())}"], "MARKET_ACTIVITY.md"))
    gl = q("select * from group_leases").pivot_table(index="group", columns="quarter", values="leases_12m")
    grp = ["Growth areas", "City of Melbourne", "Rest of Melbourne"]
    keys.append(Key(4, "Change in new leases: growth areas, City of Melbourne, rest of Melbourne",
                    [pct(gl.loc[g, p.latest_q] / gl.loc[g, p.base_q] - 1) for g in grp], "MARKET_ACTIVITY.md"))
    ws = act[act.well_sampled].copy()
    keys.append(Key(4, "Rank correlation, building rate vs change in new leases (well-sampled LGAs)",
                    [rank_corr(ws.approval_rate, ws.lease_growth)], "MARKET_ACTIVITY.md"))
    higher = ws.approval_rate >= ws.approval_rate.median()
    keys.append(Key(4, "Median rent growth, higher-building half vs lower-building half of LGAs",
                    [pct(ws[higher].rent_growth.median()), pct(ws[~higher].rent_growth.median())],
                    "MARKET_ACTIVITY.md"))
    mel = q("select * from affordable_decomposition where lga = 'Melton'").iloc[0]
    keys.append(Key(4, "Melton: approvals as a share of 2021 dwellings; part of its rise in affordable leases "
                    "that came from more new leases",
                    [share(act.set_index("lga").loc["Melton"].approval_rate),
                     share(mel.volume_effect / mel.change_affordable)], "MARKET_ACTIVITY.md"))
    return keys


def render(keys: list[Key]) -> str:
    table = pd.DataFrame({
        "part": [k.part for k in keys], "finding": [k.finding for k in keys],
        "figures": ["; ".join(k.figures) for k in keys],
        "full table in": [f"[{k.report}]({k.report})" for k in keys],
    })
    return "\n".join([
        "# Headline numbers",
        "",
        "Generated by `scripts/summary.py` from the same DuckDB tables as Parts 2–4. Don't edit by hand. "
        "Every number in the README's TL;DR is one of these figures (`tests/test_summary.py` checks it), and "
        "each figure appears in the report linked in its row. Rents are medians of new leases; real growth is "
        "deflated by Melbourne CPI.",
        "",
        md(table),
        "",
    ])


def main() -> None:
    con = growth.connect(*growth.load_inputs(), **growth.load_affordability(), **growth.load_supply())
    RESULTS.mkdir(exist_ok=True)
    SUMMARY.write_text(render(key_numbers(con)))
    print(f"wrote {SUMMARY.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
