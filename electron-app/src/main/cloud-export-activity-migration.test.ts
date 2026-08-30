import { readFileSync } from "node:fs"
import path from "node:path"

import { describe, expect, it } from "vitest"

describe("Cloud export activity migration", () => {
  const migration = readFileSync(
    path.resolve(process.cwd(), "supabase/migrations/202608300002_cloud_export_activity.sql"),
    "utf8",
  )

  it("keeps event IDs idempotent and master assets content-addressed", () => {
    expect(migration).toContain("constraint cloud_export_assets_owner_sha256_unique unique (owner_id, sha256)")
    expect(migration).toContain("client_event_id uuid not null unique")
    expect(migration).toContain("on conflict (client_event_id) do nothing")
    expect(migration).toContain("on conflict (event_id, recipient_id) do nothing")
    expect(migration).toContain("audio_expires_at timestamptz not null default (now() + interval '30 days')")
    expect(migration).toContain("status in ('uploading', 'available', 'failed', 'expiring', 'expired')")
  })

  it("persists immutable producer/source identity after profile deletion", () => {
    expect(migration).toContain("owner_handle_snapshot text not null")
    expect(migration).toContain("owner_display_name_snapshot text not null")
    expect(migration).toContain("creator_handle_snapshot text not null")
    expect(migration).toContain("creator_display_name_snapshot text not null")
    expect(migration).toContain("source_owner_handle_snapshot text")
    expect(migration).toContain("source_owner_display_name_snapshot text")
    expect(migration).toContain("source_owner_id uuid,")
    expect(migration).not.toContain("owner_id uuid not null references public.profiles")
    expect(migration).not.toContain("created_by uuid not null references public.profiles")
    expect(migration).not.toContain("source_owner_id uuid references public.profiles")
    expect(migration).toContain("public.can_read_cloud_export(event.id, viewer)")
  })

  it("generates the private object path server-side and accepts WAV masters only", () => {
    const prepare = migration.slice(
      migration.indexOf("create or replace function public.prepare_cloud_export_asset(payload jsonb)"),
      migration.indexOf("create or replace function public.prepare_cloud_export_asset(p_asset_id uuid)"),
    )

    expect(prepare).toContain("requested_path := creator::text || '/' || requested_id::text || '/' || requested_sha || '.wav'")
    expect(prepare).not.toContain("payload ->> 'objectPath'")
    expect(prepare).toContain("lower(requested_name) not like '%.wav'")
    expect(migration).toContain("mime_type is null or mime_type in ('audio/wav', 'audio/x-wav')")
    expect(migration).toContain("array['audio/wav', 'audio/x-wav']")
    expect(migration).not.toContain("application/octet-stream")
  })

  it("derives Cloud owners and identity snapshots inside the event RPC", () => {
    const rpc = migration.slice(
      migration.indexOf("create or replace function public.record_cloud_export_event"),
      migration.indexOf("create or replace function public.complete_cloud_export_asset"),
    )

    expect(rpc).toContain("security definer")
    expect(rpc).toContain("set search_path = ''")
    expect(rpc).toContain("from public.cloud_layers layer")
    expect(rpc).toContain("join public.profiles owner on owner.id = layer.owner_id")
    expect(rpc).toContain("public.can_access_cloud_library(layer.library_id, creator)")
    expect(rpc).toContain("creator_handle_snapshot, creator_display_name_snapshot")
    expect(rpc).toContain("source_owner_handle_snapshot, source_owner_display_name_snapshot")
    expect(rpc).toContain("for update")
    expect(rpc).toContain("requested_asset_status not in ('uploading', 'available')")
  })

  it("makes completion/failure idempotent and unable to downgrade available assets", () => {
    const transitions = migration.slice(
      migration.indexOf("create or replace function public.complete_cloud_export_asset"),
      migration.indexOf("create or replace function public.claim_expired_cloud_export_assets"),
    )

    expect(transitions).toContain("if current_status = 'available' then return; end if")
    expect(transitions).toContain("if current_status in ('available', 'failed', 'expired') then return; end if")
    expect(transitions).toContain("if current_status = 'expiring' then")
    expect(transitions).toContain("and asset.status = 'uploading'")
    expect(transitions).toContain("event.audio_status is distinct from")
    expect(transitions).toContain("event.audio_error is distinct from failure_message")
    expect(transitions).toContain("requested_mime not in ('audio/wav', 'audio/x-wav')")
  })

  it("claims expiration atomically and finalizes only the matching deleted object", () => {
    const cleanup = migration.slice(
      migration.indexOf("create or replace function public.claim_expired_cloud_export_assets"),
      migration.indexOf("alter table public.cloud_export_assets enable row level security"),
    )

    expect(migration).toContain("purge_claim_id uuid")
    expect(migration).toContain("purge_claim_until timestamptz")
    expect(cleanup).toContain("for update skip locked")
    expect(cleanup).toContain("purge_claim_id = gen_random_uuid()")
    expect(cleanup).toContain("asset.purge_claim_until <= now()")
    expect(cleanup).toContain("create or replace function public.finalize_cloud_export_asset_expiration")
    expect(cleanup).toContain("and asset.purge_claim_id = p_claim_id")
    expect(cleanup).toContain("from storage.objects object")
    expect(cleanup).toContain("grant execute on function public.claim_expired_cloud_export_assets(integer, integer) to service_role")
    expect(cleanup).toContain("grant execute on function public.finalize_cloud_export_asset_expiration(uuid, uuid) to service_role")
    expect(migration).not.toContain("mark_cloud_export_asset_expired")
  })

  it("blocks retries while cleanup owns a live claim", () => {
    const prepare = migration.slice(
      migration.indexOf("create or replace function public.prepare_cloud_export_asset(payload jsonb)"),
      migration.indexOf("create or replace function public.record_cloud_export_event"),
    )

    expect(prepare).toContain("where public.cloud_export_assets.status <> 'expiring'")
    expect(prepare).toContain("if current_status = 'expiring' then")
    expect(prepare).toContain("The Cloud export master is being expired. Retry shortly.")
  })

  it("keeps RLS private and publishes only activity deltas through Realtime", () => {
    expect(migration).toContain("alter table public.cloud_export_events enable row level security")
    expect(migration).toContain("public.can_read_cloud_export(event_id, auth.uid())")
    expect(migration).toContain("recipient_id = auth.uid()")
    expect(migration).toContain("public.can_access_cloud_export_object(name, auth.uid())")
    expect(migration).toContain("No authenticated DELETE policy is intentional")
    expect(migration).toContain("alter table public.cloud_export_events replica identity full")
    expect(migration).toContain("alter table public.cloud_export_recipients replica identity full")
    expect(migration).toContain("alter publication supabase_realtime add table public.cloud_export_events")
    expect(migration).toContain("alter publication supabase_realtime add table public.cloud_export_recipients")
  })
})

