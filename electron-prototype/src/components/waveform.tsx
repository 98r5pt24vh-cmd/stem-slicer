import { useId } from "react"

import { cn } from "@/lib/utils"

const DEFAULT_BARS = [
  14, 24, 35, 52, 31, 66, 78, 49, 41, 72, 88, 61, 46, 76, 92, 57, 38, 69,
  83, 55, 33, 64, 74, 45, 29, 58, 86, 63, 42, 70, 90, 54, 36, 67, 80, 48,
  26, 53, 71, 43, 20, 47, 62, 38, 18, 34, 51, 27,
]

interface WaveformProps {
  progress: number
  label: string
  compact?: boolean
  bars?: number[]
}

function WaveBars({ className, bars }: { className?: string; bars: number[] }) {
  return (
    <div className={cn("wave-bars", className)} aria-hidden="true">
      {bars.map((height, index) => (
        <span key={`${index}-${height}`} style={{ height: `${height}%` }} />
      ))}
    </div>
  )
}

export function Waveform({
  progress,
  label,
  compact = false,
  bars = DEFAULT_BARS,
}: WaveformProps) {
  const descriptionId = useId()
  const clampedProgress = Math.max(0, Math.min(progress, 1))

  return (
    <div
      className={cn("waveform", compact && "waveform-compact")}
      role="img"
      aria-labelledby={descriptionId}
    >
      <span id={descriptionId} className="sr-only">
        {label}, lecture à {Math.round(clampedProgress * 100)} pour cent
      </span>
      <WaveBars bars={bars} className="text-wave-idle" />
      <div
        className="wave-progress"
        style={{ clipPath: `inset(0 ${100 - clampedProgress * 100}% 0 0)` }}
      >
        <WaveBars bars={bars} className="text-success" />
      </div>
      <span
        className="wave-playhead"
        style={{ insetInlineStart: `${clampedProgress * 100}%` }}
        aria-hidden="true"
      />
    </div>
  )
}
