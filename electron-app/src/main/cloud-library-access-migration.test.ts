import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"

describe("Cloud trusted producer access migration", () => {
  const migration = readFileSync(
    path.resolve(process.cwd(), "supabase/migrations/202608290001_trusted_producer_library_access.sql"),
    "utf8",
  )
  const service = readFileSync(
    path.resolve(process.cwd(), "src/main/cloud-service.ts"),
    "utf8",
  )

  it("lets either connection member remove the relationship", () => {
    expect(migration).toContain("grant delete on public.connections to authenticated")
    expect(migration).toContain("requester_id = auth.uid() or addressee_id = auth.uid()")
  })

  it("enforces per-library producer blocks in the shared access function", () => {
    expect(migration).toContain("create table if not exists public.cloud_library_blocks")
    expect(migration).toContain("and block.producer_id = viewer")
    expect(migration).toContain("or public.can_access_cloud_library(id, auth.uid())")
  })

  it("uses the granted insert privilege without requiring table updates", () => {
    const accessMethod = service.slice(
      service.indexOf("async setLibraryProducerAccess"),
      service.indexOf("private async cataloguedLibraryObjectPaths"),
    )

    expect(migration).toContain("grant select, insert, delete on public.cloud_library_blocks to authenticated")
    expect(accessMethod).toContain('.insert({ library_id: library.id, producer_id: producerId })')
    expect(accessMethod).not.toContain(".upsert(")
  })
})
