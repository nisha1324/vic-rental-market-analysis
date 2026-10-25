-- Affordability: where lower-income renters are being priced out, and where
-- affordable new leases are still found.
--
-- Inputs (loaded by rentals/growth.py):
--   lga_affordability          workbook series by LGA and bedroom count, to Sep 2024
--   lga_affordability_latest   Table 14 of the Sep 2025 report: the same measures, Sep 2025
--   affordability_thresholds   Table 9: the household each bedroom count stands for and
--                              the most it can pay (30% of income), Sep 2025
--   affordability_state_revised  Figure 8 source: Victoria / metro / regional share, all
--                              bedrooms, for the last 21 quarters as published in Sep 2025
--
-- "Affordable" is Homes Victoria's measure: a new lease whose rent is no more
-- than 30% of the income of a household on Centrelink payments of the size
-- that bedroom count suits (a single on JobSeeker for 1 bedroom, a couple with
-- two children for 3). The thresholds move with those payments, so the share
-- falls when rents outrun Centrelink incomes, not just when rents rise.
--
-- Comparisons are September with September (the share is seasonal: December
-- quarters run higher), from Sep 2019, the last pre-COVID quarter used in Part 2.

create or replace table affordability_quarters as
select
    (select start_q from windows where "window" = 'since_2019') as base_q,
    (select max(quarter) from lga_affordability_latest) as latest_q,
    (select max(quarter) from lga_affordability) as workbook_q;

-- The workbook's newest quarter was revised in the later report (see the
-- audit). The largest upward revision is used below as an allowance for the
-- same thing happening to the latest quarter, which is the newest in its release.
create or replace table affordability_revision as
select
    r.area,
    r.quarter,
    w.affordable_share as workbook_share,
    r.affordable_share as later_share,
    r.affordable_share - w.affordable_share as revision
from affordability_state_revised r
join affordability_quarters q on r.quarter = q.workbook_q
join lga_affordability w on w.row_type = r.area and w.dwelling = 'all' and w.quarter = r.quarter;

create or replace table affordability_allowance as
select coalesce(greatest(max(revision), 0), 0) as allowance from affordability_revision;

-- State, metro and regional share since 2000: the workbook up to the quarter
-- before its newest, then the later report's (revised) figures.
create or replace table affordability_trend as
select a.quarter, a.row_type as area, a.affordable_share, 'workbook' as source, false as provisional
from lga_affordability a, affordability_quarters q
where a.dwelling = 'all' and a.row_type in ('victoria', 'metro', 'non_metro') and a.quarter < q.workbook_q
union all
select r.quarter, r.area, r.affordable_share, 'later report', r.quarter = q.latest_q
from affordability_state_revised r, affordability_quarters q
where r.quarter >= q.workbook_q;

-- By bedroom count and area, Sep 2019 against the latest quarter.
create or replace table affordability_by_bedroom as
select
    t.dwelling,
    t.household,
    t.affordable_rent,
    t.area,
    b.affordable_lettings as base_affordable,
    b.affordable_share as base_share,
    t.affordable_lettings as latest_affordable,
    t.affordable_share as latest_share,
    t.affordable_share - b.affordable_share as change
from affordability_thresholds t
cross join affordability_quarters q
join lga_affordability b on b.row_type = t.area and b.dwelling = t.dwelling and b.quarter = q.base_q;

-- New leases per LGA, bedroom count and quarter, from the rents workbook, used
-- as the sample size behind each share. The affordability workbook doesn't
-- publish its denominator; this count is a little smaller (it leaves out
-- leases with no bedroom count, and suppressed cells add nothing), so the
-- margins below err on the wide side.
create or replace table lga_bedroom_leases as
with bedrooms(dwelling, bedrooms) as (
    values ('1br_flat', '1br'), ('2br_flat', '2br'), ('2br_house', '2br'),
           ('3br_flat', '3br'), ('3br_house', '3br'), ('4br_house', '4br'), ('all', 'all')
)
select r.lga, any_value(r.region) as region, b.bedrooms as dwelling, r.quarter,
       coalesce(sum(r.lettings), 0) as leases
from lga_rents r
join bedrooms b using (dwelling)
where r.row_type = 'lga'
group by r.lga, b.bedrooms, r.quarter;

-- Change in the affordable share by LGA and bedroom count.
--   well_sampled  at least min_lettings new leases at both ends (as in Part 2)
--   margin        95% sampling margin on the change (two independent shares)
--   clear_fall    the fall is bigger than the margin even if the latest share
--                 is later revised up by the allowance
create or replace table lga_affordability_change as
select
    e.lga,
    e.metro,
    ne.region,
    e.dwelling,
    b.affordable_lettings as base_affordable,
    b.affordable_share as base_share,
    e.affordable_lettings as latest_affordable,
    e.affordable_share as latest_share,
    nb.leases as base_leases,
    ne.leases as latest_leases,
    e.affordable_share - b.affordable_share as change,
    e.affordable_lettings - b.affordable_lettings as change_affordable,
    1.96 * sqrt(b.affordable_share * (1 - b.affordable_share) / nullif(nb.leases, 0)
              + e.affordable_share * (1 - e.affordable_share) / nullif(ne.leases, 0)) as margin,
    least(nb.leases, ne.leases) >= getvariable('min_lettings') as well_sampled
