import { describe, expect, it } from "vitest"

import { resolveUserPaths } from "./user-paths"

describe("resolveUserPaths", () => {
  it("preserves the accepted macOS cache and document locations", () => {
    expect(resolveUserPaths({
      platform: "darwin",
      environment: {},
      homeDirectory: "/Users/producer",
    })).toEqual({
      acceptedCachePath: "/Users/producer/Library/Caches/Stem Slicer/1.9",
      prototypeCachePath: "/Users/producer/Library/Caches/Stem Slicer/electron-prototype",
      documentsRoot: "/Users/producer/Documents",
      generatedOutputRoot: "/Users/producer/Documents/Stem Slicer/Generated Loops",
      defaultExtractionOutputPath: "/Users/producer/Documents/Stem Slicer/Extracted Layers/Loop Pack Name",
    })
  })

  it("uses the native local application data folder on Windows", () => {
    expect(resolveUserPaths({
      platform: "win32",
      environment: { LOCALAPPDATA: "C:\\Users\\XT\\AppData\\Local" },
      homeDirectory: "C:\\Users\\XT",
    })).toEqual({
      acceptedCachePath: "C:\\Users\\XT\\AppData\\Local\\Stem Slicer\\1.9",
      prototypeCachePath: "C:\\Users\\XT\\AppData\\Local\\Stem Slicer\\electron-prototype",
      documentsRoot: "C:\\Users\\XT\\Documents",
      generatedOutputRoot: "C:\\Users\\XT\\Documents\\Stem Slicer\\Generated Loops",
      defaultExtractionOutputPath: "C:\\Users\\XT\\Documents\\Stem Slicer\\Extracted Layers\\Loop Pack Name",
    })
  })
})
