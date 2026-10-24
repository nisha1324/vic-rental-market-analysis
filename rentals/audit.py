"""Checks on the parsed tables: coverage, reconciliation against the report's
own published figures, internal totals and plausibility.

Each check returns plain data (DataFrames / dicts) so tests can assert on it
and scripts/audit.py can render it as Markdown.
"""
from __future__ import annotations

import pandas as pd

from rentals import parse

# A 12-month moving median shouldn't swing much from one quarter to the next
# in a suburb with plenty of leases. Bigger moves are listed for a look.
JUMP_THRESHOLD = 0.25
JUMP_MIN_LETTINGS = 100


def coverage(df: pd.DataFrame, area_col: str, value_col: str, area_types: tuple[str, ...]) -> pd.DataFrame:
    """One row per dwelling type: areas, quarter range, gaps, missing values."""
    areas = df[df["row_type"].isin(area_types)]
    rows = []
    for dwelling, g in areas.groupby("dwelling", sort=False):
        quarters = pd.DatetimeIndex(sorted(g["quarter"].unique()))
        expected = pd.date_range(quarters.min(), quarters.max(), freq="QE")
        latest = g[g["quarter"] == quarters.max()]
        rows.append({
            "dwelling": dwelling,
            "areas": g[area_col].nunique(),
            "first_quarter": quarters.min().strftime("%b %Y"),
            "last_quarter": quarters.max().strftime("%b %Y"),
            "quarters": len(quarters),
            "missing_quarters": len(expected.difference(quarters)),
            "cells": len(g),
            "missing_pct": round(100 * g[value_col].isna().mean(), 1),
            "areas_with_value_latest": int(latest[value_col].notna().sum()),
        })
    return pd.DataFrame(rows)


def reconcile_table4(suburbs: pd.DataFrame, table4: pd.DataFrame) -> pd.DataFrame:
    """Compare each Table 4 entry with the parsed median for the same suburb,
    dwelling type and latest quarter. Adds `matches` (same value) and
    `rank_ok`: a 'highest' entry is at least as high as every suburb not
    listed on that side of its group (and the reverse for 'lowest')."""
    latest = suburbs[(suburbs["row_type"] == "suburb") & (suburbs["quarter"] == suburbs["quarter"].max())]
    merged = table4.merge(latest[["dwelling", "suburb", "metro", "median_rent"]],
                          on=["dwelling", "suburb", "metro"], how="left")
    merged["matches"] = merged["published_median"] == merged["median_rent"]

    rank_ok = []
    for r in merged.itertuples():
        listed = set(table4[(table4.dwelling == r.dwelling) & (table4.metro == r.metro)
                            & (table4.side == r.side)]["suburb"])
        others = latest[(latest.dwelling == r.dwelling) & (latest.metro == r.metro)
                        & ~latest.suburb.isin(listed)]["median_rent"].dropna()
        if r.side == "highest":
            rank_ok.append(bool((others <= r.published_median).all()))
        else:
            rank_ok.append(bool((others >= r.published_median).all()))
    merged["rank_ok"] = rank_ok
    return merged


def group_totals(suburbs: pd.DataFrame) -> dict:
    """Group Total lettings vs the sum of the published suburbs in each region.

    Expected: the total is never below the sum, and any gap comes with at
    least one suppressed suburb in that region and quarter (its leases count
    towards the total but its own figure isn't published)."""
    key = ["dwelling", "region", "quarter"]
    sub = suburbs[suburbs["row_type"] == "suburb"]
    summed = sub.groupby(key).agg(published=("lettings", "sum"),
                                  suppressed=("lettings", lambda s: int(s.isna().sum())))
    total = suburbs[suburbs["row_type"] == "group_total"].set_index(key)["lettings"].rename("group_total")
    j = summed.join(total, how="inner").dropna(subset=["group_total"])
    gap = j["group_total"] - j["published"]
    return {
        "compared": len(j),
        "equal": int((gap == 0).sum()),
        "total_below_sum": int((gap < 0).sum()),
        "gap_with_suppressed_suburb": int(((gap > 0) & (j["suppressed"] > 0)).sum()),
        "gap_without_suppressed_suburb": int(((gap > 0) & (j["suppressed"] == 0)).sum()),
        "largest_gap_share": float((gap / j["group_total"]).max()),
    }


