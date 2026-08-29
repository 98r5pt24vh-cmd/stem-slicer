import { useMemo } from "react"

const FALLBACK_PEAKS = [18, 30, 22, 42, 36, 58, 31, 50, 72, 46, 64, 38, 55, 77, 43, 69]

function waveformPolygon(peaks: number[]): string {
  const source = peaks.length > 1 ? peaks : FALLBACK_PEAKS
  const lastIndex = source.length - 1
  const points = source.map((peak, index) => {
    const x = index / lastIndex * 1000
    const amplitude = Math.max(4, Math.min(100, peak)) * 0.42
    return { x, top: 50 - amplitude, bottom: 50 + amplitude }
  })
  return [
    ...points.map(({ x, top }) => `${x.toFixed(2)},${top.toFixed(2)}`),
    ...points.slice().reverse().map(({ x, bottom }) => `${x.toFixed(2)},${bottom.toFixed(2)}`),
  ].join(" ")
}

export function StudioWaveform({ peaks }: { peaks?: number[] }) {
  const points = useMemo(() => waveformPolygon(peaks ?? FALLBACK_PEAKS), [peaks])
  return (
    <svg className="studio-waveform" viewBox="0 0 1000 100" preserveAspectRatio="none" aria-hidden="true">
      <line className="studio-waveform-center" x1="0" y1="50" x2="1000" y2="50" />
      <polygon className="studio-waveform-shape" points={points} />
    </svg>
  )
}
