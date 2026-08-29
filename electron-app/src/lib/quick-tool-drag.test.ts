import { describe, expect, it } from "vitest"

import { quickFileToolFromDragHover } from "./quick-tool-drag"

describe("Quick Tool file drag hover", () => {
  it.each(["extract", "scan", "convert"] as const)("selects %s for an external file drag", (tool) => {
    expect(quickFileToolFromDragHover(tool, ["Files"])).toBe(tool)
  })

  it("ignores the folder Slicer tab and non-file drags", () => {
    expect(quickFileToolFromDragHover("slicer", ["Files"])).toBeNull()
    expect(quickFileToolFromDragHover("scan", ["text/plain"])).toBeNull()
  })
})
