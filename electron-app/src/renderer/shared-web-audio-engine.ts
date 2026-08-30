export interface SharedAudioLayer {
  id: string
  url: string
  duration: number
  gain: number
}

export interface SharedPlaybackStart {
  startedAt: number
  offsetSeconds: number
  timelineDuration: number
}

interface DecodedLayer {
  descriptor: SharedAudioLayer
  buffer: AudioBuffer
}

interface ActiveLayerNodes {
  source: AudioBufferSourceNode
  gain: GainNode
}

export const AUDIO_START_AHEAD_SECONDS = 0.02
const MAX_PLAYBACK_GAIN = 1.25
const END_EPSILON_SECONDS = 1 / 48_000

export function clampPlaybackProgress(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(value, 1))
}

export function clampPlaybackGain(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(value, MAX_PLAYBACK_GAIN))
}

export function sharedTimelineDuration(layers: Array<{ duration: number }>): number {
  const durations = layers
    .map((layer) => layer.duration)
    .filter((duration) => Number.isFinite(duration) && duration > 0)
  return durations.length > 0 ? Math.min(...durations) : 0
}

export function transportProgress(
  startedAt: number,
  currentTime: number,
  offsetSeconds: number,
  timelineDuration: number,
  loop: boolean,
): number {
  if (timelineDuration <= 0) return 0
  const elapsed = Math.max(0, currentTime - startedAt)
  const position = offsetSeconds + elapsed
  if (loop) return (position % timelineDuration) / timelineDuration
  return clampPlaybackProgress(position / timelineDuration)
}

/**
 * One Web Audio graph shared by every generated/extracted layer.
 *
 * AudioBufferSourceNode looping happens inside the audio rendering thread. The
 * UI never waits for an `ended` event to restart a file, which is the property
 * needed for a gapless layer stack.
 */
export class SharedWebAudioEngine {
  private context: AudioContext | null = null
  private masterGain: GainNode | null = null
  private descriptors = new Map<string, SharedAudioLayer>()
  private decoded = new Map<string, DecodedLayer>()
  private decodePromises = new Map<string, Promise<DecodedLayer>>()
  private active = new Map<string, ActiveLayerNodes>()
  private retiring = new Set<ActiveLayerNodes>()
  private mutedIds = new Set<string>()
  private masterVolume = 1
  private requestVersion = 0

  get currentTime(): number {
    return this.context?.currentTime ?? 0
  }

  configureLayers(layers: SharedAudioLayer[]): void {
    this.stop()
    this.replaceDescriptors(layers)
  }

  async prepareReplacement(layers: SharedAudioLayer[]): Promise<boolean> {
    const requestVersion = this.requestVersion + 1
    this.requestVersion = requestVersion
    this.replaceDescriptors(layers)
    await this.preload()
    return requestVersion === this.requestVersion
  }

  private replaceDescriptors(layers: SharedAudioLayer[]): void {
    const nextDescriptors = new Map(layers.map((layer) => [layer.id, layer]))

    for (const [id, decoded] of this.decoded) {
      const next = nextDescriptors.get(id)
      if (!next || next.url !== decoded.descriptor.url) this.decoded.delete(id)
    }
    for (const [id] of this.decodePromises) {
      if (!nextDescriptors.has(id)) this.decodePromises.delete(id)
    }

    this.descriptors = nextDescriptors
    this.mutedIds = new Set([...this.mutedIds].filter((id) => nextDescriptors.has(id)))
  }

  async preload(): Promise<void> {
    await Promise.all([...this.descriptors.keys()].map((id) => this.decodeLayer(id)))
  }

  setMasterVolume(value: number): void {
    this.masterVolume = clampPlaybackGain(value)
    if (this.masterGain && this.context) {
      this.masterGain.gain.setValueAtTime(this.masterVolume, this.context.currentTime)
    }
  }

  setLayerGain(id: string, value: number): void {
    const descriptor = this.descriptors.get(id)
    if (descriptor) descriptor.gain = clampPlaybackGain(value)
    this.applyLayerGain(id)
  }

