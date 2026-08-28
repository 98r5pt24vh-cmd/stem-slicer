import { describe, expect, it } from "vitest"

import {
  compactGenerationKey,
  generationDisplayName,
  sourceProvenance,
  stripAudioExtension,
  uniqueProducerCredits,
  uniqueProducerNames,
} from "./source-provenance"

describe("source provenance", () => {
  it("reads a standard +NRGY collaboration filename", () => {
    expect(sourceProvenance("Dm NITROV2 151 +NRGY TEENX_L6.mp3")).toEqual({
      loopName: "NITROV2",
      producers: ["+NRGY", "TEENX"],
    })
  })

  it("reads the alternate Liv catalogue format", () => {
    expect(sourceProvenance("638 TAKE ME OUT 197 Fmin Liv_L3.mp3")).toEqual({
      loopName: "TAKE ME OUT",
      producers: ["Liv"],
    })
  })

  it("keeps source credits separate from final generated-loop credits", () => {
    expect(uniqueProducerNames(["Liv", "liv", "+nrgy"])).toEqual(["Liv", "+NRGY"])
    expect(uniqueProducerCredits(["Liv"])).toEqual(["+NRGY", "Liv"])
  })

  it("keeps the primary producer first and removes duplicate credits", () => {
    expect(uniqueProducerCredits(["XT", "+nrgy", "xt", "Liv"])).toEqual(["+NRGY", "XT", "Liv"])
  })

  it("builds the compact generated-loop name with its key", () => {
    expect(generationDisplayName(1, 140, "D# minor", ["XT", "+NRGY"])).toBe("L Gen01_140_D#m +NRGY XT")
    expect(compactGenerationKey("G♭ major")).toBe("Gb")
  })

  it("removes only a final audio extension", () => {
    expect(stripAudioExtension("01_Bass.mp3")).toBe("01_Bass")
  })
})