from lga_affordability_latest e
cross join affordability_quarters q
join lga_affordability b on b.lga = e.lga and b.dwelling = e.dwelling and b.row_type = 'lga'
                        and b.quarter = q.base_q
join lga_bedroom_leases nb on nb.lga = e.lga and nb.dwelling = e.dwelling and nb.quarter = q.base_q
join lga_bedroom_leases ne on ne.lga = e.lga and ne.dwelling = e.dwelling and ne.quarter = q.latest_q
where e.row_type = 'lga';

alter table lga_affordability_change add column clear_fall boolean;
alter table lga_affordability_change add column clear_rise boolean;
update lga_affordability_change set
    clear_fall = change + (select allowance from affordability_allowance) < -margin,
    clear_rise = change > margin;

-- Where the affordable new leases are: each LGA's part of the state's
-- affordable lettings (all bedrooms), then and now.
create or replace table affordable_concentration as
with both_ends as (
    select 'base' as period, a.quarter, a.lga, a.affordable_lettings
    from lga_affordability a, affordability_quarters q
    where a.row_type = 'lga' and a.dwelling = 'all' and a.quarter = q.base_q
    union all
    select 'latest', quarter, lga, affordable_lettings
    from lga_affordability_latest
    where row_type = 'lga' and dwelling = 'all'
)
select
    period,
    quarter,
    lga,
    affordable_lettings,
    affordable_lettings / sum(affordable_lettings) over (partition by period) as share_of_state,
    row_number() over (partition by period order by affordable_lettings desc, lga) as position,
    sum(affordable_lettings) over (partition by period order by affordable_lettings desc, lga
                                   rows unbounded preceding)
        / sum(affordable_lettings) over (partition by period) as cumulative_share
from both_ends;

-- The latest median rent by LGA and dwelling type against the most the
-- matching household can pay. Thresholds are state-wide, so the 'victoria'
-- row of Table 9 is used for every area.
create or replace table rent_vs_threshold as
with bedrooms(dwelling, bedrooms) as (
    values ('1br_flat', '1br'), ('2br_flat', '2br'), ('2br_house', '2br'),
           ('3br_flat', '3br'), ('3br_house', '3br'), ('4br_house', '4br')
)
select
    r.lga,
    r.region,
    r.row_type,
    r.dwelling,
    b.bedrooms,
    t.household,
    t.affordable_rent,
    r.lettings,
    r.median_rent,
    r.median_rent - t.affordable_rent as gap,
    r.median_rent <= t.affordable_rent as affordable_at_median,
    l.affordable_share as bedroom_affordable_share
from lga_rents r
cross join affordability_quarters q
join bedrooms b using (dwelling)
join affordability_thresholds t on t.dwelling = b.bedrooms and t.area = 'victoria'
left join lga_affordability_latest l on l.lga = r.lga and l.dwelling = b.bedrooms and l.row_type = 'lga'
where r.row_type in ('lga', 'victoria', 'metro', 'non_metro') and r.quarter = q.latest_q;

-- Part 2's fastest-rising regional towns (top 10 since Sep 2019 for 2-bed
-- flats or 3-bed houses) and the LGA each sits in. The rental report doesn't
-- map its towns to LGAs, so this is by hand; a test fails if a town in the
-- top 10 has no entry here.
create or replace table town_lga as
select * from (values
    ('Glenelg', 'Portland'),
    ('Greater Bendigo', 'North Bendigo'),
    ('Greater Shepparton', 'Shepparton'),
    ('Latrobe', 'Moe-Newborough'),
    ('Latrobe', 'Morwell'),
    ('Latrobe', 'Traralgon'),
    ('Mildura', 'Mildura'),
    ('Wangaratta', 'Wangaratta'),
    ('Warrnambool', 'Warrnambool'),
    ('Wellington', 'Sale-Maffra'),
    ('Wodonga', 'Wodonga')
) as t(lga, suburb);

create or replace table fast_riser_lgas as
select
    s.dwelling as town_dwelling,
    s.suburb,
    s.rank_fastest,
    s.growth as town_growth,
    m.lga,
    c.base_share,
    c.latest_share,
    c.change,
    c.margin,
    c.well_sampled,
    c.clear_fall
from suburb_ranking s
left join town_lga m using (suburb)
left join lga_affordability_change c on c.lga = m.lga and c.dwelling = 'all'
where s."window" = 'since_2019' and not s.metro and s.rank_fastest <= 10
  and s.dwelling in ('2br_flat', '3br_house');

-- LGA rent growth (all properties, single-quarter medians) next to the change
-- in the affordable share, for well-sampled LGAs.
create or replace table lga_rent_and_affordability as
select
    c.lga,
    c.metro,
    c.base_share,
    c.latest_share,
    c.change,
    rb.median_rent as base_rent,
    re.median_rent as latest_rent,
    re.median_rent / rb.median_rent - 1 as rent_growth
from lga_affordability_change c
cross join affordability_quarters q
join lga_rents rb on rb.lga = c.lga and rb.dwelling = 'all' and rb.row_type = 'lga' and rb.quarter = q.base_q
join lga_rents re on re.lga = c.lga and re.dwelling = 'all' and re.row_type = 'lga' and re.quarter = q.latest_q
where c.dwelling = 'all' and c.well_sampled;
