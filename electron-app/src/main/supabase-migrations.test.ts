import { readdirSync } from "node:fs"
import path from "node:path"

import { describe, expect, it } from "vitest"

const MIGRATION_FILE_PATTERN = /^(\d+)_([a-z0-9_]+)\.sql$/

describe("Supabase migration history", () => {
  it("uses one unique numeric version per migration", () => {
    const migrationDirectory = path.resolve(process.cwd(), "supabase", "migrations")
    const migrationFiles = readdirSync(migrationDirectory)
      .filter((fileName) => fileName.endsWith(".sql"))
      .sort()
    const versions = migrationFiles.map((fileName) => {
      const match = MIGRATION_FILE_PATTERN.exec(fileName)
      expect(match, `${fileName} must follow <version>_<name>.sql`).not.toBeNull()
      return match?.[1]
    })

    expect(new Set(versions).size).toBe(versions.length)
  })
})
