"""Download the Homes Victoria Rental Report workbooks into data/raw/.

Source: Homes Victoria (Department of Families, Fairness and Housing),
"Rental Report - Quarterly", listed on DataVic
(https://discover.data.vic.gov.au, search "Rental Report - Quarterly").
Licence: Creative Commons Attribution 4.0 International.

Four workbooks are used:
- moving annual median rents by suburb, September quarter 2025 (the core
  time series: 7 dwelling types x 146 suburbs and towns, Mar 2000 - Sep 2025)
- quarterly median rents by Local Government Area, September quarter 2025
- affordable lettings by LGA, September quarter 2024 (the latest one with a
  public copy that can be fetched without a browser; the Sep 2025 snapshot is
  Table 14 of the report tables below)
- the report's own tables, September quarter 2025 (used to reconcile the
  parsed numbers against the figures Homes Victoria published)

The official dffh.vic.gov.au links come first. That site drops scripted
connections from some networks (it did from the machine this was built on),
so each file falls back to its Internet Archive capture, fetched with the
`id_` flag so the archive returns the original bytes. Every file's SHA-256 is
pinned: a file that differs stops the download instead of silently changing
the analysis.
"""
from pathlib import Path
import hashlib
import time
import urllib.parse
import urllib.request

DFFH = "https://www.dffh.vic.gov.au"
WAYBACK = "https://web.archive.org/web"

# file name -> (expected SHA-256, [URLs tried in order])
FILES = {
    "moving_annual_rents_by_suburb_sep2025.xlsx": (
        "817c5b8ea7985651af84519149276ef0281f8b6cfa4bcada39ea8aa87ed2952e",
        [
            f"{DFFH}/moving-annual-rent-suburb-september-quarter-2025-excel",
            f"{WAYBACK}/20260817181431id_/{DFFH}/moving-annual-rent-suburb-september-quarter-2025-excel",
        ],
    ),
    "quarterly_median_rents_by_lga_sep2025.xlsx": (
        "b8e96347494f09fea2a2ace55997fd34c9398f8509cb3450d65444aebfaaa837",
        [
            f"{DFFH}/quarterly-median-rents-local-government-area-september-quarter-2025-excel",
            f"{WAYBACK}/20260918150906id_/{DFFH}/sites/default/files/documents/202602/"
            "quarterly-median-rents-local-government-area-september-quarter-2025-excel.xlsx",
        ],
    ),
    "affordable_lettings_by_lga_sep2024.xlsx": (
        "f7117f057699b9e217f07d9325a116d4213ea67e3a96e2d588f39086226e0d11",
        [
            f"{DFFH}/affordable-lettings-local-government-area-september-quarter-2024",
            f"{WAYBACK}/20250320025117id_/{DFFH}/sites/default/files/documents/202412/"
            "Affordable-lettings-by-Local-Government-Area-September-quarter-2024.xlsx",
        ],
    ),
    "rental_report_tables_sep2025.xlsx": (
        "895746dee06f5199f877ed86f06243624aca3686c962a5cf5323e90d1f44c495",
        [
            f"{DFFH}/tables-rental-report-september-quarter-2025-excel",
            f"{WAYBACK}/20260621133954id_/{DFFH}/sites/default/files/documents/202602/"
            "Tables%20from%20Rental%20Report%20-%20September%20Quarter%202025.xlsx",
        ],
    ),
}
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
USER_AGENT = "Mozilla/5.0 (vic-rental-market-analysis; +https://github.com/nisha1324)"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# hosts that already failed in this run, so later files don't wait on them again
DEAD_HOSTS: set[str] = set()


def download(url: str, dest: Path, timeout: int = 30) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        dest.write_bytes(resp.read())


def fetch(name: str, dest: Path, retries: int = 2) -> str:
    """Try each URL in turn; keep the first file whose hash matches."""
    expected, urls = FILES[name]
    tmp = dest.with_suffix(".part")
    for url in urls:
        host = urllib.parse.urlsplit(url).netloc
        if host in DEAD_HOSTS:
            continue
        for attempt in range(1, retries + 1):
            try:
                download(url, tmp)
                break
            except OSError as exc:
                print(f"  {host} attempt {attempt} failed: {exc}")
                time.sleep(2 * attempt)
        else:
            DEAD_HOSTS.add(host)
            print(f"  skipping {host} for the rest of this run")
            continue
        if sha256(tmp) == expected:
            tmp.replace(dest)
            return url
        print(f"  hash mismatch from {host}, trying next source")
    tmp.unlink(missing_ok=True)
    raise SystemExit(f"could not get a verified copy of {name}")


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for name, (expected, _) in FILES.items():
        dest = RAW / name
        if dest.exists() and sha256(dest) == expected:
            print(f"ok (cached)  {name}")
            continue
        url = fetch(name, dest)
        source = "archive" if url.startswith(WAYBACK) else "dffh"
        print(f"ok ({source})  {name}  {dest.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
