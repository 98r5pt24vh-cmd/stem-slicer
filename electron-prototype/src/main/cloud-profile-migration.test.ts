import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"

describe("Cloud profile avatar Storage policies", () => {
  it("keeps owner SELECT access required by avatar replacement upserts", () => {
    const migration = readFileSync(
      path.resolve(process.cwd(), "supabase/migrations/202608280003_profile_avatar_replace_policy.sql"),
      "utf8",
    )

    expect(migration).toContain("for select to authenticated")
    expect(migration).toContain("bucket_id = 'profile-avatars'")
    expect(migration).toContain("auth.uid()::text")
  })
})
