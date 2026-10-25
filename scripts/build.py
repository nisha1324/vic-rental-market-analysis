"""Parse the downloaded workbooks into tidy CSVs in data/processed/.

    python scripts/download_data.py
    python scripts/build.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rentals import parse  # noqa: E402

RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

SOURCES = {
    "suburb_rents.csv": (parse.parse_suburbs, "moving_annual_rents_by_suburb_sep2025.xlsx"),
    "lga_rents.csv": (parse.parse_lgas, "quarterly_median_rents_by_lga_sep2025.xlsx"),
    "lga_affordability.csv": (parse.parse_affordability, "affordable_lettings_by_lga_sep2024.xlsx"),
    # snapshots from the September 2025 report tables (one quarter, or the last 21 for Fig 8)
    "lga_affordability_latest.csv": (parse.parse_table14, "rental_report_tables_sep2025.xlsx"),
    "affordability_thresholds.csv": (parse.parse_table9, "rental_report_tables_sep2025.xlsx"),
    "affordability_state_revised.csv": (parse.parse_fig8, "rental_report_tables_sep2025.xlsx"),
}


def load_all() -> dict:
    missing = [f for _, f in SOURCES.values() if not (RAW / f).exists()]
    if missing:
        raise SystemExit(f"missing {missing}: run scripts/download_data.py first")
    return {name: fn(RAW / f) for name, (fn, f) in SOURCES.items()}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, df in load_all().items():
        df.to_csv(OUT / name, index=False, date_format="%Y-%m-%d")
        print(f"{name:24} {len(df):>7,} rows  {df['quarter'].min():%b %Y} - {df['quarter'].max():%b %Y}")


if __name__ == "__main__":
    main()
