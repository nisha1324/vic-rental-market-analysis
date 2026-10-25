"""Fetch the Melbourne Consumer Price Index into data/reference/ for real
(inflation-adjusted) rent growth.

Source: Australian Bureau of Statistics, Consumer Price Index (dataflow
ABS,CPI,2.0.0), via the ABS Data API (https://data.api.abs.gov.au, no key
needed). Licence: Creative Commons Attribution 4.0 International.

Series key 1.10001.10.2.Q = index numbers, All groups CPI, original (not
seasonally adjusted), Melbourne, quarterly. Melbourne is the only Victorian
capital-city series; the ABS publishes no CPI for regional Victoria, so the
same series deflates regional rents too (noted in the README).

Unlike the rent workbooks, this is a small API response rather than a fixed
file, so the cleaned CSV is committed and this script is only needed to
refresh it. It checks that the quarters are continuous and stops if any
already-committed quarter's value has changed (the original series isn't
normally revised; a change means something upstream moved and the real
growth figures should be looked at again).
"""
from pathlib import Path
import csv
import io
import json
import urllib.request
from datetime import datetime, timezone

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reference" / "cpi_melbourne.csv"
META = OUT.with_suffix(".json")

URL = ("https://data.api.abs.gov.au/rest/data/ABS,CPI,2.0.0/1.10001.10.2.Q"
       "?startPeriod=1999-Q1")
START = pd.Timestamp("1999-03-31")  # the LGA rent series starts Jun 1999


def fetch(url: str = URL, timeout: int = 60) -> pd.DataFrame:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.sdmx.data+csv"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8")
    return parse(text)


def parse(text: str) -> pd.DataFrame:
    """SDMX-CSV -> one row per quarter: quarter (quarter-end date), cpi."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError("empty CPI response")
    keys = {(r["MEASURE"], r["INDEX"], r["TSEST"], r["REGION"], r["FREQ"]) for r in rows}
    if keys != {("1", "10001", "10", "2", "Q")}:
        raise ValueError(f"unexpected series in CPI response: {sorted(keys)}")
    df = pd.DataFrame({
        "quarter": pd.PeriodIndex([r["TIME_PERIOD"] for r in rows], freq="Q").to_timestamp(how="end").normalize(),
        "cpi": [float(r["OBS_VALUE"]) for r in rows],
    }).sort_values("quarter").reset_index(drop=True)
    expected = pd.date_range(df["quarter"].min(), df["quarter"].max(), freq="QE")
    if len(df) != len(expected) or not (df["quarter"].values == expected.values).all():
        raise ValueError("CPI quarters are not continuous")
    if df["quarter"].min() > START:
        raise ValueError(f"CPI starts {df['quarter'].min():%b %Y}, need {START:%b %Y}")
    return df


def check_unchanged(new: pd.DataFrame, old_path: Path = OUT) -> None:
    if not old_path.exists():
        return
    old = pd.read_csv(old_path, parse_dates=["quarter"])
    both = old.merge(new, on="quarter", how="left", suffixes=("_old", "_new"))
    changed = both[both["cpi_old"] != both["cpi_new"]]
    if len(changed):
        raise SystemExit(f"CPI values changed for {len(changed)} committed quarters, e.g.\n"
                         f"{changed.head().to_string(index=False)}")


def main() -> None:
    df = fetch()
    check_unchanged(df)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False, date_format="%Y-%m-%d")
    META.write_text(json.dumps({
        "source": "Australian Bureau of Statistics, Consumer Price Index (ABS,CPI,2.0.0)",
        "series": "Index numbers; All groups CPI; Original; Melbourne; Quarterly",
        "url": URL,
        "licence": "CC BY 4.0",
        "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "first_quarter": f"{df['quarter'].min():%Y-%m-%d}",
        "last_quarter": f"{df['quarter'].max():%Y-%m-%d}",
        "quarters": len(df),
    }, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(df)} quarters, "
          f"{df['quarter'].min():%b %Y} - {df['quarter'].max():%b %Y}")


if __name__ == "__main__":
    main()
