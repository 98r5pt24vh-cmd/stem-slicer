import { useId, useLayoutEffect, useMemo, useRef, useState } from "react"

import { cn } from "@/lib/utils"
import { downsampleWaveformPeaks, waveformBarCapacity } from "@/lib/waveform"

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
  const waveformRef = useRef<HTMLDivElement>(null)
  const [visibleBarCount, setVisibleBarCount] = useState(bars.length)
  const clampedProgress = Math.max(0, Math.min(progress, 1))
  const visibleBars = useMemo(
    () => downsampleWaveformPeaks(bars, visibleBarCount),
    [bars, visibleBarCount],
  )

  useLayoutEffect(() => {
    const waveform = waveformRef.current
    if (!waveform) return

    const updateCapacity = (width: number) => {
      const nextCount = waveformBarCapacity(width, bars.length)
      setVisibleBarCount((currentCount) =>
        currentCount === nextCount ? currentCount : nextCount,
      )
    }

    updateCapacity(waveform.getBoundingClientRect().width)

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) updateCapacity(entry.contentRect.width)
    })
    resizeObserver.observe(waveform)

    return () => resizeObserver.disconnect()
  }, [bars.length])

  return (
    <div
      ref={waveformRef}
      className={cn("waveform", compact && "waveform-compact")}
      role="img"
      aria-labelledby={descriptionId}
    >
      <span id={descriptionId} className="sr-only">
        {label}, lecture à {Math.round(clampedProgress * 100)} pour cent
      </span>
      <WaveBars bars={visibleBars} className="text-wave-idle" />
      <div
        className="wave-progress"
        style={{ clipPath: `inset(0 ${100 - clampedProgress * 100}% 0 0)` }}
      >
        <WaveBars bars={visibleBars} className="text-success" />
      </div>
      <span
        className="wave-playhead"
        style={{ insetInlineStart: `${clampedProgress * 100}%` }}
        aria-hidden="true"
      />
    </div>
  )
}
