{{ config(materialized='table') }}

select
    make_code,
    make_name
from {{ source('raw', 'src_car_make') }}
