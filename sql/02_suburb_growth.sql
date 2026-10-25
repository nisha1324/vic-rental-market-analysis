-- Rent growth by suburb, dwelling type and window.
--
-- One row per suburb x dwelling type x window where both end quarters have
-- a published median. Nothing is filtered out here; `well_sampled` marks
-- the rows that rankings may use.
--
-- Why a lease floor: a median of 15 leases can swing 50% in a quarter (see
-- results/DATA_AUDIT.md). In series with at least 100 leases at both ends of
-- a quarter, the audit found no quarterly move above 21.1%, so the floor is
-- getvariable('min_lettings') (100 by default) at BOTH ends of the window.
--
-- growth       nominal change in the median weekly rent
-- growth_pa    the same, compounded per year (comparable across windows)
-- real_growth  change after Melbourne CPI: positive means rent rose faster
--              than prices in general

create or replace table suburb_growth as
select
    e.dwelling,
    e.region,
    e.metro,
    e.suburb,
    w."window",
    w.start_q,
    w.end_q,
    b.median_rent as start_rent,
    e.median_rent as end_rent,
    b.lettings as start_lettings,
    e.lettings as end_lettings,
    e.median_rent / b.median_rent - 1 as growth,
    pow(e.median_rent / b.median_rent, 1 / w.years) - 1 as growth_pa,
    (e.median_rent / ce.cpi_annual) / (b.median_rent / cb.cpi_annual) - 1 as real_growth,
    least(b.lettings, e.lettings) >= getvariable('min_lettings') as well_sampled
from windows w
join suburb_rents b on b.quarter = w.start_q
join suburb_rents e on e.quarter = w.end_q
                   and e.dwelling = b.dwelling
                   and e.suburb = b.suburb
                   and e.region = b.region
join cpi_annual cb on cb.quarter = w.start_q
join cpi_annual ce on ce.quarter = w.end_q
where b.row_type = 'suburb'
  and b.median_rent is not null
  and e.median_rent is not null;

-- Rankings within each dwelling type and window, well-sampled rows only.
-- rank_fastest = 1 is the fastest-rising suburb.
create or replace view suburb_ranking as
select
    *,
    rank() over (partition by dwelling, "window" order by growth desc) as rank_fastest,
    rank() over (partition by dwelling, "window" order by growth asc) as rank_slowest,
    count(*) over (partition by dwelling, "window") as ranked_suburbs
from suburb_growth
where well_sampled;

-- Did rents rise fastest where they started lowest? Ranked suburbs split
-- into thirds by their rent at the start of the window (1 = cheapest).
create or replace view growth_by_start_rent as
with t as (
    select *, ntile(3) over (partition by dwelling, "window" order by start_rent, suburb) as rent_third
    from suburb_ranking
)
select
    dwelling,
    "window",
    rent_third,
    count(*) as suburbs,
    min(start_rent) as start_rent_from,
    max(start_rent) as start_rent_to,
    median(growth) as median_growth,
    count(*) filter (where not metro) as regional_suburbs
from t
group by all;
