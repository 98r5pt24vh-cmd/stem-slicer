import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { describe, expect, it } from "vitest"

import { historyRoot, isAllowedHistoryOutput, readHistoryStorageUsage } from "./activity-history"

describe("activity history filesystem boundaries", () => {
  it("only accepts individual Slicer output folders", () => {
    const documents = "/Users/test/Documents"
    expect(isAllowedHistoryOutput(documents, "generate", `${historyRoot(documents)}/Generated Loops/Gen 1`)).toBe(true)
    expect(isAllowedHistoryOutput(documents, "extract", `${historyRoot(documents)}/Quick Extract/Loop 1`)).toBe(true)
    expect(isAllowedHistoryOutput(documents, "extract", `${historyRoot(documents)}/Extracted Layers/Pack 1`)).toBe(true)
    expect(isAllowedHistoryOutput(documents, "convert", `${historyRoot(documents)}/Quick Convert/Loop 1`)).toBe(true)
    expect(isAllowedHistoryOutput(documents, "generate", `${historyRoot(documents)}/Generated Loops`)).toBe(false)
    expect(isAllowedHistoryOutput(documents, "convert", "/Users/test/Desktop/Unrelated")).toBe(false)
  })

  it("counts files and decimal bytes without double-counting nested paths", () => {
    const root = mkdtempSync(path.join(tmpdir(), "slicer-history-"))
    const nested = path.join(root, "nested")
    mkdirSync(nested)
    writeFileSync(path.join(root, "master.mp3"), Buffer.alloc(12))
    writeFileSync(path.join(nested, "layer.mp3"), Buffer.alloc(8))
    expect(readHistoryStorageUsage([root, nested])).toEqual({ bytes: 20, folders: 1, files: 2 })
  })
})
