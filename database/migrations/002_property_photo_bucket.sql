-- Public marketing-photo bucket for Credit Friendly Homes properties.
-- Run this once in the Supabase SQL Editor after 001_private_storage.sql.

insert into storage.buckets (
    id,
    name,
    public,
    file_size_limit,
    allowed_mime_types
)
values (
    'cfh-property-photos',
    'cfh-property-photos',
    true,
    10485760,
    array['image/jpeg', 'image/png', 'image/webp']
)
on conflict (id) do update
set
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

-- Public downloads are intentional because these photos are used in property marketing.
-- Uploads and deletes still occur only through the server-side Supabase secret key.
