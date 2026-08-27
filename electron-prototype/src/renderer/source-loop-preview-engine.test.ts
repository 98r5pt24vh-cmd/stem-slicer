import { describe, expect, it } from "vitest"

import { editorTimelineSeconds, editorTrackAudible } from "./source-loop-preview-engine"

describe("source loop preview helpers", () => {
  it("keeps the editor timeline at exactly eight four-beat bars", () => {
    expect(editorTimelineSeconds(120)).toBe(16)
    expect(editorTimelineSeconds(140)).toBeCloseTo(13.7142857)
  })

  it("applies mute and solo without changing transport state", () => {
    expect(editorTrackAudible("lead", new Set())).toBe(true)
    expect(editorTrackAudible("lead", new Set(["lead"]))).toBe(false)
    expect(editorTrackAudible("lead", new Set(), "lead")).toBe(true)
    expect(editorTrackAudible("lead", new Set(), "bass")).toBe(false)
    expect(editorTrackAudible("lead", new Set(["lead"]), "lead")).toBe(false)
  })
})