  setMutedIds(ids: Set<string>): void {
    const previous = this.mutedIds
    this.mutedIds = new Set(ids)
    for (const id of new Set([...previous, ...this.mutedIds])) this.applyLayerGain(id)
  }

  async start(ids: string[], progress: number, loop: boolean): Promise<SharedPlaybackStart | null> {
    this.stop()
    const requestVersion = this.requestVersion
    const uniqueIds = [...new Set(ids)].filter((id) => this.descriptors.has(id))
    if (uniqueIds.length === 0) return null

    const context = this.ensureContext()
    const decodedLayers = await Promise.all(uniqueIds.map((id) => this.decodeLayer(id)))
    if (requestVersion !== this.requestVersion) return null

    await context.resume()
    if (requestVersion !== this.requestVersion) return null

    const timelineDuration = sharedTimelineDuration(decodedLayers.map(({ descriptor, buffer }) => ({
      duration: Math.min(descriptor.duration > 0 ? descriptor.duration : buffer.duration, buffer.duration),
    })))
    if (timelineDuration <= 0) throw new Error("The selected audio layers have no playable duration.")

    const normalizedProgress = clampPlaybackProgress(progress)
    const requestedOffset = normalizedProgress >= 1 ? 0 : normalizedProgress * timelineDuration
    const offsetSeconds = Math.min(requestedOffset, Math.max(0, timelineDuration - END_EPSILON_SECONDS))
    const startedAt = context.currentTime + AUDIO_START_AHEAD_SECONDS

    for (const { descriptor, buffer } of decodedLayers) {
      const source = context.createBufferSource()
      const gain = context.createGain()
      source.buffer = buffer
      source.loop = loop
      source.loopStart = 0
      source.loopEnd = timelineDuration
      gain.gain.value = this.mutedIds.has(descriptor.id) ? 0 : descriptor.gain
      source.connect(gain)
      gain.connect(this.ensureMasterGain(context))
      this.active.set(descriptor.id, { source, gain })

      if (loop) source.start(startedAt, offsetSeconds)
      else source.start(startedAt, offsetSeconds, Math.max(END_EPSILON_SECONDS, timelineDuration - offsetSeconds))
    }

    return { startedAt, offsetSeconds, timelineDuration }
  }

  async swapPrepared(ids: string[], progress: number, loop: boolean): Promise<SharedPlaybackStart | null> {
    const requestVersion = this.requestVersion
    const uniqueIds = [...new Set(ids)].filter((id) => this.descriptors.has(id))
    if (uniqueIds.length === 0) return null

    const context = this.ensureContext()
    const decodedLayers = await Promise.all(uniqueIds.map((id) => this.decodeLayer(id)))
    if (requestVersion !== this.requestVersion) return null

    await context.resume()
    if (requestVersion !== this.requestVersion) return null

    const timelineDuration = sharedTimelineDuration(decodedLayers.map(({ descriptor, buffer }) => ({
      duration: Math.min(descriptor.duration > 0 ? descriptor.duration : buffer.duration, buffer.duration),
    })))
    if (timelineDuration <= 0) throw new Error("The selected audio layers have no playable duration.")

    const normalizedProgress = clampPlaybackProgress(progress)
    const requestedOffset = normalizedProgress >= 1 ? 0 : normalizedProgress * timelineDuration
    const offsetSeconds = Math.min(requestedOffset, Math.max(0, timelineDuration - END_EPSILON_SECONDS))
    const startedAt = context.currentTime + AUDIO_START_AHEAD_SECONDS
    const previousActive = this.active
    const nextActive = new Map<string, ActiveLayerNodes>()

    for (const { descriptor, buffer } of decodedLayers) {
      const source = context.createBufferSource()
      const gain = context.createGain()
      source.buffer = buffer
      source.loop = loop
      source.loopStart = 0
      source.loopEnd = timelineDuration
      gain.gain.value = this.mutedIds.has(descriptor.id) ? 0 : descriptor.gain
      source.connect(gain)
      gain.connect(this.ensureMasterGain(context))
      nextActive.set(descriptor.id, { source, gain })

      if (loop) source.start(startedAt, offsetSeconds)
      else source.start(startedAt, offsetSeconds, Math.max(END_EPSILON_SECONDS, timelineDuration - offsetSeconds))
    }

    this.active = nextActive
    for (const nodes of previousActive.values()) {
      this.retiring.add(nodes)
      nodes.source.addEventListener("ended", () => {
        this.disconnectNodes(nodes)
        this.retiring.delete(nodes)
      }, { once: true })
      try {
        nodes.source.stop(startedAt)
      } catch {
        this.disconnectNodes(nodes)
        this.retiring.delete(nodes)
      }
    }

    return { startedAt, offsetSeconds, timelineDuration }
  }

