export interface PlaybackProgressSource {
  getProgress: () => number
  subscribe: (listener: () => void) => () => void
}

export interface PlaybackProgressStore extends PlaybackProgressSource {
  setProgress: (progress: number) => void
}

export function clampPlaybackProgress(progress: number) {
  if (!Number.isFinite(progress)) return 0
  return Math.max(0, Math.min(progress, 1))
}

export function createPlaybackProgressStore(initialProgress = 0): PlaybackProgressStore {
  let progress = clampPlaybackProgress(initialProgress)
  const listeners = new Set<() => void>()

  return {
    getProgress: () => progress,
    setProgress: (nextProgress) => {
      const clampedProgress = clampPlaybackProgress(nextProgress)
      if (clampedProgress === progress) return
      progress = clampedProgress
      for (const listener of listeners) listener()
    },
    subscribe: (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
  }
}
