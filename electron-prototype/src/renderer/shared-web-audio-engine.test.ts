import { afterEach, describe, expect, it, vi } from "vitest"

import { clampPlaybackProgress, SharedWebAudioEngine, sharedTimelineDuration, transportProgress } from "./shared-web-audio-engine"

describe("shared Web Audio transport math", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("clamps seek positions", () => {
    expect(clampPlaybackProgress(-0.2)).toBe(0)
    expect(clampPlaybackProgress(0.42)).toBe(0.42)
    expect(clampPlaybackProgress(1.4)).toBe(1)
  })

  it("uses one safe duration for a synchronized layer stack", () => {
    expect(sharedTimelineDuration([{ duration: 7.44 }, { duration: 7.44 }, { duration: 7.42 }])).toBe(7.42)
    expect(sharedTimelineDuration([{ duration: 0 }, { duration: Number.NaN }])).toBe(0)
  })

  it("wraps continuously on the shared audio clock", () => {
    expect(transportProgress(10, 11, 6.5, 7.5, true)).toBeCloseTo(0)
    expect(transportProgress(10, 11.75, 6.5, 7.5, true)).toBeCloseTo(0.1)
  })

  it("clamps a non-looping transport at its end", () => {
    expect(transportProgress(10, 20, 0, 7.5, false)).toBe(1)
  })

  it("keeps the previous graph alive until a prepared replacement starts", async () => {
    const sources: FakeBufferSource[] = []
    const context = new FakeAudioContext(sources)
    vi.stubGlobal("AudioContext", class {
      constructor() {
        return context
      }
    })
    vi.stubGlobal("fetch", vi.fn(async () => new Response(new Uint8Array([1, 2, 3]))))

    const engine = new SharedWebAudioEngine()
    engine.configureLayers([{ id: "old", url: "stem-media://old", duration: 8, gain: 1 }])
    await engine.preload()
    await engine.start(["old"], 0.25, true)
    const oldSource = sources.at(-1)
    expect(oldSource).toBeDefined()

    await engine.prepareReplacement([{ id: "new", url: "stem-media://new", duration: 8, gain: 1 }])
    expect(oldSource?.stopTimes).toEqual([])

    const replacement = await engine.swapPrepared(["new"], 0.5, true)
    const newSource = sources.at(-1)
    expect(replacement).not.toBeNull()
    expect(newSource?.startTimes[0]).toEqual([replacement?.startedAt, 4])
    expect(oldSource?.stopTimes).toEqual([replacement?.startedAt])

    await engine.close()
  })
})

class FakeAudioParam {
  value = 1

  setValueAtTime(value: number) {
    this.value = value
  }
}

class FakeGainNode {
  gain = new FakeAudioParam()

  connect() {}

  disconnect() {}
}

class FakeBufferSource extends EventTarget {
  buffer: AudioBuffer | null = null
  loop = false
  loopStart = 0
  loopEnd = 0
  startTimes: number[][] = []
  stopTimes: Array<number | undefined> = []

  connect() {}

  disconnect() {}

  start(...values: number[]) {
    this.startTimes.push(values)
  }

  stop(when?: number) {
    this.stopTimes.push(when)
  }
}

class FakeAudioContext {
  currentTime = 10
  destination = {}
  state: AudioContextState = "running"

  constructor(private readonly sources: FakeBufferSource[]) {}

  createBufferSource() {
    const source = new FakeBufferSource()
    this.sources.push(source)
    return source as unknown as AudioBufferSourceNode
  }

  createGain() {
    return new FakeGainNode() as unknown as GainNode
  }

  async decodeAudioData() {
    return { duration: 8 } as AudioBuffer
  }

  async resume() {}

  async close() {
    this.state = "closed"
  }
}
