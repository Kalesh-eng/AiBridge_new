{{ config(materialized='table') }}

select
    seller_id as seller_key,
    seller_name,
    case seller_type_cd
        when 'D' then 'Dealer'
        when 'P' then 'Private'
        else 'Unknown'
    end as seller_type
from {{ ref('stg_seller') }}
