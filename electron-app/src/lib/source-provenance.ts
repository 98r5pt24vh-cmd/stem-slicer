export const PRIMARY_PRODUCER = "+NRGY"

export interface SourceProvenance {
  loopName: string
  producers: string[]
}

export interface ProducerIdentityDefinition {
  canonicalName: string
  aliases: string[]
}

export interface ProducerIdentityResolver {
  canonicalize: (value: string) => string
  parseCredits: (tokens: string[]) => string[]
}

interface ProvenanceLayer {
  sourceFile?: string
  sourceLoopId?: string
  sourceLoopName?: string
  producers?: string[]
}

const COMPACT_KEY = /^[A-G](?:#|b|♯|♭)?(?:(?:m|min|minor|maj|major))?$/i
const MODE_TOKEN = /^(?:m|min|minor|maj|major)$/i

export function stripAudioExtension(value: string): string {
  return value.replace(/\.(?:mp3|wav|aif|aiff|flac|m4a|ogg)$/i, "")
}

function withoutLayerSuffix(value: string): string {
  return stripAudioExtension(value)
    .replace(/(?:[_\s-])(?:layer\s*)?l?\d+$/i, "")
    .trim()
}

function keyTokenCount(tokens: string[], index: number): number {
  const token = tokens[index] ?? ""
  if (!COMPACT_KEY.test(token)) return 0
  const tonicOnly = /^[A-G](?:#|b|♯|♭)?$/i.test(token)
  return tonicOnly && MODE_TOKEN.test(tokens[index + 1] ?? "") ? 2 : 1
}

function normalizedPrimaryProducer(value: string): string {
  return value.trim() || PRIMARY_PRODUCER
}

function canonicalProducer(value: string, primaryProducer: string): string {
  return value.toLowerCase() === primaryProducer.toLowerCase() ? primaryProducer : value
}

function producerIdentityKey(value: string): string {
  return value.normalize("NFKC").trim().replace(/^@/, "").replace(/\s+/g, " ").toLocaleLowerCase()
}

export function createProducerIdentityResolver(
  identities: ProducerIdentityDefinition[] = [],
  primaryProducer = PRIMARY_PRODUCER,
): ProducerIdentityResolver {
  const primary = normalizedPrimaryProducer(primaryProducer)
  const claims = new Map<string, Set<string>>()
  const canonicalNames = new Map<string, string>()

  const addClaim = (rawAlias: string, rawCanonicalName: string) => {
    const aliasKey = producerIdentityKey(rawAlias)
    const canonicalName = canonicalProducer(rawCanonicalName.trim(), primary)
    const canonicalKey = producerIdentityKey(canonicalName)
    if (!aliasKey || !canonicalKey) return
    canonicalNames.set(canonicalKey, canonicalName)
    const owners = claims.get(aliasKey) ?? new Set<string>()
    owners.add(canonicalKey)
    claims.set(aliasKey, owners)
  }

  addClaim(primary, primary)
  for (const identity of identities) {
    const canonicalName = String(identity?.canonicalName || "").trim()
    if (!canonicalName) continue
    addClaim(canonicalName, canonicalName)
    for (const alias of identity.aliases ?? []) addClaim(String(alias || ""), canonicalName)
  }

  const resolved = new Map<string, string>()
  for (const [aliasKey, owners] of claims) {
    if (owners.size !== 1) continue
    const canonicalKey = [...owners][0]
    const canonicalName = canonicalNames.get(canonicalKey)
    if (canonicalName) resolved.set(aliasKey, canonicalName)
  }
  const patterns = [...resolved.keys()]
    .map((key) => ({ key, tokenCount: key.split(" ").length }))
    .sort((left, right) => right.tokenCount - left.tokenCount || right.key.length - left.key.length)

  return {
    canonicalize(value) {
      const trimmed = String(value || "").trim().replace(/\s+/g, " ")
      return resolved.get(producerIdentityKey(trimmed)) ?? canonicalProducer(trimmed, primary)
    },
    parseCredits(tokens) {
      const credits: string[] = []
      for (let index = 0; index < tokens.length;) {
        const match = patterns.find((pattern) => {
          if (index + pattern.tokenCount > tokens.length) return false
          return producerIdentityKey(tokens.slice(index, index + pattern.tokenCount).join(" ")) === pattern.key
        })
        if (match) {
          credits.push(resolved.get(match.key) as string)
          index += match.tokenCount
        } else {
          credits.push(tokens[index])
          index += 1
        }
      }
      return credits
    },
  }
}

function withoutMusicalKeyTokens(tokens: string[]): string[] {
  const retained: string[] = []
  for (let index = 0; index < tokens.length;) {
    const token = tokens[index] ?? ""
    const next = tokens[index + 1] ?? ""
    const tonicWithMode = /^[A-G](?:#|b|♯|♭)?$/i.test(token) && MODE_TOKEN.test(next)
    if (tonicWithMode) {
      index += 2
      continue
    }
    if (COMPACT_KEY.test(token)) {
      index += 1
      continue
    }
    retained.push(token)
    index += 1
  }
  return retained
}

export function uniqueProducerNames(values: Iterable<string>, primaryProducer = PRIMARY_PRODUCER): string[] {
  const primary = normalizedPrimaryProducer(primaryProducer)
  const credits: string[] = []
  const seen = new Set<string>()
  for (const rawValue of values) {
    const value = canonicalProducer(rawValue.trim(), primary)
    if (!value || seen.has(value.toLowerCase())) continue
    seen.add(value.toLowerCase())
    credits.push(value)
  }
  return credits
}

export function uniqueProducerCredits(values: Iterable<string>, primaryProducer = PRIMARY_PRODUCER): string[] {
  const primary = normalizedPrimaryProducer(primaryProducer)
  return uniqueProducerNames([primary, ...values], primary)
}

export function sourceProvenance(
  file: string,
  sourceLoopId = "",
  primaryProducer = PRIMARY_PRODUCER,
  identityResolver = createProducerIdentityResolver([], primaryProducer),
): SourceProvenance {
  const primary = normalizedPrimaryProducer(primaryProducer)
  const source = withoutLayerSuffix(file || sourceLoopId)
  const tokens = source.split(/\s+/).filter(Boolean)
  if (tokens.length === 0) return { loopName: "Source loop", producers: [primary] }

  let leadingIndex = 0
  if (/^\d+$/.test(tokens[leadingIndex] ?? "") && Number(tokens[leadingIndex]) > 300) leadingIndex += 1
  const leadingKeyTokens = keyTokenCount(tokens, leadingIndex)
  const bpmIndex = tokens.findIndex((token, index) => (
    index >= leadingIndex
    && /^\d{2,3}$/.test(token)
    && Number(token) >= 40
    && Number(token) <= 300
  ))

  if (bpmIndex < 0) {
    const fallbackTokens = tokens.slice(leadingIndex + leadingKeyTokens)
    return {
      loopName: fallbackTokens.join(" ") || source || "Source loop",
      producers: [primary],
    }
  }

  const loopTokens = tokens.slice(leadingIndex + leadingKeyTokens, bpmIndex)
  const producerStart = bpmIndex + 1 + (leadingKeyTokens > 0 ? 0 : keyTokenCount(tokens, bpmIndex + 1))
  const producerTokens = withoutMusicalKeyTokens(tokens.slice(producerStart))
  const producers = uniqueProducerNames(
    identityResolver.parseCredits(producerTokens).map((producer) => identityResolver.canonicalize(producer)),
    primary,
  )
  return {
    loopName: loopTokens.join(" ").trim() || "Source loop",
    producers: producers.length > 0 ? producers : [primary],
  }
}

export function provenanceForLayer(layer: ProvenanceLayer, primaryProducer = PRIMARY_PRODUCER): SourceProvenance {
  const primary = normalizedPrimaryProducer(primaryProducer)
  const parsed = sourceProvenance(layer.sourceFile ?? layer.sourceLoopId ?? "", layer.sourceLoopId, primary)
  const producers = uniqueProducerNames(layer.producers?.length ? layer.producers : parsed.producers, primary)
  return {
    loopName: layer.sourceLoopName?.trim() || parsed.loopName,
    producers: producers.length > 0 ? producers : [primary],
  }
}

export function producersForLayers(layers: ProvenanceLayer[], primaryProducer = PRIMARY_PRODUCER): string[] {
  return uniqueProducerCredits(layers.flatMap((layer) => provenanceForLayer(layer, primaryProducer).producers), primaryProducer)
}

export function compactGenerationKey(keyName: string): string {
  const normalized = keyName
    .trim()
    .replaceAll("♯", "#")
    .replaceAll("♭", "b")
  const match = /^([A-G](?:#|b)?)(?:\s*(major|maj|minor|min|m))?$/i.exec(normalized)
  if (!match) return normalized.replace(/\s+/g, "") || "Key"
  const tonic = `${match[1][0].toUpperCase()}${match[1].slice(1)}`
  const mode = match[2]?.toLowerCase() ?? "major"
  return `${tonic}${mode === "minor" || mode === "min" || mode === "m" ? "m" : ""}`
}

export function generationDisplayName(generationNumber: number, bpm: number, keyName: string, producers: Iterable<string>, primaryProducer = PRIMARY_PRODUCER): string {
  const number = Math.max(1, Math.round(generationNumber)).toString().padStart(2, "0")
  return `L Gen${number}_${Math.round(bpm)}_${compactGenerationKey(keyName)} ${uniqueProducerCredits(producers, primaryProducer).join(" ")}`
}

export function producerMonogram(producer: string): string {
  return producer.replace(/^\+/, "").replace(/[^a-z0-9]/gi, "").slice(0, 2).toUpperCase() || "P"
}
