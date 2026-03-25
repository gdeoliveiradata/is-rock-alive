with source as (
    select * from {{ source('is_rock_alive', 'event_raw') }}
)

select * from source