begin;

-- Generate already produces the exact MP3 master heard by the producer. Keep
-- that file for activity instead of expanding it to PCM WAV before upload.
alter table public.cloud_export_assets
  alter column file_name set default 'Generated master.mp3';

alter table public.cloud_export_assets
  drop constraint if exists cloud_export_assets_object_path_canonical,
  drop constraint if exists cloud_export_assets_file_name_wav,
  drop constraint if exists cloud_export_assets_file_name_audio,
  drop constraint if exists cloud_export_assets_mime_type;

alter table public.cloud_export_assets
  add constraint cloud_export_assets_object_path_canonical check (
    object_path = owner_id::text || '/' || id::text || '/' || sha256 ||
      case
        when lower(file_name) like '%.mp3' then '.mp3'
        when lower(file_name) like '%.wav' then '.wav'
        else ''
      end
  ),
  add constraint cloud_export_assets_file_name_audio check (
    lower(file_name) like '%.mp3' or lower(file_name) like '%.wav'
  ),
  add constraint cloud_export_assets_mime_type check (
    mime_type is null or mime_type in ('audio/mpeg', 'audio/wav', 'audio/x-wav')
  );

create or replace function public.prepare_cloud_export_asset(payload jsonb)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  creator uuid := auth.uid();
  creator_handle text;
  creator_display_name text;
  requested_id uuid;
  requested_sha text;
  requested_path text;
  requested_name text;
  requested_extension text;
  requested_duration double precision;
  prepared_id uuid;
begin
  if creator is null then raise exception 'Sign in to Cloud first.'; end if;
  if payload is null or jsonb_typeof(payload) <> 'object' then
    raise exception 'The Cloud export asset is invalid.';
  end if;

  select profile.handle, profile.display_name
  into creator_handle, creator_display_name
  from public.profiles profile
  where profile.id = creator;
  if not found then raise exception 'Your Cloud profile is unavailable.'; end if;

  requested_id := coalesce(nullif(payload ->> 'assetId', '')::uuid, gen_random_uuid());
  requested_sha := lower(coalesce(payload ->> 'sha256', ''));
  requested_name := left(coalesce(payload ->> 'fileName', ''), 180);
  requested_duration := greatest(0, coalesce((payload ->> 'durationSeconds')::double precision, 0));
  requested_extension := case
    when lower(requested_name) like '%.mp3' then '.mp3'
    when lower(requested_name) like '%.wav' then '.wav'
    else null
  end;
  requested_path := creator::text || '/' || requested_id::text || '/' || requested_sha || requested_extension;

  if requested_sha !~ '^[0-9a-f]{64}$' then raise exception 'The master SHA-256 is invalid.'; end if;
  if requested_name = '' then raise exception 'The master file name is required.'; end if;
  if requested_extension is null then raise exception 'The Cloud export master must be MP3 or WAV audio.'; end if;

  insert into public.cloud_export_assets (
    id, owner_id, owner_handle_snapshot, owner_display_name_snapshot,
    sha256, object_path, file_name, duration_seconds,
    status, retain_until, purge_claim_id, purge_claim_until, error_message
  ) values (
    requested_id, creator, creator_handle, creator_display_name,
    requested_sha, requested_path, requested_name, requested_duration,
    'uploading', now() + interval '30 days', null, null, null
  )
  on conflict (owner_id, sha256) do update set
    duration_seconds = greatest(public.cloud_export_assets.duration_seconds, excluded.duration_seconds),
    retain_until = greatest(public.cloud_export_assets.retain_until, excluded.retain_until),
    status = case
      when public.cloud_export_assets.status = 'available' then 'available'
      else 'uploading'
    end,
    error_message = case
      when public.cloud_export_assets.status = 'available' then public.cloud_export_assets.error_message
      else null
    end,
    purge_claim_id = null,
    purge_claim_until = null
  where public.cloud_export_assets.status <> 'expiring'
  returning id into prepared_id;

  if prepared_id is null then
    raise exception 'The Cloud export master is being expired. Retry shortly.';
  end if;

  return prepared_id;
end;
$$;