describe("Cloud export MP3 correction migration", () => {
  const migration = readFileSync(
    path.resolve(process.cwd(), "supabase/migrations/202608300003_cloud_export_mp3_and_event_id_fix.sql"),
    "utf8",
  )

  it("keeps the generated MP3 master and retains WAV compatibility for prior rows", () => {
    expect(migration).toContain("when lower(requested_name) like '%.mp3' then '.mp3'")
    expect(migration).toContain("mime_type is null or mime_type in ('audio/mpeg', 'audio/wav', 'audio/x-wav')")
    expect(migration).toContain("array['audio/mpeg', 'audio/wav', 'audio/x-wav']")
    expect(migration).not.toContain("The Cloud export master must be WAV audio.")
  })

  it("uses a variable name that cannot collide with recipient event_id columns", () => {
    const rpc = migration.slice(
      migration.indexOf("create or replace function public.record_cloud_export_event"),
      migration.indexOf("create or replace function public.complete_cloud_export_asset"),
    )

    expect(rpc).toContain("recorded_event_id uuid;")
    expect(rpc).not.toContain("\n  event_id uuid;")
    expect(rpc).toContain("values (recorded_event_id, cloud_layer.owner_id)")
    expect(rpc).toContain("where recipient.event_id = recorded_event_id")
  })
})

describe("Cloud export Storage owner-read correction migration", () => {
  const migration = readFileSync(
    path.resolve(process.cwd(), "supabase/migrations/202608300004_cloud_export_storage_owner_read.sql"),
    "utf8",
  )

  it("allows the owner to read an in-flight object required by Storage upsert", () => {
    expect(migration).toContain("create policy cloud_export_masters_owner_read")
    expect(migration).toContain("on storage.objects for select to authenticated")
    expect(migration).toContain("asset.owner_id = auth.uid()")
    expect(migration).toContain("asset.object_path = name")
  })
})
