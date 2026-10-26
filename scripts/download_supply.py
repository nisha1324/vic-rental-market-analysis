"""Fetch new-dwelling approvals and the 2021 dwelling count for every
Victorian LGA into data/reference/, as a supply signal for Part 4.

Source: Australian Bureau of Statistics via the ABS Data API
(https://data.api.abs.gov.au, no key needed). Licence: Creative Commons
Attribution 4.0 International.

- Building Approvals by LGA (dataflows ABS,BA_LGA2018 ... BA_LGA2025). Each
  dataflow holds one financial year on that year's LGA boundaries (BA_LGA2018
  = Jul 2018 - Jun 2019). Series key 1.9.1.100 = number of dwelling units,
  all sectors, new work, total residential; monthly.
- Census 2021, G36 Dwelling structure by LGA (ABS,C21_G36_LGA): total private
  dwellings, the base the approvals are scaled by.

Victorian LGA codes are the same in every vintage except Moreland, renamed
Merri-bek in 2022 (25250 -> 24700); it is mapped to the new code. Names follow
the rental report (the ABS's "Kingston (Vic.)" is "Kingston" there), and
scripts/market_activity.py stops if any of the report's 79 LGAs is unmatched.

Approvals for recent months are preliminary and get revised, so unlike the
CPI this script overwrites the committed CSVs; the analysis uses approvals to
June 2024, which are long settled. Monthly figures are summed to quarters, and
only complete quarters are kept.
"""
from pathlib import Path
import csv
import io
import json
import urllib.request
from datetime import datetime, timezone

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "data" / "reference"
APPROVALS = REF / "dwelling_approvals_lga.csv"
DWELLINGS = REF / "census2021_dwellings_lga.csv"
META = REF / "supply_abs.json"

API = "https://data.api.abs.gov.au/rest"
VINTAGES = range(2018, 2026)  # financial years 2018-19 to 2025-26
APPROVALS_URL = API + "/data/ABS,BA_LGA{y}/1.9.1.100.LGA{y}..M?format=csv"
DWELLINGS_URL = API + "/data/ABS,C21_G36_LGA,1.0.0/_T.D..LGA2021.2?format=csv"
CODELIST_URL = API + "/codelist/ABS/CL_LGA_2025/1.0.0"

RENAMED = {"25250": "24700"}  # Moreland -> Merri-bek


def is_vic_lga(code: str) -> bool:
    """Victorian LGA codes are 5 digits starting with 2; 29xxx are
    "unincorporated", "no usual address" and similar non-areas."""
    return len(code) == 5 and code.startswith("2") and not code.startswith("29")


