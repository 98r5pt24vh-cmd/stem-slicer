import { describe, expect, it } from "vitest"

import { basename, cn, formatCount } from "./utils"

describe("renderer utilities", () => {
  it("extracts names from macOS and Windows paths", () => {
    expect(basename("/Music/Library One")).toBe("Library One")
    expect(basename("C:\\Music\\Library Two")).toBe("Library Two")
  })

  it("uses French decimal grouping for catalogue counts", () => {
    expect(formatCount(13_203).replace(/\s/g, " ")).toBe("13 203")
  })

  it("merges conflicting Tailwind classes", () => {
    expect(cn("px-2", "px-4", undefined)).toContain("px-4")
    expect(cn("px-2", "px-4")).not.toContain("px-2")
  })
})