-- Avoid the PL/pgSQL ambiguity between the previous event_id variable and the
-- event_id columns used by the source and recipient tables.
create or replace function public.record_cloud_export_event(payload jsonb)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  creator uuid := auth.uid();
  creator_handle text;
  creator_display_name text;
  requested_client_event uuid;
  requested_kind text;
  requested_name text;
  requested_seed bigint;
  requested_bpm integer;
  requested_key text;
  requested_layer_count integer;
  requested_duration double precision;
  requested_triggered_slot integer;
  requested_asset uuid;
  requested_asset_status text;
  recorded_event_id uuid;
  existing_creator uuid;
  source jsonb;
  source_ordinal bigint;
  source_slot integer;
  source_triggered boolean;
  requested_cloud_layer uuid;
  cloud_layer record;
  recipient_count integer;
begin
  if creator is null then raise exception 'Sign in to Cloud first.'; end if;
  if payload is null or jsonb_typeof(payload) <> 'object' then
    raise exception 'The Cloud export event is invalid.';
  end if;
  if jsonb_typeof(payload -> 'layers') <> 'array' then
    raise exception 'The Cloud export sources are invalid.';
  end if;

  select profile.handle, profile.display_name
  into creator_handle, creator_display_name
  from public.profiles profile
  where profile.id = creator;
  if not found then raise exception 'Your Cloud profile is unavailable.'; end if;

  requested_client_event := nullif(payload ->> 'clientEventId', '')::uuid;
  requested_kind := coalesce(payload ->> 'exportKind', '');
  requested_name := left(trim(coalesce(payload ->> 'generatedLoopName', '')), 180);
  requested_seed := coalesce((payload ->> 'generationSeed')::bigint, 0);
  requested_bpm := coalesce((payload ->> 'targetBpm')::integer, 0);
  requested_key := left(trim(coalesce(payload ->> 'targetKey', '')), 64);
  requested_layer_count := coalesce(
    (payload ->> 'layerCount')::integer,
    jsonb_array_length(payload -> 'layers')
  );
  requested_duration := greatest(0, coalesce((payload ->> 'durationSeconds')::double precision, 0));
  requested_asset := nullif(payload ->> 'assetId', '')::uuid;

  if requested_client_event is null then raise exception 'The client event ID is required.'; end if;
  if requested_kind not in ('drag-all', 'layer-audio', 'layer-midi') then raise exception 'The export kind is invalid.'; end if;
  if requested_name = '' then raise exception 'The generated loop name is required.'; end if;
  if requested_bpm not between 20 and 400 then raise exception 'The target BPM is invalid.'; end if;
  if requested_key = '' then raise exception 'The target key is required.'; end if;
  if jsonb_array_length(payload -> 'layers') not between 1 and 64 then raise exception 'The layer list is invalid.'; end if;
  if requested_layer_count <> jsonb_array_length(payload -> 'layers') then raise exception 'The layer count does not match the source snapshot.'; end if;
  if requested_kind <> 'drag-all' then
    select
      count(*)::integer,
      min(coalesce((item.value ->> 'slotIndex')::integer, item.ordinality::integer - 1))
    into recipient_count, requested_triggered_slot
    from jsonb_array_elements(payload -> 'layers') with ordinality as item(value, ordinality)
    where coalesce((item.value ->> 'triggered')::boolean, false);
    if recipient_count <> 1 or requested_triggered_slot is null or requested_triggered_slot < 0 then
      raise exception 'A card export must mark exactly one source slot as triggered.';
    end if;
  end if;

  select event.id, event.created_by
  into recorded_event_id, existing_creator
  from public.cloud_export_events event
  where event.client_event_id = requested_client_event;
  if recorded_event_id is not null then
    if existing_creator <> creator then raise exception 'The client event ID belongs to another producer.'; end if;
    return recorded_event_id;
  end if;

  if requested_asset is not null then
    select asset.status
    into requested_asset_status
    from public.cloud_export_assets asset
    where asset.id = requested_asset and asset.owner_id = creator
    for update;
    if requested_asset_status is null then raise exception 'The Cloud export master is unavailable.'; end if;
    if requested_asset_status not in ('uploading', 'available') then
      raise exception 'Prepare the Cloud export master before recording activity.';
    end if;
  end if;

  insert into public.cloud_export_events (
    client_event_id, created_by, creator_handle_snapshot, creator_display_name_snapshot,
    export_kind, generated_loop_name,
    generation_seed, target_bpm, target_key, layer_count,
    triggered_slot_index, duration_seconds, asset_id,
    audio_status, audio_expires_at
  ) values (
    requested_client_event, creator, creator_handle, creator_display_name,
    requested_kind, requested_name,
    requested_seed, requested_bpm, requested_key, requested_layer_count,
    requested_triggered_slot, requested_duration, requested_asset,
    coalesce(requested_asset_status, 'preparing'), now() + interval '30 days'
  )
  on conflict (client_event_id) do nothing
  returning id into recorded_event_id;

  if recorded_event_id is null then
    select event.id, event.created_by
    into recorded_event_id, existing_creator
    from public.cloud_export_events event
    where event.client_event_id = requested_client_event;
    if recorded_event_id is null then raise exception 'The Cloud export event could not be recorded.'; end if;
    if existing_creator <> creator then raise exception 'The client event ID belongs to another producer.'; end if;
    return recorded_event_id;
  end if;

  for source, source_ordinal in
    select value, ordinality
    from jsonb_array_elements(payload -> 'layers') with ordinality
  loop
    source_slot := coalesce((source ->> 'slotIndex')::integer, source_ordinal::integer - 1);
    if source_slot < 0 then raise exception 'A source slot is invalid.'; end if;
    requested_cloud_layer := nullif(source ->> 'cloudLayerId', '')::uuid;
    source_triggered := case
      when requested_kind = 'drag-all' then requested_cloud_layer is not null
      else source_slot = requested_triggered_slot
        and coalesce((source ->> 'triggered')::boolean, false)
    end;

    if requested_cloud_layer is not null then
      select
        layer.id,
        layer.owner_id,
        owner.handle as owner_handle,
        owner.display_name as owner_display_name,
        layer.file_name,
        layer.sha256,
        coalesce(nullif(layer.metadata ->> 'source_loop_id', ''), layer.id::text) as source_loop_id,
        coalesce(nullif(layer.metadata ->> 'source_loop_name', ''), layer.file_name) as source_loop_name,
        coalesce(nullif(layer.metadata ->> 'category', ''), 'Unknown') as category
      into cloud_layer
      from public.cloud_layers layer
      join public.profiles owner on owner.id = layer.owner_id
      where layer.id = requested_cloud_layer
        and public.can_access_cloud_library(layer.library_id, creator);

      if not found then raise exception 'A Cloud source is unavailable or no longer shared.'; end if;

      insert into public.cloud_export_sources (
        event_id, slot_index, source_origin, cloud_layer_id, source_owner_id,
        source_owner_handle_snapshot, source_owner_display_name_snapshot,
        source_sha256, source_layer_name, source_loop_id, source_loop_name,
        category, triggered
      ) values (
        recorded_event_id, source_slot, 'cloud', cloud_layer.id, cloud_layer.owner_id,
        cloud_layer.owner_handle, cloud_layer.owner_display_name,
        cloud_layer.sha256, left(cloud_layer.file_name, 240),
        left(cloud_layer.source_loop_id, 500), left(cloud_layer.source_loop_name, 240),
        left(cloud_layer.category, 120), source_triggered
      );

      if source_triggered and cloud_layer.owner_id <> creator then
        insert into public.cloud_export_recipients (event_id, recipient_id)
        values (recorded_event_id, cloud_layer.owner_id)
        on conflict (event_id, recipient_id) do nothing;
      end if;
    else
      insert into public.cloud_export_sources (
        event_id, slot_index, source_origin, cloud_layer_id, source_owner_id,
        source_owner_handle_snapshot, source_owner_display_name_snapshot,
        source_sha256, source_layer_name, source_loop_id, source_loop_name,
        category, triggered
      ) values (
        recorded_event_id,
        source_slot,
        'local',
        null,
        null,
        null,
        null,
        left(coalesce(nullif(source ->> 'sourceSha256', ''), 'local-unknown'), 128),
        left(coalesce(nullif(source ->> 'sourceLayerName', ''), 'Local layer'), 240),
        left(coalesce(nullif(source ->> 'sourceLoopId', ''), 'local-unknown'), 500),
        left(coalesce(nullif(source ->> 'sourceLoopName', ''), nullif(source ->> 'sourceLayerName', ''), 'Local loop'), 240),
        left(coalesce(nullif(source ->> 'category', ''), 'Unknown'), 120),
        source_triggered
      );
    end if;
  end loop;

  if requested_kind <> 'drag-all' and not exists (
    select 1 from public.cloud_export_sources item
    where item.event_id = recorded_event_id
      and item.slot_index = requested_triggered_slot
  ) then
    raise exception 'The exported layer slot is missing from the source snapshot.';
  end if;

  select count(*)::integer into recipient_count
  from public.cloud_export_recipients recipient
  where recipient.event_id = recorded_event_id;

  if recipient_count = 0 then
    delete from public.cloud_export_events event where event.id = recorded_event_id;
    delete from public.cloud_export_assets asset
    where asset.id = requested_asset
      and asset.owner_id = creator
      and asset.status = 'uploading'
      and not exists (
        select 1 from public.cloud_export_events event
        where event.asset_id = asset.id
      );
    return null;
  end if;

  if requested_asset is not null then
    update public.cloud_export_assets asset
    set retain_until = greatest(asset.retain_until, now() + interval '30 days')
    where asset.id = requested_asset and asset.owner_id = creator;
  end if;

  return recorded_event_id;
