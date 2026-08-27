import { describe, expect, it } from "vitest"

import {
  keyFamilyForKey,
  randomKeyOutsidePreviousFamily,
  TARGET_KEY_FAMILIES,
} from "./random-key"

describe("random key generation", () => {
  it("never reuses the previous relative-key family", () => {
    const previousKey = "F minor"
    const previousFamily = keyFamilyForKey(previousKey)
    const generated = Array.from(
      { length: TARGET_KEY_FAMILIES.length - 1 },
      (_, index) => randomKeyOutsidePreviousFamily(previousKey, () => index),
    )

    expect(new Set(generated.map(keyFamilyForKey)).size).toBe(11)
    expect(generated.every((key) => key.endsWith(" minor"))).toBe(true)
    expect(generated.every((key) => keyFamilyForKey(key) !== previousFamily)).toBe(true)
  })

  it("preserves the selected major or minor mode", () => {
    expect(randomKeyOutsidePreviousFamily("C major", () => 0)).toMatch(/ major$/)
    expect(randomKeyOutsidePreviousFamily("A minor", () => 0)).toMatch(/ minor$/)
  })

  it("treats enharmonic spellings as the same family", () => {
    expect(keyFamilyForKey("A♭ major")).toBe(keyFamilyForKey("G♯ major"))
  })
})
