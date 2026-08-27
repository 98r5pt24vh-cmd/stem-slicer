import { describe, expect, it } from "vitest"

import { editorTimelineSeconds, editorTrackAudible, editorTrackGain } from "./source-loop-preview-engine"

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

  it("applies per-track preview volume after mute and solo", () => {
    const volumes = new Map([["lead", 72], ["bass", 140]])
    expect(editorTrackGain("lead", new Set(), undefined, volumes)).toBe(0.72)
    expect(editorTrackGain("bass", new Set(), undefined, volumes)).toBe(1.25)
    expect(editorTrackGain("lead", new Set(["lead"]), undefined, volumes)).toBe(0)
    expect(editorTrackGain("lead", new Set(), "bass", volumes)).toBe(0)
  })
})
