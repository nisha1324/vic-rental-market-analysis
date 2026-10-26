"""The headline numbers (scripts/summary.py -> results/SUMMARY.md) and the
README's TL;DR: every number in the TL;DR must be a generated figure, every
figure must appear in the Part report it cites, and the committed summary
must match a fresh run (skipped if the data hasn't been built)."""
import re
from pathlib import Path

import pytest

from rentals import growth
from scripts import summary
from tests.test_growth import needs_data

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

# Money, percentages, "N of M" counts, correlations and thousands. Bare small
# integers and years ("Part 2", "2019") are not figures.
NUMBER = re.compile(r"\$[\d,]+|[+\-]?\d+(?:\.\d+)?%|\d+ of \d+|[+\-]?0\.\d\d\b|\d{1,3}(?:,\d{3})+")


def normalise(text: str) -> str:
    return text.replace("−", "-")


def numbers(text: str) -> list[str]:
    return NUMBER.findall(normalise(text))


def bare(figure: str) -> str:
    # prose often gives the direction in words ("14.9% fewer"), so compare magnitudes
    return figure.lstrip("+-")


def summary_rows(text: str) -> list[tuple[str, list[str]]]:
    """(report, atomic figures) for each row of the SUMMARY.md table."""
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0].isdigit():
            figures = [f for group in cells[2].split("; ") for f in group.split(" → ")]
            report = re.search(r"\(([A-Z_]+\.md)\)", cells[3]).group(1)
            rows.append((report, figures))
    return rows


def tldr(readme: str) -> str:
    m = re.search(r"^## TL;DR\n(.*?)^## ", readme, flags=re.S | re.M)
    assert m, "README has no '## TL;DR' section"
    return m.group(1)


def unbacked(tldr_text: str, summary_text: str) -> list[str]:
    known = {bare(f) for _, figures in summary_rows(summary_text) for f in figures}
    return [n for n in numbers(tldr_text) if bare(n) not in known]


@pytest.fixture(scope="module")
def committed() -> str:
    return (RESULTS / "SUMMARY.md").read_text()


def test_summary_has_a_row_per_part(committed):
    rows = summary_rows(committed)
    assert len(rows) >= 15
    assert {r for r, _ in rows} == {"GROWTH.md", "AFFORDABILITY.md", "MARKET_ACTIVITY.md"}


def in_report(figure: str, text: str) -> bool:
    """Verbatim, or for "N of M" counts, "N of the M" or both numbers in one table row."""
    if figure in text:
        return True
    m = re.fullmatch(r"(\d+) of (\d+)", figure)
    if not m:
        return False
    if f"{m[1]} of the {m[2]}" in text:
        return True
    return any(line.startswith("|") and {m[1], m[2]} <= {c.strip() for c in line.split("|")}
               for line in text.splitlines())


def test_each_figure_appears_in_its_report(committed):
    for report, figures in summary_rows(committed):
        text = normalise((RESULTS / report).read_text())
        missing = [f for f in figures if not in_report(f, text)]
        assert not missing, f"{report} doesn't contain {missing}"


def test_every_tldr_number_is_a_headline_figure(committed):
    text = tldr((ROOT / "README.md").read_text())
    assert len(numbers(text)) >= 20  # the check would pass vacuously on an empty TL;DR
    assert unbacked(text, committed) == []


def test_unbacked_number_is_caught(committed):
    # the checker itself: a figure that isn't in the summary is reported, with
    # the sign and the Unicode minus handled
    assert unbacked("Rents rose 37.5% (−0.7% real), and 99.9% of 3 of 4.", committed) == ["99.9%", "3 of 4"]


@needs_data
def test_committed_summary_is_current(committed):
    con = growth.connect(*growth.load_inputs(), **growth.load_affordability(), **growth.load_supply())
    assert summary.render(summary.key_numbers(con)) == committed
