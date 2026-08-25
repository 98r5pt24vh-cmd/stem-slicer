import { describe, expect, it } from "vitest"

import { downsampleWaveformPeaks, waveformBarCapacity } from "./waveform"

describe("responsive waveform rendering", () => {
  it("keeps the original peaks when every bar fits", () => {
    const peaks = [10, 20, 30, 40]

    expect(downsampleWaveformPeaks(peaks, 4)).toBe(peaks)
    expect(downsampleWaveformPeaks(peaks, 8)).toBe(peaks)
  })

  it("compresses the complete source timeline into the requested width", () => {
    expect(downsampleWaveformPeaks([1, 2, 3, 4, 5, 6, 7, 8], 4)).toEqual([
      2, 4, 6, 8,
    ])
  })

  it("preserves a late transient instead of clipping the end", () => {
    const peaks = Array.from({ length: 110 }, () => 4)
    peaks[87] = 96

    const visiblePeaks = downsampleWaveformPeaks(peaks, 60)

    expect(visiblePeaks).toHaveLength(60)
    expect(visiblePeaks).toContain(96)
    expect(visiblePeaks.at(-1)).toBe(4)
  })

  it("fits bars and gaps inside the measured content width", () => {
    expect(waveformBarCapacity(200, 110)).toBe(67)
    expect(waveformBarCapacity(400, 110)).toBe(110)
    expect(waveformBarCapacity(0, 110)).toBe(0)
  })
})
