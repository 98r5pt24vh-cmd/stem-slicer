import type { SourceLoopEditorLayer } from "@/shared/contracts"

const PREVIEW_BARS = 8
const BEATS_PER_BAR = 4
const PEAK_COUNT = 110

interface ActivePreviewNode {
  source: AudioBufferSourceNode
  gain: GainNode
}

export interface SourceLoopPreviewStart {
  startedAt: number
  duration: number
}

export function editorTimelineSeconds(bpm: number): number {
  return PREVIEW_BARS * BEATS_PER_BAR * 60 / bpm
}

export function audioBufferPeaks(buffer: AudioBuffer, count = PEAK_COUNT): number[] {
  const peaks: number[] = []
  const framesPerBin = Math.max(1, Math.ceil(buffer.length / count))
  for (let bin = 0; bin < count; bin += 1) {
    const start = bin * framesPerBin
    const end = Math.min(buffer.length, start + framesPerBin)
    let peak = 0
    for (let channel = 0; channel < buffer.numberOfChannels; channel += 1) {
      const samples = buffer.getChannelData(channel)
      for (let frame = start; frame < end; frame += 1) peak = Math.max(peak, Math.abs(samples[frame] ?? 0))
    }
    peaks.push(Math.max(5, Math.round(Math.min(1, peak) * 100)))
  }
  return peaks
}

export class SourceLoopPreviewEngine {
  private context: AudioContext | null = null
  private readonly buffers = new Map<string, AudioBuffer>()
  private readonly pending = new Map<string, Promise<AudioBuffer>>()
  private active: ActivePreviewNode[] = []

  get currentTime(): number {
    return this.context?.currentTime ?? 0
  }

  async prepare(layers: SourceLoopEditorLayer[]): Promise<Map<string, number[]>> {
    const decoded = await Promise.all(layers.map(async (layer) => [layer.identity, await this.decode(layer)] as const))
    return new Map(decoded.map(([identity, buffer]) => [identity, audioBufferPeaks(buffer)]))
  }

  async play(
    layers: SourceLoopEditorLayer[],
    bpm: number,
    soloIdentity?: string,
  ): Promise<SourceLoopPreviewStart> {
    this.stop()
    const context = this.ensureContext()
    await context.resume()
    const duration = editorTimelineSeconds(bpm)
    const timelineFrames = Math.max(1, Math.round(duration * context.sampleRate))
    const startedAt = context.currentTime + 0.025

    for (const layer of layers) {
      const decoded = await this.decode(layer)
      const rendered = this.renderTrack(context, decoded, layer, bpm, timelineFrames)
      const source = context.createBufferSource()
      const gain = context.createGain()
      source.buffer = rendered
      source.loop = true
      source.loopStart = 0
      source.loopEnd = duration
      gain.gain.value = soloIdentity && soloIdentity !== layer.identity ? 0 : 1
      source.connect(gain)
      gain.connect(context.destination)
      source.start(startedAt)
      this.active.push({ source, gain })
    }
    return { startedAt, duration }
  }

  stop(): void {
    for (const node of this.active) {
      try {
        node.source.stop()
      } catch {
        // The preview source may already be stopped.
      }
      node.source.disconnect()
      node.gain.disconnect()
    }
    this.active = []
  }

  async close(): Promise<void> {
    this.stop()
    const context = this.context
    this.context = null
    this.buffers.clear()
    this.pending.clear()
    if (context && context.state !== "closed") await context.close()
  }

  private ensureContext(): AudioContext {
    if (!this.context || this.context.state === "closed") this.context = new AudioContext({ latencyHint: "interactive" })
    return this.context
  }

  private async decode(layer: SourceLoopEditorLayer): Promise<AudioBuffer> {
    const cached = this.buffers.get(layer.identity)
    if (cached) return cached
    const existing = this.pending.get(layer.identity)
    if (existing) return existing
    const promise = (async () => {
      const api = window.stemSlicer
      if (!api) throw new Error("The desktop audio preview service is unavailable.")
      const response = await fetch(api.mediaUrl(layer.path))
      if (!response.ok) throw new Error(`Unable to load ${layer.file}.`)
      const buffer = await this.ensureContext().decodeAudioData(await response.arrayBuffer())
      this.buffers.set(layer.identity, buffer)
      return buffer
    })().finally(() => this.pending.delete(layer.identity))
    this.pending.set(layer.identity, promise)
    return promise
  }

  private renderTrack(
    context: AudioContext,
    source: AudioBuffer,
    layer: SourceLoopEditorLayer,
    bpm: number,
    timelineFrames: number,
  ): AudioBuffer {
    const target = context.createBuffer(source.numberOfChannels, timelineFrames, context.sampleRate)
    const framesPerBeat = context.sampleRate * 60 / bpm
    const trimStart = Math.max(0, Math.round(layer.trimStartBeats * framesPerBeat))
    const trimEnd = Math.max(0, Math.round(layer.trimEndBeats * framesPerBeat))
    const offset = Math.max(0, Math.round(layer.offsetBeats * framesPerBeat))
    const readableFrames = Math.max(0, Math.min(source.length - trimStart - trimEnd, timelineFrames - offset))
    if (readableFrames <= 0) return target
    for (let channel = 0; channel < source.numberOfChannels; channel += 1) {
      const segment = source.getChannelData(channel).subarray(trimStart, trimStart + readableFrames)
      target.copyToChannel(segment, channel, offset)
    }
    return target
  }
}
