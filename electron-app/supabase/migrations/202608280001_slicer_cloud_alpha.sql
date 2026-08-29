-- Slicer Cloud alpha: two-account library sharing with least-privilege RLS.
-- Run once in a fresh Supabase project's SQL editor.

create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  handle text not null unique,
  display_name text not null,
  avatar_path text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint profiles_handle_format check (handle ~ '^[a-z0-9][a-z0-9_-]{2,31}$'),
  constraint profiles_display_name_length check (char_length(display_name) between 1 and 64)
);

create table if not exists public.connections (
  id uuid primary key default gen_random_uuid(),
  requester_id uuid not null references public.profiles(id) on delete cascade,
  addressee_id uuid not null references public.profiles(id) on delete cascade,
  status text not null default 'pending',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint connections_distinct_people check (requester_id <> addressee_id),
  constraint connections_status check (status in ('pending', 'accepted', 'declined'))
);

create unique index if not exists connections_unique_pair
  on public.connections (least(requester_id, addressee_id), greatest(requester_id, addressee_id));

create table if not exists public.cloud_libraries (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(id) on delete cascade,
  name text not null,
  source_fingerprint text not null,
  manifest_version integer not null default 1,
  status text not null default 'uploading',
  layer_count integer not null default 0,
  loop_count integer not null default 0,
  total_bytes bigint not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint cloud_libraries_name_length check (char_length(name) between 1 and 120),
  constraint cloud_libraries_status check (status in ('uploading', 'ready', 'failed', 'archived')),
  constraint cloud_libraries_nonnegative_counts check (layer_count >= 0 and loop_count >= 0 and total_bytes >= 0)
);

create index if not exists cloud_libraries_owner_status
  on public.cloud_libraries(owner_id, status);

