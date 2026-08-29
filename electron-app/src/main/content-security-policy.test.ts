import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"

describe("renderer content security policy", () => {
  it("allows public Supabase profile avatars without opening arbitrary image hosts", () => {
    const index = readFileSync(path.resolve(process.cwd(), "index.html"), "utf8")

    expect(index).toContain("img-src 'self' data: blob: stem-media: https://*.supabase.co http://localhost:*")
  })
})
