# Victorian Rental Market Analysis

> **Status: in progress. Part 1 of 5 is done: data, parser and audit.** The workbooks download with pinned checksums and parse into tidy tables, and an audit reconciles them against the figures Homes Victoria published. No findings yet; they come in Parts 2–4 (see [Roadmap](#roadmap)).

**Business question:** rents in Victoria have climbed for years, but not evenly. **Where are rents rising fastest, where is it still affordable to rent, and how has that changed since before COVID?** The answer matters to anyone who prices, manages or plans rental housing:

- a **property manager or agency** setting rents and choosing which suburbs to grow its rent roll in,
- a **community housing provider or council** deciding where lower-income renters are being priced out,
- an **employer or university** advising staff and students on where they can afford to live (Melbourne is one of Australia's biggest international-student cities).

## Data

**Source:** Homes Victoria (Department of Families, Fairness and Housing), *Rental Report – Quarterly*, published on [DataVic](https://discover.data.vic.gov.au/) (search "Rental Report - Quarterly"). Licence: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The figures come from rental bonds lodged with the Residential Tenancies Bond Authority, so they cover new leases, not every rent being paid.

| Table | Grain | Coverage | Measures |
|---|---|---|---|
| Moving annual rents by suburb | 146 suburbs and towns (110 metro, 36 regional) × 7 dwelling types | Mar 2000 – Sep 2025, 103 quarters | median weekly rent and number of new leases in the 12 months to each quarter |
| Quarterly median rents by LGA | 79 Local Government Areas × 7 dwelling types | Jun 1999 – Sep 2025, 106 quarters | median weekly rent and number of new leases in that quarter |
| Affordable lettings by LGA | 79 LGAs × bedrooms (1–4, all) | Mar 2000 – Sep 2024, 99 quarters | new leases affordable to a lower-income household on Centrelink payments (rent ≤ 30% of gross income), count and share |
| Report tables, Sep 2025 | | | used only to check the parsed numbers |

Dwelling types: 1-, 2- and 3-bedroom flats; 2-, 3- and 4-bedroom houses; all properties.

**Getting the files.** `scripts/download_data.py` tries the official dffh.vic.gov.au links first. That site drops scripted connections from some networks (including the one this was built on), so each file falls back to its Internet Archive capture of the same official URL. Each file's SHA-256 is pinned, so whichever source serves it, the bytes must be identical or the download stops. The affordability series ends in September 2024 because that is the latest workbook with a copy that can be fetched without a browser.

## Data audit (Part 1)

The audit runs every check below and fails loudly if a hard check breaks. Full output: [`results/DATA_AUDIT.md`](results/DATA_AUDIT.md).

- **The parser reads the right cells.** Table 4 of the September 2025 report lists the highest and lowest suburb rents for 2-bedroom flats and 3-bedroom houses. **All 49 entries match** the parsed data exactly, and all 49 hold up as top or bottom of their group when checked against every suburb not listed.
- **Totals add up once suppression is accounted for.** Small areas are published as '-', but their leases still count towards the totals. So a region's Group Total equals the sum of its published suburbs in only 81.7% of region-quarters, but it is never below that sum, and every gap comes with at least one suppressed suburb. The state total equals the sum of the regional Group Totals in all 742 LGA dwelling-quarters, and the affordability state total equals the sum of its LGAs in all 495.
- **No gaps, no impossible values.** Every series is continuous; no zero or negative rents; no median without a lease count; every affordability share is between 0 and 1.
- **Small samples are noisy, so rankings need a floor.** In series with at least 100 leases the 12-month median never moves more than 21.1% in a quarter. Allow series down to 10 leases and 55 quarterly moves exceed 25%. In September 2025, 31 of the 141 published 2-bedroom-house medians rest on fewer than 30 leases, against 2 of 143 for 3-bedroom houses and 6 of 145 for 2-bedroom flats. The analysis will rank on the well-sampled types and set a minimum lease count.
- **Four names fixed** so the tables join: `Wanagaratta` → Wangaratta, `Geelong-Newcomb` → Geelong-Newcombe, `Mornington Penin'a` → Mornington Peninsula, `Queenscliff` → Queenscliffe.
- **Repeated rows checked, not trusted.** The LGA and affordability sheets repeat the state total as Metro + Non-Metro. The repeat differs from the main total by at most 1 lease (LGA rents) or 2 leases / 0.001 of a share (affordability), which is rounding; it is dropped after the check.

**So what for the analysis:** the published numbers can be trusted as parsed, but region totals must come from the Group Total rows (not from summing suburbs), and any "fastest-rising suburb" ranking needs a minimum lease count, or it will mostly pick up noise from small series.

## Roadmap

- [x] **Part 1: data.** Download with pinned checksums, parse to tidy tables, audit and reconcile against the published report, tests.
- [ ] **Part 2: where rents are rising fastest.** 1-year, 5-year and since-pre-COVID (Sep 2019) growth by suburb and dwelling type, with a minimum lease count; inner vs outer Melbourne vs regional; real (CPI-adjusted) growth. SQL on DuckDB over the tidy tables.
- [ ] **Part 3: affordability.** Where the share of affordable new leases has collapsed and where affordable stock remains, by LGA and bedroom count, joined to LGA rents.
- [ ] **Part 4: market activity.** New-lease volumes as a signal of supply (e.g. growth corridors vs the inner city), and how volume relates to rent growth.
- [ ] **Part 5: write-up.** Charts, TL;DR, recommendations for each audience, limitations.

## How to run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/download_data.py   # 4 workbooks (~3.4 MB) into data/raw/, checksums verified
python scripts/build.py           # tidy CSVs into data/processed/
python scripts/audit.py           # writes results/DATA_AUDIT.md; exits non-zero if a hard check fails
pytest -q                         # 18 tests (the real-data ones skip if data/raw/ is empty)
```

## Project structure

```
scripts/download_data.py   sources, fallbacks and pinned SHA-256 per file
scripts/build.py           workbooks -> data/processed/*.csv
scripts/audit.py           checks -> results/DATA_AUDIT.md
rentals/parse.py           wide Excel sheets -> long tables (+ Table 4 for reconciliation)
rentals/audit.py           coverage, reconciliation, totals, plausibility checks
tests/                     parser tests on synthetic workbooks; audit tests on synthetic and real data
results/DATA_AUDIT.md      generated audit report
```

## Attribution

Contains data from Homes Victoria, *Rental Report – Quarterly* (September quarter 2025 and, for affordable lettings, September quarter 2024), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The tidy tables in this repo are derived from that data; names were standardised as listed above.
