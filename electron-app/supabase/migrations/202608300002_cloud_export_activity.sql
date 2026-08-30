-- Cloud export activity is an immutable audit trail created only when a user
-- starts a native drag. Generation alone does not create activity.
--
-- Event metadata is retained. Master audio is private, deduplicated by owner
-- and SHA-256, and expires after 30 days. A scheduled Edge Function using the
-- service role must claim a row, physically remove its Storage object, then
-- finalize that exact claim. SQL metadata changes alone never remove Storage.

create table if not exists public.cloud_export_assets (
  id uuid primary key default gen_random_uuid(),
  -- Deliberately not a profiles FK: this immutable audit identity must survive
  -- account/profile deletion until the retained master is physically purged.
  owner_id uuid not null,
  owner_handle_snapshot text not null,
  owner_display_name_snapshot text not null,
  sha256 text not null,
  object_path text not null unique,
  file_name text not null default 'Generated master.wav',
  mime_type text,
  byte_size bigint,
  duration_seconds double precision not null default 0,
  status text not null default 'uploading',
  retain_until timestamptz not null default (now() + interval '30 days'),
  purge_claim_id uuid,
  purge_claim_until timestamptz,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint cloud_export_assets_owner_sha256_unique unique (owner_id, sha256),
  constraint cloud_export_assets_sha256_format check (sha256 ~ '^[0-9a-f]{64}$'),
  constraint cloud_export_assets_object_path_canonical check (
    object_path = owner_id::text || '/' || id::text || '/' || sha256 || '.wav'
  ),
  constraint cloud_export_assets_file_name_length check (char_length(file_name) between 1 and 180),
  constraint cloud_export_assets_file_name_wav check (lower(file_name) like '%.wav'),
  constraint cloud_export_assets_owner_handle_length check (char_length(owner_handle_snapshot) between 1 and 64),
  constraint cloud_export_assets_owner_display_name_length check (char_length(owner_display_name_snapshot) between 1 and 120),
  constraint cloud_export_assets_mime_type check (
    mime_type is null or mime_type in ('audio/wav', 'audio/x-wav')
  ),
  constraint cloud_export_assets_byte_size check (byte_size is null or byte_size > 0),
  constraint cloud_export_assets_duration check (duration_seconds >= 0),
  constraint cloud_export_assets_status check (status in ('uploading', 'available', 'failed', 'expiring', 'expired')),
  constraint cloud_export_assets_purge_claim check (
    (status = 'expiring' and purge_claim_id is not null and purge_claim_until is not null)
    or (status <> 'expiring' and purge_claim_id is null and purge_claim_until is null)
  ),
  constraint cloud_export_assets_error_length check (error_message is null or char_length(error_message) <= 500)
);

create index if not exists cloud_export_assets_owner_status
  on public.cloud_export_assets(owner_id, status, retain_until);
create index if not exists cloud_export_assets_expiration
  on public.cloud_export_assets(retain_until, purge_claim_until)
  where status <> 'expired';

