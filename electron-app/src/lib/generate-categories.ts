import type { CategorySummary } from "@/shared/contracts"

export const GENERATE_CATEGORY_OPTIONS = [
  "Arp", "Bass", "Chords", "Counter", "Guitar Chords", "Keys",
  "Lead", "Pad", "Pluck", "Strings", "Texture", "Vocal Chop",
]

const GENERATE_CATEGORY_ALIASES = new Map([
  ["bells", "Keys"],
  ["piano", "Keys"],
])

export function mergeGenerateCategories(...groups: CategorySummary[][]): CategorySummary[] {
  const supported = new Set(GENERATE_CATEGORY_OPTIONS.map((category) => category.toLowerCase()))
  const canonicalNames = new Map(GENERATE_CATEGORY_OPTIONS.map((category) => [category.toLowerCase(), category]))
  const counts = new Map<string, number>()
  for (const group of groups) {
    for (const category of group) {
      const rawKey = category.name.trim().toLowerCase()
      const key = (GENERATE_CATEGORY_ALIASES.get(rawKey) ?? rawKey).toLowerCase()
      if (!supported.has(key) || category.count <= 0) continue
      const name = canonicalNames.get(key) ?? category.name.trim()
      counts.set(name, (counts.get(name) ?? 0) + category.count)
    }
  }
  return [...counts].map(([name, count]) => ({ name, count }))
    .sort((left, right) => right.count - left.count || left.name.localeCompare(right.name))
}
