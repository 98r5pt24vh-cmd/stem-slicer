import { describe, expect, it, vi } from "vitest"

import { createPlaybackProgressStore } from "./playback-progress"

describe("playback progress store", () => {
  it("clamps progress and only notifies listeners when the value changes", () => {
    const store = createPlaybackProgressStore()
    const listener = vi.fn()
    const unsubscribe = store.subscribe(listener)

    store.setProgress(0.25)
    store.setProgress(0.25)
    store.setProgress(2)
    store.setProgress(Number.NaN)

    expect(store.getProgress()).toBe(0)
    expect(listener).toHaveBeenCalledTimes(3)

    unsubscribe()
    store.setProgress(0.5)
    expect(listener).toHaveBeenCalledTimes(3)
  })
})
