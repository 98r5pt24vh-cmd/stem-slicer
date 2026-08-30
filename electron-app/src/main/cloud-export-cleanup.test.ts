import { readFileSync } from "node:fs"
import path from "node:path"

import { describe, expect, it } from "vitest"

describe("Cloud export audio cleanup", () => {
  const source = readFileSync(
    path.resolve(process.cwd(), "supabase/functions/purge-expired-cloud-exports/index.ts"),
    "utf8",
  )
  const deployment = readFileSync(
    path.resolve(process.cwd(), "supabase/functions/purge-expired-cloud-exports/README.md"),
    "utf8",
  )

  it("claims rows before deletion and finalizes only after Storage removal", () => {
    const claim = source.indexOf('supabase.rpc("claim_expired_cloud_export_assets"')
    const storageDelete = source.indexOf(".remove(assets.map")
    const metadataTransition = source.indexOf('supabase.rpc("finalize_cloud_export_asset_expiration"')

    expect(source).toContain('Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")')
    expect(source).toContain('Deno.env.get("CLOUD_EXPORT_CLEANUP_SECRET")')
    expect(source).not.toContain('.from("cloud_export_assets")')
    expect(source).toContain("p_lease_seconds: LEASE_SECONDS")
    expect(source).toContain("p_claim_id: asset.claim_id")
    expect(claim).toBeGreaterThan(0)
    expect(storageDelete).toBeGreaterThan(claim)
    expect(metadataTransition).toBeGreaterThan(storageDelete)
  })

  it("documents the required remote schedule without committing a secret", () => {
    expect(deployment).toContain("CLOUD_EXPORT_CLEANUP_SECRET")
    expect(deployment).toContain("Supabase Cron")
    expect(deployment).toMatch(/every 15\s+minutes/)
    expect(deployment).toContain("x-cloud-cleanup-secret")
    expect(deployment).toContain("Never commit either value")
  })
})
