-- Market activity: where new leases are being signed, whether new building
-- explains it, and what that did to rents and to affordable leases.
--
-- Inputs (loaded by rentals/growth.py), besides the rents and affordability tables:
--   dwelling_approvals   ABS new dwelling units approved per LGA and quarter, Sep 2018 on
--   census_dwellings     ABS Census 2021 total private dwellings per LGA
--
-- A new lease is a bond lodged with the RTBA, so the count measures new
-- tenancies: newly built rentals, but also existing rentals changing tenant.
-- A fall can mean fewer rentals or tenants moving less; the count alone can't
-- tell the two apart, which is why the approvals are brought in.
--
-- Volumes are 12-month sums (the four quarters to each date), which removes
-- the seasonal swing; affordability is published for single quarters, so the
-- decomposition at the end uses the September quarters as Part 3 does.

-- The periods. Leases: the 12 months to Sep 2019 (pre-COVID, as in Parts 2
-- and 3) against the 12 months to the latest quarter. Approvals: from July
-- 2018 to 15 months before the latest quarter (June 2024), so most dwellings
-- approved in the window were finished and could be let by Sep 2025; a later
-- window is kept as a check on that choice.
create or replace table activity_periods as
select
    (select start_q from windows where "window" = 'since_2019') as base_q,
    (select end_q from windows where "window" = 'since_2019') as latest_q,
    date '2018-09-30' as approvals_from,
    ((select end_q from windows where "window" = 'since_2019') - interval 15 month)::date as approvals_to,
    date '2019-09-30' as late_from,
    ((select end_q from windows where "window" = 'since_2019') - interval 3 month)::date as late_to;

-- Melbourne's seven growth-area councils (Victorian Planning Authority), where
-- most new suburbs are being built. Mitchell is "regional" in the rental
-- report but is one of the seven, so it is grouped here.
create or replace table growth_area as
select * from (values ('Cardinia'), ('Casey'), ('Hume'), ('Melton'), ('Mitchell'),
                      ('Whittlesea'), ('Wyndham')) as t(lga);

create or replace table lga_group as
select
    l.lga,
    l.metro,
    case when g.lga is not null then 'Growth areas'
         when l.lga = 'Melbourne' then 'City of Melbourne'
         when l.metro then 'Rest of Melbourne'
         else 'Rest of regional Victoria' end as "group"
from (select distinct lga, metro from lga_affordability_latest where row_type = 'lga') l
left join growth_area g using (lga);

-- 12-month new leases (all properties) per LGA and for the state, metro and
-- regional totals. Null unless all four quarters are published.
create or replace table annual_leases as
select
    row_type,
    lga,
    quarter,
    case when count(lettings) over w4 = 4 then sum(lettings) over w4 end as leases_12m
from lga_rents
where dwelling = 'all' and row_type in ('lga', 'victoria', 'metro', 'non_metro')
window w4 as (partition by row_type, lga order by quarter rows between 3 preceding and current row)
qualify count(*) over w4 = 4;

-- By group, indexed to the 12 months to Sep 2019 = 100. sum() skips suppressed
-- LGA cells, so they count as 0 (a handful of leases in tiny LGAs).
create or replace table group_leases as
with q as (
    select g."group", r.quarter, sum(r.lettings) as leases
    from lga_rents r join lga_group g using (lga)
    where r.dwelling = 'all' and r.row_type = 'lga'
    group by g."group", r.quarter
), a as (
    select "group", quarter, sum(leases) over w4 as leases_12m
    from q
    window w4 as (partition by "group" order by quarter rows between 3 preceding and current row)
    qualify count(*) over w4 = 4
)
select
    a."group",
    a.quarter,
    a.leases_12m,
    100.0 * a.leases_12m / b.leases_12m as index_2019
from a
join a b on b."group" = a."group" and b.quarter = (select base_q from activity_periods);

