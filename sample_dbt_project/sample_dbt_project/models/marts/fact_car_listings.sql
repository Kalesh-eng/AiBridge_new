{{ config(materialized='table') }}

select
    l.listing_id,
    dc.car_key,
    ds.seller_key,
    l.list_price as price,
    l.listed_date
from {{ ref('stg_listing') }} l
left join {{ ref('dim_car') }} dc on l.car_id = dc.car_key
left join {{ ref('dim_seller') }} ds on l.seller_id = ds.seller_key
