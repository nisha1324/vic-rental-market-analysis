"""Parser tests on small synthetic workbooks laid out like the real ones."""
import math

import openpyxl
import pandas as pd
import pytest

from rentals import parse


def suburb_rows():
    return [
        ("Moving annual median rent by suburb and town", None, "Lease commenced in year ending ", None, None, None),
        ("Two bedroom flat", None, "Jun 2025", "Jun 2025", "Sep 2025", "Sep 2025"),
        (None, None, "Count", "Median", "Count", "Median"),
        ("Inner Melbourne", "Docklands", 2900, 690, 2950, 700),
        (None, "Wanagaratta", "-", "-", 12, 410),
        (None, "Group Total", 2950, 680, 2970, 690),
        ("Geelong", "Corio", 100, 400, 110, 405),
        (None, None, None, None, None, None),
    ]


def write_book(path, sheets):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(list(row))
    wb.save(path)
    return path


def test_quarter_end():
    assert parse.quarter_end("Sep 2025") == pd.Timestamp("2025-09-30")
    assert parse.quarter_end(" Mar 2000 ") == pd.Timestamp("2000-03-31")
    assert parse.quarter_end("Dec 1999") == pd.Timestamp("1999-12-31")
    with pytest.raises(ValueError):
        parse.quarter_end("September 2025")


def test_clean_value():
    assert parse.clean_value(650, "x") == 650.0
    assert math.isnan(parse.clean_value("-", "x"))
    assert math.isnan(parse.clean_value(None, "x"))
    for bad in ("n.p.", "650", True):
        with pytest.raises(ValueError):
            parse.clean_value(bad, "x")


def test_wide_to_long_fills_region_and_fixes_names():
    df = parse.wide_to_long(suburb_rows(), parse.SUBURB_LAYOUT, "t")
    assert len(df) == 4 * 2  # four labelled rows x two quarters; blank row skipped
    corio = df[df.area == "Corio"]
    assert set(corio.region) == {"Geelong"}
    wang = df[df.area == "Wangaratta"].set_index("quarter")
    assert set(wang.region) == {"Inner Melbourne"}  # filled down from the block's first row
    assert math.isnan(wang.loc["2025-06-30", "median_rent"])
    assert wang.loc["2025-09-30", "median_rent"] == 410
    assert wang.loc["2025-09-30", "lettings"] == 12


def test_unknown_value_raises_with_location():
    rows = suburb_rows()
    rows[3] = ("Inner Melbourne", "Docklands", 2900, "n.p.", 2950, 700)
    with pytest.raises(ValueError, match=r"t!r3c3"):
        parse.wide_to_long(rows, parse.SUBURB_LAYOUT, "t")


def test_unknown_measure_raises():
    rows = suburb_rows()
    rows[2] = (None, None, "Count", "Mean", "Count", "Median")
    with pytest.raises(ValueError, match="unknown measure"):
        parse.wide_to_long(rows, parse.SUBURB_LAYOUT, "t")


def test_parse_suburbs_types_and_flags(tmp_path):
    path = write_book(tmp_path / "s.xlsx", {name: suburb_rows() for name in parse.SUBURB_SHEETS})
    df = parse.parse_suburbs(path)
    assert set(df.dwelling) == set(parse.SUBURB_SHEETS.values())
    assert df.loc[df.suburb == "Group Total", "row_type"].eq("group_total").all()
    assert df.loc[df.suburb == "Corio", "metro"].eq(False).all()
    assert df.loc[df.suburb == "Docklands", "metro"].eq(True).all()
    assert str(df["lettings"].dtype) == "Int64"


def test_parse_suburbs_missing_sheet(tmp_path):
    path = write_book(tmp_path / "s.xlsx", {"1 bedroom flat": suburb_rows()})
    with pytest.raises(ValueError, match="missing sheets"):
        parse.parse_suburbs(path)


def lga_rows(repeat_lettings=101):
    return [
        ("Quarterly median rents by Local Government Area", None, None, None),
        ("2 bedroom flats", None, "Sep 2025", "Sep 2025"),
        (None, None, "Count", "Median"),
        ("Barwon South West", "Queenscliff", 10, 400),
        (None, "Group Total", 100, 420),
        ("Table Total", "Victoria", 100, 420),
        (None, None, None, None),
        ("METRO NON-METRO", "Metro", 60, 450),
        (None, "Non-Metro", 40, 380),
        (None, "Victoria", repeat_lettings, 420),
    ]


def test_parse_lgas_drops_repeat_within_tolerance(tmp_path):
    path = write_book(tmp_path / "l.xlsx", {name: lga_rows() for name in parse.LGA_SHEETS})
    df = parse.parse_lgas(path)
    assert set(df.row_type) == {"lga", "group_total", "victoria", "metro", "non_metro"}
    assert (df.row_type == "victoria").sum() == len(parse.LGA_SHEETS)
    assert "Queenscliffe" in set(df.lga)


def test_parse_lgas_repeat_beyond_tolerance_raises(tmp_path):
    path = write_book(tmp_path / "l.xlsx", {name: lga_rows(repeat_lettings=105) for name in parse.LGA_SHEETS})
    with pytest.raises(ValueError, match="differ"):
        parse.parse_lgas(path)


def affordability_rows(repeat_share=0.5):
    return [
        ("Affordable lettings by LGA", None, None),
        ("Two bedroom", None, None),
        (" ", "Sep 2024", "Sep 2024"),
        (None, "Affordable", "Percent"),
        ("Alpine", 50, 0.5),
        ("Ararat", 50, 0.5),
        ("Table Total", 100, 0.5),
        (None, None, None),
        ("Metro", 40, 0.4),
        ("Non-Metro", 60, 0.6),
        ("Table Total", 100, repeat_share),
    ]


def test_parse_affordability_keeps_first_total(tmp_path):
    path = write_book(tmp_path / "a.xlsx", {n: affordability_rows() for n in parse.AFFORDABILITY_SHEETS})
    df = parse.parse_affordability(path)
    vic = df[df.row_type == "victoria"]
    assert len(vic) == len(parse.AFFORDABILITY_SHEETS)
    assert set(vic.lga) == {"Victoria"}
    assert set(df.loc[df.row_type == "lga", "lga"]) == {"Alpine", "Ararat"}


def test_parse_affordability_share_mismatch_raises(tmp_path):
    path = write_book(tmp_path / "a.xlsx",
                      {n: affordability_rows(repeat_share=0.52) for n in parse.AFFORDABILITY_SHEETS})
    with pytest.raises(ValueError, match="affordable_share"):
        parse.parse_affordability(path)


def test_parse_table4(tmp_path):
    rows = [
        ("Table 4: Highest and lowest", None, None, None, None),
        ("Highest median rents", None, None, "Lowest median rents", None),
        ("2 bedroom flat", None, None, "2 bedroom flat", None),
        ("Metropolitan Melbourne", None, None, "Metropolitan Melbourne", None),
        ("Docklands", 763, None, "Melton", 365),
        ("Regional Victoria", None, None, "Regional Victoria", None),
        ("Geelong-Newcomb", 460, None, "Horsham", 320),
        (None, None, None, "Portland", 350),
    ]
    path = write_book(tmp_path / "t.xlsx", {"Table 4": rows})
    t = parse.parse_table4(path)
    assert len(t) == 5
    row = t[t.suburb == "Geelong-Newcombe"].iloc[0]
    assert (row.dwelling, row.metro, row.side, row.published_median) == ("2br_flat", False, "highest", 460)
    assert t[t.suburb == "Portland"].iloc[0].side == "lowest"
