-- State-wide headline: Victoria, metropolitan and non-metropolitan medians.
--
-- These rows come from the quarterly LGA workbook (the suburb workbook has no
-- state total). They are medians of leases signed in that quarter only, so
-- the windows compare September quarter with September quarter (no seasonal
-- mismatch) and deflate by that quarter's CPI rather than a 4-quarter average.

create or replace table state_growth as
select
    e.dwelling,
    e.row_type as area,
    w."window",
    b.median_rent as start_rent,
    e.median_rent as end_rent,
    b.lettings as start_lettings,
    e.lettings as end_lettings,
    e.median_rent / b.median_rent - 1 as growth,
    pow(e.median_rent / b.median_rent, 1 / w.years) - 1 as growth_pa,
    (e.median_rent / ce.cpi) / (b.median_rent / cb.cpi) - 1 as real_growth
from windows w
join lga_rents b on b.quarter = w.start_q
join lga_rents e on e.quarter = w.end_q
                and e.dwelling = b.dwelling
                and e.row_type = b.row_type
join cpi cb on cb.quarter = w.start_q
join cpi ce on ce.quarter = w.end_q
where b.row_type in ('victoria', 'metro', 'non_metro');
