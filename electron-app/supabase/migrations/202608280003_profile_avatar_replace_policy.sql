-- Replacing an existing Storage object uses an upsert. Supabase Storage needs
-- SELECT permission in addition to INSERT and UPDATE for that operation.

drop policy if exists profile_avatars_owner_select on storage.objects;
create policy profile_avatars_owner_select
on storage.objects for select to authenticated
using (
  bucket_id = 'profile-avatars'
  and (storage.foldername(name))[1] = auth.uid()::text
);
