-- Rent growth by region, from the Group Total rows.
--
-- The audit showed region totals must come from the published Group Total
-- rows: suppressed suburbs still count towards them, so summing suburbs
-- undercounts. A median can't be rebuilt from suburb medians anyway.
-- Region totals rest on hundreds or thousands of leases, so no floor needed.
--
-- `band` groups the 13 Homes Victoria regions three ways for the summary:
-- Inner Melbourne on its own (the CBD fringe, where the COVID dip was
-- deepest), the other 8 metro regions, and the 4 regional ones.

create or replace table region_growth as
select
    e.dwelling,
    e.region,
    e.metro,
    case when e.region = 'Inner Melbourne' then 'Inner Melbourne'
         when e.metro then 'Rest of Melbourne'
         else 'Regional Victoria' end as band,
    w."window",
    b.median_rent as start_rent,
    e.median_rent as end_rent,
    b.lettings as start_lettings,
    e.lettings as end_lettings,
    e.median_rent / b.median_rent - 1 as growth,
    pow(e.median_rent / b.median_rent, 1 / w.years) - 1 as growth_pa,
    (e.median_rent / ce.cpi_annual) / (b.median_rent / cb.cpi_annual) - 1 as real_growth
from windows w
join suburb_rents b on b.quarter = w.start_q
join suburb_rents e on e.quarter = w.end_q
                   and e.dwelling = b.dwelling
                   and e.region = b.region
                   and e.row_type = b.row_type
join cpi_annual cb on cb.quarter = w.start_q
join cpi_annual ce on ce.quarter = w.end_q
where b.row_type = 'group_total';

-- Each region's path since Sep 2019 as an index (Sep 2019 = 100), next to
-- CPI on the same basis, plus the low point: how far rents fell during
-- COVID and when they bottomed out.
create or replace table region_index as
with base as (
    select dwelling, region, median_rent as base_rent
    from suburb_rents
    where row_type = 'group_total' and quarter = date '2019-09-30'
)
select
    s.dwelling,
    s.region,
    s.metro,
    s.quarter,
    s.median_rent,
    100 * s.median_rent / base.base_rent as rent_index,
    100 * c.cpi_annual / c0.cpi_annual as cpi_index
from suburb_rents s
join base using (dwelling, region)
join cpi_annual c on c.quarter = s.quarter
join cpi_annual c0 on c0.quarter = date '2019-09-30'
where s.row_type = 'group_total' and s.quarter >= date '2019-09-30';

create or replace view region_low_point as
with low as (
    select dwelling, region, min(rent_index) as low_index
    from region_index
    group by dwelling, region
), low_quarter as (
    -- earliest quarter at the low, if the low was hit more than once
    select r.dwelling, r.region, l.low_index, min(r.quarter) as low_quarter
    from region_index r
    join low l on l.dwelling = r.dwelling and l.region = r.region and r.rent_index = l.low_index
    group by all
)
select
    l.dwelling,
    l.region,
    l.low_index - 100 as low_vs_2019,  -- index points = % below Sep 2019
    l.low_quarter,
    -- first quarter after the low with rents back at or above Sep 2019
    -- (null if rents never fell below Sep 2019)
    case when l.low_index < 100 then (
        select min(r.quarter) from region_index r
        where r.dwelling = l.dwelling and r.region = l.region
          and r.quarter > l.low_quarter and r.rent_index >= 100
    ) end as back_above_2019
from low_quarter l;
