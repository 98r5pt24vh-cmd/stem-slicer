import { describe, expect, it } from "vitest"

import { clampPlaybackProgress, sharedTimelineDuration, transportProgress } from "./shared-web-audio-engine"

describe("shared Web Audio transport math", () => {
  it("clamps seek positions", () => {
    expect(clampPlaybackProgress(-0.2)).toBe(0)
    expect(clampPlaybackProgress(0.42)).toBe(0.42)
    expect(clampPlaybackProgress(1.4)).toBe(1)
  })

  it("uses one safe duration for a synchronized layer stack", () => {
    expect(sharedTimelineDuration([{ duration: 7.44 }, { duration: 7.44 }, { duration: 7.42 }])).toBe(7.42)
    expect(sharedTimelineDuration([{ duration: 0 }, { duration: Number.NaN }])).toBe(0)
  })

  it("wraps continuously on the shared audio clock", () => {
    expect(transportProgress(10, 11, 6.5, 7.5, true)).toBeCloseTo(0)
    expect(transportProgress(10, 11.75, 6.5, 7.5, true)).toBeCloseTo(0.1)
  })

  it("clamps a non-looping transport at its end", () => {
    expect(transportProgress(10, 20, 0, 7.5, false)).toBe(1)
  })
})
