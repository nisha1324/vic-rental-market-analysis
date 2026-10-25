-- Growth windows and the CPI used to deflate rents.
--
-- Inputs (loaded by rentals/growth.py): suburb_rents, lga_rents, cpi.
--
-- Every window ends in the latest quarter of the suburb series. Three
-- starting points answer different questions:
--   1y           what is happening now
--   5y           the medium term; NB for Sep 2025 this starts in Sep 2020,
--                the depth of the COVID rent dip in inner Melbourne, so it
--                flatters areas that fell then
--   since_2019   against the last quarter before COVID (the 12 months to
--                Sep 2019 are entirely pre-pandemic)

create or replace table windows as
with latest as (select max(quarter) as end_q from suburb_rents)
select
    w.name as "window",
    w.ord,
    case when w.name = 'since_2019' then date '2019-09-30'
         else (latest.end_q - to_years(w.years))::date end as start_q,
    latest.end_q
from latest, (values (1, '1y', 1), (2, '5y', 5), (3, 'since_2019', null)) as w(ord, name, years)
order by w.ord;

-- Years between the two quarters, for annualised (compound) growth.
alter table windows add column years double;
update windows set years = datediff('month', start_q, end_q) / 12.0;

-- The suburb medians are moving annual figures: the Sep 2025 number covers
-- leases that started from Oct 2024 to Sep 2025. So each one is deflated by
-- the average CPI over the same four quarters, not by the single quarter's
-- index. The LGA medians are for a single quarter and use that quarter's CPI.
create or replace table cpi_annual as
select
    quarter,
    cpi,
    avg(cpi) over w4 as cpi_annual
from cpi
window w4 as (order by quarter rows between 3 preceding and current row)
qualify count(*) over w4 = 4;
