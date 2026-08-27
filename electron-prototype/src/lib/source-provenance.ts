export const PRIMARY_PRODUCER = "+NRGY"

export interface SourceProvenance {
  loopName: string
  producers: string[]
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

function canonicalProducer(value: string): string {
  return value.toLowerCase() === PRIMARY_PRODUCER.toLowerCase() ? PRIMARY_PRODUCER : value
}

export function uniqueProducerCredits(values: Iterable<string>): string[] {
  const credits = [PRIMARY_PRODUCER]
  const seen = new Set([PRIMARY_PRODUCER.toLowerCase()])
  for (const rawValue of values) {
    const value = canonicalProducer(rawValue.trim())
    if (!value || seen.has(value.toLowerCase())) continue
    seen.add(value.toLowerCase())
    credits.push(value)
  }
  return credits
}

export function sourceProvenance(file: string, sourceLoopId = ""): SourceProvenance {
  const source = withoutLayerSuffix(file || sourceLoopId)
  const tokens = source.split(/\s+/).filter(Boolean)
  if (tokens.length === 0) return { loopName: "Source loop", producers: [PRIMARY_PRODUCER] }

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
      producers: [PRIMARY_PRODUCER],
    }
  }

  const loopTokens = tokens.slice(leadingIndex + leadingKeyTokens, bpmIndex)
  const producerStart = bpmIndex + 1 + (leadingKeyTokens > 0 ? 0 : keyTokenCount(tokens, bpmIndex + 1))
  const producers = uniqueProducerCredits(tokens.slice(producerStart))
  return {
    loopName: loopTokens.join(" ").trim() || "Source loop",
    producers,
  }
}

export function provenanceForLayer(layer: ProvenanceLayer): SourceProvenance {
  const parsed = sourceProvenance(layer.sourceFile ?? layer.sourceLoopId ?? "", layer.sourceLoopId)
  return {
    loopName: layer.sourceLoopName?.trim() || parsed.loopName,
    producers: uniqueProducerCredits(layer.producers?.length ? layer.producers : parsed.producers),
  }
}

export function producersForLayers(layers: ProvenanceLayer[]): string[] {
  return uniqueProducerCredits(layers.flatMap((layer) => provenanceForLayer(layer).producers))
}

export function generationDisplayName(generationNumber: number, bpm: number, producers: Iterable<string>): string {
  const number = Math.max(1, Math.round(generationNumber)).toString().padStart(2, "0")
  return `L Generation ${number} ${Math.round(bpm)} ${uniqueProducerCredits(producers).join(" ")}`
}

export function producerMonogram(producer: string): string {
  return producer.replace(/^\+/, "").replace(/[^a-z0-9]/gi, "").slice(0, 2).toUpperCase() || "P"
}