create table if not exists public.cloud_export_events (
  id uuid primary key default gen_random_uuid(),
  client_event_id uuid not null unique,
  -- Deliberately not a profiles FK: this is the immutable actor snapshot.
  created_by uuid not null,
  creator_handle_snapshot text not null,
  creator_display_name_snapshot text not null,
  export_kind text not null,
  generated_loop_name text not null,
  generation_seed bigint not null,
  target_bpm integer not null,
  target_key text not null,
  layer_count integer not null,
  triggered_slot_index integer,
  duration_seconds double precision not null default 0,
  asset_id uuid references public.cloud_export_assets(id) on delete set null,
  audio_status text not null default 'preparing',
  audio_error text,
  audio_expires_at timestamptz not null default (now() + interval '30 days'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint cloud_export_events_kind check (export_kind in ('drag-all', 'layer-audio', 'layer-midi')),
  constraint cloud_export_events_generated_name_length check (char_length(generated_loop_name) between 1 and 180),
  constraint cloud_export_events_creator_handle_length check (char_length(creator_handle_snapshot) between 1 and 64),
  constraint cloud_export_events_creator_display_name_length check (char_length(creator_display_name_snapshot) between 1 and 120),
  constraint cloud_export_events_target_bpm check (target_bpm between 20 and 400),
  constraint cloud_export_events_target_key_length check (char_length(target_key) between 1 and 64),
  constraint cloud_export_events_layer_count check (layer_count between 1 and 64),
  constraint cloud_export_events_duration check (duration_seconds >= 0),
  constraint cloud_export_events_trigger check (
    (export_kind = 'drag-all' and triggered_slot_index is null)
    or (export_kind in ('layer-audio', 'layer-midi') and triggered_slot_index >= 0)
  ),
  constraint cloud_export_events_audio_status check (
    audio_status in ('preparing', 'uploading', 'available', 'failed', 'expired')
  ),
  constraint cloud_export_events_audio_error_length check (audio_error is null or char_length(audio_error) <= 500)
);

create index if not exists cloud_export_events_created_by_date
  on public.cloud_export_events(created_by, created_at desc);
create index if not exists cloud_export_events_asset_id
  on public.cloud_export_events(asset_id);
create index if not exists cloud_export_events_expiration
  on public.cloud_export_events(audio_expires_at)
  where audio_status <> 'expired';

create table if not exists public.cloud_export_sources (
  event_id uuid not null references public.cloud_export_events(id) on delete cascade,
  slot_index integer not null,
  source_origin text not null,
  cloud_layer_id uuid references public.cloud_layers(id) on delete set null,
  -- Cloud owner identity is an immutable event snapshot, not a live profile FK.
  source_owner_id uuid,
  source_owner_handle_snapshot text,
  source_owner_display_name_snapshot text,
  source_sha256 text not null,
  source_layer_name text not null,
  source_loop_id text not null,
  source_loop_name text not null,
  category text not null,
  triggered boolean not null default false,
  created_at timestamptz not null default now(),
  primary key (event_id, slot_index),
  constraint cloud_export_sources_slot_index check (slot_index >= 0),
  constraint cloud_export_sources_origin check (source_origin in ('local', 'cloud')),
  constraint cloud_export_sources_cloud_identity check (
    (
      source_origin = 'cloud'
      and source_owner_id is not null
      and source_owner_handle_snapshot is not null
      and source_owner_display_name_snapshot is not null
    )
    or (
      source_origin = 'local'
      and source_owner_id is null
      and source_owner_handle_snapshot is null
      and source_owner_display_name_snapshot is null
    )
  ),
  constraint cloud_export_sources_owner_handle_length check (
    source_owner_handle_snapshot is null or char_length(source_owner_handle_snapshot) between 1 and 64
  ),
  constraint cloud_export_sources_owner_display_name_length check (
    source_owner_display_name_snapshot is null or char_length(source_owner_display_name_snapshot) between 1 and 120
  ),
  constraint cloud_export_sources_sha_length check (char_length(source_sha256) between 1 and 128),
  constraint cloud_export_sources_layer_name_length check (char_length(source_layer_name) between 1 and 240),
  constraint cloud_export_sources_loop_id_length check (char_length(source_loop_id) between 1 and 500),
  constraint cloud_export_sources_loop_name_length check (char_length(source_loop_name) between 1 and 240),
  constraint cloud_export_sources_category_length check (char_length(category) between 1 and 120)
);

create index if not exists cloud_export_sources_owner_id
  on public.cloud_export_sources(source_owner_id);
create index if not exists cloud_export_sources_cloud_layer_id
  on public.cloud_export_sources(cloud_layer_id);

create table if not exists public.cloud_export_recipients (
  event_id uuid not null references public.cloud_export_events(id) on delete cascade,
  recipient_id uuid not null references public.profiles(id) on delete cascade,
  read_at timestamptz,
  created_at timestamptz not null default now(),
  primary key (event_id, recipient_id)
);

create index if not exists cloud_export_recipients_unread
  on public.cloud_export_recipients(recipient_id, created_at desc)
  where read_at is null;

drop trigger if exists cloud_export_assets_touch_updated_at on public.cloud_export_assets;
create trigger cloud_export_assets_touch_updated_at
before update on public.cloud_export_assets
for each row execute function public.touch_updated_at();

drop trigger if exists cloud_export_events_touch_updated_at on public.cloud_export_events;
create trigger cloud_export_events_touch_updated_at
before update on public.cloud_export_events
for each row execute function public.touch_updated_at();

create or replace function public.can_read_cloud_export(requested_event uuid, viewer uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.cloud_export_events event
    where event.id = requested_event
      and (
        event.created_by = viewer
        or exists (
          select 1
          from public.cloud_export_recipients recipient
          where recipient.event_id = event.id
            and recipient.recipient_id = viewer
        )
      )
  );
$$;

create or replace function public.can_read_cloud_export_asset(requested_asset uuid, viewer uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.cloud_export_assets asset
    where asset.id = requested_asset
      and (
        asset.owner_id = viewer
        or exists (
          select 1
          from public.cloud_export_events event
          where event.asset_id = asset.id
            and event.audio_status = 'available'
            and event.audio_expires_at > now()
            and public.can_read_cloud_export(event.id, viewer)
        )
      )
  );
$$;

create or replace function public.can_access_cloud_export_object(requested_object text, viewer uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.cloud_export_assets asset
    where asset.object_path = requested_object
      and asset.status = 'available'
      and asset.retain_until > now()
      and public.can_read_cloud_export_asset(asset.id, viewer)
  );
$$;

revoke all on function public.can_read_cloud_export(uuid, uuid) from public;
revoke all on function public.can_read_cloud_export_asset(uuid, uuid) from public;
revoke all on function public.can_access_cloud_export_object(text, uuid) from public;
grant execute on function public.can_read_cloud_export(uuid, uuid) to authenticated;
grant execute on function public.can_read_cloud_export_asset(uuid, uuid) to authenticated;
grant execute on function public.can_access_cloud_export_object(text, uuid) to authenticated;

-- Prepare or reuse one content-addressed master. A previously available asset
-- remains available and only has its retention extended; failed or expired
-- assets return to uploading so the desktop can retry the same object path.
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
  -- Ignore every client-provided path. The authenticated owner, generated row
  -- ID and digest define one canonical private WAV object.
  requested_path := creator::text || '/' || requested_id::text || '/' || requested_sha || '.wav';

  if requested_sha !~ '^[0-9a-f]{64}$' then raise exception 'The master SHA-256 is invalid.'; end if;
  if requested_name = '' then raise exception 'The master file name is required.'; end if;
  if lower(requested_name) not like '%.wav' then raise exception 'The Cloud export master must be WAV audio.'; end if;

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
  -- A cleanup claim owns the object until finalization or lease expiry. Do not
  -- let a client retry race the Storage deletion already in progress.
  where public.cloud_export_assets.status <> 'expiring'
  returning id into prepared_id;

  if prepared_id is null then
    raise exception 'The Cloud export master is being expired. Retry shortly.';
  end if;

  return prepared_id;
end;
$$;

-- Retry an already catalogued asset without granting clients general UPDATE
-- access. Available assets are immutable and remain untouched.
create or replace function public.prepare_cloud_export_asset(p_asset_id uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  creator uuid := auth.uid();
  current_status text;
begin
  if creator is null then raise exception 'Sign in to Cloud first.'; end if;

  select asset.status into current_status
  from public.cloud_export_assets asset
  where asset.id = p_asset_id and asset.owner_id = creator;
  if current_status is null then raise exception 'The Cloud export master is unavailable.'; end if;
  if current_status in ('available', 'uploading') then return; end if;
  if current_status = 'expiring' then
    raise exception 'The Cloud export master is being expired. Retry shortly.';
  end if;

  update public.cloud_export_assets asset
  set status = 'uploading', error_message = null,
      purge_claim_id = null, purge_claim_until = null,
      retain_until = greatest(asset.retain_until, now() + interval '30 days')
  where asset.id = p_asset_id
    and asset.owner_id = creator
    and asset.status in ('failed', 'expired');

  update public.cloud_export_events event
  set audio_status = case when event.audio_expires_at > now() then 'uploading' else 'expired' end,
      audio_error = null
  where event.asset_id = p_asset_id
    and event.created_by = creator
    and (
      event.audio_status is distinct from case when event.audio_expires_at > now() then 'uploading' else 'expired' end
      or event.audio_error is not null
    );
end;
$$;

-- The RPC accepts camelCase JSON from the Electron contract. Cloud owners and
-- immutable Cloud source metadata are always derived from cloud_layers; owner
-- identifiers supplied by a client are never trusted.
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
  event_id uuid;
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
  into event_id, existing_creator
  from public.cloud_export_events event
  where event.client_event_id = requested_client_event;
  if event_id is not null then
    if existing_creator <> creator then raise exception 'The client event ID belongs to another producer.'; end if;
    return event_id;
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
  returning id into event_id;

  -- Concurrent retries can both pass the earlier fast-path lookup. The unique
  -- client_event_id gate makes one insert win; the other returns that same row.
  if event_id is null then
    select event.id, event.created_by
    into event_id, existing_creator
    from public.cloud_export_events event
    where event.client_event_id = requested_client_event;
    if event_id is null then raise exception 'The Cloud export event could not be recorded.'; end if;
    if existing_creator <> creator then raise exception 'The client event ID belongs to another producer.'; end if;
    return event_id;
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
        event_id, source_slot, 'cloud', cloud_layer.id, cloud_layer.owner_id,
        cloud_layer.owner_handle, cloud_layer.owner_display_name,
        cloud_layer.sha256, left(cloud_layer.file_name, 240),
        left(cloud_layer.source_loop_id, 500), left(cloud_layer.source_loop_name, 240),
        left(cloud_layer.category, 120), source_triggered
      );

      if source_triggered and cloud_layer.owner_id <> creator then
        insert into public.cloud_export_recipients (event_id, recipient_id)
        values (event_id, cloud_layer.owner_id)
        on conflict (event_id, recipient_id) do nothing;
      end if;
    else
      insert into public.cloud_export_sources (
        event_id, slot_index, source_origin, cloud_layer_id, source_owner_id,
        source_owner_handle_snapshot, source_owner_display_name_snapshot,
        source_sha256, source_layer_name, source_loop_id, source_loop_name,
        category, triggered
      ) values (
        event_id,
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
    where item.event_id = event_id
      and item.slot_index = requested_triggered_slot
  ) then
    raise exception 'The exported layer slot is missing from the source snapshot.';
  end if;

  select count(*)::integer into recipient_count
  from public.cloud_export_recipients recipient
  where recipient.event_id = event_id;

  -- A local-only drag has nobody to notify and is not Cloud activity.
  if recipient_count = 0 then
    delete from public.cloud_export_events event where event.id = event_id;
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

  return event_id;
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
  if requested_mime not in ('audio/wav', 'audio/x-wav') then
    raise exception 'The Cloud export master must be WAV audio.';
  end if;

  select asset.object_path, asset.status
  into requested_object, current_status
  from public.cloud_export_assets asset
  where asset.id = p_asset_id and asset.owner_id = creator
  for update;
  if requested_object is null then raise exception 'The Cloud export master is unavailable.'; end if;
  -- A retry that loses to a successful upload is harmless. In particular, a
  -- late completion never mutates an already available asset.
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

create or replace function public.fail_cloud_export_asset(p_asset_id uuid, p_error text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  creator uuid := auth.uid();
  current_status text;
  failure_message text := left(coalesce(nullif(trim(p_error), ''), 'Cloud upload failed.'), 500);
begin
  if creator is null then raise exception 'Sign in to Cloud first.'; end if;

  select asset.status into current_status
  from public.cloud_export_assets asset
  where asset.id = p_asset_id and asset.owner_id = creator
  for update;
  if current_status is null then raise exception 'The Cloud export master is unavailable.'; end if;
  -- A late failing upload must never downgrade a successful upload or resurrect
  -- an expired asset. Repeated failures are idempotent no-ops.
  if current_status in ('available', 'failed', 'expired') then return; end if;
  if current_status = 'expiring' then
    raise exception 'The Cloud export master is being expired. Retry shortly.';
  end if;

  update public.cloud_export_assets asset
  set status = 'failed', error_message = failure_message,
      purge_claim_id = null, purge_claim_until = null
  where asset.id = p_asset_id
    and asset.owner_id = creator
    and asset.status = 'uploading';

  update public.cloud_export_events event
  set audio_status = case when event.audio_expires_at > now() then 'failed' else 'expired' end,
      audio_error = failure_message
  where event.asset_id = p_asset_id
    and event.created_by = creator
    and (
      event.audio_status is distinct from case when event.audio_expires_at > now() then 'failed' else 'expired' end
      or event.audio_error is distinct from failure_message
    );
end;
$$;

-- Atomically reserve expired objects for one cleanup worker. SKIP LOCKED makes
-- concurrent scheduled invocations safe; an abandoned lease can be reclaimed.
create or replace function public.claim_expired_cloud_export_assets(
  p_limit integer default 100,
  p_lease_seconds integer default 300
)
returns table(asset_id uuid, object_path text, claim_id uuid)
language plpgsql
security definer
set search_path = ''
as $$
begin
  return query
  with candidates as (
    select asset.id
    from public.cloud_export_assets asset
    where (
      (
        asset.status in ('uploading', 'available', 'failed')
        and asset.retain_until <= now()
      ) or (
        asset.status = 'expiring'
        and asset.purge_claim_until <= now()
      )
    )
    and not exists (
      select 1
      from public.cloud_export_events event
      where event.asset_id = asset.id
        and event.audio_expires_at > now()
    )
    order by coalesce(asset.purge_claim_until, asset.retain_until), asset.id
    for update skip locked
    limit greatest(1, least(coalesce(p_limit, 100), 500))
  ), claimed as (
    update public.cloud_export_assets asset
    set status = 'expiring',
        purge_claim_id = gen_random_uuid(),
        purge_claim_until = now() + make_interval(
          secs => greatest(30, least(coalesce(p_lease_seconds, 300), 900))
        ),
        error_message = null
    from candidates candidate
    where asset.id = candidate.id
    returning asset.id, asset.object_path, asset.purge_claim_id
  )
  select claimed.id, claimed.object_path, claimed.purge_claim_id
  from claimed;
end;
$$;

-- Finalization is token-bound and refuses to claim success while the object is
-- still present. Physical Storage deletion is performed by the Edge Function,
-- because a SQL status transition does not delete a Storage object.
create or replace function public.finalize_cloud_export_asset_expiration(
  p_asset_id uuid,
  p_claim_id uuid
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  requested_object text;
begin
  select asset.object_path into requested_object
  from public.cloud_export_assets asset
  where asset.id = p_asset_id
    and asset.status = 'expiring'
    and asset.purge_claim_id = p_claim_id
  for update;
  if requested_object is null then
    raise exception 'The Cloud export cleanup claim is unavailable.';
  end if;

  if exists (
    select 1 from storage.objects object
    where object.bucket_id = 'cloud-export-masters'
      and object.name = requested_object
  ) then
    raise exception 'The Cloud export master still exists in Storage.';
  end if;

  update public.cloud_export_assets asset
  set status = 'expired', error_message = null,
      purge_claim_id = null, purge_claim_until = null
  where asset.id = p_asset_id
    and asset.status = 'expiring'
    and asset.purge_claim_id = p_claim_id;

  update public.cloud_export_events event
  set audio_status = 'expired', audio_error = null
  where event.asset_id = p_asset_id
    and event.audio_expires_at <= now()
    and (event.audio_status is distinct from 'expired' or event.audio_error is not null);
end;
$$;

revoke all on function public.prepare_cloud_export_asset(jsonb) from public;
revoke all on function public.prepare_cloud_export_asset(uuid) from public;
revoke all on function public.record_cloud_export_event(jsonb) from public;
revoke all on function public.complete_cloud_export_asset(uuid, bigint, text) from public;
revoke all on function public.fail_cloud_export_asset(uuid, text) from public;
revoke all on function public.claim_expired_cloud_export_assets(integer, integer) from public;
revoke all on function public.finalize_cloud_export_asset_expiration(uuid, uuid) from public;
grant execute on function public.prepare_cloud_export_asset(jsonb) to authenticated;
grant execute on function public.prepare_cloud_export_asset(uuid) to authenticated;
grant execute on function public.record_cloud_export_event(jsonb) to authenticated;
grant execute on function public.complete_cloud_export_asset(uuid, bigint, text) to authenticated;
grant execute on function public.fail_cloud_export_asset(uuid, text) to authenticated;
grant execute on function public.claim_expired_cloud_export_assets(integer, integer) to service_role;
grant execute on function public.finalize_cloud_export_asset_expiration(uuid, uuid) to service_role;

alter table public.cloud_export_assets enable row level security;
alter table public.cloud_export_events enable row level security;
alter table public.cloud_export_sources enable row level security;
alter table public.cloud_export_recipients enable row level security;

revoke all on public.cloud_export_assets, public.cloud_export_events,
  public.cloud_export_sources, public.cloud_export_recipients from anon;
revoke all on public.cloud_export_assets, public.cloud_export_events,
  public.cloud_export_sources, public.cloud_export_recipients from authenticated;

grant select on public.cloud_export_assets to authenticated;
grant select on public.cloud_export_events to authenticated;
grant select on public.cloud_export_sources to authenticated;
grant select, update (read_at) on public.cloud_export_recipients to authenticated;

drop policy if exists cloud_export_assets_participant_read on public.cloud_export_assets;
create policy cloud_export_assets_participant_read
on public.cloud_export_assets for select to authenticated
using (public.can_read_cloud_export_asset(id, auth.uid()));

drop policy if exists cloud_export_events_participant_read on public.cloud_export_events;
create policy cloud_export_events_participant_read
on public.cloud_export_events for select to authenticated
using (public.can_read_cloud_export(id, auth.uid()));

drop policy if exists cloud_export_sources_participant_read on public.cloud_export_sources;
create policy cloud_export_sources_participant_read
on public.cloud_export_sources for select to authenticated
using (public.can_read_cloud_export(event_id, auth.uid()));

drop policy if exists cloud_export_recipients_participant_read on public.cloud_export_recipients;
create policy cloud_export_recipients_participant_read
on public.cloud_export_recipients for select to authenticated
using (recipient_id = auth.uid());

drop policy if exists cloud_export_recipients_self_read_receipt on public.cloud_export_recipients;
create policy cloud_export_recipients_self_read_receipt
on public.cloud_export_recipients for update to authenticated
using (recipient_id = auth.uid())
with check (recipient_id = auth.uid());

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'cloud-export-masters',
  'cloud-export-masters',
  false,
  50000000,
  array['audio/wav', 'audio/x-wav']
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists cloud_export_masters_owner_insert on storage.objects;
create policy cloud_export_masters_owner_insert
on storage.objects for insert to authenticated
with check (
  bucket_id = 'cloud-export-masters'
  and (storage.foldername(name))[1] = auth.uid()::text
  and exists (
    select 1 from public.cloud_export_assets asset
    where asset.object_path = name
      and asset.owner_id = auth.uid()
      and asset.status = 'uploading'
  )
);

drop policy if exists cloud_export_masters_owner_update on storage.objects;
create policy cloud_export_masters_owner_update
on storage.objects for update to authenticated
using (
  bucket_id = 'cloud-export-masters'
  and (storage.foldername(name))[1] = auth.uid()::text
  and exists (
    select 1 from public.cloud_export_assets asset
    where asset.object_path = name
      and asset.owner_id = auth.uid()
      and asset.status = 'uploading'
  )
)
with check (
  bucket_id = 'cloud-export-masters'
  and (storage.foldername(name))[1] = auth.uid()::text
  and exists (
    select 1 from public.cloud_export_assets asset
    where asset.object_path = name
      and asset.owner_id = auth.uid()
      and asset.status = 'uploading'
  )
);

drop policy if exists cloud_export_masters_participant_read on storage.objects;
create policy cloud_export_masters_participant_read
on storage.objects for select to authenticated
using (
  bucket_id = 'cloud-export-masters'
  and public.can_access_cloud_export_object(name, auth.uid())
);

-- No authenticated DELETE policy is intentional: the immutable audit trail's
-- audio is removed only by the scheduled cleanup Edge Function/service role.

alter table public.cloud_export_events replica identity full;
alter table public.cloud_export_recipients replica identity full;

-- Supabase creates this publication in hosted projects. The guarded block also
-- works in a local project and never tries to add the same table twice.
do $$
declare
  publishes_all boolean;
begin
  if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    execute 'create publication supabase_realtime';
  end if;

  select puballtables into publishes_all
  from pg_publication
  where pubname = 'supabase_realtime';

  if not coalesce(publishes_all, false)
    and not exists (
      select 1 from pg_publication_tables
      where pubname = 'supabase_realtime'
        and schemaname = 'public'
        and tablename = 'cloud_export_events'
    ) then
    execute 'alter publication supabase_realtime add table public.cloud_export_events';
  end if;

  if not coalesce(publishes_all, false)
    and not exists (
      select 1 from pg_publication_tables
      where pubname = 'supabase_realtime'
        and schemaname = 'public'
        and tablename = 'cloud_export_recipients'
    ) then
    execute 'alter publication supabase_realtime add table public.cloud_export_recipients';
  end if;
end;
$$;
