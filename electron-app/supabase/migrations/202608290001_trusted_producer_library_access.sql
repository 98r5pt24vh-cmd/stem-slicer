-- Trusted producers can end a connection, while library owners can revoke one
-- producer's access without pausing the library for everyone else.

create table if not exists public.cloud_library_blocks (
  library_id uuid not null references public.cloud_libraries(id) on delete cascade,
  producer_id uuid not null references public.profiles(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (library_id, producer_id)
);

create index if not exists cloud_library_blocks_producer_id
  on public.cloud_library_blocks(producer_id);

alter table public.cloud_library_blocks enable row level security;

revoke all on public.cloud_library_blocks from anon;
grant select, insert, delete on public.cloud_library_blocks to authenticated;

drop policy if exists cloud_library_blocks_owner_read on public.cloud_library_blocks;
create policy cloud_library_blocks_owner_read
on public.cloud_library_blocks for select to authenticated
using (
  exists (
    select 1 from public.cloud_libraries library
    where library.id = library_id and library.owner_id = auth.uid()
  )
);

drop policy if exists cloud_library_blocks_owner_insert on public.cloud_library_blocks;
create policy cloud_library_blocks_owner_insert
on public.cloud_library_blocks for insert to authenticated
with check (
  producer_id <> auth.uid()
  and exists (
    select 1 from public.cloud_libraries library
    where library.id = library_id and library.owner_id = auth.uid()
  )
  and public.are_connected(auth.uid(), producer_id)
);

drop policy if exists cloud_library_blocks_owner_delete on public.cloud_library_blocks;
create policy cloud_library_blocks_owner_delete
on public.cloud_library_blocks for delete to authenticated
using (
  exists (
    select 1 from public.cloud_libraries library
    where library.id = library_id and library.owner_id = auth.uid()
  )
);

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
      and (
        library.owner_id = viewer
        or (
          library.status = 'ready'
          and public.are_connected(library.owner_id, viewer)
          and not exists (
            select 1
            from public.cloud_library_blocks block
            where block.library_id = library.id
              and block.producer_id = viewer
          )
        )
      )
  );
$$;

revoke all on function public.can_access_cloud_library(uuid, uuid) from public;
grant execute on function public.can_access_cloud_library(uuid, uuid) to authenticated;

drop policy if exists cloud_libraries_connected_read on public.cloud_libraries;
create policy cloud_libraries_connected_read
on public.cloud_libraries for select to authenticated
using (
  owner_id = auth.uid()
  or public.can_access_cloud_library(id, auth.uid())
);

grant delete on public.connections to authenticated;

drop policy if exists connections_member_delete on public.connections;
create policy connections_member_delete
on public.connections for delete to authenticated
using (requester_id = auth.uid() or addressee_id = auth.uid());
