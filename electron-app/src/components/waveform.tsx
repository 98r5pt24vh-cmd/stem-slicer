import { memo, useId, useLayoutEffect, useMemo, useRef, useState } from "react"

import { cn } from "@/lib/utils"
import { clampPlaybackProgress, type PlaybackProgressSource } from "@/lib/playback-progress"
import { downsampleWaveformPeaks, waveformBarCapacity } from "@/lib/waveform"

const DEFAULT_BARS = [
  14, 24, 35, 52, 31, 66, 78, 49, 41, 72, 88, 61, 46, 76, 92, 57, 38, 69,
  83, 55, 33, 64, 74, 45, 29, 58, 86, 63, 42, 70, 90, 54, 36, 67, 80, 48,
  26, 53, 71, 43, 20, 47, 62, 38, 18, 34, 51, 27,
]

interface WaveformProps {
  progress?: number
  progressSource?: PlaybackProgressSource
  progressActive?: boolean
  label: string
  compact?: boolean
  bars?: number[]
}

const WaveBars = memo(function WaveBars({ className, bars }: { className?: string; bars: number[] }) {
  return (
    <div className={cn("wave-bars", className)} aria-hidden="true">
      {bars.map((height, index) => (
        <span key={`${index}-${height}`} style={{ height: `${height}%` }} />
      ))}
    </div>
  )
})

export function Waveform({
  progress = 0,
  progressSource,
  progressActive = true,
  label,
  compact = false,
  bars = DEFAULT_BARS,
}: WaveformProps) {
  const descriptionId = useId()
  const waveformRef = useRef<HTMLDivElement>(null)
  const progressRef = useRef<HTMLDivElement>(null)
  const playheadRef = useRef<HTMLSpanElement>(null)
  const descriptionRef = useRef<HTMLSpanElement>(null)
  const waveformWidthRef = useRef(0)
  const lastAccessiblePercentRef = useRef(-1)
  const [visibleBarCount, setVisibleBarCount] = useState(bars.length)
  const visibleBars = useMemo(
    () => downsampleWaveformPeaks(bars, visibleBarCount),
    [bars, visibleBarCount],
  )

  useLayoutEffect(() => {
    const applyProgress = () => {
      const nextProgress = progressActive
        ? clampPlaybackProgress(progressSource?.getProgress() ?? progress)
        : 0
      if (progressRef.current) {
        progressRef.current.style.clipPath = `inset(0 ${100 - nextProgress * 100}% 0 0)`
      }
      if (playheadRef.current) {
        playheadRef.current.style.transform = `translate3d(${nextProgress * waveformWidthRef.current - 0.5}px, 0, 0)`
      }
      const accessiblePercent = Math.round(nextProgress * 100)
      if (descriptionRef.current && accessiblePercent !== lastAccessiblePercentRef.current) {
        descriptionRef.current.textContent = `${label}, lecture à ${accessiblePercent} pour cent`
        lastAccessiblePercentRef.current = accessiblePercent
      }
    }

    applyProgress()
    return progressSource?.subscribe(applyProgress)
  }, [label, progress, progressActive, progressSource])

  useLayoutEffect(() => {
    const waveform = waveformRef.current
    if (!waveform) return

    const updateCapacity = (width: number) => {
      waveformWidthRef.current = width
      const nextCount = waveformBarCapacity(width, bars.length)
      setVisibleBarCount((currentCount) =>
        currentCount === nextCount ? currentCount : nextCount,
      )
      const nextProgress = progressActive
        ? clampPlaybackProgress(progressSource?.getProgress() ?? progress)
        : 0
      if (playheadRef.current) {
        playheadRef.current.style.transform = `translate3d(${nextProgress * width - 0.5}px, 0, 0)`
      }
    }

    updateCapacity(waveform.getBoundingClientRect().width)

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) updateCapacity(entry.contentRect.width)
    })
    resizeObserver.observe(waveform)

    return () => resizeObserver.disconnect()
  }, [bars.length, progress, progressActive, progressSource])

  return (
    <div
      ref={waveformRef}
      className={cn("waveform", compact && "waveform-compact")}
      role="img"
      aria-labelledby={descriptionId}
    >
      <span ref={descriptionRef} id={descriptionId} className="sr-only" />
      <WaveBars bars={visibleBars} className="text-wave-idle" />
      <div
        ref={progressRef}
        className="wave-progress"
      >
        <WaveBars bars={visibleBars} className="text-success" />
      </div>
      <span
        ref={playheadRef}
        className="wave-playhead"
        aria-hidden="true"
      />
    </div>
  )
}
