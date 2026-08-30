export const TARGET_KEY_FAMILIES = [
  "C major / A minor", "C♯ major / A♯ minor", "D major / B minor",
  "D♯ major / C minor", "E major / C♯ minor", "F major / D minor",
  "F♯ major / D♯ minor", "G major / E minor", "G♯ major / F minor",
  "A major / F♯ minor", "A♯ major / G minor", "B major / G♯ minor",
]

const ENHARMONIC_SHARPS: Record<string, string> = {
  Db: "C#",
  Eb: "D#",
  Gb: "F#",
  Ab: "G#",
  Bb: "A#",
}

export function normalizeKeyName(value: string): string {
  const text = value
    .normalize("NFKC")
    .replace(/[\u200B-\u200D\u2060\uFEFF]/g, "")
    .replace(/\uFE0E|\uFE0F/g, "")
    .replace(/[\u266f＃]/g, "#")
    .replace(/[\u266dᵇ]/g, "b")
    .trim()
  const [rawTonic = "", rawMode = ""] = text.split(/\s+/, 2)
  const tonic = rawTonic
    ? `${rawTonic[0].toUpperCase()}${rawTonic.slice(1)}`
    : ""
  const mode = rawMode.toLowerCase()
  return `${ENHARMONIC_SHARPS[tonic] ?? tonic} ${mode}`.trim()
}

export function keyFamilyForKey(keyName: string): string {
  const normalizedKey = normalizeKeyName(keyName)
  return TARGET_KEY_FAMILIES.find((family) => family
    .split("/")
    .some((member) => normalizeKeyName(member) === normalizedKey))
    ?? TARGET_KEY_FAMILIES[0]
}

export function compactKeyFamilyLabel(family: string): string {
  return family
    .split("/")
    .map((member) => member.trim().replace(/ major$/i, " Maj").replace(/ minor$/i, " min"))
    .join(" / ")
}

export function keyFromFamily(family: string, previousKey: string): string {
  const members = family.split("/").map((member) => member.trim())
  return previousKey.toLowerCase().endsWith(" minor") && members[1] ? members[1] : members[0]
}

function secureIndex(upperExclusive: number): number {
  const value = globalThis.crypto.getRandomValues(new Uint32Array(1))[0]
  return value % upperExclusive
}

export function randomKeyOutsidePreviousFamily(
  previousKey: string,
  drawIndex: (upperExclusive: number) => number = secureIndex,
): string {
  const previousFamily = keyFamilyForKey(previousKey)
  const choices = TARGET_KEY_FAMILIES.filter((family) => family !== previousFamily)
  const index = drawIndex(choices.length)
  if (!Number.isInteger(index) || index < 0 || index >= choices.length) {
    throw new RangeError("Random-key index is outside the available family range.")
  }
  return keyFromFamily(choices[index], previousKey)
}
