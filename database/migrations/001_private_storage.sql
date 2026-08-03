-- Credit Friendly Homes private operational storage.
-- Run this once in the Supabase SQL Editor.

create table if not exists public.cfh_properties (
    property_id uuid primary key,
    status text not null,
    address text not null,
    city text not null,
    state text not null,
    zip_code text not null,
    bedrooms integer,
    monthly_payment numeric,
    down_payment numeric,
    payload jsonb not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists cfh_properties_market_idx
    on public.cfh_properties (state, city, status);

create index if not exists cfh_properties_payment_idx
    on public.cfh_properties (monthly_payment, down_payment);

create table if not exists public.cfh_buyers (
    buyer_id uuid primary key,
    first_name text not null,
    last_name text not null default '',
    email text not null default '',
    phone text not null default '',
    do_not_contact boolean not null default false,
    payload jsonb not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists cfh_buyers_contact_idx
    on public.cfh_buyers (email, phone);

alter table public.cfh_properties enable row level security;
alter table public.cfh_buyers enable row level security;

revoke all on table public.cfh_properties from anon, authenticated;
revoke all on table public.cfh_buyers from anon, authenticated;

grant select, insert, update, delete on table public.cfh_properties to service_role;
grant select, insert, update, delete on table public.cfh_buyers to service_role;

create or replace function public.cfh_set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists cfh_properties_set_updated_at on public.cfh_properties;
create trigger cfh_properties_set_updated_at
before update on public.cfh_properties
for each row execute function public.cfh_set_updated_at();

drop trigger if exists cfh_buyers_set_updated_at on public.cfh_buyers;
create trigger cfh_buyers_set_updated_at
before update on public.cfh_buyers
for each row execute function public.cfh_set_updated_at();
