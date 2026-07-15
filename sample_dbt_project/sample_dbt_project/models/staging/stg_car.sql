{{ config(materialized='table') }}

select
    car_id,
    make_code,
    model_name,
    model_year,
    fuel_type
from {{ source('raw', 'src_car') }}
