{{ config(materialized='table') }}

select
    seller_id,
    seller_name,
    seller_type_cd
from {{ source('raw', 'src_seller') }}
