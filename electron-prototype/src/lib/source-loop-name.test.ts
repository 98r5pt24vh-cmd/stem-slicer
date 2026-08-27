import { describe, expect, it } from "vitest"

import { studioLayerName } from "./source-loop-name"

describe("studioLayerName", () => {
  it("keeps only the loop name and layer number for the standard library format", () => {
    expect(studioLayerName({
      file: "G#m FOCUS 144 +NRGY_L10.mp3",
      bpm: 144,
      keyName: "G♯ minor",
      layerIndex: 10,
    })).toEqual({
      loopName: "FOCUS",
      layerLabel: "Layer 10",
      fullLabel: "FOCUS · Layer 10",
    })
  })

  it("does not confuse digits inside a loop name with the BPM", () => {
    expect(studioLayerName({
      file: "Am FOCUS2 154 +NRGY_L1.mp3",
      bpm: 154,
      keyName: "A minor",
      layerIndex: 1,
    }).fullLabel).toBe("FOCUS2 · Layer 1")
  })

  it("keeps the label clean after the BPM and key are edited in Studio", () => {
    expect(studioLayerName({
      file: "G#m FOCUS 144 +NRGY_L4.mp3",
      bpm: 152,
      keyName: "A minor",
      layerIndex: 4,
    }).fullLabel).toBe("FOCUS · Layer 4")
  })

  it("removes a leading catalogue number from alternate producer filenames", () => {
    expect(studioLayerName({
      file: "638 TAKE ME OUT 197 Fmin Liv_L3.mp3",
      bpm: 197,
      keyName: "F minor",
      layerIndex: 3,
    }).fullLabel).toBe("TAKE ME OUT · Layer 3")
  })
})
