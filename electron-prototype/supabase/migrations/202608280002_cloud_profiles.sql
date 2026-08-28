-- Slicer Cloud profile foundation: public identity metadata and user-owned avatars.

alter table public.profiles
  add column if not exists bio text,
  add column if not exists instagram_handle text,
  add column if not exists aliases text[] not null default '{}',
  add column if not exists open_to_collaborate boolean not null default false;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.profiles'::regclass
      and conname = 'profiles_bio_length'
  ) then
    alter table public.profiles
      add constraint profiles_bio_length
      check (bio is null or char_length(bio) <= 280);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.profiles'::regclass
      and conname = 'profiles_instagram_format'
  ) then
    alter table public.profiles
      add constraint profiles_instagram_format
      check (instagram_handle is null or instagram_handle ~ '^[A-Za-z0-9._]{1,30}$');
  end if;

  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.profiles'::regclass
      and conname = 'profiles_alias_count'
  ) then
    alter table public.profiles
      add constraint profiles_alias_count
      check (cardinality(aliases) <= 12);
  end if;
end;
$$;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'profile-avatars',
  'profile-avatars',
  true,
  5000000,
  array['image/png']
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists profile_avatars_owner_insert on storage.objects;
create policy profile_avatars_owner_insert
on storage.objects for insert to authenticated
with check (
  bucket_id = 'profile-avatars'
  and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists profile_avatars_owner_update on storage.objects;
create policy profile_avatars_owner_update
on storage.objects for update to authenticated
using (
  bucket_id = 'profile-avatars'
  and (storage.foldername(name))[1] = auth.uid()::text
)
with check (
  bucket_id = 'profile-avatars'
  and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists profile_avatars_owner_delete on storage.objects;
create policy profile_avatars_owner_delete
on storage.objects for delete to authenticated
using (
  bucket_id = 'profile-avatars'
  and (storage.foldername(name))[1] = auth.uid()::text
);
