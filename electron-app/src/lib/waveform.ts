const WAVE_BAR_MIN_WIDTH = 1
const WAVE_BAR_GAP = 2

export function waveformBarCapacity(width: number, sourceCount: number) {
  if (!Number.isFinite(width) || width <= 0 || sourceCount <= 0) {
    return 0
  }

  const capacity = Math.floor(
    (width + WAVE_BAR_GAP) / (WAVE_BAR_MIN_WIDTH + WAVE_BAR_GAP),
  )

  return Math.max(1, Math.min(sourceCount, capacity))
}

export function downsampleWaveformPeaks(peaks: number[], targetCount: number) {
  if (targetCount <= 0 || peaks.length === 0) {
    return []
  }

  if (peaks.length <= targetCount) {
    return peaks
  }

  return Array.from({ length: targetCount }, (_, index) => {
    const start = Math.floor((index * peaks.length) / targetCount)
    const end = Math.max(
      start + 1,
      Math.floor(((index + 1) * peaks.length) / targetCount),
    )

    let peak = peaks[start] ?? 0
    for (let sourceIndex = start + 1; sourceIndex < end; sourceIndex += 1) {
      peak = Math.max(peak, peaks[sourceIndex] ?? 0)
    }
    return peak
  })
}
