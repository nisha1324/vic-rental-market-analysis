"""Rent growth (Part 2) and affordability (Part 3), computed in DuckDB.

The analysis itself is SQL in sql/*.sql (commented, one question per file,
run in order). This module loads the tidy CSVs and the CPI into an
in-memory DuckDB database, sets the parameters and runs the files, so the
same SQL serves the scripts, the tests and anyone who wants to query it.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql"
PROCESSED = ROOT / "data" / "processed"
CPI_CSV = ROOT / "data" / "reference" / "cpi_melbourne.csv"

# Leases needed at BOTH ends of a window before a suburb is ranked. From the
# audit: at >= 100 leases no quarterly move in the 12-month median exceeds
# 21.1%; at >= 10, 55 moves exceed 25%.
MIN_LETTINGS = 100

# Dwelling types the suburb rankings lead with: the two Homes Victoria uses
# in its own report (Table 4), and the two with the most suburbs above the
# floor. 2-bedroom houses have only 24 suburbs with 100+ leases at both ends
# of the since-2019 window, so they are reported but not ranked on.
HEADLINE_DWELLINGS = ("2br_flat", "3br_house")

COLUMNS = {
    "suburb_rents": {"dwelling": "VARCHAR", "region": "VARCHAR", "suburb": "VARCHAR",
                     "row_type": "VARCHAR", "metro": "BOOLEAN", "quarter": "DATE",
                     "lettings": "BIGINT", "median_rent": "DOUBLE"},
    "lga_rents": {"dwelling": "VARCHAR", "region": "VARCHAR", "lga": "VARCHAR",
                  "row_type": "VARCHAR", "quarter": "DATE", "lettings": "BIGINT",
                  "median_rent": "DOUBLE"},
    "cpi": {"quarter": "DATE", "cpi": "DOUBLE"},
    "lga_affordability": {"dwelling": "VARCHAR", "lga": "VARCHAR", "row_type": "VARCHAR", "quarter": "DATE",
                          "affordable_lettings": "BIGINT", "affordable_share": "DOUBLE"},
    "lga_affordability_latest": {"dwelling": "VARCHAR", "lga": "VARCHAR", "row_type": "VARCHAR",
                                 "metro": "BOOLEAN", "quarter": "DATE", "affordable_lettings": "BIGINT",
                                 "affordable_share": "DOUBLE"},
    "affordability_thresholds": {"dwelling": "VARCHAR", "household": "VARCHAR", "weekly_income": "DOUBLE",
                                 "affordable_rent": "DOUBLE", "area": "VARCHAR", "quarter": "DATE",
                                 "affordable_lettings": "BIGINT", "affordable_share": "DOUBLE"},
    "affordability_state_revised": {"area": "VARCHAR", "quarter": "DATE", "affordable_share": "DOUBLE"},
}
AFFORDABILITY_TABLES = ("lga_affordability", "lga_affordability_latest", "affordability_thresholds",
                        "affordability_state_revised")


def connect(suburbs: pd.DataFrame, lgas: pd.DataFrame, cpi: pd.DataFrame,
            min_lettings: int = MIN_LETTINGS, **affordability: pd.DataFrame) -> duckdb.DuckDBPyConnection:
    """Load the inputs as tables and run every sql/*.sql file.

    The affordability tables (AFFORDABILITY_TABLES, as keyword arguments) are
    optional: any not given is created empty, so the Part 3 SQL runs and
    returns nothing."""
    unknown = set(affordability) - set(AFFORDABILITY_TABLES)
    if unknown:
        raise TypeError(f"unknown tables {sorted(unknown)}")
    con = duckdb.connect()
    inputs = {"suburb_rents": suburbs, "lga_rents": lgas, "cpi": cpi}
    for name in AFFORDABILITY_TABLES:
        inputs[name] = affordability.get(name, pd.DataFrame(columns=list(COLUMNS[name])))
    for name, df in inputs.items():
        cols = COLUMNS[name]
        con.register("_in", df[list(cols)])
        select = ", ".join(f"cast({c} as {t}) as {c}" for c, t in cols.items())
        con.execute(f"create table {name} as select {select} from _in")
        con.unregister("_in")
    con.execute(f"set variable min_lettings = {int(min_lettings)}")
    for path in sorted(SQL_DIR.glob("*.sql")):
        con.execute(path.read_text())
    return con


def load_inputs(processed: Path = PROCESSED, cpi_csv: Path = CPI_CSV) -> tuple[pd.DataFrame, ...]:
    missing = [p for p in (processed / "suburb_rents.csv", processed / "lga_rents.csv", cpi_csv)
               if not p.exists()]
    if missing:
        raise SystemExit(f"missing {[str(p) for p in missing]}: run scripts/build.py "
                         "(and scripts/download_cpi.py for the CPI) first")
    read = lambda p: pd.read_csv(p, parse_dates=["quarter"])  # noqa: E731
    return read(processed / "suburb_rents.csv"), read(processed / "lga_rents.csv"), read(cpi_csv)


def load_affordability(processed: Path = PROCESSED) -> dict[str, pd.DataFrame]:
    paths = {name: processed / f"{name}.csv" for name in AFFORDABILITY_TABLES}
    missing = [str(p) for p in paths.values() if not p.exists()]
    if missing:
        raise SystemExit(f"missing {missing}: run scripts/build.py first")
    return {name: pd.read_csv(p, parse_dates=["quarter"]) for name, p in paths.items()}


def query(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    return con.execute(sql).df()


def floor_sensitivity(con: duckdb.DuckDBPyConnection, floors=(50, 100, 200), top: int = 10,
                      window: str = "since_2019") -> pd.DataFrame:
    """How much the top-`top` fastest-rising suburbs depend on the lease floor.

    For each headline dwelling type and floor: how many suburbs qualify, how
    many of the top list at the default floor are still in it, and how many of
    those that left were excluded by the floor itself (too few leases) rather
    than overtaken by a suburb the floor let in. Also who fills the two ends:
    regional suburbs in the top list, Inner Melbourne suburbs in the bottom."""
    g = query(con, f"select * from suburb_growth where \"window\" = '{window}'")
    rows = []
    for dwelling in HEADLINE_DWELLINGS:
        d = g[g["dwelling"] == dwelling]
        least = d[["start_lettings", "end_lettings"]].min(axis=1)

        def top_at(floor: int) -> set[str]:
            return set(d[least >= floor].nlargest(top, "growth", keep="all")["suburb"])

        def bottom_at(floor: int) -> pd.DataFrame:
            return d[least >= floor].nsmallest(top, "growth", keep="all")

        base = top_at(MIN_LETTINGS)
        for floor in floors:
            qualifying = set(d.loc[least >= floor, "suburb"])
            kept = top_at(floor) & base
            rows.append({"dwelling": dwelling, "floor": floor, "suburbs": len(qualifying),
                         "top_kept": len(kept), "top_base": len(base),
                         "left_below_floor": len(base - qualifying),
                         "left_overtaken": len((base & qualifying) - kept),
                         "top_regional": int((~d[d["suburb"].isin(top_at(floor))]["metro"]).sum()),
                         "bottom_inner": int((bottom_at(floor)["region"] == "Inner Melbourne").sum()),
                         "bottom_size": len(bottom_at(floor))})
    return pd.DataFrame(rows)
