import { describe, expect, it } from "vitest"

import {
  compactGenerationKey,
  createProducerIdentityResolver,
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

  it("keeps a repeated alias in the loop title while canonicalizing the producer credit", () => {
    const identities = createProducerIdentityResolver([
      { canonicalName: "XT", aliases: ["Tinex", "T-Next Is Here"] },
    ])

    expect(sourceProvenance("Tinex 140 Tinex_L1.mp3", "", "+NRGY", identities)).toEqual({
      loopName: "Tinex",
      producers: ["XT"],
    })
    expect(sourceProvenance("NIGHT DRIVE 140 T-Next Is Here_L1.mp3", "", "+NRGY", identities)).toEqual({
      loopName: "NIGHT DRIVE",
      producers: ["XT"],
    })
    expect(sourceProvenance("PARIS 123 C#MIN @Tinex_L1.mp3", "", "+NRGY", identities).producers).toEqual(["XT"])
  })

  it("never treats compact or separated musical keys as producer names", () => {
    for (const key of ["C#MIN", "c#min", "C#m", "C# MIN", "c# minor", "D♭MAJ", "Db major", "E", "F#", "g♭"]) {
      expect(sourceProvenance(`LOOP 140 XT ${key}_L1.mp3`, "", "XT").producers).toEqual(["XT"])
    }
  })

  it("uses the signed-in producer for sources without explicit credits", () => {
    expect(sourceProvenance("FMIN PRIVATE LOOP 140_L1.mp3", "", "XT")).toEqual({
      loopName: "PRIVATE LOOP",
      producers: ["XT"],
    })
    expect(uniqueProducerCredits(["+NRGY"], "XT")).toEqual(["XT", "+NRGY"])
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