  stop(): void {
    this.requestVersion += 1
    for (const nodes of this.active.values()) this.stopNodes(nodes)
    for (const nodes of this.retiring) this.stopNodes(nodes)
    this.active.clear()
    this.retiring.clear()
  }

  async close(): Promise<void> {
    this.stop()
    const context = this.context
    this.context = null
    this.masterGain = null
    this.decoded.clear()
    this.decodePromises.clear()
    if (context && context.state !== "closed") await context.close()
  }

  private ensureContext(): AudioContext {
    if (!this.context || this.context.state === "closed") {
      this.context = new AudioContext({ latencyHint: "interactive" })
      this.masterGain = null
    }
    this.ensureMasterGain(this.context)
    return this.context
  }

  private ensureMasterGain(context: AudioContext): GainNode {
    if (!this.masterGain) {
      this.masterGain = context.createGain()
      this.masterGain.gain.value = this.masterVolume
      this.masterGain.connect(context.destination)
    }
    return this.masterGain
  }

  private async decodeLayer(id: string): Promise<DecodedLayer> {
    const descriptor = this.descriptors.get(id)
    if (!descriptor) throw new Error("The selected audio layer is no longer available.")

    const cached = this.decoded.get(id)
    if (cached?.descriptor.url === descriptor.url) return cached

    const pending = this.decodePromises.get(id)
    if (pending) return pending

    const promise = (async () => {
      const response = await fetch(descriptor.url)
      if (!response.ok) throw new Error(`Audio file could not be loaded (${response.status}).`)
      const encoded = await response.arrayBuffer()
      const buffer = await this.ensureContext().decodeAudioData(encoded)
      const latestDescriptor = this.descriptors.get(id)
      if (!latestDescriptor || latestDescriptor.url !== descriptor.url) {
        throw new Error("The audio layer changed while it was being decoded.")
      }
      const decodedLayer = { descriptor: latestDescriptor, buffer }
      this.decoded.set(id, decodedLayer)
      return decodedLayer
    })().finally(() => {
      if (this.decodePromises.get(id) === promise) this.decodePromises.delete(id)
    })

    this.decodePromises.set(id, promise)
    return promise
  }

  private applyLayerGain(id: string): void {
    const nodes = this.active.get(id)
    const descriptor = this.descriptors.get(id)
    if (!nodes || !descriptor || !this.context) return
    const value = this.mutedIds.has(id) ? 0 : descriptor.gain
    nodes.gain.gain.setValueAtTime(value, this.context.currentTime)
  }

  private stopNodes(nodes: ActiveLayerNodes): void {
    try {
      nodes.source.stop()
    } catch {
      // A source may already have ended naturally.
    }
    this.disconnectNodes(nodes)
  }

  private disconnectNodes(nodes: ActiveLayerNodes): void {
    try {
      nodes.source.disconnect()
    } catch {
      // A node can already be disconnected by an ended callback.
    }
    try {
      nodes.gain.disconnect()
    } catch {
      // A node can already be disconnected by an ended callback.
    }
  }
}
