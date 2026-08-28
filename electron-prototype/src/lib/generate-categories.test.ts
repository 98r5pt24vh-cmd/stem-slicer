import { describe, expect, it } from "vitest"

import { GENERATE_CATEGORY_OPTIONS, mergeGenerateCategories } from "./generate-categories"

describe("Generate categories", () => {
  it("pins the deployed V4.2 taxonomy to twelve categories", () => {
    expect(GENERATE_CATEGORY_OPTIONS).toEqual([
      "Arp", "Bass", "Chords", "Counter", "Guitar Chords", "Keys",
      "Lead", "Pad", "Pluck", "Strings", "Texture", "Vocal Chop",
    ])
  })

  it("folds legacy Piano and Bells counts into Keys and rejects retired labels", () => {
    expect(mergeGenerateCategories([
      { name: "Keys", count: 223 },
      { name: "Bells", count: 104 },
      { name: "Piano", count: 21 },
      { name: "Synth", count: 1 },
      { name: "Guitar Lead", count: 1 },
      { name: "Percussion", count: 1 },
    ])).toEqual([{ name: "Keys", count: 348 }])
  })
})