create table if not exists public.cloud_layers (
  id uuid primary key default gen_random_uuid(),
  library_id uuid not null references public.cloud_libraries(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete cascade,
  object_path text not null unique,
  file_name text not null,
  relative_path text not null,
  sha256 text not null,
  byte_size bigint not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint cloud_layers_positive_size check (byte_size > 0),
  constraint cloud_layers_sha256_format check (sha256 ~ '^[0-9a-f]{64}$')
);

create index if not exists cloud_layers_library_id on public.cloud_layers(library_id);
create index if not exists cloud_layers_owner_id on public.cloud_layers(owner_id);
create index if not exists cloud_layers_category on public.cloud_layers((metadata ->> 'category'));

-- Lineage tables are included now so the alpha can preserve provenance without
-- exposing it in the interface until the workflow is ready.
create table if not exists public.generation_runs (
  id uuid primary key default gen_random_uuid(),
  created_by uuid not null references public.profiles(id) on delete cascade,
  contributor_ids uuid[] not null default '{}',
  seed bigint not null,
  target_bpm integer not null,
  target_key text not null,
  layer_count integer not null,
  created_at timestamptz not null default now(),
  constraint generation_runs_layer_count check (layer_count > 0)
);

create table if not exists public.generation_sources (
  id uuid primary key default gen_random_uuid(),
  generation_id uuid not null references public.generation_runs(id) on delete cascade,
  slot_index integer not null,
  cloud_layer_id uuid references public.cloud_layers(id) on delete set null,
  source_owner_id uuid references public.profiles(id) on delete set null,
  source_sha256 text not null,
  source_loop_id text not null,
  category text not null,
  created_at timestamptz not null default now(),
  constraint generation_sources_slot_index check (slot_index >= 0),
  unique(generation_id, slot_index)
);

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists profiles_touch_updated_at on public.profiles;
create trigger profiles_touch_updated_at
before update on public.profiles
for each row execute function public.touch_updated_at();

drop trigger if exists connections_touch_updated_at on public.connections;
create trigger connections_touch_updated_at
before update on public.connections
for each row execute function public.touch_updated_at();

drop trigger if exists cloud_libraries_touch_updated_at on public.cloud_libraries;
create trigger cloud_libraries_touch_updated_at
before update on public.cloud_libraries
for each row execute function public.touch_updated_at();

create or replace function public.protect_connection_members()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if new.requester_id <> old.requester_id or new.addressee_id <> old.addressee_id then
    raise exception 'Connection members cannot be changed';
  end if;
  return new;
end;
$$;

drop trigger if exists connections_protect_members on public.connections;
create trigger connections_protect_members
before update on public.connections
for each row execute function public.protect_connection_members();

create or replace function public.are_connected(first_user uuid, second_user uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.connections connection
    where connection.status = 'accepted'
      and (
        (connection.requester_id = first_user and connection.addressee_id = second_user)
        or
        (connection.requester_id = second_user and connection.addressee_id = first_user)
      )
  );
$$;

create or replace function public.can_access_cloud_library(requested_library uuid, viewer uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.cloud_libraries library
    where library.id = requested_library
      and library.status = 'ready'
      and (
        library.owner_id = viewer
        or public.are_connected(library.owner_id, viewer)
      )
  );
$$;

create or replace function public.can_access_cloud_object(requested_object text, viewer uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.cloud_layers layer
    where layer.object_path = requested_object
      and public.can_access_cloud_library(layer.library_id, viewer)
  );
$$;

revoke all on function public.are_connected(uuid, uuid) from public;
revoke all on function public.can_access_cloud_library(uuid, uuid) from public;
revoke all on function public.can_access_cloud_object(text, uuid) from public;
grant execute on function public.are_connected(uuid, uuid) to authenticated;
grant execute on function public.can_access_cloud_library(uuid, uuid) to authenticated;
grant execute on function public.can_access_cloud_object(text, uuid) to authenticated;

alter table public.profiles enable row level security;
alter table public.connections enable row level security;
alter table public.cloud_libraries enable row level security;
alter table public.cloud_layers enable row level security;
alter table public.generation_runs enable row level security;
alter table public.generation_sources enable row level security;

revoke all on public.profiles, public.connections, public.cloud_libraries,
  public.cloud_layers, public.generation_runs, public.generation_sources from anon;

grant select, insert, update on public.profiles to authenticated;
grant select, insert, update on public.connections to authenticated;
grant select, insert, update, delete on public.cloud_libraries to authenticated;
grant select, insert, update, delete on public.cloud_layers to authenticated;
grant select, insert on public.generation_runs to authenticated;
grant select, insert on public.generation_sources to authenticated;

drop policy if exists profiles_authenticated_read on public.profiles;
create policy profiles_authenticated_read
on public.profiles for select to authenticated
using (true);

drop policy if exists profiles_insert_self on public.profiles;
create policy profiles_insert_self
on public.profiles for insert to authenticated
with check (id = auth.uid());

drop policy if exists profiles_update_self on public.profiles;
create policy profiles_update_self
on public.profiles for update to authenticated
using (id = auth.uid())
with check (id = auth.uid());

drop policy if exists connections_members_read on public.connections;
create policy connections_members_read
on public.connections for select to authenticated
using (requester_id = auth.uid() or addressee_id = auth.uid());

drop policy if exists connections_request on public.connections;
create policy connections_request
on public.connections for insert to authenticated
with check (requester_id = auth.uid() and addressee_id <> auth.uid() and status = 'pending');

drop policy if exists connections_addressee_reply on public.connections;
create policy connections_addressee_reply
on public.connections for update to authenticated
using (addressee_id = auth.uid() and status = 'pending')
with check (addressee_id = auth.uid() and status in ('accepted', 'declined'));

drop policy if exists cloud_libraries_connected_read on public.cloud_libraries;
create policy cloud_libraries_connected_read
on public.cloud_libraries for select to authenticated
using (owner_id = auth.uid() or public.are_connected(owner_id, auth.uid()));

drop policy if exists cloud_libraries_owner_insert on public.cloud_libraries;
create policy cloud_libraries_owner_insert
on public.cloud_libraries for insert to authenticated
with check (owner_id = auth.uid());

drop policy if exists cloud_libraries_owner_update on public.cloud_libraries;
create policy cloud_libraries_owner_update
on public.cloud_libraries for update to authenticated
using (owner_id = auth.uid())
with check (owner_id = auth.uid());

drop policy if exists cloud_libraries_owner_delete on public.cloud_libraries;
create policy cloud_libraries_owner_delete
on public.cloud_libraries for delete to authenticated
using (owner_id = auth.uid());

drop policy if exists cloud_layers_connected_read on public.cloud_layers;
create policy cloud_layers_connected_read
on public.cloud_layers for select to authenticated
using (public.can_access_cloud_library(library_id, auth.uid()));

drop policy if exists cloud_layers_owner_insert on public.cloud_layers;
create policy cloud_layers_owner_insert
on public.cloud_layers for insert to authenticated
with check (
  owner_id = auth.uid()
  and exists (
    select 1 from public.cloud_libraries library
    where library.id = library_id and library.owner_id = auth.uid()
  )
);

drop policy if exists cloud_layers_owner_update on public.cloud_layers;
create policy cloud_layers_owner_update
on public.cloud_layers for update to authenticated
using (owner_id = auth.uid())
with check (owner_id = auth.uid());

drop policy if exists cloud_layers_owner_delete on public.cloud_layers;
create policy cloud_layers_owner_delete
on public.cloud_layers for delete to authenticated
using (owner_id = auth.uid());

drop policy if exists generation_runs_participant_read on public.generation_runs;
create policy generation_runs_participant_read
on public.generation_runs for select to authenticated
using (created_by = auth.uid() or auth.uid() = any(contributor_ids));

drop policy if exists generation_runs_creator_insert on public.generation_runs;
create policy generation_runs_creator_insert
on public.generation_runs for insert to authenticated
with check (created_by = auth.uid());

drop policy if exists generation_sources_participant_read on public.generation_sources;
create policy generation_sources_participant_read
on public.generation_sources for select to authenticated
using (
  exists (
    select 1 from public.generation_runs run
    where run.id = generation_id
      and (run.created_by = auth.uid() or auth.uid() = any(run.contributor_ids))
  )
);

drop policy if exists generation_sources_creator_insert on public.generation_sources;
create policy generation_sources_creator_insert
on public.generation_sources for insert to authenticated
with check (
  exists (
    select 1 from public.generation_runs run
    where run.id = generation_id and run.created_by = auth.uid()
  )
);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'cloud-layers',
  'cloud-layers',
  false,
  50000000,
  array[
    'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav',
    'audio/aiff', 'audio/x-aiff', 'audio/flac', 'audio/mp4',
    'audio/x-m4a', 'application/octet-stream'
  ]
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists cloud_layers_storage_owner_insert on storage.objects;
create policy cloud_layers_storage_owner_insert
on storage.objects for insert to authenticated
with check (
  bucket_id = 'cloud-layers'
  and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists cloud_layers_storage_connected_read on storage.objects;
create policy cloud_layers_storage_connected_read
on storage.objects for select to authenticated
using (
  bucket_id = 'cloud-layers'
  and (
    (storage.foldername(name))[1] = auth.uid()::text
    or public.can_access_cloud_object(name, auth.uid())
  )
);

drop policy if exists cloud_layers_storage_owner_delete on storage.objects;
create policy cloud_layers_storage_owner_delete
on storage.objects for delete to authenticated
using (
  bucket_id = 'cloud-layers'
  and (storage.foldername(name))[1] = auth.uid()::text
);