end;
$$;

create or replace function public.complete_cloud_export_asset(
  p_asset_id uuid,
  p_byte_size bigint,
  p_mime_type text
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  creator uuid := auth.uid();
  requested_object text;
  current_status text;
  requested_mime text := lower(trim(coalesce(p_mime_type, '')));
begin
  if creator is null then raise exception 'Sign in to Cloud first.'; end if;
  if p_byte_size is null or p_byte_size <= 0 or p_byte_size > 50000000 then
    raise exception 'The master byte size is invalid.';
  end if;
  if requested_mime not in ('audio/mpeg', 'audio/wav', 'audio/x-wav') then
    raise exception 'The Cloud export master must be MP3 or WAV audio.';
  end if;

  select asset.object_path, asset.status
  into requested_object, current_status
  from public.cloud_export_assets asset
  where asset.id = p_asset_id and asset.owner_id = creator
  for update;
  if requested_object is null then raise exception 'The Cloud export master is unavailable.'; end if;
  if current_status = 'available' then return; end if;
  if current_status = 'expiring' then
    raise exception 'The Cloud export master is being expired. Retry shortly.';
  end if;
  if current_status <> 'uploading' then
    raise exception 'Prepare the Cloud export master before completing it.';
  end if;
  if not exists (
    select 1 from storage.objects object
    where object.bucket_id = 'cloud-export-masters'
      and object.name = requested_object
  ) then raise exception 'The master upload has not reached Cloud Storage.'; end if;

  update public.cloud_export_assets asset
  set status = 'available', byte_size = p_byte_size, mime_type = requested_mime,
      error_message = null, purge_claim_id = null, purge_claim_until = null,
      retain_until = greatest(asset.retain_until, now() + interval '30 days')
  where asset.id = p_asset_id
    and asset.owner_id = creator
    and asset.status = 'uploading';

  update public.cloud_export_events event
  set audio_status = case when event.audio_expires_at > now() then 'available' else 'expired' end,
      audio_error = null
  where event.asset_id = p_asset_id
    and event.created_by = creator
    and (
      event.audio_status is distinct from case when event.audio_expires_at > now() then 'available' else 'expired' end
      or event.audio_error is not null
    );
end;
$$;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'cloud-export-masters',
  'cloud-export-masters',
  false,
  50000000,
  array['audio/mpeg', 'audio/wav', 'audio/x-wav']
)
on conflict (id) do update set
  public = false,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

commit;
