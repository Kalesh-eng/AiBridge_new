{{ config(materialized='table') }}

select
    c.car_id as car_key,
    m.make_name as brand,
    c.model_name as model,
    c.model_year as model_year,
    c.fuel_type as fuel_type,
    case
        when c.model_year >= 2020 then 'New'
        when c.model_year >= 2015 then 'Recent'
        else 'Older'
    end as age_bracket
from {{ ref('stg_car') }} c
left join {{ ref('stg_car_make') }} m
    on c.make_code = m.make_code
