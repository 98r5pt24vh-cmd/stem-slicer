import { describe, expect, it } from "vitest"

import {
  generationDisplayName,
  sourceProvenance,
  stripAudioExtension,
  uniqueProducerCredits,
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
      producers: ["+NRGY", "Liv"],
    })
  })

  it("keeps the primary producer first and removes duplicate credits", () => {
    expect(uniqueProducerCredits(["XT", "+nrgy", "xt", "Liv"])).toEqual(["+NRGY", "XT", "Liv"])
  })

  it("builds the canonical generated-loop name", () => {
    expect(generationDisplayName(1, 140, ["XT", "+NRGY"])).toBe("L Generation 01 140 +NRGY XT")
  })

  it("removes only a final audio extension", () => {
    expect(stripAudioExtension("01_Bass.mp3")).toBe("01_Bass")
  })
})