def lga_totals(lgas: pd.DataFrame) -> dict:
    """The Victoria row vs the regional Group Totals, the published LGAs and
    Metro + Non-Metro. As with suburbs, suppressed LGAs count towards the
    totals, so Victoria can exceed the sum of the published LGAs."""
    key = ["dwelling", "quarter"]
    vic = lgas[lgas["row_type"] == "victoria"].set_index(key)["lettings"]
    published = lgas[lgas["row_type"] == "lga"].groupby(key).agg(
        published=("lettings", "sum"), suppressed=("lettings", lambda s: int(s.isna().sum())))
    published = published.reindex(vic.index)
    groups = lgas[lgas["row_type"] == "group_total"].groupby(key)["lettings"].sum().reindex(vic.index)
    metro = lgas[lgas["row_type"] == "metro"].set_index(key)["lettings"]
    non_metro = lgas[lgas["row_type"] == "non_metro"].set_index(key)["lettings"]
    split = (metro + non_metro).reindex(vic.index)
    gap = vic - published["published"]
    return {
        "quarters": len(vic),
        "victoria_eq_group_totals": int((vic == groups).sum()),
        "victoria_eq_lga_sum": int((gap == 0).sum()),
        "victoria_below_lga_sum": int((gap < 0).sum()),
        "gap_without_suppressed_lga": int(((gap > 0) & (published["suppressed"] == 0)).sum()),
        "victoria_eq_metro_plus_non_metro": int((vic == split).sum()),
        "max_abs_gap_metro_split": float((vic - split).abs().max()),
    }


def affordability_totals(aff: pd.DataFrame) -> dict:
    key = ["dwelling", "quarter"]
    vic = aff[aff["row_type"] == "victoria"].set_index(key)["affordable_lettings"]
    lga_sum = aff[aff["row_type"] == "lga"].groupby(key)["affordable_lettings"].sum()
    shares = aff["affordable_share"]
    return {
        "quarters": len(vic),
        "victoria_eq_lga_sum": int((vic == lga_sum.reindex(vic.index)).sum()),
        "share_out_of_range": int(((shares < 0) | (shares > 1)).sum()),
    }


def plausibility(suburbs: pd.DataFrame, lgas: pd.DataFrame) -> dict:
    out = {}
    for name, df in {"suburb": suburbs, "lga": lgas}.items():
        out[f"{name}_nonpositive_median"] = int((df["median_rent"] <= 0).sum())
        out[f"{name}_negative_lettings"] = int((df["lettings"] < 0).sum())
        out[f"{name}_median_without_lettings"] = int((df["median_rent"].notna() & df["lettings"].isna()).sum())
        out[f"{name}_smallest_published_lettings"] = float(df["lettings"].min())
    return out


def median_jumps(suburbs: pd.DataFrame, threshold: float = JUMP_THRESHOLD,
                 min_lettings: int = JUMP_MIN_LETTINGS) -> pd.DataFrame:
    """Quarter-on-quarter moves in the moving annual median bigger than
    `threshold`, where both quarters have at least `min_lettings` leases."""
    sub = suburbs[suburbs["row_type"] == "suburb"].sort_values(["dwelling", "suburb", "quarter"])
    g = sub.groupby(["dwelling", "suburb"])
    sub = sub.assign(prev_median=g["median_rent"].shift(), prev_lettings=g["lettings"].shift(),
                     prev_quarter=g["quarter"].shift())
    sub["change"] = sub["median_rent"] / sub["prev_median"] - 1
    consecutive = (sub["quarter"] - sub["prev_quarter"]).dt.days.between(88, 93)
    big = (sub["lettings"] >= min_lettings) & (sub["prev_lettings"] >= min_lettings)
    flagged = sub[(consecutive & big & (sub["change"].abs() > threshold)).fillna(False)]
    return flagged[["dwelling", "suburb", "quarter", "prev_median", "median_rent", "lettings", "change"]] \
        .sort_values("change", key=abs, ascending=False).reset_index(drop=True)


def small_samples(suburbs: pd.DataFrame, threshold: int = 30) -> pd.DataFrame:
    """Latest-quarter suburb medians resting on fewer than `threshold` leases."""
    latest = suburbs[(suburbs["row_type"] == "suburb") & (suburbs["quarter"] == suburbs["quarter"].max())]
    return latest.groupby("dwelling", sort=False).agg(
        published=("median_rent", "count"),
        under_threshold=("lettings", lambda s: int((s < threshold).sum())),
    ).reset_index()


def name_fixes_used(raw_names: set[str]) -> dict[str, str]:
    return {k: v for k, v in parse.NAME_FIXES.items() if k in raw_names}
