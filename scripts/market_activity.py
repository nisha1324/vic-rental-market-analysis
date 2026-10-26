"""Part 4: market activity. Runs sql/*.sql in DuckDB and writes
results/MARKET_ACTIVITY.md, the LGA table as CSV and the charts.

    python scripts/build.py
    python scripts/market_activity.py
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
from scripts.affordability import AREA_COLOR, area_of, pts  # noqa: E402
from scripts.growth import INK, INK_2, MUTED, GRID, SURFACE, md, money, style  # noqa: E402

RESULTS = ROOT / "results"
CHARTS = RESULTS / "charts"

GROUPS = ["Growth areas", "City of Melbourne", "Rest of Melbourne", "Rest of regional Victoria"]
# Categorical slots 1 and 2 (validated as a pair) for the two groups that
# gained leases; the two that lost them are context, in neutral ink, told
# apart by line style and direct labels.
GROUP_STYLE = {"Growth areas": ("#2a78d6", "-"), "City of Melbourne": ("#eb6834", "-"),
               "Rest of Melbourne": (INK_2, "-"), "Rest of regional Victoria": (MUTED, "--")}
EFFECT_COLOR = {"more new leases (volume)": "#2a78d6", "higher affordable share": "#eb6834"}


def pct(x: float) -> str:
    return f"{100 * x:+.1f}%"


def share(x: float) -> str:
    return f"{100 * x:.1f}%"


def spearman(d: pd.DataFrame, x: str, y: str) -> float:
    return d[x].rank().corr(d[y].rank())


def chart_index(gl: pd.DataFrame, path: Path) -> None:
    d = gl[gl.quarter >= pd.Timestamp("2015-09-30")]
    fig, ax = plt.subplots(figsize=(8.6, 5.0), facecolor=SURFACE)
    last = d.quarter.max()
    ends = d[d.quarter == last].set_index("group").index_2019
    # spread the end labels so they don't collide
    order = ends.sort_values(ascending=False)
    label_y, prev = {}, None
    for grp, v in order.items():
        y = v if prev is None else min(v, prev - 4.5)
        label_y[grp], prev = y, y
    for grp in GROUPS:
        color, ls = GROUP_STYLE[grp]
        g = d[d.group == grp]
        ax.plot(g.quarter, g.index_2019, color=color, linestyle=ls, linewidth=2, zorder=3)
        ax.scatter([last], [ends[grp]], s=30, color=color, zorder=4, edgecolors=SURFACE, linewidths=1.5)
        ax.annotate(f"{grp} {ends[grp]:.0f}", (last, label_y[grp]), xytext=(8, 0), textcoords="offset points",
                    va="center", fontsize=8.5, color=INK)
    ax.axhline(100, color=MUTED, linewidth=0.8)
    base = pd.Timestamp("2019-09-30")
    ax.axvline(base, color=MUTED, linewidth=0.8, linestyle=":")
    ax.text(base, d.index_2019.max() + 2, " Sep 2019 = 100", fontsize=8, color=INK_2, va="bottom")
    ax.set_xlim(d.quarter.min() - pd.Timedelta(days=60), last + pd.Timedelta(days=1150))
    ax.set_ylim(min(70, d.index_2019.min() - 5), d.index_2019.max() + 12)
    years = range(2016, last.year + 1, 2)
    ax.set_xticks([pd.Timestamp(f"{y}-09-30") for y in years], [str(y) for y in years])
    style(ax)
    ax.grid(axis="x", visible=False)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_title("New leases signed in the last 12 months, indexed to the 12 months to Sep 2019",
                 loc="left", fontsize=10.5, color=INK, pad=12)
    fig.text(0.01, 0.015, "Growth areas: Cardinia, Casey, Hume, Melton, Mitchell, Whittlesea, Wyndham. "
             "All properties. Source: Homes Victoria Rental Report.", fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def chart_scatter(act: pd.DataFrame, path: Path, labels: list[str]) -> None:
    fig, ax = plt.subplots(figsize=(8.6, 5.6), facecolor=SURFACE)
    for metro, g in act.groupby("metro"):
        ax.scatter(100 * g.approval_rate, 100 * g.lease_growth, s=40, color=AREA_COLOR[area_of(metro)],
                   edgecolors=SURFACE, linewidths=1.5, zorder=3, label=area_of(metro))
    # labels to the left of the dot where two neighbours would collide
    left = {"Surf Coast", "Horsham"}
    for r in act[act.lga.isin(labels)].itertuples():
        name = "City of Melbourne" if r.lga == "Melbourne" else r.lga
        ax.annotate(name, (100 * r.approval_rate, 100 * r.lease_growth), xytext=(-6 if r.lga in left else 6, 3),
                    ha="right" if r.lga in left else "left", textcoords="offset points", fontsize=8, color=INK)
    ax.axhline(0, color=MUTED, linewidth=0.8)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:+.0f}%")
    ax.set_xlabel("New dwellings approved Jul 2018 – Jun 2024, as a share of the LGA's dwellings in 2021",
                  fontsize=9, color=INK_2)
    ax.set_ylabel("Change in new leases a year, 2019 to 2025", fontsize=9, color=INK_2)
    style(ax)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_title("Where more homes were approved, more new leases were signed (one dot per LGA)",
                 loc="left", fontsize=10.5, color=INK, pad=12)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK_2, loc="upper left")
    fig.text(0.01, 0.015, f"LGAs with at least {growth.MIN_LETTINGS} new leases in both September quarters. "
             "Sources: Homes Victoria Rental Report; ABS Building Approvals; ABS Census 2021.",
             fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def chart_decomposition(dec: pd.DataFrame, path: Path) -> None:
    d = dec.sort_values("change_affordable")
    fig, ax = plt.subplots(figsize=(8.6, 4.6), facecolor=SURFACE)
    y = range(len(d))
    vol_c, share_c = EFFECT_COLOR.values()
    for yi, r in zip(y, d.itertuples()):
        # volume first from zero, then the share effect stacked on whichever side it falls
        left_v = 0 if r.volume_effect >= 0 else r.volume_effect
        ax.barh(yi, abs(r.volume_effect), left=left_v, height=0.6, color=vol_c, edgecolor=SURFACE, linewidth=2)
        start = max(r.volume_effect, 0)
        ax.barh(yi, r.share_effect, left=start, height=0.6, color=share_c, edgecolor=SURFACE, linewidth=2)
        ax.text(start + r.share_effect + 12, yi, f"+{r.change_affordable:,.0f}", va="center", fontsize=8.5,
                color=INK)
    ax.set_yticks(list(y), [f"{lga}  " for lga in d.lga], fontsize=9, color=INK)
    ax.axvline(0, color=MUTED, linewidth=0.8)
    ax.set_xlim(min(-60, d.volume_effect.min() - 20), d.change_affordable.max() * 1.12)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")
    style(ax)
    ax.set_xlabel("Change in affordable new leases in the September quarter, 2019 to 2025", fontsize=9,
                  color=INK_2)
    fig.suptitle("Why affordable leases rose: more leases, or a bigger affordable share?",
                 x=0.01, ha="left", fontsize=11, color=INK)
    ax.set_title("LGAs where the affordable share rose clearly (Part 3)", loc="left", fontsize=9,
                 color=INK_2, pad=8)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in EFFECT_COLOR.values()]
    fig.legend(handles, list(EFFECT_COLOR), loc="lower center", ncol=2, frameon=False, fontsize=9,
               bbox_to_anchor=(0.5, 0.04), labelcolor=INK_2)
    fig.text(0.01, 0.012, "The two parts add up to the change. Source: Homes Victoria Rental Report "
             "(affordable lettings).", fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.09, 1, 0.97))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    con = growth.connect(*growth.load_inputs(), **growth.load_affordability(), **growth.load_supply())
    q = lambda sql: growth.query(con, sql)  # noqa: E731
    p = q("select * from activity_periods").iloc[0]
    base_q, latest_q = p.base_q, p.latest_q
    appr = q("select * from lga_approvals order by lga")
    act = q("select * from lga_activity order by lga")
    gl = q("select * from group_leases order by \"group\", quarter")
    totals = q("select * from annual_leases where row_type != 'lga' order by row_type, quarter")
    shares = q("select * from lga_activity_share order by lga")
    dec = q("select * from affordable_decomposition order by lga")

    # The joins to the ABS tables are by name; stop if any LGA is unmatched or short of quarters.
    if appr.dwellings_2021.isna().any() or len(appr) != len(act) or (appr.approval_quarters != 24).any():
        raise SystemExit("ABS approvals or dwellings don't cover every LGA for 24 quarters: "
                         "rerun scripts/download_supply.py and check the names")

    RESULTS.mkdir(exist_ok=True)
    CHARTS.mkdir(exist_ok=True)
    act.to_csv(RESULTS / "lga_activity.csv", index=False, float_format="%.4f")
    ws = act[act.well_sampled].copy()
    chart_index(gl, CHARTS / "lease_volume_index.png")
    chart_scatter(ws, CHARTS / "approvals_vs_lease_growth.png",
                  labels=["Melton", "Mitchell", "Wyndham", "Melbourne", "Casey", "Cardinia", "Hume",
                          "Whittlesea", "Ballarat", "Frankston", "Horsham", "Wellington", "Surf Coast"])
    rises = dec[dec.well_sampled & dec.clear_rise]
    chart_decomposition(rises, CHARTS / "affordable_decomposition.png")

    # --- state / metro / regional ---
    t = totals[totals.quarter.isin([base_q, latest_q])].pivot_table(index="row_type", columns="quarter",
                                                                      values="leases_12m")
    area_label = {"victoria": "Victoria", "metro": "Metro Melbourne", "non_metro": "Regional Victoria"}
    total_table = pd.DataFrame({
        "area": [area_label[a] for a in ("victoria", "metro", "non_metro")],
        f"12 months to {base_q:%b %Y}": [f"{t.loc[a, base_q]:,.0f}" for a in ("victoria", "metro", "non_metro")],
        f"12 months to {latest_q:%b %Y}": [f"{t.loc[a, latest_q]:,.0f}" for a in ("victoria", "metro", "non_metro")],
        "change": [pct(t.loc[a, latest_q] / t.loc[a, base_q] - 1) for a in ("victoria", "metro", "non_metro")],
    })
    vic = totals[totals.row_type == "victoria"].set_index("quarter").leases_12m
    sep = vic[vic.index.month == 9].loc["2015":]
    vic_table = pd.DataFrame({"12 months to": [f"Sep {d.year}" for d in sep.index],
                              "new leases, Victoria": [f"{v:,.0f}" for v in sep]})

    # --- groups ---
    gb = gl[gl.quarter.isin([base_q, latest_q])].pivot_table(index="group", columns="quarter", values="leases_12m")
    ga = act.groupby("group").agg(lgas=("lga", "size"), approvals=("approvals", "sum"),
                                  dwellings=("dwellings_2021", "sum"))
    group_table = pd.DataFrame({
        "group": GROUPS, "LGAs": [int(ga.loc[g, "lgas"]) for g in GROUPS],
        f"new leases, 12 months to {base_q:%b %Y}": [f"{gb.loc[g, base_q]:,.0f}" for g in GROUPS],
        f"12 months to {latest_q:%b %Y}": [f"{gb.loc[g, latest_q]:,.0f}" for g in GROUPS],
        "change": [pct(gb.loc[g, latest_q] / gb.loc[g, base_q] - 1) for g in GROUPS],
        "dwellings approved": [f"{ga.loc[g, 'approvals']:,.0f}" for g in GROUPS],
        "share of approvals": [share(ga.loc[g, "approvals"] / ga.approvals.sum()) for g in GROUPS],
        "approved / 2021 dwellings": [share(ga.loc[g, "approvals"] / ga.loc[g, "dwellings"]) for g in GROUPS],
    })
    peak = gl[gl.group == "City of Melbourne"].set_index("quarter").index_2019
    peak = peak[peak.index.month == 9]

    # --- LGAs ---
    def lga_table(df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({
            "LGA": df.lga, "group": df.group,
            f"12m to {base_q:%b %Y}": df.base_leases_12m.map(lambda v: f"{v:,.0f}"),
            f"12m to {latest_q:%b %Y}": df.latest_leases_12m.map(lambda v: f"{v:,.0f}"),
            "change": [f"{c:+,.0f} ({pct(g)})" for c, g in zip(df.lease_change, df.lease_growth)],
            "approved / 2021 dwellings": df.approval_rate.map(share),
            "rent growth": df.rent_growth.map(pct),
            "affordable share": df.affordable_change.map(pts),
        })

    gains = ws.sort_values(["lease_change", "lga"], ascending=[False, True]).head(10)
    losses = ws.sort_values(["lease_growth", "lga"]).head(10)
    s = shares.set_index("lga")
    falling = act[act.lease_change < 0]
    n_ranked = act.lease_change.notna().sum()
    gain_total = act.loc[act.lease_change > 0, "lease_change"].sum()

    # --- building and leases ---
    corr_rows = []
    pairs = [("approval_rate", "lease_growth", "building rate → change in new leases"),
             ("approval_rate_late", "lease_growth", "same, approvals Jul 2019 – Jun 2025 (check)"),
             ("approval_rate", "rent_growth", "building rate → rent growth"),
             ("lease_growth", "rent_growth", "change in new leases → rent growth"),
             ("approval_rate", "affordable_change", "building rate → change in affordable share"),
             ("lease_growth", "affordable_change", "change in new leases → change in affordable share")]
    for x, y, label in pairs:
        corr_rows.append({"relationship": label,
                          f"all ({len(ws)})": f"{spearman(ws, x, y):.2f}",
                          f"Metro Melbourne ({int(ws.metro.sum())})": f"{spearman(ws[ws.metro], x, y):.2f}",
                          f"Regional Victoria ({int((~ws.metro).sum())})": f"{spearman(ws[~ws.metro], x, y):.2f}"})
    corr_table = pd.DataFrame(corr_rows)
    top_rate = ws.sort_values("approval_rate", ascending=False).head(10)
    rate_table = pd.DataFrame({
        "LGA": top_rate.lga, "group": top_rate.group,
        "dwellings approved": top_rate.approvals.map(lambda v: f"{v:,.0f}"),
        "2021 dwellings": top_rate.dwellings_2021.map(lambda v: f"{v:,.0f}"),
        "approved / 2021 dwellings": top_rate.approval_rate.map(share),
        "change in new leases": top_rate.lease_growth.map(pct),
        "rent growth": top_rate.rent_growth.map(pct),
    })
    # halves of the well-sampled LGAs by building rate
    ws["building"] = (ws.approval_rate >= ws.approval_rate.median()).map({True: "higher half", False: "lower half"})
    halves = ws.groupby("building").agg(lgas=("lga", "size"), rate=("approval_rate", "median"),
                                        leases=("lease_growth", "median"), rent=("rent_growth", "median"),
                                        afford=("affordable_change", "median"))
    halves_table = pd.DataFrame({
        "building rate": halves.index, "LGAs": halves.lgas,
        "median approved / 2021 dwellings": halves.rate.map(share),
        "median change in new leases": halves.leases.map(pct),
        "median rent growth": halves.rent.map(pct),
        "median change in affordable share": halves.afford.map(pts),
    })
    stalled = act[(act.group == "Growth areas") & (act.lease_growth < 0.05)].sort_values("lga")
    stalled_text = "; ".join(
        f"{r.lga} approved {share(r.approval_rate)} of its 2021 dwellings, but new leases changed "
        f"{pct(r.lease_growth)} and rents rose {pct(r.rent_growth)}" for r in stalled.itertuples())
    mel = act.set_index("lga").loc["Melbourne"]
    similar = ws[(ws.lga != "Melbourne") & ((ws.approval_rate - mel.approval_rate).abs() <= 0.03)]

    # --- decomposition ---
    r = rises.sort_values("change_affordable", ascending=False)

    def part(v: float, row) -> str:
        # a percentage split only means something when both parts push the same way
        both = row.volume_effect >= 0 and row.share_effect >= 0
        return f"{v:+,.0f} ({share(v / row.change_affordable)})" if both else f"{v:+,.0f}"
    dec_table = pd.DataFrame({
        "LGA": r.lga, "area": r.metro.map(area_of),
        "affordable leases (Sep qtr)": [f"{a:,.0f} → {b:,.0f} ({b - a:+,.0f})" for a, b in zip(r.a0, r.a1)],
        "new leases (Sep qtr)": [f"{a:,.0f} → {b:,.0f}" for a, b in zip(r.n0, r.n1)],
        "affordable share": [f"{share(a)} → {share(b)}" for a, b in zip(r.s0, r.s1)],
        "volume effect": [part(row.volume_effect, row) for row in r.itertuples()],
        "share effect": [part(row.share_effect, row) for row in r.itertuples()],
    })
    named = r.set_index("lga")
    # the recovered denominator against the rents workbook's lease count
    leases = q("select lga, base_leases, latest_leases from lga_affordability_change where dwelling = 'all'")
    den = dec[dec.well_sampled].merge(leases, on="lga")
    den_ratio = pd.concat([den.n0 / den.base_leases, den.n1 / den.latest_leases])
    den_ratio.index = list(den.lga) * 2
    odd = den_ratio[den_ratio > 1.2]

    lines = [
        "# Part 4: market activity",
        "",
        "Generated by `scripts/market_activity.py` from the SQL in `sql/06_market_activity.sql` (DuckDB) over the "
        "tidy tables and the ABS supply data in `data/reference/`. Don't edit by hand.",
        "",
        "## The measure",
        "",
        "A new lease is a rental bond lodged with the Residential Tenancies Bond Authority. The count measures "
        "new tenancies: newly built homes let for the first time, and existing rentals changing tenant. Volumes "
        f"are 12-month sums (the four quarters to each date), compared for the 12 months to {base_q:%B %Y} and to "
        f"{latest_q:%B %Y}. To tell new homes from turnover, new dwelling approvals from the ABS are summed per LGA "
        f"from {p.approvals_from - pd.DateOffset(months=2):%B %Y} to {p.approvals_to:%B %Y} "
        "(so most were built and could be let by the latest quarter) and divided by the LGA's private dwellings "
        "in the 2021 Census: the **building rate**. Approvals are not completions; some are never built.",
        "",
        "## Victoria as a whole",
        "",
        md(total_table),
        "",
        "Over the longer run (12 months to each September):",
        "",
        md(vic_table),
        "",
        "## By group",
        "",
        "Melbourne's seven growth-area councils (Victorian Planning Authority), the City of Melbourne, the rest of "
        "Melbourne and the rest of regional Victoria. Mitchell is regional in the rental report but is a growth "
        "area, so it is grouped with them. Suppressed LGA cells count as 0 in the group sums, so they can be a "
        "few leases below the official totals.",
        "",
        md(group_table),
        "",
        "City of Melbourne, indexed to the 12 months to September 2019 = 100: "
        + ", ".join(f"{d.year} {v:.0f}" for d, v in peak.loc["2019":].items()) + ".",
        "",
        "## By LGA",
        "",
        f"{len(falling)} of the {n_ranked} LGAs with a full count in both periods signed fewer new leases in the "
        f"12 months to {latest_q:%B %Y} than in the 12 months to {base_q:%B %Y}. Of the {gain_total:,.0f} extra "
        f"leases in the LGAs that grew, the City of Melbourne accounts for {share(s.loc['Melbourne', 'share_of_gains'])} "
        f"and the growth areas for "
        f"{share(shares.loc[shares.group == 'Growth areas', 'lease_change'].clip(lower=0).sum() / gain_total)}. "
        f"Tables below: the {len(ws)} LGAs with at least {growth.MIN_LETTINGS} new leases in both September "
        "quarters (as in Part 3). Rent growth is the change in the median rent of new leases, September quarter "
        "2019 to 2025 (all properties); the affordable share change is from Part 3.",
        "",
        "### Most extra new leases",
        "",
        md(lga_table(gains)),
        "",
        "### Biggest falls (%)",
        "",
        md(lga_table(losses)),
        "",
        "## Building and new leases",
        "",
        "Rank correlations (Spearman) across the well-sampled LGAs. Correlation isn't cause: places that build a "
        "lot also differ in other ways (land price, distance from the city, who moves there).",
        "",
        md(corr_table),
        "",
        "Split into halves by building rate:",
        "",
        md(halves_table),
        "",
        "### Highest building rates",
        "",
        md(rate_table),
        "",
        f"**Not every growth area turned building into rentals.** {stalled_text}. The approvals data can't say "
        "whether those homes were bought by owner-occupiers, are still being built, or are let in ways the bond "
        "count misses.",
        "",
        f"**The City of Melbourne is the outlier the other way:** new leases {pct(mel.lease_growth)} on a building "
        f"rate of {share(mel.approval_rate)}. The {len(similar)} other well-sampled LGAs with a building rate within "
        f"3 points of it had a median change of {pct(similar.lease_growth.median())} (range "
        f"{pct(similar.lease_growth.min())} to {pct(similar.lease_growth.max())}); only "
        + ", ".join(f"{x.lga} ({pct(x.lease_growth)})" for x in similar[similar.lease_growth >= mel.lease_growth].itertuples())
        + " grew as fast. So the city's extra leases likely include more tenants moving in and out of existing "
        "apartments, not only new ones; the bond data can't say who they are.",
        "",
        "## Why affordable leases rose where they did",
        "",
        "Part 3 found a clear rise in the affordable share in a few LGAs. The change in the number of affordable "
        "new leases (share × leases, September quarters) splits exactly into a **volume effect** (more new leases "
        "at the average share) and a **share effect** (a higher share of the average number of leases). The "
        "share's own denominator is recovered as affordable leases ÷ share (only where the share is at least 5% "
        "at both ends, as the share is rounded to 0.1%). Across the well-sampled LGAs it is a median "
        f"{pct(den_ratio.drop(odd.index).median() - 1)} above the rents workbook's lease count (which leaves out "
        "leases with no bedroom count)"
        + ("" if odd.empty else
           f", except {', '.join(sorted(set(odd.index)))} at {odd.min():.1f}–{odd.max():.1f} times, a gap that has "
           "been there since 2000, so the two workbooks count that LGA's leases differently. The split below uses "
           "the affordability workbook's own figures throughout, so it isn't affected") + ".",
        "",
        md(dec_table),
        "",
        f"**Melton:** {share(named.loc['Melton', 'volume_effect'] / named.loc['Melton', 'change_affordable'])} of "
        f"the rise came from more leases. **Wyndham:** "
        f"{share(named.loc['Wyndham', 'volume_effect'] / named.loc['Wyndham', 'change_affordable'])}. "
        f"**Mitchell:** {share(named.loc['Mitchell', 'volume_effect'] / named.loc['Mitchell', 'change_affordable'])}. "
        f"**Ballarat:** none ({named.loc['Ballarat', 'volume_effect']:+,.0f}); its new leases were flat, so all of "
        "its rise is a higher share. The share effect means rents there rose more slowly than the affordability "
        "thresholds, which move with Centrelink payments (the 2019 thresholds aren't in these files, so that "
        "can't be split further).",
        "",
        "Full table: [`lga_activity.csv`](lga_activity.csv) (every LGA: leases in both periods, approvals in both "
        "windows, 2021 dwellings, building rates, rent growth, affordable share change, `well_sampled`).",
        "",
    ]
    (RESULTS / "MARKET_ACTIVITY.md").write_text("\n".join(lines))
    print(f"wrote results/MARKET_ACTIVITY.md, 1 CSV and 3 charts in {CHARTS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