-- Dwellings approved per LGA in the two windows, and the main window as a
-- share of the LGA's 2021 dwelling count: how much the place has been adding.
create or replace table lga_approvals as
select
    a.lga,
    sum(a.approvals) filter (where a.quarter between p.approvals_from and p.approvals_to) as approvals,
    count(*) filter (where a.quarter between p.approvals_from and p.approvals_to) as approval_quarters,
    sum(a.approvals) filter (where a.quarter between p.late_from and p.late_to) as approvals_late,
    any_value(c.dwellings_2021) as dwellings_2021
from dwelling_approvals a
cross join activity_periods p
join census_dwellings c using (lga)
group by a.lga;

alter table lga_approvals add column approval_rate double;
alter table lga_approvals add column approval_rate_late double;
update lga_approvals set approval_rate = approvals / dwellings_2021,
                         approval_rate_late = approvals_late / dwellings_2021;

-- One row per LGA: new leases then and now, building, rent growth and the
-- change in the affordable share (Part 3), for the LGAs Part 3 ranked
-- (well_sampled: at least min_lettings new leases in both September quarters).
create or replace table lga_activity as
select
    g.lga,
    g.metro,
    g."group",
    b.leases_12m as base_leases_12m,
    e.leases_12m as latest_leases_12m,
    e.leases_12m - b.leases_12m as lease_change,
    e.leases_12m / b.leases_12m - 1 as lease_growth,
    ap.approvals,
    ap.approvals_late,
    ap.dwellings_2021,
    ap.approval_rate,
    ap.approval_rate_late,
    re.median_rent / rb.median_rent - 1 as rent_growth,
    c.change as affordable_change,
    c.clear_rise as affordable_clear_rise,
    c.clear_fall as affordable_clear_fall,
    coalesce(c.well_sampled, false) as well_sampled
from lga_group g
cross join activity_periods p
left join annual_leases b on b.row_type = 'lga' and b.lga = g.lga and b.quarter = p.base_q
left join annual_leases e on e.row_type = 'lga' and e.lga = g.lga and e.quarter = p.latest_q
left join lga_approvals ap on ap.lga = g.lga
left join lga_rents rb on rb.lga = g.lga and rb.dwelling = 'all' and rb.row_type = 'lga' and rb.quarter = p.base_q
left join lga_rents re on re.lga = g.lga and re.dwelling = 'all' and re.row_type = 'lga' and re.quarter = p.latest_q
left join lga_affordability_change c on c.lga = g.lga and c.dwelling = 'all';

-- Each LGA's part of the change in Victoria's new leases, and of the
-- dwellings approved.
create or replace table lga_activity_share as
select
    lga,
    "group",
    lease_change,
    lease_change / sum(lease_change) filter (where lease_change > 0) over () as share_of_gains,
    approvals / sum(approvals) over () as share_of_approvals
from lga_activity
where lease_change is not null;

-- Why did affordable leases rise? Split the change in the number of
-- affordable new leases (A = share s x leases N, September quarters) into
--   volume effect  more (or fewer) new leases at the average share
--   share effect   a higher (or lower) share of the average number of leases
-- The two add up exactly to the change. N is the share's own denominator,
-- recovered as A / s from the published count and share (the share is
-- rounded to 0.1%, so N is good to about 0.1% when s is large), so only
-- rows with a share of at least 5% at both ends are used.
create or replace table affordable_decomposition as
with ends as (
    select c.lga, c.metro, c.base_affordable as a0, c.latest_affordable as a1,
           c.base_share as s0, c.latest_share as s1, c.well_sampled, c.clear_rise, c.clear_fall
    from lga_affordability_change c
    where c.dwelling = 'all' and c.base_share >= 0.05 and c.latest_share >= 0.05
)
select
    lga,
    metro,
    a0,
    a1,
    a1 - a0 as change_affordable,
    s0,
    s1,
    a0 / s0 as n0,
    a1 / s1 as n1,
    (a1 / s1 - a0 / s0) * (s0 + s1) / 2 as volume_effect,
    (s1 - s0) * (a0 / s0 + a1 / s1) / 2 as share_effect,
    well_sampled,
    clear_rise,
    clear_fall
from ends;
