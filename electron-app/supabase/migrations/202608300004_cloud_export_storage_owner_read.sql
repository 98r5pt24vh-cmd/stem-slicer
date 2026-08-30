begin;

-- Supabase Storage upserts require SELECT in addition to INSERT and UPDATE.
-- The participant policy intentionally exposes only completed masters, so the
-- producer also needs read access to their own in-flight object while a queued
-- export is uploading or retrying.
drop policy if exists cloud_export_masters_owner_read on storage.objects;
create policy cloud_export_masters_owner_read
on storage.objects for select to authenticated
using (
  bucket_id = 'cloud-export-masters'
  and (storage.foldername(name))[1] = auth.uid()::text
  and exists (
    select 1
    from public.cloud_export_assets asset
    where asset.object_path = name
      and asset.owner_id = auth.uid()
  )
);

commit;
