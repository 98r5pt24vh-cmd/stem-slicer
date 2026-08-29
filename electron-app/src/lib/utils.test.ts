import { describe, expect, it } from "vitest"

import { basename, cn, extractionFolderNameForSource, formatCount, formatDecimalBytes, joinPath, outputFolderNameError } from "./utils"

describe("renderer utilities", () => {
  it("extracts names from macOS and Windows paths", () => {
    expect(basename("/Music/Library One")).toBe("Library One")
    expect(basename("C:\\Music\\Library Two")).toBe("Library Two")
  })

  it("joins native macOS and Windows folder paths", () => {
    expect(joinPath("/Users/producer/Extracted Layers/", "Noise Extracted Layers")).toBe("/Users/producer/Extracted Layers/Noise Extracted Layers")
    expect(joinPath("C:\\Users\\XT\\Extracted Layers\\", "Noise Extracted Layers")).toBe("C:\\Users\\XT\\Extracted Layers\\Noise Extracted Layers")
  })

  it("derives a portable extraction folder name from the source folder", () => {
    expect(extractionFolderNameForSource("/Users/producer/Noise by Me")).toBe("Noise by Me Extracted Layers")
    expect(extractionFolderNameForSource("C:\\Loops\\A:B? Pack")).toBe("A B Pack Extracted Layers")
    expect(extractionFolderNameForSource("C:\\Loops\\CON")).toBe("Loop pack Extracted Layers")
  })

  it("validates editable output folder names for Mac and Windows", () => {
    expect(outputFolderNameError("Noise by Me Extracted Layers")).toBe("")
    expect(outputFolderNameError("Noise/Extracted")).toContain("Remove slashes")
    expect(outputFolderNameError("NUL")).toBe("Choose a different folder name.")
  })

  it("uses French decimal grouping for catalogue counts", () => {
    expect(formatCount(13_203).replace(/\s/g, " ")).toBe("13 203")
  })

  it("formats storage with decimal macOS units", () => {
    expect(formatDecimalBytes(850_000_000)).toBe("850 Mo")
    expect(formatDecimalBytes(2_560_000_000)).toBe("2,56 Go")
  })

  it("merges conflicting Tailwind classes", () => {
    expect(cn("px-2", "px-4", undefined)).toContain("px-4")
    expect(cn("px-2", "px-4")).not.toContain("px-2")
  })
})
