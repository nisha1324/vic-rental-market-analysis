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


def report_tables(flag_ararat="R", fig8_date=None):
    """A report-tables workbook with Fig 8 source, Table 9 and Table 14 laid
    out like the real one (labels in the same columns, blank spacer rows)."""
    import datetime as dt
    fig8 = [("Figure 8 source:  Affordable rental dwellings", None, None, None),
            (None, None, None, None),
            (None, "Victoria\n%", "Metro\n%", "Regional\n%"),
            (dt.datetime(2025, 6, 1), 0.155, 0.102, 0.387),
            (fig8_date or dt.datetime(2025, 9, 1), 0.144, 0.097, 0.364),
            (None, None, None, None)]
    t9 = [("Table 9: Rental affordability", None, None, None, None, None, None),
          (None,) * 7,
          ("Household type", None, "Single", "Parent", "Couple 2", "Couple 4", "Total"),
          ("Assumed property size", None, "1 bedroom", "2 bedroom", "3 bedroom", "4+ bedroom", None),
          ("Weekly income (net of RA)", None, 390.55, 728.39, 1083.9, 1347.2, None),
          ("Affordable weekly rent", None, 225, 345, 450, 545, None),
          ("Affordable rentals (number)", None, None, None, None, None, None),
          (None, "Metropolitan Melbourne", 1, 2, 3, 4, 10),
          (None, "Regional Victoria", 5, 6, 7, 8, 26),
          (None, "Victoria", 6, 8, 10, 12, 36),
          ("Affordable rentals (% of total)", None, None, None, None, None, None),
          (None, "Metropolitan Melbourne", 0.01, 0.02, 0.03, 0.04, 0.025),
          (None, "Regional Victoria", 0.1, 0.2, 0.3, 0.4, 0.25),
          (None, "Victoria", 0.02, 0.04, 0.06, 0.08, 0.05)]
    t14 = [("Table 14: Affordable rental dwellings by LGA",) + (None,) * 12,
           (None, "1 Bedroom", None, "2 Bedrooms", None, "3 Bedrooms", None, "4+ Bedrooms", None, "Total", None, None, None),
           (None, "Affordable", None, "Affordable", None, "Affordable", None, "Affordable", None, "Affordable", None, None, None),
           (None, "#", "%", "#", "%", "#", "%", "#", "%", "#", "%", None, "Metro/RV"),
           ("Alpine", 3, 0.6, 3, 0.188, 10, 0.417, 4, 0.571, 20, 0.385, None, "R"),
           ("Banyule", 0, 0, 1, 0.003, 11, 0.032, 9, 0.068, 21, 0.022, None, "M"),
           ("Queenscliff", 0, 0, 1, 0.1, 1, 0.1, 0, 0, 2, 0.05, None, flag_ararat),
           ("Total", 3, 0.1, 5, 0.01, 22, 0.05, 13, 0.1, 43, 0.04),
           (None,) * 13]
    return {"Fig 8 source": fig8, "Table 9": t9, "Table 14": t14}


def test_parse_fig8_and_report_quarter(tmp_path):
    path = write_book(tmp_path / "r.xlsx", report_tables())
    f = parse.parse_fig8(path)
    assert len(f) == 6 and set(f.area) == {"victoria", "metro", "non_metro"}
    assert parse.report_quarter(path) == pd.Timestamp("2025-09-30")
    row = f[(f.area == "non_metro") & (f.quarter == pd.Timestamp("2025-06-30"))].iloc[0]
    assert row.affordable_share == 0.387


def test_parse_fig8_rejects_non_date(tmp_path):
    path = write_book(tmp_path / "r.xlsx", report_tables(fig8_date="Sep 2025"))
    with pytest.raises(ValueError, match="unexpected date"):
        parse.parse_fig8(path)


def test_parse_table9(tmp_path):
    t = parse.parse_table9(write_book(tmp_path / "r.xlsx", report_tables())).set_index(["dwelling", "area"])
    assert len(t) == 15
    three = t.loc[("3br", "non_metro")]
    assert (three.household, three.affordable_rent, three.affordable_lettings, three.affordable_share) == \
        ("Couple 2", 450, 7, 0.3)
    assert t.loc[("4br", "victoria"), "affordable_rent"] == 545
    assert t.loc[("all", "victoria"), "affordable_lettings"] == 36
    assert math.isnan(t.loc[("all", "metro"), "affordable_rent"])
    assert (t["quarter"] == pd.Timestamp("2025-09-30")).all()


def test_parse_table14(tmp_path):
    t = parse.parse_table14(write_book(tmp_path / "r.xlsx", report_tables()))
    assert len(t) == 4 * 5
    assert set(t.loc[t.row_type == "lga", "lga"]) == {"Alpine", "Banyule", "Queenscliffe"}  # name fixed
    alpine = t[(t.lga == "Alpine") & (t.dwelling == "4br")].iloc[0]
    assert (alpine.affordable_lettings, alpine.affordable_share, alpine.metro) == (4, 0.571, False)
    assert t[(t.lga == "Banyule")].metro.all()
    vic = t[t.row_type == "victoria"].set_index("dwelling")
    assert vic.loc["all", "affordable_lettings"] == 43 and vic.loc["all", "lga"] == "Victoria"


def test_parse_table14_unknown_flag_raises(tmp_path):
    with pytest.raises(ValueError, match="Metro/RV flag"):
        parse.parse_table14(write_book(tmp_path / "r.xlsx", report_tables(flag_ararat="?")))
