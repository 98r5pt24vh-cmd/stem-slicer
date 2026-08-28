-- Owners can manage every lifecycle state. Connected producers only discover
-- libraries that are actively shared and ready for Generate.

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
        )
      )
  );
$$;

drop policy if exists cloud_libraries_connected_read on public.cloud_libraries;
create policy cloud_libraries_connected_read
on public.cloud_libraries for select to authenticated
using (
  owner_id = auth.uid()
  or (
    status = 'ready'
    and public.are_connected(owner_id, auth.uid())
  )
);