def get(url: str, accept: str = "text/csv", timeout: int = 180) -> str:
    req = urllib.request.Request(url, headers={"Accept": accept})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def lga_names(xml: str) -> dict[str, str]:
    """ABS code -> name as the rental report spells it, from the 2025 codelist."""
    import xml.etree.ElementTree as ET
    ns = {"str": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
          "com": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common"}
    names = {}
    for code in ET.fromstring(xml).iterfind(".//str:Code", ns):
        cid = code.get("id")
        if is_vic_lga(cid):
            names[cid] = code.find("com:Name", ns).text
    return {c: standard_name(n) for c, n in names.items()}


def standard_name(abs_name: str) -> str:
    name = abs_name.removesuffix(" (Vic.)")
    return {"Colac Otway": "Colac-Otway"}.get(name, name)


def parse_approvals(text: str, vintage: int) -> pd.DataFrame:
    """One BA_LGA dataflow (SDMX-CSV) -> Victorian LGA x month rows."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError(f"empty approvals response for BA_LGA{vintage}")
    keys = {(r["MEASURE"], r["SECTOR"], r["WORK_TYPE"], r["BUILDING_TYPE"], r["FREQ"]) for r in rows}
    if keys != {("1", "9", "1", "100", "M")}:
        raise ValueError(f"unexpected series in BA_LGA{vintage}: {sorted(keys)}")
    df = pd.DataFrame({
        "abs_code": [RENAMED.get(r["REGION"], r["REGION"]) for r in rows],
        "month": pd.PeriodIndex([r["TIME_PERIOD"] for r in rows], freq="M"),
        "approvals": [int(float(r["OBS_VALUE"])) for r in rows],
    })
    df = df[df["abs_code"].map(is_vic_lga)]
    start = pd.Period(f"{vintage}-07", freq="M")
    outside = df[(df["month"] < start) | (df["month"] > start + 11)]
    if len(outside):
        raise ValueError(f"BA_LGA{vintage} has months outside Jul {vintage} - Jun {vintage + 1}")
    return df


def to_quarters(monthly: pd.DataFrame) -> pd.DataFrame:
    """Sum months to quarter-end dates, keeping only quarters with all 3 months."""
    m = monthly.assign(quarter=monthly["month"].dt.asfreq("Q").dt.to_timestamp(how="end").dt.normalize())
    q = m.groupby(["abs_code", "quarter"]).agg(approvals=("approvals", "sum"), months=("month", "nunique"))
    q = q[q["months"] == 3].drop(columns="months").reset_index()
    return q


def parse_dwellings(text: str) -> pd.DataFrame:
    rows = list(csv.DictReader(io.StringIO(text)))
    keys = {(r["DWTSTRD"], r["SUM"], r["REGION_TYPE"], r["STATE"], r["TIME_PERIOD"]) for r in rows}
    if keys != {("_T", "D", "LGA2021", "2", "2021")}:
        raise ValueError(f"unexpected series in C21_G36_LGA: {sorted(keys)}")
    df = pd.DataFrame({"abs_code": [RENAMED.get(r["REGION"], r["REGION"]) for r in rows],
                       "dwellings_2021": [int(r["OBS_VALUE"]) for r in rows]})
    return df[df["abs_code"].map(is_vic_lga)]


def main() -> None:
    names = lga_names(get(CODELIST_URL, accept="application/xml"))
    monthly = pd.concat([parse_approvals(get(APPROVALS_URL.format(y=y)), y) for y in VINTAGES])
    if monthly.duplicated(["abs_code", "month"]).any():
        raise ValueError("an LGA-month appears in more than one vintage")
    approvals = to_quarters(monthly)
    dwellings = parse_dwellings(get(DWELLINGS_URL))

    codes = set(names)
    for label, df in (("approvals", approvals), ("dwellings", dwellings)):
        unknown = set(df["abs_code"]) - codes
        missing = codes - set(df["abs_code"])
        if unknown or missing:
            raise ValueError(f"{label}: codes not in the 2025 codelist {sorted(unknown)}, "
                             f"codelist LGAs missing {sorted(missing)}")
    per_lga = approvals.groupby("abs_code")["quarter"].nunique()
    if per_lga.nunique() != 1:
        raise ValueError("LGAs cover different numbers of quarters")

    approvals.insert(0, "lga", approvals["abs_code"].map(names))
    dwellings.insert(0, "lga", dwellings["abs_code"].map(names))
    approvals = approvals.sort_values(["lga", "quarter"])
    dwellings = dwellings.sort_values("lga")
    REF.mkdir(parents=True, exist_ok=True)
    approvals.to_csv(APPROVALS, index=False, date_format="%Y-%m-%d")
    dwellings.to_csv(DWELLINGS, index=False)
    META.write_text(json.dumps({
        "source": "Australian Bureau of Statistics: Building Approvals by LGA (ABS,BA_LGA2018-2025); "
                  "Census 2021 G36 Dwelling structure by LGA (ABS,C21_G36_LGA)",
        "approvals_series": "Number of dwelling units; Total sectors; New; Total residential; monthly, "
                            "summed to complete quarters",
        "dwellings_series": "Total private dwellings, Census 2021 (place of enumeration)",
        "approvals_url": APPROVALS_URL,
        "dwellings_url": DWELLINGS_URL,
        "licence": "CC BY 4.0",
        "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "first_quarter": f"{approvals['quarter'].min():%Y-%m-%d}",
        "last_quarter": f"{approvals['quarter'].max():%Y-%m-%d}",
        "lgas": int(approvals["lga"].nunique()),
        "renamed_codes": RENAMED,
    }, indent=2) + "\n")
    print(f"wrote {APPROVALS.relative_to(ROOT)}: {len(approvals)} rows, {approvals['lga'].nunique()} LGAs, "
          f"{approvals['quarter'].min():%b %Y} - {approvals['quarter'].max():%b %Y}")
    print(f"wrote {DWELLINGS.relative_to(ROOT)}: {len(dwellings)} LGAs, "
          f"{dwellings['dwellings_2021'].sum():,} private dwellings")


if __name__ == "__main__":
    main()
