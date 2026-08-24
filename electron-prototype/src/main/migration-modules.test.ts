import { describe, expect, it } from "vitest"

import { migrationModules } from "./migration-modules"

describe("migration boundary", () => {
  it("keeps the accepted catalogue in the TypeScript-owned surface", () => {
    expect(migrationModules.find((module) => module.id === "library-catalog")).toMatchObject({
      runtime: "TypeScript",
      state: "connected",
    })
  })

  it("marks MERT as a temporary adapter instead of claiming a completed port", () => {
    expect(migrationModules.find((module) => module.id === "mert-inference")).toMatchObject({
      runtime: "Python adapter",
      state: "queued",
    })
  })
})
