"""Part 2: where rents are rising fastest. Runs sql/*.sql in DuckDB and writes
results/GROWTH.md, the growth tables as CSV and the charts.

    python scripts/build.py
    python scripts/growth.py
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

RESULTS = ROOT / "results"
CHARTS = RESULTS / "charts"

WINDOW_LABEL = {"1y": "1 year", "5y": "5 years", "since_2019": "since Sep 2019"}
DWELLING_LABEL = {"1br_flat": "1-bed flat", "2br_flat": "2-bed flat", "3br_flat": "3-bed flat",
                  "2br_house": "2-bed house", "3br_house": "3-bed house", "4br_house": "4-bed house",
                  "all": "all properties"}
AREA_LABEL = {"victoria": "Victoria", "metro": "Metro Melbourne", "non_metro": "Regional Victoria"}

# Categorical slots 1-3 of the reference palette (validated all-pairs; slot 3
# is below 3:1 contrast, so every chart is direct-labelled and has a table in
# GROWTH.md). Colour follows the band, never the rank.
BAND_COLOR = {"Inner Melbourne": "#2a78d6", "Rest of Melbourne": "#eb6834", "Regional Victoria": "#1baf7a"}
INK, INK_2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1"
SURFACE = "#fcfcfb"


def pct(x: float, sign: bool = True) -> str:
    return f"{100 * x:+.1f}%" if sign else f"{100 * x:.1f}%"


def money(x: float) -> str:
    return f"${x:,.0f}"


def md(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False)


def style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=INK_2, labelsize=9, length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def cpi_change(con, table: str, col: str, start: str, end: str) -> float:
    r = growth.query(con, f"select max({col}) filter (where quarter = date '{end}') / "
                          f"max({col}) filter (where quarter = date '{start}') - 1 as c from {table}")
    return float(r["c"].iloc[0])


def bar_chart(ax, labels, values, colors, cpi: float, title: str) -> None:
    y = range(len(labels))[::-1]
    ax.barh(list(y), [100 * v for v in values], color=colors, height=0.62, edgecolor=SURFACE, linewidth=2)
    for yi, v in zip(y, values):
        # surface-coloured box so a label never sits on top of the CPI line
        ax.text(100 * v + 0.8, yi, pct(v), va="center", fontsize=8.5, color=INK, zorder=4,
                bbox={"facecolor": SURFACE, "edgecolor": "none", "pad": 1.0})
    ax.set_yticks(list(y), labels, fontsize=9, color=INK)
    ax.axvline(100 * cpi, color=INK_2, linestyle=(0, (4, 3)), linewidth=1.2)
    ax.text(100 * cpi + 0.6, len(labels) - 0.35, f"Melbourne CPI {pct(cpi)}", fontsize=8,
            color=INK_2, va="bottom")
    ax.set_xlim(0, 100 * max(values) * 1.16)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.set_title(title, loc="left", fontsize=10.5, color=INK, pad=12)
    style(ax)


def legend(fig, bands, y: float) -> None:
    handles = [plt.Rectangle((0, 0), 1, 1, color=BAND_COLOR[b]) for b in bands]
    fig.legend(handles, bands, loc="lower center", ncol=len(bands), frameon=False, fontsize=9,
               bbox_to_anchor=(0.5, y), labelcolor=INK_2)


def chart_regions(regions: pd.DataFrame, cpi: float, path: Path) -> None:
    d = regions[(regions.dwelling == "all") & (regions.window == "since_2019")].sort_values("growth", ascending=False)
    fig, ax = plt.subplots(figsize=(8.6, 5.4), facecolor=SURFACE)
    bar_chart(ax, d["region"], d["growth"], [BAND_COLOR[b] for b in d["band"]], cpi,
              "Median weekly rent of new leases, all properties: change from Sep 2019 to Sep 2025")
    fig.text(0.01, 0.015, "Bars past the dashed line rose faster than prices in general. 12-month medians "
             "from the Group Total rows. Source: Homes Victoria Rental Report; ABS CPI.",
             fontsize=7.5, color=MUTED)
    legend(fig, list(BAND_COLOR), 0.045)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def chart_index(index: pd.DataFrame, regions: pd.DataFrame, path: Path) -> None:
    d = index[index.dwelling == "all"]
    since = regions[(regions.dwelling == "all") & (regions.window == "since_2019")].set_index("region")
    fastest, slowest = since["growth"].idxmax(), since["growth"].idxmin()
    fig, ax = plt.subplots(figsize=(8.6, 5.0), facecolor=SURFACE)
    for region, g in d.groupby("region"):
        if region not in (fastest, slowest):
            ax.plot(g["quarter"], g["rent_index"], color="#c9c8c2", linewidth=1.1, zorder=1)
    cpi = d.drop_duplicates("quarter").sort_values("quarter")
    ax.plot(cpi["quarter"], cpi["cpi_index"], color=INK_2, linestyle=(0, (4, 3)), linewidth=1.6, zorder=2)
    for region in (fastest, slowest):
        g = d[d.region == region].sort_values("quarter")
        ax.plot(g["quarter"], g["rent_index"], color=BAND_COLOR[since.loc[region, "band"]], linewidth=2.2, zorder=3)
    last = d["quarter"].max()
    ends = [(fastest, d[(d.region == fastest) & (d.quarter == last)]["rent_index"].iloc[0], INK),
            (slowest, d[(d.region == slowest) & (d.quarter == last)]["rent_index"].iloc[0], INK),
            ("Melbourne CPI", cpi["cpi_index"].iloc[-1], INK_2)]
    for name, v, color in ends:
        ax.annotate(f"{name} {v:.0f}", (last, v), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=8.5, color=color)
    ax.text(pd.Timestamp("2020-01-31"), 141, "grey: the other 11 regions", fontsize=8, color=MUTED)
    ax.axhline(100, color=MUTED, linewidth=0.8)
    ax.set_xlim(d["quarter"].min(), last + pd.Timedelta(days=560))
    ax.set_xticks([pd.Timestamp(f"{y}-01-01") for y in range(2020, last.year + 1)],
                  [str(y) for y in range(2020, last.year + 1)])
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.grid(axis="x", visible=False)
    ax.set_title("Rents indexed to Sep 2019 = 100 (12-month median, all properties), with CPI on the same basis",
                 loc="left", fontsize=10.5, color=INK, pad=12)
    style(ax)
    ax.grid(axis="x", visible=False)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    fig.text(0.01, 0.015, "Fastest and slowest of the 13 regions highlighted. Source: Homes Victoria Rental "
             "Report; ABS CPI (4-quarter average, to match the 12-month medians).", fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def chart_suburbs(ranking: pd.DataFrame, cpi: float, path: Path, top: int = 10, bottom: int = 5) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 6.4), facecolor=SURFACE)
    for ax, dwelling in zip(axes, growth.HEADLINE_DWELLINGS):
        d = ranking[(ranking.dwelling == dwelling) & (ranking.window == "since_2019")].sort_values(
            ["growth", "suburb"], ascending=[False, True])
        d = pd.concat([d.head(top), d.tail(bottom)])
        labels = [f"{s}  " for s in d["suburb"]]
        bar_chart(ax, labels, d["growth"], [BAND_COLOR[b] for b in d["band"]], cpi,
                  f"{DWELLING_LABEL[dwelling].capitalize()}s: top {top} and bottom {bottom} of "
                  f"{int(d['ranked_suburbs'].iloc[0])} suburbs")
        ax.axhline(bottom - 0.5, color=MUTED, linewidth=0.8, linestyle=":")
    fig.suptitle("Change in median weekly rent of new leases, Sep 2019 to Sep 2025", x=0.01, ha="left",
                 fontsize=12, color=INK)
    fig.text(0.01, 0.015, f"Ranked only where both years have at least {growth.MIN_LETTINGS} new leases. "
             "Source: Homes Victoria Rental Report (moving annual rents by suburb); ABS CPI.",
             fontsize=7.5, color=MUTED)
    legend(fig, list(BAND_COLOR), 0.04)
    fig.tight_layout(rect=(0, 0.07, 1, 0.97))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def band(region: str, metro: bool) -> str:
    return "Inner Melbourne" if region == "Inner Melbourne" else ("Rest of Melbourne" if metro else "Regional Victoria")


def main() -> None:
    con = growth.connect(*growth.load_inputs())
    q = lambda sql: growth.query(con, sql)  # noqa: E731
    windows = q("select * from windows order by ord")
    end = windows["end_q"].iloc[0]
    state = q("select * from state_growth")
    regions = q("select * from region_growth")
    sub = q("select * from suburb_growth")
    ranking = q("select * from suburb_ranking")
    ranking["band"] = [band(r, m) for r, m in zip(ranking["region"], ranking["metro"])]
    index = q("select * from region_index order by dwelling, region, quarter")
    lows = q("select * from region_low_point")
    sens = growth.floor_sensitivity(con)

    cpi_ma = {w.window: cpi_change(con, "cpi_annual", "cpi_annual", w.start_q.date(), w.end_q.date())
              for w in windows.itertuples()}
    cpi_q = {w.window: cpi_change(con, "cpi", "cpi", w.start_q.date(), w.end_q.date())
             for w in windows.itertuples()}

    RESULTS.mkdir(exist_ok=True)
    CHARTS.mkdir(exist_ok=True)
    order = {w: i for i, w in enumerate(WINDOW_LABEL)}
    sub.sort_values(["dwelling", "window", "suburb"], key=lambda s: s.map(order) if s.name == "window" else s) \
       .to_csv(RESULTS / "suburb_growth.csv", index=False, date_format="%Y-%m-%d", float_format="%.4f")
    regions.sort_values(["dwelling", "window", "region"], key=lambda s: s.map(order) if s.name == "window" else s) \
           .to_csv(RESULTS / "region_growth.csv", index=False, float_format="%.4f")
    chart_regions(regions, cpi_ma["since_2019"], CHARTS / "region_growth_since_2019.png")
    chart_index(index, regions, CHARTS / "region_index.png")
    chart_suburbs(ranking, cpi_ma["since_2019"], CHARTS / "suburb_growth_since_2019.png")

    # --- tables for the report ---
    win_table = pd.DataFrame({
        "window": [WINDOW_LABEL[w] for w in windows["window"]],
        "from": windows["start_q"].dt.strftime("%b %Y"),
        "to": windows["end_q"].dt.strftime("%b %Y"),
        "Melbourne CPI (4-quarter avg)": [pct(cpi_ma[w]) for w in windows["window"]],
        "Melbourne CPI (quarter)": [pct(cpi_q[w]) for w in windows["window"]],
    })

    st = state[state.dwelling.isin(["all", *growth.HEADLINE_DWELLINGS])].copy()
    st["key"] = st["dwelling"].map({d: i for i, d in enumerate(["all", *growth.HEADLINE_DWELLINGS])})
    st["akey"] = st["area"].map({a: i for i, a in enumerate(AREA_LABEL)})
    st = st.sort_values(["key", "akey", "window"], key=lambda s: s.map(order) if s.name == "window" else s)
    state_table = pd.DataFrame({
        "dwelling": st["dwelling"].map(DWELLING_LABEL),
        "area": st["area"].map(AREA_LABEL),
        "window": st["window"].map(WINDOW_LABEL),
        "from": st["start_rent"].map(money),
        "to": st["end_rent"].map(money),
        "growth": st["growth"].map(pct),
        "per year": st["growth_pa"].map(pct),
        "real growth": st["real_growth"].map(pct),
    })

    wide = regions.pivot_table(index=["region", "band"], columns=["dwelling", "window"], values=["growth", "real_growth"])
    all_since = regions[(regions.dwelling == "all") & (regions.window == "since_2019")].sort_values("growth", ascending=False)
    region_table = pd.DataFrame([{
        "region": r.region,
        "band": r.band,
        "Sep 2019 → Sep 2025": f"{money(r.start_rent)} → {money(r.end_rent)}",
        "since Sep 2019": pct(r.growth),
        "real since 2019": pct(r.real_growth),
        "5 years": pct(wide.loc[(r.region, r.band), ("growth", "all", "5y")]),
        "1 year": pct(wide.loc[(r.region, r.band), ("growth", "all", "1y")]),
        "real 1 year": pct(wide.loc[(r.region, r.band), ("real_growth", "all", "1y")]),
        "2-bed flat since 2019": pct(wide.loc[(r.region, r.band), ("growth", "2br_flat", "since_2019")]),
        "3-bed house since 2019": pct(wide.loc[(r.region, r.band), ("growth", "3br_house", "since_2019")]),
    } for r in all_since.itertuples()])

    band_rows = []
    for b in BAND_COLOR:
        g = all_since[all_since.band == b]
        band_rows.append({"band": b, "regions": len(g),
                          "since Sep 2019 (range)": f"{pct(g.growth.min())} to {pct(g.growth.max())}",
                          "real since 2019 (range)": f"{pct(g.real_growth.min())} to {pct(g.real_growth.max())}"})
    band_table = pd.DataFrame(band_rows)

    dips = lows[(lows.low_vs_2019 < 0) & lows.dwelling.isin(["all", "1br_flat", "2br_flat"])].sort_values("low_vs_2019")
    dip_table = pd.DataFrame({
        "region": dips["region"],
        "dwelling": dips["dwelling"].map(DWELLING_LABEL),
        "low vs Sep 2019": dips["low_vs_2019"].map(lambda v: f"{v:+.1f}%"),
        "low quarter": dips["low_quarter"].dt.strftime("%b %Y"),
        "back to Sep 2019 level": dips["back_above_2019"].dt.strftime("%b %Y").fillna("not yet"),
    })
    no_dip = sorted(set(lows.loc[(lows.dwelling == "all") & (lows.low_vs_2019 >= 0), "region"]))

    def rank_table(dwelling: str, window: str, top: int = 10, bottom: int = 5) -> pd.DataFrame:
        d = ranking[(ranking.dwelling == dwelling) & (ranking.window == window)].sort_values(
            ["growth", "suburb"], ascending=[False, True])
        d = pd.concat([d.head(top), d.tail(bottom)])
        return pd.DataFrame({
            "rank": d["rank_fastest"].astype(int),
            "suburb": d["suburb"], "region": d["region"],
            "from": d["start_rent"].map(money), "to": d["end_rent"].map(money),
            "leases (from / to)": [f"{a:,} / {b:,}" for a, b in zip(d["start_lettings"], d["end_lettings"])],
            "growth": d["growth"].map(pct), "real growth": d["real_growth"].map(pct),
        })

    real_fall = (ranking.assign(fell=ranking["real_growth"] < 0)
                 .groupby(["dwelling", "window"])
                 .agg(ranked=("suburb", "size"), real_fall=("fell", "sum"), median_growth=("growth", "median"))
                 .reset_index())
    real_fall = real_fall[real_fall.dwelling.isin(["all", *growth.HEADLINE_DWELLINGS])]
    real_fall = real_fall.sort_values(["dwelling", "window"], key=lambda s: s.map(order) if s.name == "window" else s)
    real_table = pd.DataFrame({
        "dwelling": real_fall["dwelling"].map(DWELLING_LABEL),
        "window": real_fall["window"].map(WINDOW_LABEL),
        "suburbs ranked": real_fall["ranked"],
        "median suburb growth": real_fall["median_growth"].map(pct),
        "real rent fell": [f"{int(f)} ({100 * f / n:.0f}%)" for f, n in zip(real_fall["real_fall"], real_fall["ranked"])],
    })

    thirds = q("select * from growth_by_start_rent")
    thirds = thirds[thirds.dwelling.isin(growth.HEADLINE_DWELLINGS)].sort_values(
        ["dwelling", "window", "rent_third"], key=lambda s: s.map(order) if s.name == "window" else s)
    thirds_table = pd.DataFrame({
        "dwelling": thirds["dwelling"].map(DWELLING_LABEL),
        "window": thirds["window"].map(WINDOW_LABEL),
        "third by starting rent": thirds["rent_third"].map({1: "cheapest", 2: "middle", 3: "dearest"}),
        "starting rent": [f"{money(a)}–{money(b)}" for a, b in zip(thirds.start_rent_from, thirds.start_rent_to)],
        "suburbs": thirds["suburbs"],
        "of which regional": thirds["regional_suburbs"],
        "median growth": thirds["median_growth"].map(pct),
    })

    coverage = (sub.groupby(["dwelling", "window"]).agg(published=("suburb", "size"), ranked=("well_sampled", "sum"))
                .reset_index().query("window == 'since_2019'"))
    coverage_table = pd.DataFrame({"dwelling": coverage["dwelling"].map(DWELLING_LABEL),
                                   "suburbs with both medians": coverage["published"],
                                   f"with {growth.MIN_LETTINGS}+ leases at both ends": coverage["ranked"].astype(int)})

    sens_table = sens.assign(dwelling=sens["dwelling"].map(DWELLING_LABEL)).rename(columns={
        "floor": "lease floor", "suburbs": "suburbs ranked",
        "top_kept": f"of the top 10 at {growth.MIN_LETTINGS}, still top 10",
        "left_below_floor": "left: too few leases", "left_overtaken": "left: overtaken",
        "top_regional": "regional suburbs in the top 10",
        "bottom_inner": "Inner Melbourne suburbs in the bottom 10"}).drop(columns=["top_base", "bottom_size"])

    one_year = ranking[(ranking.window == "1y") & ranking.dwelling.isin(growth.HEADLINE_DWELLINGS)]
    flat_1y = one_year[one_year.growth == 0].groupby("dwelling").size()
    ties = one_year.groupby(["dwelling", "growth"]).size().groupby("dwelling").max()
    recent = sub[sub.window == "1y"]
    round5 = float(pd.concat([recent.start_rent, recent.end_rent]).mod(5).eq(0).mean())

    lines = [
        "# Part 2: where rents are rising fastest",
        "",
        "Generated by `scripts/growth.py` from the SQL in `sql/` (DuckDB) over the tidy tables and the "
        "ABS Melbourne CPI. Don't edit by hand.",
        "",
        "## Windows and inflation",
        "",
        f"Every window ends in {end:%B %Y}, the latest quarter. Real growth deflates rents by Melbourne CPI: "
        "the 12-month suburb and region medians by the CPI averaged over the same four quarters, the "
        "single-quarter state medians by that quarter's CPI. The 5-year window starts in September 2020, "
        "during the COVID dip in inner Melbourne, so it flatters the areas that fell then; *since Sep 2019* "
        "compares with the last full pre-pandemic year.",
        "",
        md(win_table),
        "",
        "## State-wide (quarterly LGA workbook)",
        "",
        "Median weekly rent of new leases signed in the September quarter, so September is compared with September.",
        "",
        md(state_table),
        "",
        "## By region (Group Total rows, all properties unless stated)",
        "",
        md(region_table),
        "",
        "Grouped into three bands:",
        "",
        md(band_table),
        "",
        "## The COVID dip",
        "",
        "Lowest 12-month median between Sep 2019 and now, relative to Sep 2019, for regions where rents fell "
        f"below their Sep 2019 level (all properties, 1-bed and 2-bed flats). For all properties, "
        f"{len(no_dip)} of 13 regions never fell below Sep 2019: {', '.join(no_dip)}.",
        "",
        md(dip_table),
        "",
        "## By suburb",
        "",
        f"Ranked only where the suburb has at least **{growth.MIN_LETTINGS} new leases in both** the start and "
        "end year (see the audit: below that, 12-month medians jump around). Rankings use 2-bedroom flats and "
        "3-bedroom houses, the two types the Rental Report itself highlights and the two with the most suburbs "
        "above the floor. Coverage since Sep 2019:",
        "",
        md(coverage_table),
        "",
    ]
    for dwelling in growth.HEADLINE_DWELLINGS:
        for window in ("since_2019", "1y"):
            lines += [f"### {DWELLING_LABEL[dwelling].capitalize()}s, {WINDOW_LABEL[window]}: top 10 and bottom 5", "",
                      md(rank_table(dwelling, window)), ""]
    lines += [
        "Ties share a rank. Medians are published in whole dollars and "
        f"{100 * round5:.0f}% of the suburb medians in the 1-year window are multiples of $5, so 1-year "
        "changes are coarse. Over the last year, "
        + "; ".join(f"{DWELLING_LABEL[d]}s: no change (0.0%) in {int(flat_1y.get(d, 0))} of "
                    f"{int((one_year.dwelling == d).sum())} ranked suburbs, and up to {int(ties[d])} suburbs "
                    "share one value"
                    for d in growth.HEADLINE_DWELLINGS)
        + ". Read the 1-year ranks as bands, not exact places.",
        "",
        "## Cheapest vs dearest suburbs",
        "",
        "Ranked suburbs split into equal thirds by their rent at the start of the window (ties at a boundary "
        "are split alphabetically). The cheapest third is mostly regional, so this partly restates the "
        "regional pattern above.",
        "",
        md(thirds_table),
        "",
        "## Real growth: where rents fell behind inflation",
        "",
        md(real_table),
        "",
        "## Does the lease floor drive the ranking?",
        "",
        "Top-10 fastest-rising suburbs since Sep 2019 at three floors, compared with the default list "
        f"({growth.MIN_LETTINGS}). A suburb leaves the list either because it has too few leases to clear a "
        "higher floor, or because a suburb a lower floor lets in overtakes it.",
        "",
        md(sens_table),
        "",
        "Full tables: [`suburb_growth.csv`](suburb_growth.csv) (every suburb, dwelling type and window, with "
        "`well_sampled`) and [`region_growth.csv`](region_growth.csv).",
        "",
    ]
    (RESULTS / "GROWTH.md").write_text("\n".join(lines))
    print(f"wrote results/GROWTH.md, 2 CSVs and 3 charts in {CHARTS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
