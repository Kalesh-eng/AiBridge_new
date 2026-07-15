{{ config(materialized='table') }}

select
    listing_id,
    car_id,
    seller_id,
    list_price,
    listed_date
from {{ source('raw', 'src_listing') }}
