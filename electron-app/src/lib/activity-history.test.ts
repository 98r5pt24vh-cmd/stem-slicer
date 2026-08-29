import { describe, expect, it } from "vitest"

import { parseConvertHistory, parseExtractionHistory, prependUniqueActivity } from "./activity-history"

describe("activity history persistence", () => {
  it("keeps valid single-file and folder extractions", () => {
    const entries = parseExtractionHistory(JSON.stringify([
      { id: "single", mode: "single", sourcePath: "/loop.mp3", outputFolder: "/single", createdAt: "2026-08-28T12:00:00.000Z", sourceFileCount: 1, outputCount: 5, outputs: ["/single/L1.mp3"] },
      { id: "folder", mode: "folder", sourcePath: "/pack", outputFolder: "/folder", createdAt: "2026-08-28T12:01:00.000Z", sourceFileCount: 12, outputCount: 45, outputs: ["/folder/L1.mp3"] },
      { id: "invalid", mode: "archive" },
    ]))

    expect(entries.map((entry) => entry.mode)).toEqual(["single", "folder"])
  })

  it("rejects incomplete conversion entries", () => {
    expect(parseConvertHistory(JSON.stringify([{ id: "broken", artifact: { path: "/file.mp3" } }]))).toEqual([])
    expect(parseConvertHistory("not-json")).toEqual([])
  })

  it("moves a repeated output to the front without duplicating it", () => {
    const entries = prependUniqueActivity(
      [{ output: "a", version: 1 }, { output: "b", version: 1 }],
      { output: "a", version: 2 },
      (entry) => entry.output,
    )

    expect(entries).toEqual([{ output: "a", version: 2 }, { output: "b", version: 1 }])
  })
})
