"""Part 3: affordability. Runs sql/*.sql in DuckDB and writes
results/AFFORDABILITY.md, the LGA table as CSV and the charts.

    python scripts/build.py
    python scripts/affordability.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from rentals import growth  # noqa: E402
from scripts.growth import DWELLING_LABEL, INK, INK_2, MUTED, GRID, SURFACE, md, money, style  # noqa: E402

RESULTS = ROOT / "results"
CHARTS = RESULTS / "charts"

# Categorical slots 1 and 3 of the reference palette (validated as a pair; the
# green is below 3:1 contrast, so every chart is direct-labelled and every
# figure is also in a table). Victoria as a whole is neutral ink.
AREA_COLOR = {"Metro Melbourne": "#2a78d6", "Regional Victoria": "#1baf7a"}
AREA_LABEL = {"victoria": "Victoria", "metro": "Metro Melbourne", "non_metro": "Regional Victoria"}
BEDROOMS = {"1br": "1 bedroom", "2br": "2 bedrooms", "3br": "3 bedrooms", "4br": "4+ bedrooms", "all": "all"}


def pts(x: float) -> str:
    """A change in a share, in percentage points."""
    return f"{100 * x:+.1f} pts"


def share(x: float) -> str:
    return f"{100 * x:.1f}%"


def area_of(metro: bool) -> str:
    return "Metro Melbourne" if metro else "Regional Victoria"


def chart_trend(trend: pd.DataFrame, path: Path) -> None:
    d = trend[trend.quarter.dt.month == 9].sort_values("quarter")
    fig, ax = plt.subplots(figsize=(8.6, 5.0), facecolor=SURFACE)
    colors = {"non_metro": AREA_COLOR["Regional Victoria"], "victoria": INK, "metro": AREA_COLOR["Metro Melbourne"]}
    last = d.quarter.max()
    for area, color in colors.items():
        g = d[d.area == area]
        ax.plot(g.quarter, 100 * g.affordable_share, color=color, linewidth=2, zorder=3)
        settled = g[~g.provisional]
        ax.scatter(settled.quarter, 100 * settled.affordable_share, s=14, color=color, zorder=4,
                   edgecolors=SURFACE, linewidths=1)
        end = g[g.quarter == last].iloc[0]
        ax.scatter([last], [100 * end.affordable_share], s=36, facecolors=SURFACE, edgecolors=color,
                   linewidths=1.6, zorder=5)
        ax.annotate(f"{AREA_LABEL[area]} {share(end.affordable_share)}", (last, 100 * end.affordable_share),
                    xytext=(8, 0), textcoords="offset points", va="center", fontsize=8.5, color=INK)
    base = pd.Timestamp("2019-09-30")
    ax.axvline(base, color=MUTED, linewidth=0.8, linestyle=":")
    ax.text(base, 88, " Sep 2019", fontsize=8, color=INK_2, va="top")
    ax.set_ylim(0, 90)
    ax.set_xlim(d.quarter.min() - pd.Timedelta(days=200), last + pd.Timedelta(days=1750))
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    years = range(2000, last.year + 1, 5)
    ax.set_xticks([pd.Timestamp(f"{y}-09-30") for y in years], [str(y) for y in years])
    style(ax)
    ax.grid(axis="x", visible=False)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_title("Share of new leases affordable to a lower-income household (September quarters)",
                 loc="left", fontsize=10.5, color=INK, pad=12)
    fig.text(0.01, 0.015, "Open circle: Sep 2025, the newest quarter of its release, likely to be revised up. "
             "Source: Homes Victoria Rental Report (affordable lettings).", fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def chart_change(change: pd.DataFrame, path: Path, falls: int = 12, rises: int = 6) -> None:
    d = change[(change.dwelling == "all") & change.well_sampled].sort_values(["change", "lga"])
    d = pd.concat([d.head(falls), d.tail(rises)])
    fig, ax = plt.subplots(figsize=(8.6, 6.6), facecolor=SURFACE)
    y = list(range(len(d)))[::-1]
    for yi, r in zip(y, d.itertuples()):
        color = AREA_COLOR[area_of(r.metro)]
        ax.plot([100 * r.base_share, 100 * r.latest_share], [yi, yi], color="#c9c8c2", linewidth=2, zorder=1)
        ax.scatter([100 * r.base_share], [yi], s=34, color=SURFACE, edgecolors=INK_2, linewidths=1.2, zorder=2)
        ax.scatter([100 * r.latest_share], [yi], s=46, color=color, edgecolors=SURFACE, linewidths=1.5, zorder=3)
        right = max(r.base_share, r.latest_share)
        ax.text(100 * right + 2, yi, pts(r.change), va="center", fontsize=8, color=INK)
    ax.set_yticks(y, [f"{lga}  " for lga in d.lga], fontsize=9, color=INK)
    ax.axhline(rises - 0.5, color=MUTED, linewidth=0.8, linestyle=":")
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    style(ax)
    fig.suptitle("Affordable share of new leases by LGA, Sep 2019 (open circle) to Sep 2025 (filled)",
                 x=0.01, ha="left", fontsize=11, color=INK)
    ax.set_title(f"The {falls} biggest falls (above the dotted line) and the {rises} biggest rises",
                 loc="left", fontsize=9, color=INK_2, pad=8)
    handles = [plt.Line2D([], [], marker="o", linestyle="", color=c, markersize=7) for c in AREA_COLOR.values()]
    fig.legend(handles, list(AREA_COLOR), loc="lower center", ncol=2, frameon=False, fontsize=9,
               bbox_to_anchor=(0.5, 0.035), labelcolor=INK_2)
    fig.text(0.01, 0.012, f"All bedroom counts. LGAs with at least {growth.MIN_LETTINGS} new leases in both "
             "quarters. Source: Homes Victoria Rental Report.", fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.07, 1, 0.97))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def chart_scatter(rel: pd.DataFrame, path: Path, labels: list[str]) -> None:
    fig, ax = plt.subplots(figsize=(8.6, 5.6), facecolor=SURFACE)
    for metro, g in rel.groupby("metro"):
        ax.scatter(100 * g.rent_growth, 100 * g.change, s=40, color=AREA_COLOR[area_of(metro)],
                   edgecolors=SURFACE, linewidths=1.5, zorder=3, label=area_of(metro))
    for r in rel[rel.lga.isin(labels)].itertuples():
        ax.annotate(r.lga, (100 * r.rent_growth, 100 * r.change), xytext=(6, 3), textcoords="offset points",
                    fontsize=8, color=INK)
    ax.axhline(0, color=MUTED, linewidth=0.8)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:+.0f}%")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:+.0f} pts")
    ax.set_xlabel("Change in median weekly rent of new leases, Sep 2019 to Sep 2025 (all properties)",
                  fontsize=9, color=INK_2)
    ax.set_ylabel("Change in affordable share", fontsize=9, color=INK_2)
    style(ax)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_title("Where rents rose most, affordable leases disappeared fastest (one dot per LGA)",
                 loc="left", fontsize=10.5, color=INK, pad=12)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK_2, loc="upper right")
    fig.text(0.01, 0.015, f"LGAs with at least {growth.MIN_LETTINGS} new leases in both quarters. Single-quarter "
             "LGA medians. Source: Homes Victoria Rental Report.", fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    con = growth.connect(*growth.load_inputs(), **growth.load_affordability())
    q = lambda sql: growth.query(con, sql)  # noqa: E731
    quarters = q("select * from affordability_quarters").iloc[0]
    base_q, latest_q = quarters.base_q, quarters.latest_q
    revision = q("select * from affordability_revision order by area")
    allowance = float(q("select allowance from affordability_allowance").iloc[0, 0])
    trend = q("select * from affordability_trend order by area, quarter")
    beds = q("select * from affordability_by_bedroom")
    change = q("select * from lga_affordability_change order by dwelling, lga")
    fast = q("select * from fast_riser_lgas order by town_dwelling, rank_fastest, suburb")
    conc = q("select * from affordable_concentration order by period, position")
    rvt = q("select * from rent_vs_threshold")
    rel = q("select * from lga_rent_and_affordability order by lga")

    RESULTS.mkdir(exist_ok=True)
    CHARTS.mkdir(exist_ok=True)
    change.to_csv(RESULTS / "lga_affordability_change.csv", index=False, float_format="%.4f")
    chart_trend(trend, CHARTS / "affordability_trend.png")
    chart_change(change, CHARTS / "lga_affordability_change.png")
    extremes = rel.sort_values("change")
    chart_scatter(rel, CHARTS / "rent_growth_vs_affordability.png",
                  labels=[*extremes.head(5).lga, *extremes.tail(4).lga])

    # --- thresholds ---
    t = beds[beds.area == "victoria"].set_index("dwelling")
    thr = con.execute("select * from affordability_thresholds where area = 'victoria' and dwelling != 'all' "
                      "order by dwelling").df()
    thr_table = pd.DataFrame({
        "bedrooms": thr.dwelling.map(BEDROOMS), "household": thr.household,
        "weekly income": thr.weekly_income.map(lambda v: f"${v:,.2f}"),
        "most it can pay (affordable rent)": thr.affordable_rent.map(money),
    })

    # --- trend ---
    sep = trend[trend.quarter.dt.month == 9]
    keep_years = [2000, 2005, 2010, 2015, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
    sep = sep[sep.quarter.dt.year.isin(keep_years)]
    wide = sep.pivot_table(index="quarter", columns="area", values="affordable_share").sort_index()
    src = sep.drop_duplicates("quarter").set_index("quarter")
    trend_table = pd.DataFrame({
        "September": wide.index.year,
        "Victoria": wide["victoria"].map(share), "Metro Melbourne": wide["metro"].map(share),
        "Regional Victoria": wide["non_metro"].map(share),
        "source": [("later report, provisional" if src.loc[i, "provisional"] else src.loc[i, "source"])
                   for i in wide.index],
    })

    # --- by bedroom ---
    b = beds.copy()
    b["akey"] = b.area.map({a: i for i, a in enumerate(AREA_LABEL)})
    b = b.sort_values(["akey", "dwelling"])
    bed_table = pd.DataFrame({
        "area": b.area.map(AREA_LABEL), "bedrooms": b.dwelling.map(BEDROOMS),
        f"affordable {base_q:%b %Y}": [f"{share(s)} ({n:,})" for s, n in zip(b.base_share, b.base_affordable)],
        f"affordable {latest_q:%b %Y}": [f"{share(s)} ({n:,})" for s, n in zip(b.latest_share, b.latest_affordable)],
        "change": b.change.map(pts),
    })

    # --- LGAs ---
    ws = change[(change.dwelling == "all") & change.well_sampled]
    n_all = int((change.dwelling == "all").sum())

    def lga_table(df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({
            "LGA": df.lga, "area": df.metro.map(area_of),
            f"{base_q:%b %Y}": [f"{share(s)} ({n:,} of ~{int(l):,})" for s, n, l in
                                zip(df.base_share, df.base_affordable, df.base_leases)],
            f"{latest_q:%b %Y}": [f"{share(s)} ({n:,} of ~{int(l):,})" for s, n, l in
                                  zip(df.latest_share, df.latest_affordable, df.latest_leases)],
            "change": df.change.map(pts), "± margin": df.margin.map(lambda m: f"{100 * m:.1f}"),
            "clear": ["fall" if f else ("rise" if r else "no") for f, r in zip(df.clear_fall, df.clear_rise)],
        })

    falls = ws.sort_values(["change", "lga"]).head(15)
    rises = ws[ws.change > 0].sort_values(["change", "lga"], ascending=[False, True]).head(10)
    summary = ws.groupby("metro").agg(lgas=("lga", "size"), clear_fall=("clear_fall", "sum"),
                                      clear_rise=("clear_rise", "sum"), median_change=("change", "median"))
    summary_table = pd.DataFrame({
        "area": [area_of(m) for m in summary.index], "well-sampled LGAs": summary.lgas,
        "clear fall": summary.clear_fall.astype(int), "clear rise": summary.clear_rise.astype(int),
        "neither": (summary.lgas - summary.clear_fall - summary.clear_rise).astype(int),
        "median change": summary.median_change.map(pts),
    })

    # bedroom-level clear falls (2br: the single-parent household)
    bed_ws = change[(change.dwelling != "all") & change.well_sampled]
    bed_counts = bed_ws.groupby("dwelling").agg(lgas=("lga", "size"), clear_fall=("clear_fall", "sum"),
                                                clear_rise=("clear_rise", "sum"),
                                                median_change=("change", "median")).reset_index()
    bed_counts_table = pd.DataFrame({
        "bedrooms": bed_counts.dwelling.map(BEDROOMS), "well-sampled LGAs": bed_counts.lgas,
        "clear fall": bed_counts.clear_fall.astype(int), "clear rise": bed_counts.clear_rise.astype(int),
        "median change": bed_counts.median_change.map(pts),
    })

    # --- fast risers ---
    unmapped = fast[fast.lga.isna()]
    if len(unmapped):
        raise SystemExit(f"towns without an LGA in sql/05 town_lga: {sorted(unmapped.suburb)}")
    fast_table = pd.DataFrame({
        "town (Part 2)": fast.suburb, "type": fast.town_dwelling.map(DWELLING_LABEL),
        "Part 2 rank": fast.rank_fastest.astype(int), "rent growth since 2019": fast.town_growth.map(lambda v: f"{100 * v:+.1f}%"),
        "LGA": fast.lga, f"affordable {base_q:%b %Y}": fast.base_share.map(share),
        f"affordable {latest_q:%b %Y}": fast.latest_share.map(share), "change": fast.change.map(pts),
        "clear fall": fast.clear_fall.map({True: "yes", False: "no"}),
        f"{growth.MIN_LETTINGS}+ leases": fast.well_sampled.map({True: "yes", False: "no"}),
    })
    fast_lgas = fast.drop_duplicates("lga")

    # --- rent growth vs change ---
    corr_rows = []
    for name, g in [("all", rel), ("Metro Melbourne", rel[rel.metro]), ("Regional Victoria", rel[~rel.metro])]:
        corr_rows.append({"LGAs": name, "n": len(g),
                          "Spearman (ranks)": f"{g.rent_growth.rank().corr(g.change.rank()):.2f}",
                          "Pearson": f"{g.rent_growth.corr(g.change):.2f}"})
    corr_table = pd.DataFrame(corr_rows)
    low_metro = rel[rel.metro & (rel.base_share < 0.03)]
    rel_table = rel.sort_values("change").assign(
        area=lambda d: d.metro.map(area_of),
        rent=lambda d: [f"{money(a)} → {money(b)}" for a, b in zip(d.base_rent, d.latest_rent)],
        rent_growth=lambda d: d.rent_growth.map(lambda v: f"{100 * v:+.1f}%"),
        change=lambda d: d.change.map(pts))[["lga", "area", "rent", "rent_growth", "change"]]

    # --- concentration ---
    def top(period: str, n: int) -> pd.DataFrame:
        return conc[(conc.period == period) & (conc.position <= n)]

    conc_table = pd.DataFrame({
        "position": range(1, 11),
        f"{base_q:%b %Y}": [f"{r.lga} {r.affordable_lettings:,} ({share(r.share_of_state)})" for r in top("base", 10).itertuples()],
        f"{latest_q:%b %Y}": [f"{r.lga} {r.affordable_lettings:,} ({share(r.share_of_state)})" for r in top("latest", 10).itertuples()],
    })
    cum = {p: {n: float(top(p, n).cumulative_share.iloc[-1]) for n in (2, 5, 10)} for p in ("base", "latest")}
    totals = conc.groupby("period").affordable_lettings.sum()

    # --- rent vs threshold ---
    r_lga = rvt[(rvt.row_type == "lga") & rvt.median_rent.notna()]
    rvt_rows = []
    for dwelling in ["1br_flat", "2br_flat", "2br_house", "3br_house", "4br_house"]:
        g = r_lga[(r_lga.dwelling == dwelling) & (r_lga.lettings >= 30)]
        s = rvt[(rvt.dwelling == dwelling) & (rvt.row_type != "lga")].set_index("row_type")
        rvt_rows.append({
            "dwelling": DWELLING_LABEL[dwelling], "household": g.household.iloc[0],
            "affordable rent": money(g.affordable_rent.iloc[0]),
            "Victoria median (gap)": f"{money(s.loc['victoria', 'median_rent'])} ({s.loc['victoria', 'gap']:+,.0f})",
            "Metro median (gap)": f"{money(s.loc['metro', 'median_rent'])} ({s.loc['metro', 'gap']:+,.0f})",
            "Regional median (gap)": f"{money(s.loc['non_metro', 'median_rent'])} ({s.loc['non_metro', 'gap']:+,.0f})",
            "LGAs with 30+ leases": len(g),
            "median at or under the affordable rent": int(g.affordable_at_median.sum()),
        })
    rvt_table = pd.DataFrame(rvt_rows)
    h3 = r_lga[(r_lga.dwelling == "3br_house") & (r_lga.lettings >= 30)]
    agree = int((h3.affordable_at_median == (h3.bedroom_affordable_share >= 0.5)).sum())
    affordable_3br = h3[h3.affordable_at_median].sort_values("median_rent")
    affordable_3br_list = ", ".join(f"{r.lga} ({money(r.median_rent)})" for r in affordable_3br.itertuples())

    lines = [
        "# Part 3: affordability",
        "",
        "Generated by `scripts/affordability.py` from the SQL in `sql/05_affordability.sql` (DuckDB) over the "
        "tidy tables. Don't edit by hand.",
        "",
        "## The measure",
        "",
        "Homes Victoria counts a new lease as **affordable** if its rent is no more than 30% of the income of a "
        "lower-income household on Centrelink payments, sized to the number of bedrooms. Table 9 of the "
        f"{latest_q:%B %Y} report gives the households and thresholds (it doesn't show how the threshold is "
        "worked out from the income figure, so the thresholds are used as published):",
        "",
        md(thr_table),
        "",
        "The thresholds move with Centrelink payments, so the share falls when rents outrun those incomes, not "
        "simply when rents rise. Only the latest thresholds are published in the files used here. Every "
        f"comparison is September with September, from {base_q:%B %Y} (the share is seasonal; December quarters "
        "run higher).",
        "",
        "## Revisions",
        "",
        f"The newest quarter of a release gets revised (see the data audit). {latest_q:%B %Y} is the newest "
        "quarter of its own release, so the largest revision seen so far is used as an allowance: a fall only "
        f"counts as clear if it is still bigger than the sampling margin after adding **{pts(allowance)}** to "
        "the latest share.",
        "",
        md(revision.assign(area=revision.area.map(AREA_LABEL), quarter=revision.quarter.dt.strftime("%b %Y"),
                           revision=revision.revision.map(pts))),
        "",
        "## Since 2000",
        "",
        "Share of new leases (all bedroom counts) that are affordable, September quarters. To September 2023 "
        "from the affordability workbook; from September 2024 from the revised series in the later report.",
        "",
        md(trend_table),
        "",
        "## By bedroom count",
        "",
        f"Affordable share (and number) of new leases in the {base_q:%B %Y} and {latest_q:%B %Y} quarters.",
        "",
        md(bed_table),
        "",
        "## By LGA",
        "",
        f"All bedroom counts. {len(ws)} of {n_all} LGAs had at least {growth.MIN_LETTINGS} new leases in both "
        "quarters (counted from the LGA rents workbook, which leaves out leases with no bedroom count, so it "
        "slightly understates the base the shares are calculated on). `± margin` is the 95% sampling margin on "
        f"the change, in points; a **clear fall** is bigger than the margin even with the {pts(allowance)} "
        "revision allowance; a **clear rise** is bigger than the margin.",
        "",
        md(summary_table),
        "",
        "### Biggest falls",
        "",
        md(lga_table(falls)),
        "",
        "### Rises",
        "",
        md(lga_table(rises)),
        "",
        "### By bedroom count",
        "",
        f"The same test for each bedroom count, LGAs with at least {growth.MIN_LETTINGS} leases of that size in "
        "both quarters:",
        "",
        md(bed_counts_table),
        "",
        "## Part 2's fastest-rising regional towns",
        "",
        "Every regional town in the top 10 for rent growth since September 2019 (2-bedroom flats or 3-bedroom "
        "houses), and the affordable share in the LGA it sits in (all bedroom counts).",
        "",
        md(fast_table),
        "",
        f"**{int(fast_lgas.clear_fall.sum())} of the {len(fast_lgas)} LGAs had a clear fall.**"
        + ("" if fast_lgas.well_sampled.all() else
           " " + ", ".join(fast_lgas.loc[~fast_lgas.well_sampled, "lga"]) + f" has fewer than {growth.MIN_LETTINGS} "
           "new leases in a quarter, so it is left out of the LGA rankings above, but its fall is also bigger "
           "than its (wider) margin."),
        "",
        "## Rent growth and the affordable share",
        "",
        f"For the {len(rel)} well-sampled LGAs: the change in the median rent of new leases (single-quarter "
        "medians, all properties) against the change in the affordable share.",
        "",
        md(corr_table),
        "",
        f"The link is weaker in Melbourne partly because there was little left to lose: {len(low_metro)} of the "
        f"{int(rel.metro.sum())} metro LGAs had under 3% of new leases affordable in {base_q:%B %Y}, and none of "
        f"them has moved by more than {100 * low_metro.change.abs().max():.1f} points since.",
        "",
        "<details><summary>Every LGA</summary>",
        "",
        md(rel_table),
        "",
        "</details>",
        "",
        "## Where the affordable leases are",
        "",
        f"Each LGA's part of all affordable new leases in Victoria: {totals['base']:,} in {base_q:%B %Y}, "
        f"{totals['latest']:,} in {latest_q:%B %Y}. The top 2 LGAs held {share(cum['base'][2])} then and "
        f"{share(cum['latest'][2])} now; the top 5, {share(cum['base'][5])} and {share(cum['latest'][5])}; "
        f"the top 10, {share(cum['base'][10])} and {share(cum['latest'][10])}.",
        "",
        md(conc_table),
        "",
        "## Rents against the affordable rent",
        "",
        f"Median weekly rent of new leases in the {latest_q:%B %Y} quarter against the most the matching "
        "household can pay (gap in dollars a week). The LGA count uses LGAs with at least 30 leases of that type "
        "in the quarter.",
        "",
        md(rvt_table),
        "",
        f"3-bedroom houses with a median at or under $450: {affordable_3br_list}. As a check on the join, an LGA's "
        "3-bedroom-house median is at or under the threshold exactly when at least half its 3-bedroom leases are "
        f"affordable in {agree} of {len(h3)} LGAs (the share counts 3-bedroom flats too).",
        "",
        "Full table: [`lga_affordability_change.csv`](lga_affordability_change.csv) (every LGA and bedroom "
        "count, with leases, margin, `well_sampled`, `clear_fall` and `clear_rise`).",
        "",
    ]
    (RESULTS / "AFFORDABILITY.md").write_text("\n".join(lines))
    print(f"wrote results/AFFORDABILITY.md, 1 CSV and 3 charts in {CHARTS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
