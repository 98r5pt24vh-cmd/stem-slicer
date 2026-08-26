import { Dialog } from "@base-ui/react/dialog"
import { Select as BaseSelect } from "@base-ui/react/select"
import {
  AudioLines,
  Check,
  ChevronDown,
  ChevronLeft,
  CircleAlert,
  Cloud,
  CloudCog,
  Database,
  FolderCog,
  FolderOpen,
  History,
  Layers3,
  Lock,
  Music2,
  Pause,
  Play,
  Plus,
  Radio,
  RefreshCw,
  Repeat2,
  RotateCcw,
  ScanLine,
  Settings2,
  SkipBack,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Unlock,
  Volume2,
  WandSparkles,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { Waveform } from "@/components/waveform"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { basename, cn, formatCount } from "@/lib/utils"
import { AUDIO_START_AHEAD_SECONDS, SharedWebAudioEngine, transportProgress } from "@/renderer/shared-web-audio-engine"
import type {
  AudioArtifact,
  AudioJobKind,
  AudioJobRequest,
  AudioJobResult,
  BatchJobResult,
  GenerateResult,
  LibraryOverview,
  QuickConvertResult,
  QuickExtractResult,
  QuickScanResult,
  ViewId,
} from "@/shared/contracts"

interface NavItem {
  id: ViewId
  label: string
  icon: LucideIcon
  badge?: string
}

interface GeneratedLayer {
  id: string
  role: string
  file: string
  category: string
  bpm: number
  keyName: string
  octave: number
  volume: number
  duration: number
  alternateKey?: string
  path?: string
  midiPath?: string
  sourcePath?: string
  identity?: string
  sourceKeyRank?: 1 | 2
  locked?: boolean
  bars: number[]
}

interface HistoryEntry {
  id: string
  bpm: number
  keyName: string
  recipe: string
  createdAt: string
  layerCount: number
  generation: GenerateResult
  layers: GeneratedLayer[]
}

function MetronomeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M8 19 10 5h4l2 14Z" />
      <path d="M6.5 21h11" />
      <path d="m12 16 4-9" />
      <circle cx="16" cy="7" r="1" fill="currentColor" stroke="none" />
    </svg>
  )
}

function MidiFileIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M3 2h14v16H3V2Zm9 3h3v2h-3V5ZM9 8h3v2H9V8Zm-3 3h3v2H6v-2Zm-2 3h3v2H4v-2Z"
      />
    </svg>
  )
}

type QuickToolId = "extract" | "scan" | "convert"

const NAVIGATION: NavItem[] = [
  { id: "stem-slicer", label: "Stem Slicer", icon: FolderCog },
  { id: "quick-tools", label: "Quick Tools", icon: Wrench },
  { id: "generate", label: "Generate", icon: Sparkles },
  { id: "history", label: "History", icon: History },
  { id: "cloud", label: "Connected Libraries", icon: Cloud, badge: "WIP" },
]

const TARGET_KEY_FAMILIES = [
  "C major / A minor", "C♯ major / A♯ minor", "D major / B minor",
  "D♯ major / C minor", "E major / C♯ minor", "F major / D minor",
  "F♯ major / D♯ minor", "G major / E minor", "G♯ major / F minor",
  "A major / F♯ minor", "A♯ major / G minor", "B major / G♯ minor",
]

const ENHARMONIC_SHARPS: Record<string, string> = {
  "D♭": "C♯",
  "E♭": "D♯",
  "G♭": "F♯",
  "A♭": "G♯",
  "B♭": "A♯",
}

function normalizeKeyName(value: string): string {
  const [tonic, mode] = value.trim().split(/\s+/, 2)
  return `${ENHARMONIC_SHARPS[tonic] ?? tonic} ${mode ?? ""}`.trim()
}

function keyFamilyForKey(keyName: string): string {
  const normalizedKey = normalizeKeyName(keyName)
  return TARGET_KEY_FAMILIES.find((family) => family.split("/").some((member) => normalizeKeyName(member) === normalizedKey))
    ?? TARGET_KEY_FAMILIES[0]
}

function keyFromFamily(family: string, previousKey: string): string {
  const members = family.split("/").map((member) => member.trim())
  return previousKey.toLowerCase().endsWith(" minor") && members[1] ? members[1] : members[0]
}

const SHARP_CAMELOT_KEYS: Record<string, string> = {
  "1A": "G♯ minor", "2A": "D♯ minor", "3A": "A♯ minor", "4A": "F minor",
  "5A": "C minor", "6A": "G minor", "7A": "D minor", "8A": "A minor",
  "9A": "E minor", "10A": "B minor", "11A": "F♯ minor", "12A": "C♯ minor",
  "1B": "B major", "2B": "F♯ major", "3B": "C♯ major", "4B": "G♯ major",
  "5B": "D♯ major", "6B": "A♯ major", "7B": "F major", "8B": "C major",
  "9B": "G major", "10B": "D major", "11B": "A major", "12B": "E major",
}

const FLAT_CAMELOT_KEYS: Record<string, string> = {
  "1A": "A♭ minor", "2A": "E♭ minor", "3A": "B♭ minor", "4A": "F minor",
  "5A": "C minor", "6A": "G minor", "7A": "D minor", "8A": "A minor",
  "9A": "E minor", "10A": "B minor", "11A": "G♭ minor", "12A": "D♭ minor",
  "1B": "B major", "2B": "G♭ major", "3B": "D♭ major", "4B": "A♭ major",
  "5B": "E♭ major", "6B": "B♭ major", "7B": "F major", "8B": "C major",
  "9B": "G major", "10B": "D major", "11B": "A major", "12B": "E major",
}

function formatCamelotKey(camelot: string, notation: string, mode: "detected" | "relative" = "detected") {
  const match = /^(1[0-2]|[1-9])([AB])$/.exec(camelot)
  if (!match) return "—"
  const targetMode = mode === "relative" ? (match[2] === "A" ? "B" : "A") : match[2]
  const table = notation.startsWith("Flats") ? FLAT_CAMELOT_KEYS : SHARP_CAMELOT_KEYS
  return table[`${match[1]}${targetMode}`] ?? "—"
}

function formatModePitch(key: string, notation: string) {
  if (!notation.startsWith("Flats")) return key.replaceAll("#", "♯")
  return ({ "C#": "D♭", "D#": "E♭", "F#": "G♭", "G#": "A♭", "A#": "B♭" } as Record<string, string>)[key] ?? key
}

function pathFromDrop(event: React.DragEvent<HTMLElement>) {
  event.preventDefault()
  const file = event.dataTransfer.files.item(0)
  return file && window.stemSlicer ? window.stemSlicer.pathForFile(file) : ""
}

const INITIAL_LAYERS: GeneratedLayer[] = [
  {
    id: "lead",
    role: "Main idea",
    file: "NRGY_129_Fm_Lead_07.wav",
    category: "Lead",
    bpm: 129,
    keyName: "F minor",
    octave: 0,
    volume: 82,
    duration: 7.44,
    alternateKey: "A♭ major",
    bars: [18, 38, 63, 47, 78, 92, 61, 53, 85, 72, 48, 68, 96, 74, 43, 62, 88, 57, 35, 71, 83, 51, 29, 66, 78, 44, 24, 58, 91, 69, 39, 74, 87, 55, 32, 65, 80, 49, 27, 56, 73, 42, 22, 48, 67, 38, 18, 30],
  },
  {
    id: "chords",
    role: "Harmony",
    file: "NRGY_129_Fm_Chords_14.wav",
    category: "Chords",
    bpm: 129,
    keyName: "F minor",
    octave: -1,
    volume: 74,
    duration: 7.44,
    alternateKey: "A♭ major",
    bars: [43, 57, 68, 72, 61, 78, 84, 71, 66, 77, 82, 74, 64, 73, 88, 79, 67, 72, 81, 75, 62, 70, 85, 76, 63, 69, 80, 73, 60, 67, 78, 70, 58, 65, 75, 68, 54, 61, 71, 64, 50, 57, 67, 60, 45, 53, 62, 55],
  },
  {
    id: "counter",
    role: "Counter line",
    file: "NRGY_129_Fm_Counter_22.wav",
    category: "Counter",
    bpm: 129,
    keyName: "F minor",
    octave: 1,
    volume: 68,
    duration: 7.44,
    bars: [12, 27, 49, 72, 42, 21, 58, 86, 61, 33, 18, 47, 79, 93, 64, 38, 23, 55, 82, 68, 41, 19, 44, 75, 88, 59, 34, 16, 51, 80, 65, 37, 20, 46, 73, 84, 56, 31, 15, 48, 76, 62, 35, 18, 43, 69, 52, 24],
  },
  {
    id: "bass",
    role: "Low end",
    file: "NRGY_129_Fm_Bass_05.wav",
    category: "Bass",
    bpm: 129,
    keyName: "F minor",
    octave: -1,
    volume: 79,
    duration: 7.44,
    bars: [55, 70, 64, 48, 82, 76, 59, 43, 88, 73, 57, 45, 84, 79, 61, 47, 90, 75, 58, 44, 86, 77, 60, 46, 89, 74, 56, 42, 83, 78, 62, 49, 91, 72, 54, 41, 81, 76, 59, 45, 87, 71, 53, 40, 79, 68, 51, 38],
  },
  {
    id: "pad",
    role: "Atmosphere",
    file: "NRGY_129_Fm_Pad_18.wav",
    category: "Pad",
    bpm: 129,
    keyName: "F minor",
    octave: 0,
    volume: 61,
    duration: 7.44,
    alternateKey: "A♭ major",
    bars: [28, 34, 42, 47, 53, 58, 63, 68, 72, 75, 78, 81, 83, 85, 86, 87, 88, 88, 87, 86, 84, 81, 78, 74, 70, 65, 60, 55, 50, 45, 41, 37, 34, 32, 31, 30, 31, 33, 36, 40, 45, 51, 58, 65, 71, 76, 80, 82],
  },
]

const FALLBACK_LIBRARY: LibraryOverview = {
  databaseDetected: false,
  databasePath: "",
  totalLayers: 0,
  roots: [],
  categories: [],
  error: "Le catalogue sera lu au lancement dans Electron.",
}

const HISTORY_STORAGE_KEY = "stem-slicer-electron.generate-history.v1"

function loadGenerateHistory(): HistoryEntry[] {
  try {
    const stored = window.localStorage.getItem(HISTORY_STORAGE_KEY)
    if (!stored) return []
    const parsed = JSON.parse(stored)
    return Array.isArray(parsed)
      ? parsed
        .filter((item) => item && typeof item === "object" && item.generation?.masterPath && Array.isArray(item.layers))
        .map((item) => ({ ...item, recipe: "Generated" }))
      : []
  } catch {
    return []
  }
}

type PlaybackMode = "idle" | "solo" | "mix"

function usePlaybackClock(layers: GeneratedLayer[], stackPlayback: boolean) {
  const [playing, setPlaying] = useState(false)
  const [progress, setProgress] = useState(0)
  const [masterVolume, setMasterVolume] = useState(78)
  const [error, setError] = useState("")
  const [mode, setMode] = useState<PlaybackMode>(stackPlayback ? "mix" : "idle")
  const [soloId, setSoloId] = useState<string | null>(null)
  const [lastSoloId, setLastSoloId] = useState<string | null>(null)
  const [syncEnabled, setSyncEnabled] = useState(stackPlayback)
  const [loopEnabled, setLoopEnabled] = useState(false)
  const [mutedIds, setMutedIds] = useState<string[]>([])
  const [syncSoloId, setSyncSoloId] = useState<string | null>(null)
  const engineRef = useRef<SharedWebAudioEngine | null>(null)
  if (!engineRef.current) engineRef.current = new SharedWebAudioEngine()
  const playableIdsRef = useRef<string[]>([])
  const modeRef = useRef<PlaybackMode>(stackPlayback ? "mix" : "idle")
  const soloIdRef = useRef<string | null>(null)
  const lastSoloIdRef = useRef<string | null>(null)
  const syncEnabledRef = useRef(stackPlayback)
  const loopEnabledRef = useRef(false)
  const mutedIdsRef = useRef(new Set<string>())
  const syncSoloIdRef = useRef<string | null>(null)
  const playingRef = useRef(false)
  const positionRef = useRef(0)
  const startedAtRef = useRef(0)
  const startedOffsetSecondsRef = useRef(0)
  const timelineDurationRef = useRef(0)
  const playbackSessionRef = useRef(0)
  const scrubbingRef = useRef(false)
  const scrubEndingRef = useRef(false)
  const scrubSessionRef = useRef(0)
  const resumeAfterScrubRef = useRef(false)
  const scrubTargetRef = useRef<{ id: string; progress: number } | null>(null)
  const layerSourcesJson = JSON.stringify(layers.map((layer) => ({
    id: layer.id,
    path: layer.path ?? "",
    duration: layer.duration,
    revision: `${layer.octave}:${layer.sourceKeyRank ?? 1}`,
  })))

  const commitPlaying = useCallback((nextPlaying: boolean) => {
    playingRef.current = nextPlaying
    setPlaying(nextPlaying)
  }, [])

  const commitMode = useCallback((nextMode: PlaybackMode, nextSoloId: string | null) => {
    modeRef.current = nextMode
    soloIdRef.current = nextSoloId
    setMode(nextMode)
    setSoloId(nextSoloId)
  }, [])

  const commitLastSoloId = useCallback((nextSoloId: string | null) => {
    lastSoloIdRef.current = nextSoloId
    setLastSoloId(nextSoloId)
  }, [])

  const commitSyncEnabled = useCallback((nextEnabled: boolean) => {
    syncEnabledRef.current = nextEnabled
    setSyncEnabled(nextEnabled)
  }, [])

  const commitLoopEnabled = useCallback((nextEnabled: boolean) => {
    loopEnabledRef.current = nextEnabled
    setLoopEnabled(nextEnabled)
  }, [])

  const commitMutedIds = useCallback((nextMutedIds: Set<string>) => {
    mutedIdsRef.current = nextMutedIds
    engineRef.current?.setMutedIds(nextMutedIds)
    setMutedIds(Array.from(nextMutedIds))
  }, [])

  const commitSyncSoloId = useCallback((nextSoloId: string | null) => {
    syncSoloIdRef.current = nextSoloId
    setSyncSoloId(nextSoloId)
  }, [])

  const getCurrentProgress = useCallback(() => {
    if (!playingRef.current || timelineDurationRef.current <= 0) return positionRef.current
    return transportProgress(
      startedAtRef.current,
      engineRef.current?.currentTime ?? startedAtRef.current,
      startedOffsetSecondsRef.current,
      timelineDurationRef.current,
      loopEnabledRef.current,
    )
  }, [])

  useEffect(() => {
    const engine = engineRef.current
    if (!engine) return
    const preservedSyncEnabled = syncEnabledRef.current
    const preservedLoopEnabled = loopEnabledRef.current
    const canHotSwap = playingRef.current
      && modeRef.current === "mix"
      && preservedSyncEnabled
      && preservedLoopEnabled
      && playableIdsRef.current.length > 0
      && timelineDurationRef.current > 0
    playbackSessionRef.current += 1
    const sources = JSON.parse(layerSourcesJson) as Array<{ id: string; path: string; revision: string }>
    const mediaApi = window.stemSlicer
    const playable = mediaApi ? sources.filter((source) => source.path) : []
    playableIdsRef.current = playable.map((source) => source.id)
    const descriptors = playable.map((source) => {
      const layer = layers.find((candidate) => candidate.id === source.id)
      return {
        id: source.id,
        url: mediaApi ? `${mediaApi.mediaUrl(source.path)}&revision=${encodeURIComponent(source.revision)}` : "",
        duration: layer?.duration ?? 0,
        gain: Math.max(0, Math.min(1, (layer?.volume ?? 100) / 100)),
      }
    })
    engine.setMasterVolume(masterVolume / 100)
    setError("")

    if (canHotSwap && playable.length > 0) {
      const preparePromise = engine.prepareReplacement(descriptors)
      commitMode("mix", null)
      commitLastSoloId(null)
      commitSyncEnabled(true)
      commitLoopEnabled(true)
      commitMutedIds(new Set())
      commitSyncSoloId(null)
      scrubbingRef.current = false
      scrubEndingRef.current = false
      scrubSessionRef.current += 1
      resumeAfterScrubRef.current = false
      scrubTargetRef.current = null
      let cancelled = false
      void preparePromise.then(async (prepared) => {
        if (cancelled || !prepared) return
        const progressAtSwap = transportProgress(
          startedAtRef.current,
          engine.currentTime + AUDIO_START_AHEAD_SECONDS,
          startedOffsetSecondsRef.current,
          timelineDurationRef.current,
          true,
        )
        const started = await engine.swapPrepared(playableIdsRef.current, progressAtSwap, true)
        if (cancelled || !started) return
        startedAtRef.current = started.startedAt
        startedOffsetSecondsRef.current = started.offsetSeconds
        timelineDurationRef.current = started.timelineDuration
        positionRef.current = started.offsetSeconds / started.timelineDuration
        setProgress(positionRef.current)
        commitPlaying(true)
      }).catch((loadError) => {
        if (cancelled) return
        engine.stop()
        commitPlaying(false)
        setError(loadError instanceof Error ? loadError.message : "Audio replacement failed.")
      })
      return () => {
        cancelled = true
      }
    }

    engine.configureLayers(descriptors)
    commitPlaying(false)
    positionRef.current = 0
    setProgress(0)
    commitMode(preservedSyncEnabled ? "mix" : "idle", null)
    commitLastSoloId(null)
    commitSyncEnabled(preservedSyncEnabled)
    commitLoopEnabled(preservedLoopEnabled)
    commitMutedIds(new Set())
    commitSyncSoloId(null)
    scrubbingRef.current = false
    scrubEndingRef.current = false
    scrubSessionRef.current += 1
    resumeAfterScrubRef.current = false
    scrubTargetRef.current = null
    let cancelled = false
    void engine.preload().catch((loadError) => {
      if (!cancelled) setError(loadError instanceof Error ? loadError.message : "Audio decoding failed.")
    })
    return () => {
      cancelled = true
    }
  // The serialized source list deliberately excludes volume so slider changes do not reset playback.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [commitLastSoloId, commitLoopEnabled, commitMode, commitMutedIds, commitPlaying, commitSyncEnabled, commitSyncSoloId, layerSourcesJson])

  useEffect(() => {
    if (stackPlayback === syncEnabledRef.current) return
    playbackSessionRef.current += 1
    engineRef.current?.stop()
    positionRef.current = 0
    setProgress(0)
    commitPlaying(false)
    setError("")
    commitSyncEnabled(stackPlayback)
    commitMutedIds(new Set())
    commitSyncSoloId(null)
    commitLastSoloId(null)
    commitMode(stackPlayback ? "mix" : "idle", null)
  }, [commitLastSoloId, commitMode, commitMutedIds, commitPlaying, commitSyncEnabled, commitSyncSoloId, stackPlayback])

  useEffect(() => () => {
    void engineRef.current?.close()
  }, [])

  useEffect(() => {
    for (const layer of layers) {
      engineRef.current?.setLayerGain(layer.id, layer.volume / 100)
    }
    engineRef.current?.setMasterVolume(masterVolume / 100)
  }, [layers, masterVolume])

  const activePlaybackIds = useCallback(() => {
    if (modeRef.current === "mix") return playableIdsRef.current
    if (modeRef.current === "solo" && soloIdRef.current && playableIdsRef.current.includes(soloIdRef.current)) return [soloIdRef.current]
    return []
  }, [])

  const startPlayback = useCallback(async (ids: string[], nextProgress: number) => {
    const engine = engineRef.current
    if (!engine || ids.length === 0) return false
    const session = playbackSessionRef.current + 1
    playbackSessionRef.current = session
    commitPlaying(false)
    setError("")
    try {
      const started = await engine.start(ids, nextProgress, loopEnabledRef.current)
      if (!started || session !== playbackSessionRef.current) return false
      startedAtRef.current = started.startedAt
      startedOffsetSecondsRef.current = started.offsetSeconds
      timelineDurationRef.current = started.timelineDuration
      positionRef.current = started.offsetSeconds / started.timelineDuration
      setProgress(positionRef.current)
      commitPlaying(true)
      return true
    } catch (playError) {
      if (session !== playbackSessionRef.current) return false
      engine.stop()
      commitPlaying(false)
      setError(playError instanceof Error ? playError.message : "Audio playback failed.")
      return false
    }
  }, [commitPlaying])

  const pausePlayback = useCallback(() => {
    const nextProgress = getCurrentProgress()
    playbackSessionRef.current += 1
    engineRef.current?.stop()
    positionRef.current = nextProgress
    setProgress(nextProgress)
    commitPlaying(false)
  }, [commitPlaying, getCurrentProgress])

  useEffect(() => {
    let frame = 0
    const tick = () => {
      if (playingRef.current) {
        const engine = engineRef.current
        const duration = timelineDurationRef.current
        if (!engine || duration <= 0) {
          commitPlaying(false)
        } else {
          const elapsedPosition = startedOffsetSecondsRef.current + Math.max(0, engine.currentTime - startedAtRef.current)
          if (!loopEnabledRef.current && elapsedPosition >= duration) {
            playbackSessionRef.current += 1
            engine.stop()
            positionRef.current = 0
            setProgress(0)
            commitPlaying(false)
          } else {
            const nextProgress = getCurrentProgress()
            positionRef.current = nextProgress
            setProgress(nextProgress)
          }
        }
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [commitPlaying, getCurrentProgress])

  const toggleMix = useCallback(async () => {
    if (!syncEnabledRef.current) return
    if (modeRef.current === "mix" && playingRef.current) {
      pausePlayback()
      return
    }

    const startingMix = modeRef.current !== "mix"
    if (startingMix) {
      playbackSessionRef.current += 1
      engineRef.current?.stop()
      positionRef.current = 0
      setProgress(0)
      commitMode("mix", null)
      commitMutedIds(new Set())
      commitSyncSoloId(null)
    }

    const activeIds = playableIdsRef.current
    if (activeIds.length === 0) {
      setError("Generate or extract real audio before starting playback.")
      return
    }
    await startPlayback(activeIds, startingMix ? 0 : positionRef.current)
  }, [commitMode, commitMutedIds, commitSyncSoloId, pausePlayback, startPlayback])

  const toggleLayer = useCallback(async (id: string) => {
    if (!playableIdsRef.current.includes(id)) {
      setError("This layer has no playable audio file.")
      return
    }

    if (syncEnabledRef.current) {
      commitSyncSoloId(null)
      const nextMutedIds = new Set(mutedIdsRef.current)
      if (nextMutedIds.has(id)) {
        nextMutedIds.delete(id)
        commitMutedIds(nextMutedIds)
      } else {
        nextMutedIds.add(id)
        commitMutedIds(nextMutedIds)
      }
      return
    }

    commitLastSoloId(id)
    if (modeRef.current === "solo" && soloIdRef.current === id) {
      if (playingRef.current) pausePlayback()
      else await startPlayback([id], positionRef.current)
      return
    }

    playbackSessionRef.current += 1
    engineRef.current?.stop()
    positionRef.current = 0
    setProgress(0)
    commitMode("solo", id)
    commitMutedIds(new Set())
    await startPlayback([id], 0)
  }, [commitLastSoloId, commitMode, commitMutedIds, commitSyncSoloId, pausePlayback, startPlayback])

  const toggleSynchronizedSolo = useCallback(async (id: string) => {
    if (!playableIdsRef.current.includes(id)) {
      setError("This layer has no playable audio file.")
      return
    }

    setError("")
    const restoreFullMix = syncSoloIdRef.current === id
    const nextMutedIds = restoreFullMix
      ? new Set<string>()
      : new Set(playableIdsRef.current.filter((playableId) => playableId !== id))

    if (syncEnabledRef.current) {
      if (modeRef.current !== "mix") commitMode("mix", null)
      commitSyncSoloId(restoreFullMix ? null : id)
      commitMutedIds(nextMutedIds)
      return
    }

    const shouldResume = playingRef.current
    const nextProgress = getCurrentProgress()
    playbackSessionRef.current += 1
    engineRef.current?.stop()
    positionRef.current = nextProgress
    setProgress(nextProgress)
    commitPlaying(false)
    commitSyncEnabled(true)
    commitMode("mix", null)
    commitSyncSoloId(id)
    commitMutedIds(nextMutedIds)
    if (shouldResume) await startPlayback(playableIdsRef.current, nextProgress)
  }, [commitMode, commitMutedIds, commitPlaying, commitSyncEnabled, commitSyncSoloId, getCurrentProgress, startPlayback])

  const togglePrimary = useCallback(async () => {
    if (syncEnabledRef.current) {
      await toggleMix()
      return
    }
    const previousSoloId = lastSoloIdRef.current
    if (!previousSoloId || !playableIdsRef.current.includes(previousSoloId)) return
    await toggleLayer(previousSoloId)
  }, [toggleLayer, toggleMix])

  const stop = useCallback(() => {
    scrubSessionRef.current += 1
    scrubbingRef.current = false
    scrubEndingRef.current = false
    resumeAfterScrubRef.current = false
    scrubTargetRef.current = null
    pausePlayback()
  }, [pausePlayback])

  const rewind = useCallback(() => {
    scrubSessionRef.current += 1
    scrubbingRef.current = false
    scrubEndingRef.current = false
    resumeAfterScrubRef.current = false
    scrubTargetRef.current = null
    playbackSessionRef.current += 1
    engineRef.current?.stop()
    positionRef.current = 0
    setProgress(0)
    commitPlaying(false)
  }, [commitPlaying])

  const toggleLoopMode = useCallback(async () => {
    const nextEnabled = !loopEnabledRef.current
    if (!playingRef.current) {
      commitLoopEnabled(nextEnabled)
      return
    }
    const nextProgress = getCurrentProgress()
    const ids = activePlaybackIds()
    playbackSessionRef.current += 1
    engineRef.current?.stop()
    positionRef.current = nextProgress
    commitLoopEnabled(nextEnabled)
    await startPlayback(ids, nextProgress)
  }, [activePlaybackIds, commitLoopEnabled, getCurrentProgress, startPlayback])

  const reset = useCallback(() => {
    scrubSessionRef.current += 1
    scrubbingRef.current = false
    scrubEndingRef.current = false
    resumeAfterScrubRef.current = false
    scrubTargetRef.current = null
    playbackSessionRef.current += 1
    engineRef.current?.stop()
    positionRef.current = 0
    setProgress(0)
    commitPlaying(false)
    setError("")
    commitSyncEnabled(stackPlayback)
    commitLoopEnabled(false)
    commitMutedIds(new Set())
    commitSyncSoloId(null)
    commitLastSoloId(null)
    commitMode(stackPlayback ? "mix" : "idle", null)
  }, [commitLastSoloId, commitLoopEnabled, commitMode, commitMutedIds, commitPlaying, commitSyncEnabled, commitSyncSoloId, stackPlayback])

  const beginScrub = useCallback((id: string) => {
    scrubSessionRef.current += 1
    scrubbingRef.current = true
    scrubEndingRef.current = false
    const currentProgress = getCurrentProgress()
    resumeAfterScrubRef.current = playingRef.current
    scrubTargetRef.current = { id, progress: currentProgress }
    playbackSessionRef.current += 1
    engineRef.current?.stop()
    positionRef.current = currentProgress
    setProgress(currentProgress)
    commitPlaying(false)

    if (!syncEnabledRef.current && (modeRef.current !== "solo" || soloIdRef.current !== id)) {
      commitMode("solo", id)
      commitLastSoloId(id)
      commitMutedIds(new Set())
    }
  }, [commitLastSoloId, commitMode, commitMutedIds, commitPlaying, getCurrentProgress])

  const previewScrub = useCallback((id: string, nextProgress: number) => {
    const clampedProgress = Math.max(0, Math.min(nextProgress, 1))
    scrubTargetRef.current = { id, progress: clampedProgress }
    positionRef.current = clampedProgress
    setProgress(clampedProgress)
  }, [])

  const endScrub = useCallback(async () => {
    if (!scrubbingRef.current || scrubEndingRef.current) return
    scrubEndingRef.current = true
    const shouldResume = resumeAfterScrubRef.current
    const target = scrubTargetRef.current
    resumeAfterScrubRef.current = false
    scrubTargetRef.current = null
    scrubbingRef.current = false
    scrubEndingRef.current = false

    if (target) {
      positionRef.current = target.progress
      setProgress(target.progress)
    }

    if (!shouldResume) {
      return
    }

    const activeIds = syncEnabledRef.current
      ? playableIdsRef.current
      : target && playableIdsRef.current.includes(target.id) ? [target.id] : []
    if (activeIds.length === 0) {
      commitPlaying(false)
      return
    }

    await startPlayback(activeIds, target?.progress ?? positionRef.current)
  }, [commitPlaying, startPlayback])

  const mutedIdSet = useMemo(() => new Set(mutedIds), [mutedIds])
  return {
    playing,
    progress,
    mode,
    soloId,
    lastSoloId,
    syncEnabled,
    loopEnabled,
    mutedIds: mutedIdSet,
    syncSoloId,
    beginScrub,
    previewScrub,
    endScrub,
    togglePrimary,
    toggleLoopMode,
    toggleLayer,
    toggleSynchronizedSolo,
    stop,
    rewind,
    reset,
    masterVolume,
    setMasterVolume,
    error,
  }
}

type PlaybackClock = ReturnType<typeof usePlaybackClock>

interface AudioJobState {
  jobId: string
  busy: boolean
  percent: number
  current: number
  total: number
  phase: string
  message: string
  error: string
  artifacts: AudioArtifact[]
  result: AudioJobResult | null
}

const EMPTY_AUDIO_JOB: AudioJobState = {
  jobId: "",
  busy: false,
  percent: 0,
  current: 0,
  total: 0,
  phase: "idle",
  message: "Ready",
  error: "",
  artifacts: [],
  result: null,
}

function useAudioJob(kind: AudioJobKind) {
  const [state, setState] = useState<AudioJobState>(EMPTY_AUDIO_JOB)
  const jobIdRef = useRef("")
  const waitingRef = useRef(false)

  useEffect(() => {
    const api = window.stemSlicer
    if (!api) return
    return api.onAudioJobEvent((event) => {
      if (event.kind !== kind) return
      if (jobIdRef.current && event.jobId !== jobIdRef.current) return
      if (!jobIdRef.current && !waitingRef.current) return
      jobIdRef.current = event.jobId
      if (event.type === "progress") {
        setState((current) => ({
          ...current,
          jobId: event.jobId,
          busy: true,
          percent: event.percent ?? current.percent,
          current: event.current ?? current.current,
          total: event.total ?? current.total,
          phase: event.phase ?? current.phase,
          message: event.message,
        }))
        return
      }
      if (event.type === "artifact" && event.artifact) {
        setState((current) => {
          const retained = current.artifacts.filter((item) => item.path !== event.artifact?.path)
          return { ...current, artifacts: [...retained, event.artifact as AudioArtifact], message: event.message }
        })
        return
      }
      waitingRef.current = false
      jobIdRef.current = ""
      if (event.type === "completed") {
        setState((current) => ({ ...current, busy: false, percent: 100, phase: "complete", message: event.message, result: event.result ?? null }))
      } else {
        setState((current) => ({ ...current, busy: false, phase: event.type, message: event.message, error: event.error ?? event.message }))
      }
    })
  }, [kind])

  const start = useCallback(async (request: AudioJobRequest) => {
    const api = window.stemSlicer
    if (!api) throw new Error("Electron desktop API is unavailable.")
    waitingRef.current = true
    jobIdRef.current = ""
    setState({ ...EMPTY_AUDIO_JOB, busy: true, phase: "starting", message: "Starting local engine…" })
    try {
      const started = await api.startAudioJob(kind, request)
      jobIdRef.current = started.jobId
      setState((current) => ({ ...current, jobId: started.jobId }))
      return started.jobId
    } catch (error) {
      waitingRef.current = false
      const message = error instanceof Error ? error.message : "The local engine could not start."
      setState({ ...EMPTY_AUDIO_JOB, error: message, message, phase: "failed" })
      throw error
    }
  }, [kind])

  const cancel = useCallback(() => {
    if (!jobIdRef.current) return
    void window.stemSlicer?.cancelAudioJob(jobIdRef.current)
  }, [])

  return { ...state, start, cancel }
}

function AudioArtifactCard({ artifact, compact = false }: { artifact: AudioArtifact; compact?: boolean }) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState(false)
  const [progress, setProgress] = useState(0)
  const [playbackError, setPlaybackError] = useState("")
  const mediaUrl = window.stemSlicer?.mediaUrl(artifact.path) ?? ""

  const togglePlayback = async () => {
    const audio = audioRef.current
    if (!audio) return
    if (!audio.paused) {
      audio.pause()
      return
    }
    setPlaybackError("")
    try {
      await audio.play()
    } catch (error) {
      setPlaybackError(error instanceof Error ? error.message : "Audio playback failed.")
    }
  }

  const beginDrag = (event: React.DragEvent, path: string) => {
    event.preventDefault()
    window.stemSlicer?.startFileDrag(path)
  }

  return (
    <article className={cn("audio-artifact-card", compact && "is-compact")}>
      <audio
        ref={audioRef}
        src={mediaUrl}
        preload="auto"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onError={() => setPlaybackError(`Audio file could not be loaded: ${artifact.name}`)}
        onEnded={() => { setPlaying(false); setProgress(0) }}
        onTimeUpdate={(event) => {
          const audio = event.currentTarget
          setProgress(audio.duration > 0 ? audio.currentTime / audio.duration : 0)
        }}
      />
      <div className="audio-artifact-main">
        <header title={playbackError || undefined}>
          <div>
            <strong title={artifact.name}>{artifact.displayName}</strong>
            {playbackError ? <small>{playbackError}</small> : <div className="artifact-metadata">
              <span><MetronomeIcon /> {artifact.bpm} BPM</span>
              <span><Music2 aria-hidden="true" /> {artifact.key}</span>
            </div>}
          </div>
          <span className="artifact-duration">{artifact.duration.toFixed(1)}s</span>
        </header>
        <div className="artifact-wave-row">
          <button type="button" onClick={togglePlayback} aria-label={playing ? `Pause ${artifact.displayName}` : `Play ${artifact.displayName}`}>{playing ? <Pause aria-hidden="true" /> : <Play className="play-glyph" aria-hidden="true" />}</button>
          <Waveform progress={progress} compact label={`Waveform for ${artifact.displayName}`} bars={artifact.peaks.map((value) => Math.max(8, value * 100))} />
        </div>
      </div>
      <div className="artifact-side-actions">
        <button type="button" draggable onDragStart={(event) => beginDrag(event, artifact.path)}><AudioLines aria-hidden="true" />Audio</button>
        <button type="button" onClick={() => void window.stemSlicer?.revealPath(artifact.path)}><FolderOpen aria-hidden="true" />Reveal</button>
      </div>
    </article>
  )
}

function Select({
  id,
  label,
  value,
  onChange,
  options,
  disabled = false,
  forceBelow = false,
  className,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  options: string[]
  disabled?: boolean
  forceBelow?: boolean
  className?: string
}) {
  const labelId = `${id}-label`
  return (
    <div className={cn("control-field", className)}>
      <span id={labelId}>{label}</span>
      <BaseSelect.Root
        id={id}
        items={options.map((option) => ({ label: option, value: option }))}
        value={value}
        disabled={disabled}
        onValueChange={(nextValue) => {
          if (nextValue) onChange(nextValue)
        }}
      >
        <BaseSelect.Trigger className="custom-select-trigger" aria-labelledby={labelId}>
          <BaseSelect.Value />
          <BaseSelect.Icon><ChevronDown aria-hidden="true" /></BaseSelect.Icon>
        </BaseSelect.Trigger>
        <BaseSelect.Portal>
          <BaseSelect.Positioner
            className="custom-select-positioner"
            side="bottom"
            align="start"
            sideOffset={5}
            alignItemWithTrigger={false}
            collisionAvoidance={forceBelow ? { side: "none", align: "shift", fallbackAxisSide: "none" } : undefined}
          >
            <BaseSelect.Popup className="custom-select-popup">
              <BaseSelect.List className="custom-select-list">
                {options.map((option) => (
                  <BaseSelect.Item className="custom-select-item" key={option} value={option}>
                    <BaseSelect.ItemText>{option}</BaseSelect.ItemText>
                    <BaseSelect.ItemIndicator><Check aria-hidden="true" /></BaseSelect.ItemIndicator>
                  </BaseSelect.Item>
                ))}
              </BaseSelect.List>
            </BaseSelect.Popup>
          </BaseSelect.Positioner>
        </BaseSelect.Portal>
      </BaseSelect.Root>
    </div>
  )
}

function LayerCategorySelect({
  id,
  value,
  options,
  disabled,
  onChange,
}: {
  id: string
  value: string
  options: string[]
  disabled: boolean
  onChange: (value: string) => void
}) {
  const items = Array.from(new Set([value, ...options]))
  return (
    <BaseSelect.Root
      id={id}
      items={items.map((option) => ({ label: option, value: option }))}
      value={value}
      disabled={disabled}
      onValueChange={(nextValue) => nextValue && onChange(nextValue)}
    >
      <BaseSelect.Trigger className="custom-select-trigger layer-category-trigger" aria-label={`Category: ${value}`}>
        <BaseSelect.Value />
        <BaseSelect.Icon><ChevronDown aria-hidden="true" /></BaseSelect.Icon>
      </BaseSelect.Trigger>
      <BaseSelect.Portal>
        <BaseSelect.Positioner
          className="custom-select-positioner"
          side="bottom"
          align="start"
          sideOffset={5}
          alignItemWithTrigger={false}
          collisionAvoidance={{ side: "none", align: "shift", fallbackAxisSide: "none" }}
        >
          <BaseSelect.Popup className="custom-select-popup layer-category-popup">
            <BaseSelect.List className="custom-select-list">
              {items.map((option) => (
                <BaseSelect.Item className="custom-select-item" key={option} value={option}>
                  <BaseSelect.ItemText>{option}</BaseSelect.ItemText>
                </BaseSelect.Item>
              ))}
            </BaseSelect.List>
          </BaseSelect.Popup>
        </BaseSelect.Positioner>
      </BaseSelect.Portal>
    </BaseSelect.Root>
  )
}

const LAYER_OCTAVE_OPTIONS = [
  { value: "1", label: "OCT +1" },
  { value: "0", label: "OCT 0" },
  { value: "-1", label: "OCT −1" },
]

function LayerOctaveSelect({
  id,
  value,
  disabled,
  onChange,
}: {
  id: string
  value: number
  disabled: boolean
  onChange: (value: number) => void
}) {
  return (
    <BaseSelect.Root
      id={id}
      items={LAYER_OCTAVE_OPTIONS}
      value={String(value)}
      disabled={disabled}
      onValueChange={(nextValue) => nextValue && onChange(Number(nextValue))}
    >
      <BaseSelect.Trigger className="custom-select-trigger layer-octave-trigger" aria-label={`Octave ${value}`}>
        <BaseSelect.Value />
        <BaseSelect.Icon><ChevronDown aria-hidden="true" /></BaseSelect.Icon>
      </BaseSelect.Trigger>
      <BaseSelect.Portal>
        <BaseSelect.Positioner
          className="custom-select-positioner"
          side="bottom"
          align="start"
          sideOffset={4}
          alignItemWithTrigger={false}
          collisionAvoidance={{ side: "none", align: "shift", fallbackAxisSide: "none" }}
        >
          <BaseSelect.Popup className="custom-select-popup layer-octave-popup">
            <BaseSelect.List className="custom-select-list">
              {LAYER_OCTAVE_OPTIONS.map((option) => (
                <BaseSelect.Item className="custom-select-item" key={option.value} value={option.value}>
                  <BaseSelect.ItemText>{option.label}</BaseSelect.ItemText>
                </BaseSelect.Item>
              ))}
            </BaseSelect.List>
          </BaseSelect.Popup>
        </BaseSelect.Positioner>
      </BaseSelect.Portal>
    </BaseSelect.Root>
  )
}

function AppSidebar({
  activeView,
  collapsed,
  onNavigate,
  onToggle,
}: {
  activeView: ViewId
  collapsed: boolean
  onNavigate: (view: ViewId) => void
  onToggle: () => void
}) {
  return (
    <aside className={cn("app-sidebar", collapsed && "is-collapsed")} aria-label="Navigation principale">
      <div className="spectral-stripe" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
      </div>
      <div className="sidebar-titlebar app-drag-region" />
      <div className="sidebar-brand">
        <button
          type="button"
          className="brand-mark app-no-drag"
          onClick={() => collapsed ? onToggle() : onNavigate("generate")}
          aria-label={collapsed ? "Déplier la barre latérale" : "Ouvrir Generate"}
          title={collapsed ? "Déplier la barre latérale" : "Stem Slicer"}
        >
          <AudioLines aria-hidden="true" />
        </button>
        <div className="sidebar-copy">
          <strong>Stem Slicer</strong>
          <span>Electron prototype</span>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="sidebar-collapse app-no-drag"
          onClick={onToggle}
          aria-label={collapsed ? "Déplier la barre latérale" : "Replier la barre latérale"}
          title={collapsed ? "Déplier" : "Replier"}
        >
          <ChevronLeft />
        </Button>
      </div>

      <nav className="sidebar-nav" aria-label="Espaces de travail">
        <p className="sidebar-group-label">Workspace</p>
        {NAVIGATION.map((item) => {
          const Icon = item.icon
          const isActive = activeView === item.id
          return (
            <button
              key={item.id}
              type="button"
              className={cn("nav-item", isActive && "is-active")}
              onClick={() => onNavigate(item.id)}
              aria-current={isActive ? "page" : undefined}
              aria-label={collapsed ? item.label : undefined}
              title={collapsed ? item.label : undefined}
            >
              <Icon aria-hidden="true" />
              <span className="nav-label">{item.label}</span>
              {item.badge ? <Badge variant="warning" className="nav-beta">{item.badge}</Badge> : null}
            </button>
          )
        })}
      </nav>

      <div className="sidebar-footer">
        <div className="connection-dot" aria-hidden="true" />
        <div className="sidebar-copy">
          <strong>Local engine</strong>
          <span>1.9B cache · read-only</span>
        </div>
        <Button variant="ghost" size="icon" aria-label="Ouvrir les réglages" title="Réglages">
          <Settings2 />
        </Button>
      </div>
    </aside>
  )
}

function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string
  title: string
  description: string
  actions?: React.ReactNode
}) {
  return (
    <header className="page-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="page-description">{description}</p>
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  )
}

function LayerCard({
  layer,
  progress,
  playing,
  isAudible,
  mixActive,
  isMuted,
  isSyncSolo,
  onPlay,
  onSynchronizedSolo,
  onSeek,
  onScrubStart,
  onScrubEnd,
  onChange,
  onToggleAlternateKey,
  onToggleLock,
  onRemove,
  categoryOptions,
  canRemove,
  updating = false,
  variant = "generate",
}: {
  layer: GeneratedLayer
  progress: number
  playing: boolean
  isAudible: boolean
  mixActive: boolean
  isMuted: boolean
  isSyncSolo: boolean
  onPlay: () => void
  onSynchronizedSolo: () => void
  onSeek: (progress: number) => void
  onScrubStart: () => void
  onScrubEnd: () => void | Promise<void>
  onChange: (layer: GeneratedLayer) => void
  onToggleAlternateKey?: () => void
  onToggleLock?: () => void
  onRemove?: () => void
  categoryOptions?: string[]
  canRemove?: boolean
  updating?: boolean
  variant?: "generate" | "extract"
}) {
  const waveformScrubberRef = useRef<HTMLInputElement>(null)
  const isGenerateCard = variant === "generate"
  const visibleProgress = mixActive || isAudible ? progress : 0
  const seekWaveformFromPointer = (event: React.PointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    if (bounds.width <= 0) return
    onSeek((event.clientX - bounds.left) / bounds.width)
  }
  const beginDrag = (event: React.DragEvent, path: string | undefined) => {
    if (!path) return
    event.preventDefault()
    window.stemSlicer?.startFileDrag(path)
  }

  return (
    <Card className={cn("layer-card", isGenerateCard ? "layer-tone-spectral" : "layer-tone-extract", !isGenerateCard && "is-extract", isAudible && "is-audible", isMuted && "is-muted", isSyncSolo && "is-sync-solo")} aria-label={`${layer.category}, ${layer.file}`}>
      <CardHeader>
        <div className="layer-heading">
          {isGenerateCard ? (
            <LayerCategorySelect
              id={`layer-category-${layer.id}`}
              value={layer.category}
              disabled={updating}
              options={categoryOptions ?? []}
              onChange={(category) => onChange({ ...layer, category, locked: false })}
            />
          ) : <CardTitle className="layer-category-static">{layer.category}</CardTitle>}
          <CardDescription className="truncate" title={layer.file}>
            {layer.file}
          </CardDescription>
        </div>
        {isGenerateCard ? <div className="layer-card-actions">
          <button type="button" className={cn("layer-mini-action layer-lock-action", layer.locked && "is-active")} disabled={!layer.identity || updating} aria-pressed={Boolean(layer.locked)} aria-label={`${layer.locked ? "Libérer" : "Garder"} ${layer.role} pour la prochaine génération`} onClick={onToggleLock}>{layer.locked ? <Lock aria-hidden="true" /> : <Unlock aria-hidden="true" />}<span>Lock</span></button>
          <button type="button" className="layer-mini-action layer-remove-action" disabled={!canRemove || updating} aria-label={`Supprimer la card ${layer.role}`} onClick={onRemove}><X aria-hidden="true" /></button>
        </div> : null}
      </CardHeader>
      <CardContent>
        <div className="layer-transport">
          <button
            type="button"
            className={cn("card-play-button", isSyncSolo && "is-sync-solo")}
            onClick={onPlay}
            onContextMenu={(event) => {
              event.preventDefault()
              onSynchronizedSolo()
            }}
            aria-pressed={mixActive ? !isMuted : playing && isAudible}
            aria-label={mixActive
              ? isSyncSolo ? `${layer.role} est isolé dans le mix synchronisé. Clic droit pour rétablir le mix complet`
                : isMuted ? `Réactiver ${layer.role} dans le mix. Clic droit pour l’isoler dans le mix synchronisé`
                  : `Mettre ${layer.role} en pause dans le mix. Clic droit pour l’isoler dans le mix synchronisé`
              : playing && isAudible ? `Mettre ${layer.role} en pause. Clic droit pour l’isoler dans le mix synchronisé`
                : `Lire ${layer.role} en solo. Clic droit pour l’isoler dans le mix synchronisé`}
            title={isSyncSolo ? "Clic droit : rétablir le mix synchronisé" : "Clic droit : isoler cette card dans le mix synchronisé"}
          >
            {mixActive ? !isMuted ? <Pause /> : <Play className="play-glyph" /> : playing && isAudible ? <Pause /> : <Play className="play-glyph" />}
          </button>
          <div
            className="waveform-reader"
            onPointerDown={(event) => {
              if (event.button !== 0) return
              event.preventDefault()
              waveformScrubberRef.current?.focus({ preventScroll: true })
              onScrubStart()
              event.currentTarget.setPointerCapture(event.pointerId)
              seekWaveformFromPointer(event)
            }}
            onPointerMove={(event) => {
              if (event.currentTarget.hasPointerCapture(event.pointerId)) seekWaveformFromPointer(event)
            }}
            onPointerUp={(event) => {
              if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
              event.currentTarget.releasePointerCapture(event.pointerId)
              void onScrubEnd()
            }}
            onPointerCancel={(event) => {
              if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
              void onScrubEnd()
            }}
          >
            <Waveform
              progress={visibleProgress}
              label={`Forme d’onde de ${layer.role}`}
              bars={layer.bars}
            />
            <input
              ref={waveformScrubberRef}
              className="waveform-scrubber"
              type="range"
              min="0"
              max="1000"
              value={Math.round(visibleProgress * 1000)}
              aria-label={`Position de lecture de ${layer.role}`}
              tabIndex={-1}
              onChange={(event) => onSeek(Number(event.target.value) / 1000)}
            />
            <span className="wave-time tabular" aria-hidden="true">
              {(visibleProgress * layer.duration).toFixed(1)} / {layer.duration.toFixed(1)} s
            </span>
          </div>
        </div>

        <div className="layer-metadata">
          <span><MetronomeIcon /> {layer.bpm} BPM</span>
          <span><Music2 aria-hidden="true" /> {layer.keyName}</span>
          {layer.alternateKey && layer.identity && onToggleAlternateKey ? (
            <button type="button" className="layer-alt-key" disabled={updating} title="Basculer entre la clé Top-1 et Top-2" onClick={onToggleAlternateKey}>
              <Radio aria-hidden="true" /> {layer.sourceKeyRank === 2 ? "Top-1" : layer.alternateKey}
            </button>
          ) : (
            <span className="muted" title="Aucune seconde clé mesurée"><CircleAlert aria-hidden="true" /> Top-2 unavailable</span>
          )}
        </div>

        <div className="layer-controls">
          <label className="layer-volume-control">
            <Volume2 aria-hidden="true" />
            <input
              type="range"
              min="0"
              max="100"
              value={layer.volume}
              aria-label={`Volume de ${layer.role}`}
              onChange={(event) => onChange({ ...layer, volume: Number(event.target.value) })}
            />
            <output className="tabular">{layer.volume}%</output>
          </label>
          {isGenerateCard ? <LayerOctaveSelect
            id={`layer-octave-${layer.id}`}
            value={layer.octave}
            disabled={updating || !layer.identity}
            onChange={(octave) => onChange({ ...layer, octave })}
          /> : null}
          <Button
            variant="outline"
            size="sm"
            disabled={!layer.midiPath}
            draggable={Boolean(layer.midiPath)}
            aria-label={`Exporter le MIDI de ${layer.role}`}
            title={layer.midiPath ? "Drag MIDI or click to reveal it" : "MIDI unavailable"}
            onClick={() => layer.midiPath && void window.stemSlicer?.revealPath(layer.midiPath)}
            onDragStart={(event) => beginDrag(event, layer.midiPath)}
          >
            <MidiFileIcon /> MIDI
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!layer.path}
            draggable={Boolean(layer.path)}
            aria-label={`Exporter ${layer.role}`}
            title={layer.path ? "Drag audio or click to reveal it" : "Render this layer before exporting it"}
            onClick={() => layer.path && void window.stemSlicer?.revealPath(layer.path)}
            onDragStart={(event) => beginDrag(event, layer.path)}
          >
            <AudioLines /> Audio
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function aggregateCategories(roots: LibraryOverview["roots"]) {
  const counts = new Map<string, number>()
  for (const root of roots) {
    for (const category of root.categories ?? []) {
      counts.set(category.name, (counts.get(category.name) ?? 0) + category.count)
    }
  }
  return Array.from(counts, ([name, count]) => ({ name, count }))
    .sort((left, right) => right.count - left.count)
}

function LibraryManager({
  library,
  selectedPaths,
  selectedLayerCount,
  selectedCategoryCount,
  selectionMessage,
  onSelectedPathsChange,
  onAddFolder,
  onRemoveFolder,
}: {
  library: LibraryOverview
  selectedPaths: string[]
  selectedLayerCount: number
  selectedCategoryCount: number
  selectionMessage: string
  onSelectedPathsChange: React.Dispatch<React.SetStateAction<string[]>>
  onAddFolder: () => Promise<void>
  onRemoveFolder: (libraryRoot: string) => Promise<void>
}) {
  const selectedSet = new Set(selectedPaths)
  const [removingPath, setRemovingPath] = useState<string | null>(null)
  const toggleLibrary = (path: string, checked: boolean) => {
    onSelectedPathsChange((current) => checked
      ? Array.from(new Set([...current, path]))
      : current.filter((item) => item !== path))
  }
  const removeFolder = async (libraryRoot: string) => {
    if (removingPath) return
    setRemovingPath(libraryRoot)
    try {
      await onRemoveFolder(libraryRoot)
    } finally {
      setRemovingPath(null)
    }
  }

  return (
    <Dialog.Root>
      <Dialog.Trigger className="manage-library-trigger">
        <SlidersHorizontal aria-hidden="true" /> Manage library
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Backdrop className="dialog-backdrop" />
        <Dialog.Viewport className="dialog-viewport">
          <Dialog.Popup className="library-manager-dialog">
            <header className="library-manager-header">
              <div>
                <Dialog.Title>Manage library</Dialog.Title>
                <Dialog.Description>Choose which indexed folders Generate can use.</Dialog.Description>
              </div>
              <Dialog.Close className="dialog-close" aria-label="Close library manager"><X /></Dialog.Close>
            </header>

            <div className="library-manager-metrics" aria-live="polite">
              <div><strong className="tabular">{selectedPaths.length}/{library.roots.length}</strong><span>Libraries active</span></div>
              <div><strong className="tabular">{formatCount(selectedLayerCount)}</strong><span>Layers selected</span></div>
              <div><strong className="tabular">{selectedCategoryCount}</strong><span>Categories available</span></div>
            </div>

            <div className="library-manager-list-heading">
              <strong>Indexed folders</strong>
              <div>
                <button type="button" onClick={() => onSelectedPathsChange(library.roots.map((root) => root.path))}>Select all</button>
                <button type="button" onClick={() => onSelectedPathsChange([])}>Select none</button>
              </div>
            </div>

            <div className="library-manager-list" role="group" aria-label="Libraries available to Generate">
              {library.roots.length > 0 ? library.roots.map((root) => {
                const checked = selectedSet.has(root.path)
                return (
                  <div className={cn("library-manager-row", checked && "is-selected")} key={root.path}>
                    <label>
                      <input type="checkbox" checked={checked} onChange={(event) => toggleLibrary(root.path, event.target.checked)} />
                      <span>
                        <strong>{root.name}</strong>
                        <small title={root.path}>{root.path}</small>
                      </span>
                      <output className="tabular">{formatCount(root.layerCount)}</output>
                    </label>
                    <button type="button" className="library-reveal" aria-label={`Afficher ${root.name} dans le Finder`} title="Afficher dans le Finder" onClick={() => window.stemSlicer?.revealPath(root.path)}>
                      <FolderOpen aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="library-remove"
                      aria-label={`Retirer ${root.name} du catalogue`}
                      title="Retirer uniquement l’index — le dossier audio reste intact"
                      disabled={removingPath === root.path}
                      onClick={() => void removeFolder(root.path)}
                    >
                      <Trash2 aria-hidden="true" />
                    </button>
                  </div>
                )
              }) : <p className="library-manager-empty">No indexed library is available yet.</p>}
            </div>

            {selectionMessage ? <p className="library-manager-notice" role="status"><FolderOpen aria-hidden="true" /> {selectionMessage}</p> : null}

            <footer className="library-manager-footer">
              <Button variant="outline" onClick={onAddFolder}><Plus /> Add folder</Button>
              <Dialog.Close className="dialog-done">Done</Dialog.Close>
            </footer>
          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function GenerateView({
  library,
  layers,
  setLayers,
  currentGenerationResult,
  setCurrentGenerationResult,
  onAddHistory,
  onUpdateHistory,
  onLibraryRefresh,
  playback,
}: {
  library: LibraryOverview
  layers: GeneratedLayer[]
  setLayers: React.Dispatch<React.SetStateAction<GeneratedLayer[]>>
  currentGenerationResult: GenerateResult | null
  setCurrentGenerationResult: React.Dispatch<React.SetStateAction<GenerateResult | null>>
  onAddHistory: (entry: HistoryEntry) => void
  onUpdateHistory: (generation: GenerateResult, layers: GeneratedLayer[]) => void
  onLibraryRefresh: () => Promise<void>
  playback: PlaybackClock
}) {
  const [bpm, setBpm] = useState(140)
  const [keyName, setKeyName] = useState("F minor")
  const [status, setStatus] = useState("Local Generate engine ready")
  const [selectionMessage, setSelectionMessage] = useState("")
  const [currentSeed, setCurrentSeed] = useState<number | null>(null)
  const [previousSeed, setPreviousSeed] = useState<number | null>(null)
  const [recipeDirty, setRecipeDirty] = useState(false)
  const [selectedLibraryPaths, setSelectedLibraryPaths] = useState<string[]>([])
  const knownLibraryPathsRef = useRef<Set<string>>(new Set())
  const handledGenerationRef = useRef("")
  const handledUpdateRef = useRef("")
  const handledScanRef = useRef("")
  const currentGenerationDirectoryRef = useRef("")
  const generateJob = useAudioJob("generate")
  const generateUpdateJob = useAudioJob("generate-update")
  const libraryScanJob = useAudioJob("library-scan")
  const generationResult = generateJob.result as GenerateResult | null
  const generationUpdateResult = generateUpdateJob.result as GenerateResult | null
  const mixActive = playback.mode === "mix"
  const selectedLibrarySet = new Set(selectedLibraryPaths)
  const selectedRoots = library.roots.filter((root) => selectedLibrarySet.has(root.path))
  const selectedLayerCount = selectedRoots.reduce((sum, root) => sum + root.layerCount, 0)
  const selectedRootCategories = aggregateCategories(selectedRoots)
  const allLibrariesSelected = library.roots.length > 0 && selectedRoots.length === library.roots.length
  const selectedCategories = selectedRootCategories.length > 0
    ? selectedRootCategories
    : allLibrariesSelected ? library.categories : []
  const largestCategoryCount = selectedCategories[0]?.count || 1

  useEffect(() => {
    if (!currentGenerationResult) return
    if (currentGenerationDirectoryRef.current !== currentGenerationResult.outputDirectory) {
      currentGenerationDirectoryRef.current = currentGenerationResult.outputDirectory
      setRecipeDirty(false)
    }
    setBpm(Math.round(currentGenerationResult.targetBpm))
    setKeyName(currentGenerationResult.targetKey)
    setCurrentSeed(currentGenerationResult.seed)
  }, [currentGenerationResult])

  useEffect(() => {
    const availablePaths = library.roots.map((root) => root.path)
    const availableSet = new Set(availablePaths)
    const knownPaths = knownLibraryPathsRef.current
    setSelectedLibraryPaths((current) => {
      if (knownPaths.size === 0) return availablePaths
      const retained = current.filter((path) => availableSet.has(path))
      const newlyIndexed = availablePaths.filter((path) => !knownPaths.has(path))
      return [...retained, ...newlyIndexed]
    })
    knownLibraryPathsRef.current = availableSet
  }, [library.roots])

  useEffect(() => {
    if (!generationResult) return
    const resultIdentity = `${generationResult.outputDirectory}:${generationResult.seed}`
    if (handledGenerationRef.current === resultIdentity) return
    handledGenerationRef.current = resultIdentity
    setCurrentGenerationResult(generationResult)
    setRecipeDirty(false)
    const nextLayers = generationResult.layers.map((artifact, index): GeneratedLayer => ({
      id: `${generationResult.seed}-${index}-${artifact.category ?? "layer"}`,
      role: artifact.category ?? `Layer ${index + 1}`,
      file: artifact.name,
      category: artifact.category ?? "Layer",
      bpm: artifact.bpm,
      keyName: artifact.key,
      volume: 78,
      duration: artifact.duration,
      alternateKey: artifact.alternateKey,
      path: artifact.path,
      midiPath: artifact.midiPath,
      sourcePath: artifact.sourcePath,
      identity: artifact.identity,
      sourceKeyRank: artifact.sourceKeyRank ?? 1,
      octave: artifact.octave ?? 0,
      locked: artifact.locked ?? false,
      bars: artifact.peaks.map((peak) => Math.max(8, Math.round(peak * 100))),
    }))
    setLayers(nextLayers)
    const elapsedLabel = generationResult.elapsedSeconds ? ` in ${generationResult.elapsedSeconds.toFixed(1)}s` : ""
    setStatus(`${generationResult.layers.length} real layers generated${elapsedLabel}`)
    onAddHistory({
      id: crypto.randomUUID(),
      bpm: generationResult.targetBpm,
      keyName: generationResult.targetKey,
      recipe: "Generated",
      createdAt: new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" }).format(new Date()),
      layerCount: generationResult.layers.length,
      generation: generationResult,
      layers: nextLayers,
    })
  }, [generationResult, onAddHistory, playback, setCurrentGenerationResult, setLayers])

  useEffect(() => {
    if (!generationUpdateResult) return
    const resultIdentity = `${generationUpdateResult.outputDirectory}:${generationUpdateResult.layers.map((item) => `${item.identity}:${item.octave}:${item.sourceKeyRank}`).join("|")}`
    if (handledUpdateRef.current === resultIdentity) return
    handledUpdateRef.current = resultIdentity
    setCurrentGenerationResult(generationUpdateResult)
    const nextLayers = generationUpdateResult.layers.map((artifact, index): GeneratedLayer => {
      const previous = layers.find((layer) => layer.identity === artifact.identity) ?? layers[index]
      return {
        ...previous,
        id: previous?.id ?? `${generationUpdateResult.seed}-${index}-${artifact.category ?? "layer"}`,
        role: previous?.role ?? artifact.category ?? `Layer ${index + 1}`,
        file: artifact.name,
        category: artifact.category ?? previous?.category ?? "Layer",
        bpm: artifact.bpm,
        keyName: artifact.key,
        octave: artifact.octave ?? 0,
        duration: artifact.duration,
        alternateKey: artifact.alternateKey,
        path: artifact.path,
        midiPath: artifact.midiPath,
        sourcePath: artifact.sourcePath,
        identity: artifact.identity,
        sourceKeyRank: artifact.sourceKeyRank ?? 1,
        locked: previous?.locked ?? artifact.locked ?? false,
        bars: artifact.peaks.map((peak) => Math.max(8, Math.round(peak * 100))),
      }
    })
    setLayers(nextLayers)
    onUpdateHistory(generationUpdateResult, nextLayers)
    setStatus("Generated layer and master updated")
  }, [generationUpdateResult, layers, onUpdateHistory, playback, setCurrentGenerationResult, setLayers])

  useEffect(() => {
    if (generateUpdateJob.error) setStatus(generateUpdateJob.error)
  }, [generateUpdateJob.error])

  useEffect(() => {
    const scanResult = libraryScanJob.result
    if (!scanResult || !("root" in scanResult)) return
    const identity = `${scanResult.root}:${scanResult.totalFiles}:${scanResult.updated}`
    if (handledScanRef.current === identity) return
    handledScanRef.current = identity
    setSelectionMessage(`${basename(scanResult.root)} indexed · ${formatCount(scanResult.totalFiles)} files`)
    void onLibraryRefresh()
  }, [libraryScanJob.result, onLibraryRefresh])

  const pickFolder = async () => {
    const result = await window.stemSlicer?.pickLibraryFolder()
    if (!result || result.canceled || result.paths.length === 0) return
    const root = result.paths[0]
    setSelectionMessage(`${basename(root)} · preparing scan…`)
    void libraryScanJob.start({ root, databasePath: library.databasePath }).catch(() => undefined)
  }

  const removeFolder = async (libraryRoot: string) => {
    try {
      const overview = await window.stemSlicer?.removeLibraryRoot(libraryRoot)
      setSelectedLibraryPaths((current) => current.filter((item) => item !== libraryRoot))
      setSelectionMessage(`${basename(libraryRoot)} removed from the catalogue · audio files preserved`)
      if (overview) await onLibraryRefresh()
    } catch (error) {
      setSelectionMessage(error instanceof Error ? error.message : "The indexed folder could not be removed.")
    }
  }

  const handleGenerate = (seedOverride?: number) => {
    if (generateJob.busy) {
      generateJob.cancel()
      return
    }
    if (selectedLibraryPaths.length === 0) {
      setStatus("Select at least one indexed library before Generate.")
      return
    }
    const categories = layers
      .map((layer) => layer.category)
      .filter((category) => category && category !== "Unassigned" && category !== "Layer")
    const requestedCategories = categories.length > 0
      ? categories
      : selectedCategories.slice(0, 5).map((category) => category.name)
    if (requestedCategories.length === 0) {
      setStatus("No category is available for the current selection.")
      return
    }
    const seed = seedOverride ?? crypto.getRandomValues(new Uint32Array(1))[0]
    if (currentSeed !== seed) {
      setPreviousSeed(currentSeed)
      setCurrentSeed(seed)
    }
    setStatus("Selecting and rendering real layers…")
    void generateJob.start({
      databasePath: library.databasePath,
      libraryRoots: selectedLibraryPaths,
      categories: requestedCategories,
      targetBpm: bpm,
      targetKey: keyName,
      seed,
      bars: 8,
      lockedIdentitiesBySlot: layers.map((layer) => layer.locked && layer.identity ? layer.identity : null),
      excludedIdentities: seedOverride == null
        ? layers.filter((layer) => !layer.locked && layer.identity).map((layer) => layer.identity as string)
        : [],
    }).catch(() => undefined)
  }

  const updateGeneratedLayer = (slotIndex: number, next: GeneratedLayer) => {
    const previous = layers[slotIndex]
    if (!previous) return
    if (next.octave === previous.octave) {
      if (next.category !== previous.category) setRecipeDirty(true)
      setLayers((current) => current.map((item) => item.id === next.id ? next : item))
      return
    }
    if (!currentGenerationResult?.outputDirectory || !previous.identity || generateUpdateJob.busy) return
    setStatus(`Updating ${previous.role} octave…`)
    void generateUpdateJob.start({
      outputDirectory: currentGenerationResult.outputDirectory,
      identity: previous.identity,
      slotIndex,
      update: "octave",
      octave: next.octave as -1 | 0 | 1,
    }).catch(() => undefined)
  }

  const toggleAlternateKey = (slotIndex: number) => {
    const layer = layers[slotIndex]
    if (!currentGenerationResult?.outputDirectory || !layer?.identity || !layer.alternateKey || generateUpdateJob.busy) return
    const nextRank = layer.sourceKeyRank === 2 ? 1 : 2
    setStatus(`Updating ${layer.role} source key…`)
    void generateUpdateJob.start({
      outputDirectory: currentGenerationResult.outputDirectory,
      identity: layer.identity,
      slotIndex,
      update: "source-key",
      sourceKeyRank: nextRank,
    }).catch(() => undefined)
  }

  const toggleLayerLock = (slotIndex: number) => {
    setLayers((current) => current.map((layer, index) => index === slotIndex ? { ...layer, locked: !layer.locked } : layer))
  }

  const removeLayerCard = (slotIndex: number) => {
    setRecipeDirty(true)
    setLayers((current) => current.length <= 1 ? current : current.filter((_, index) => index !== slotIndex))
  }

  const addLayerCard = () => {
    setRecipeDirty(true)
    setLayers((current) => {
      const layerNumber = current.length + 1
      const waveformTemplate = INITIAL_LAYERS[current.length % INITIAL_LAYERS.length]
      const currentCategories = new Set(current.map((layer) => layer.category))
      const nextCategory = selectedCategories.find((category) => !currentCategories.has(category.name))?.name
        ?? selectedCategories[0]?.name
        ?? "Lead"
      return [...current, {
        id: `extra-${Date.now()}`,
        role: `Layer ${layerNumber}`,
        file: "Select a source layer",
        category: nextCategory,
        bpm,
        keyName,
        octave: 0,
        volume: 75,
        duration: 7.44,
        bars: waveformTemplate.bars,
      }]
    })
  }

  return (
    <div className="page-stack generate-page">
      <PageHeader
        eyebrow="Workspace / Generate"
        title="Build a new layer stack"
        description="Set the musical constraints, inspect the catalogue and work through the generated layers below."
        actions={
          <Badge variant={library.databaseDetected && !library.error ? "success" : "warning"}>{library.databaseDetected ? "1.9B catalogue connected" : "Catalogue unavailable"}</Badge>
        }
      />

      <Card className="generation-console">
        <CardContent className="generation-controls">
          <label className="control-field" htmlFor="target-bpm">
            <span>Target BPM</span>
            <Input
              id="target-bpm"
              type="number"
              min="60"
              max="240"
              value={bpm}
              onChange={(event) => setBpm(Number(event.target.value))}
            />
          </label>
          <Select id="target-key" label="Target key" value={keyFamilyForKey(keyName)} onChange={(family) => setKeyName(keyFromFamily(family, keyName))} options={TARGET_KEY_FAMILIES} forceBelow />
          <div className="generate-action">
            <span className="sr-only" aria-live="polite">{generateJob.error || (generateJob.busy ? generateJob.message : status)}</span>
            <Button variant="outline" className="previous-seed-button" size="sm" disabled={generateJob.busy || previousSeed == null} onClick={() => previousSeed != null && handleGenerate(previousSeed)} title={previousSeed == null ? "No previous seed yet" : `Generate seed ${previousSeed}`}><RotateCcw /> Previous</Button>
          <Button className="hardware-button generate-hardware" size="lg" onClick={() => handleGenerate()} disabled={!generateJob.busy && selectedLibraryPaths.length === 0}>
              {generateJob.busy ? <X /> : <WandSparkles />}
              {generateJob.busy ? `${generateJob.percent}% · Cancel` : "Generate"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <section className="generate-catalogue glass-panel" aria-labelledby="generate-catalogue-title">
        <div className="catalogue-toolbar">
          <div className="catalogue-heading">
            <span className="catalogue-icon" aria-hidden="true"><Database /></span>
            <div>
              <h2 id="generate-catalogue-title">Layer library</h2>
              <p>Categories available to the current Generate selection</p>
            </div>
          </div>
          <div className="catalogue-actions">
            <div className="catalogue-layer-count" aria-label={`${formatCount(selectedLayerCount)} layers selected for Generate`}>
              <strong className="tabular">{formatCount(selectedLayerCount)}</strong>
              <span>layers selected</span>
            </div>
            <LibraryManager
              library={library}
              selectedPaths={selectedLibraryPaths}
              selectedLayerCount={selectedLayerCount}
              selectedCategoryCount={selectedCategories.length}
              selectionMessage={selectionMessage}
              onSelectedPathsChange={setSelectedLibraryPaths}
              onAddFolder={pickFolder}
              onRemoveFolder={removeFolder}
            />
          </div>
        </div>

        <div className="catalogue-distribution-heading">
          <strong>Categories</strong>
          <span><b className="tabular">{selectedCategories.length}</b> available for Generate · automatic and manual labels</span>
        </div>
        <div className="catalogue-distribution" aria-label={`${selectedCategories.length} categories available for Generate`}>
          {selectedCategories.length > 0 ? selectedCategories.map((category) => (
            <div className="category-compact" key={category.name}>
              <span className="category-compact-meter" aria-hidden="true"><span style={{ width: `${Math.max(5, (category.count / largestCategoryCount) * 100)}%` }} /></span>
              <strong title={category.name}>{category.name}</strong>
              <small className="tabular">{formatCount(category.count)}</small>
            </div>
          )) : <p className="catalogue-empty">Select at least one indexed library to view its categories.</p>}
        </div>
      </section>

      <section className="generated-layers-section" aria-labelledby="generated-layers-title">
        <header className="generate-layer-toolbar">
          <div><h2 id="generated-layers-title">Generated layers</h2><span>{layers.length} synchronized cards · shared BPM and key</span></div>
          <Button
            variant="outline"
            size="sm"
            disabled={!currentGenerationResult?.masterPath || recipeDirty}
            draggable={Boolean(currentGenerationResult?.masterPath && !recipeDirty)}
            title={recipeDirty ? "Generate the edited stack before dragging its master" : currentGenerationResult?.masterPath ? "Drag the rendered master containing the complete stack" : "Generate a stack first"}
            onClick={() => currentGenerationResult?.outputDirectory && void window.stemSlicer?.revealPath(currentGenerationResult.outputDirectory)}
            onDragStart={(event) => {
              if (!currentGenerationResult?.masterPath || recipeDirty) return
              event.preventDefault()
              window.stemSlicer?.startFileDrag(currentGenerationResult.masterPath)
            }}
          ><Layers3 /> Drag all</Button>
        </header>

        <div className="layer-scroll" tabIndex={0} aria-label="Generated layer cards">
          <div className="layer-grid">
            {layers.map((layer, index) => (
              <LayerCard
                key={layer.id}
                layer={layer}
                progress={playback.progress}
                playing={playback.playing}
                mixActive={mixActive}
                isMuted={playback.mode === "mix" && playback.mutedIds.has(layer.id)}
                isAudible={playback.mode === "mix" ? !playback.mutedIds.has(layer.id) : playback.soloId === layer.id}
                isSyncSolo={playback.syncSoloId === layer.id}
                onPlay={() => void playback.toggleLayer(layer.id)}
                onSynchronizedSolo={() => void playback.toggleSynchronizedSolo(layer.id)}
                onScrubStart={() => playback.beginScrub(layer.id)}
                onSeek={(nextProgress) => playback.previewScrub(layer.id, nextProgress)}
                onScrubEnd={playback.endScrub}
                onChange={(next) => updateGeneratedLayer(index, next)}
                onToggleAlternateKey={() => toggleAlternateKey(index)}
                onToggleLock={() => toggleLayerLock(index)}
                onRemove={() => removeLayerCard(index)}
                categoryOptions={selectedCategories.map((category) => category.name)}
                canRemove={layers.length > 1}
                updating={generateUpdateJob.busy}
              />
            ))}
            <button type="button" className="add-layer-card" onClick={addLayerCard}>
              <span aria-hidden="true"><Plus /></span>
              <strong>Add layer card</strong>
              <small>Add another layer to this stack</small>
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}

function OperationSwitch({ checked, onChange, label, accent }: { checked: boolean; onChange: (checked: boolean) => void; label: string; accent: "red" | "yellow" | "orange" }) {
  return (
    <label className={cn("operation-switch", `accent-${accent}`)}>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span aria-hidden="true" />
      <span className="sr-only">{label}</span>
    </label>
  )
}

function StemSlicerView() {
  const [sourceFolder, setSourceFolder] = useState("")
  const [outputFolder, setOutputFolder] = useState("/Users/nrgy/Documents/Stem Slicer/Extracted Layers/Loop Pack Name")
  const [layerExtraction, setLayerExtraction] = useState(true)
  const [keyAnalysis, setKeyAnalysis] = useState(true)
  const [keyMode, setKeyMode] = useState("Detected")
  const [keyNotation, setKeyNotation] = useState("Sharps #")
  const [keyDestination, setKeyDestination] = useState("Copy to analyzed loops")
  const [nameTokens, setNameTokens] = useState(["Key", "Loop name", "BPM", "Prod name"])
  const [draggedToken, setDraggedToken] = useState<string | null>(null)
  const [conversion, setConversion] = useState(false)
  const [targetBpmEnabled, setTargetBpmEnabled] = useState(true)
  const [targetKeyEnabled, setTargetKeyEnabled] = useState(true)
  const [targetBpm, setTargetBpm] = useState(120)
  const [targetKey, setTargetKey] = useState(TARGET_KEY_FAMILIES[0])
  const batchJob = useAudioJob("batch")

  const enabledOperationCount = [layerExtraction, keyAnalysis, conversion].filter(Boolean).length
  const batchResult = batchJob.result as BatchJobResult | null
  const previewValues: Record<string, string> = {
    Key: keyNotation === "Sharps #" ? "A♯m" : "B♭m",
    "Loop name": "CALLMEUR3",
    BPM: "137",
    "Prod name": "+NRGY_L1",
  }
  const namePreview = `${nameTokens.map((token) => previewValues[token]).join(" ")}.mp3`

  const pickSourceFolder = async () => {
    const result = await window.stemSlicer?.pickLibraryFolder()
    if (!result || result.canceled || result.paths.length === 0) return
    setSourceFolder(result.paths[0])
  }

  const pickOutputFolder = async () => {
    const result = await window.stemSlicer?.pickLibraryFolder()
    if (!result || result.canceled || result.paths.length === 0) return
    setOutputFolder(result.paths[0])
  }

  const dropToken = (target: string) => {
    if (!draggedToken || draggedToken === target) return
    setNameTokens((current) => {
      const next = current.filter((token) => token !== draggedToken)
      next.splice(next.indexOf(target), 0, draggedToken)
      return next
    })
    setDraggedToken(null)
  }

  const processBatch = () => {
    if (batchJob.busy) {
      batchJob.cancel()
      return
    }
    if (!sourceFolder || enabledOperationCount === 0) return
    const tokenMap: Record<string, string> = {
      Key: "KEY",
      "Loop name": "LOOP NAME",
      BPM: "BPM",
      "Prod name": "PROD NAME",
    }
    void batchJob.start({
      sourceFolder,
      outputFolder,
      extractionEnabled: layerExtraction,
      keyAnalysisEnabled: keyAnalysis,
      conversionEnabled: conversion,
      keyMode: keyMode === "Relative minor" ? "relative_minor" : keyMode === "Relative major" ? "relative_major" : "detected",
      accidentals: keyNotation === "Flats ♭" ? "flats" : "sharps",
      destinationMode: keyDestination === "Rename originals" ? "rename_in_place" : "copy_to_output",
      tokenOrder: nameTokens.map((token) => tokenMap[token]),
      targetBpmEnabled,
      targetBpm,
      targetKeyEnabled,
      targetKey,
    }).catch(() => undefined)
  }

  return (
    <div className="page-stack stem-slicer-page">
      <PageHeader
        eyebrow="Workspace / Stem Slicer"
        title="Stem Slicer"
        description="Configure one batch from its source folder through extraction, key naming and conversion."
      />

      <section className="batch-workflow-shell unified-batch-workflow" aria-label="Stem Slicer batch workflow">
        <section className="unified-source" aria-labelledby="stem-source-heading">
          <div className="unified-source-heading">
            <span className="unified-source-icon"><FolderOpen aria-hidden="true" /></span>
            <div><span>Batch input</span><h2 id="stem-source-heading">Source folder</h2></div>
          </div>
          <button
            type="button"
            className="unified-source-picker"
            onClick={pickSourceFolder}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              const path = pathFromDrop(event)
              if (path) setSourceFolder(path)
            }}
          >
            <span><strong>{sourceFolder ? basename(sourceFolder) : "Choose a loop folder"}</strong><small>{sourceFolder || "Drop a folder here or browse your files"}</small></span>
            <span>Browse folder</span>
          </button>
          <dl className="unified-batch-summary">
            <div><dt>Operations</dt><dd>{enabledOperationCount} enabled</dd></div>
            <div><dt>Output</dt><dd title={outputFolder}>{layerExtraction ? basename(outputFolder) : "Per operation"}</dd></div>
            <div><dt>Originals</dt><dd>{keyDestination === "Rename originals" ? "Rename" : "Preserved"}</dd></div>
          </dl>
        </section>

        <section className="unified-pipeline-surface" aria-labelledby="stem-pipeline-heading">
          <div className="unified-pipeline-heading">
            <div><span>Single batch pipeline</span><h2 id="stem-pipeline-heading">Enabled operations run together</h2><p>Configure the complete process below, then process the source folder once.</p></div>
            <div className="unified-pipeline-route" aria-label={`${enabledOperationCount} operations enabled`}>
              <span data-enabled={layerExtraction}><Layers3 aria-hidden="true" />Extract</span>
              <i aria-hidden="true" />
              <span data-enabled={keyAnalysis}><ScanLine aria-hidden="true" />Key & naming</span>
              <i aria-hidden="true" />
              <span data-enabled={conversion}><Repeat2 aria-hidden="true" />Convert</span>
            </div>
          </div>

          <div className="unified-operations-grid">
          <section className={cn("unified-operation-card operation-extract", !layerExtraction && "is-disabled")} aria-labelledby="extract-operation-title">
            <header className="unified-operation-header">
              <span className="unified-operation-number">01</span>
              <span className="unified-operation-icon"><Layers3 aria-hidden="true" /></span>
              <div><h3 id="extract-operation-title">Layer extraction</h3><p>Extract every detected layer from each source loop.</p></div>
              <div className="unified-operation-toggle"><span>{layerExtraction ? "On" : "Off"}</span><OperationSwitch checked={layerExtraction} onChange={setLayerExtraction} label="Enable layer extraction" accent="red" /></div>
            </header>
            <div className="unified-operation-body">
              <div className="unified-output-label"><span>Output location</span><small>Destination for extracted layers</small></div>
              <div className="unified-output-path"><FolderOpen aria-hidden="true" /><strong title={outputFolder}>{outputFolder}</strong></div>
              <div className="unified-output-actions"><Button variant="outline" size="sm" onClick={pickOutputFolder}>Change</Button><Button variant="outline" size="sm" onClick={() => void window.stemSlicer?.revealPath(outputFolder)}>Open folder</Button></div>
              <div className="unified-operation-note"><span>Input</span><strong>{sourceFolder ? basename(sourceFolder) : "Waiting for source"}</strong></div>
            </div>
          </section>

          <section className={cn("unified-operation-card operation-key", !keyAnalysis && "is-disabled")} aria-labelledby="key-operation-title">
            <header className="unified-operation-header">
              <span className="unified-operation-number">02</span>
              <span className="unified-operation-icon"><ScanLine aria-hidden="true" /></span>
              <div><h3 id="key-operation-title">Key & naming</h3><p>Analyze musical relationships and compose output names.</p></div>
              <div className="unified-operation-toggle"><span>{keyAnalysis ? "On" : "Off"}</span><OperationSwitch checked={keyAnalysis} onChange={setKeyAnalysis} label="Enable key analysis" accent="yellow" /></div>
            </header>
            <div className="unified-operation-body unified-key-body">
              <div className="unified-key-choices">
                <SegmentedChoice label="Key mode" value={keyMode} options={["Detected", "Relative minor", "Relative major"]} onChange={setKeyMode} />
                <SegmentedChoice label="Notation" value={keyNotation} options={["Sharps #", "Flats ♭"]} onChange={setKeyNotation} />
              </div>
              <div className="unified-naming-block">
                <div className="unified-field-label"><span>Output name structure</span><small>Drag to reorder</small></div>
                <div className="naming-token-list">
                  {nameTokens.map((token, index) => (
                    <button
                      type="button"
                      draggable
                      className="naming-token"
                      key={token}
                      onDragStart={() => setDraggedToken(token)}
                      onDragEnd={() => setDraggedToken(null)}
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={() => dropToken(token)}
                      aria-label={`${token}, position ${index + 1} of ${nameTokens.length}.`}
                    >
                      <span aria-hidden="true">⠿</span>{token}
                    </button>
                  ))}
                </div>
              </div>
              <SegmentedChoice label="Destination" value={keyDestination} options={["Copy to analyzed loops", "Rename originals"]} onChange={setKeyDestination} />
              <div className="unified-name-preview"><span>Preview</span><strong>{namePreview}</strong></div>
            </div>
          </section>

          <section className={cn("unified-operation-card operation-convert", !conversion && "is-disabled")} aria-labelledby="convert-operation-title">
            <header className="unified-operation-header">
              <span className="unified-operation-number">03</span>
              <span className="unified-operation-icon"><Repeat2 aria-hidden="true" /></span>
              <div><h3 id="convert-operation-title">BPM & key conversion</h3><p>Retune and retime the output in the same batch.</p></div>
              <div className="unified-operation-toggle"><span>{conversion ? "On" : "Off"}</span><OperationSwitch checked={conversion} onChange={setConversion} label="Enable BPM and key conversion" accent="orange" /></div>
            </header>
            <div className="unified-operation-body unified-convert-body">
              <label className="unified-target-field">
                <span className="unified-target-heading"><input type="checkbox" checked={targetBpmEnabled} onChange={(event) => setTargetBpmEnabled(event.target.checked)} /><b>Target BPM</b></span>
                <Input aria-label="Stem Slicer target BPM" type="number" min="40" max="300" value={targetBpm} disabled={!targetBpmEnabled} onChange={(event) => setTargetBpm(Number(event.target.value))} />
              </label>
              <div className="unified-target-field">
                <label className="unified-target-heading"><input type="checkbox" checked={targetKeyEnabled} onChange={(event) => setTargetKeyEnabled(event.target.checked)} /><b>Target key</b></label>
                <Select id="stem-target-key" label="Stem Slicer target key" value={targetKey} onChange={setTargetKey} options={TARGET_KEY_FAMILIES} disabled={!targetKeyEnabled} className="inline-select" />
              </div>
              <div className="unified-convert-route"><Repeat2 aria-hidden="true" /><div><span>Conversion input</span><strong>{layerExtraction ? "Extracted layers" : "Source loops"}</strong><small>Automatically follows the extraction setting.</small></div></div>
            </div>
          </section>
          </div>

          <div className="batch-process-bar" aria-label="Batch process status">
            <div className="batch-process-copy" role="status"><span>Process status</span><strong>{batchJob.error || (batchJob.busy ? batchJob.message : batchResult ? `${batchResult.outputs.length} outputs ready` : sourceFolder ? `${basename(sourceFolder)} ready` : "Choose a source folder to begin")}</strong></div>
            <div className="batch-operation-summary" aria-label={`${enabledOperationCount} operations enabled`}>
              <span data-enabled={layerExtraction}>Extract</span><span data-enabled={keyAnalysis}>Key</span><span data-enabled={conversion}>Convert</span>
            </div>
            <div className="batch-progress" role="progressbar" aria-label="Batch progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={batchJob.percent}><span style={{ width: `${batchJob.percent}%` }} /></div>
            <div className="batch-process-stats"><span>{batchResult?.files ?? batchJob.total ?? 0} files</span><span>{batchJob.percent}%</span><span>{batchResult?.failures.length ?? (batchJob.error ? 1 : 0)} errors</span></div>
            <Button className="hardware-button" onClick={processBatch} disabled={!batchJob.busy && (!sourceFolder || enabledOperationCount === 0)}>{batchJob.busy ? "Cancel" : "Process loops"}</Button>
          </div>
        </section>
      </section>
    </div>
  )
}

function EmptyState({ icon: Icon, title, description, action }: { icon: LucideIcon; title: string; description: string; action: React.ReactNode }) {
  return (
    <div className="empty-state">
      <span className="empty-icon"><Icon /></span>
      <h2>{title}</h2>
      <p>{description}</p>
      {action}
    </div>
  )
}

function SegmentedChoice({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <div className="segmented-field">
      <span>{label}</span>
      <div className="segmented-control" role="group" aria-label={label}>
        {options.map((option) => <button key={option} type="button" aria-pressed={value === option} onClick={() => onChange(option)}>{option}</button>)}
      </div>
    </div>
  )
}

function QuickToolsView({
  previewLayers,
  setPreviewLayers,
  playback,
  onActiveToolChange,
}: {
  previewLayers: GeneratedLayer[]
  setPreviewLayers: React.Dispatch<React.SetStateAction<GeneratedLayer[]>>
  playback: PlaybackClock
  onActiveToolChange: (tool: QuickToolId) => void
}) {
  const quickTools: Array<{ id: QuickToolId; label: string; description: string; icon: LucideIcon }> = [
    { id: "extract", label: "Quick Extract", description: "Split one loop into playable layers", icon: AudioLines },
    { id: "scan", label: "Quick Scan", description: "Read BPM, key and relative modes", icon: ScanLine },
    { id: "convert", label: "Quick Convert", description: "Retune and time-stretch one loop", icon: Repeat2 },
  ]

  const [activeTool, setActiveTool] = useState<QuickToolId>("extract")
  const [scanFile, setScanFile] = useState("")
  const [convertFile, setConvertFile] = useState("")
  const [extractFile, setExtractFile] = useState("")
  const [degreeReference, setDegreeReference] = useState("Major")
  const [notation, setNotation] = useState("Sharps #")
  const [convertBpm, setConvertBpm] = useState(120)
  const [convertKey, setConvertKey] = useState(TARGET_KEY_FAMILIES[0])
  const [extractBpmEnabled, setExtractBpmEnabled] = useState(false)
  const [extractKeyEnabled, setExtractKeyEnabled] = useState(false)
  const [extractBpm, setExtractBpm] = useState(120)
  const [extractKey, setExtractKey] = useState(TARGET_KEY_FAMILIES[0])
  const extractJob = useAudioJob("quick-extract")
  const scanJob = useAudioJob("quick-scan")
  const convertJob = useAudioJob("quick-convert")
  const scanResult = scanJob.result as QuickScanResult | null
  const extractResult = extractJob.result as QuickExtractResult | null
  const convertResult = convertJob.result as QuickConvertResult | null
  const extractedLayers = extractResult?.layers ?? extractJob.artifacts
  const extractedMixActive = playback.mode === "mix"

  const selectTool = (tool: QuickToolId) => {
    if (tool === activeTool) return
    playback.reset()
    setActiveTool(tool)
    onActiveToolChange(tool)
  }

  useEffect(() => {
    setPreviewLayers((current) => {
      const currentByPath = new Map(current.map((layer) => [layer.path, layer]))
      return extractedLayers.map((artifact, index) => {
        const retained = currentByPath.get(artifact.path)
        return {
          id: `quick-extract-${artifact.path}`,
          role: `Layer ${index + 1}`,
          file: artifact.name,
          category: artifact.category ?? "Extracted",
          bpm: artifact.bpm,
          keyName: artifact.key || "—",
          octave: 0,
          volume: retained?.volume ?? 78,
          duration: artifact.duration,
          path: artifact.path,
          midiPath: artifact.midiPath,
          sourcePath: artifact.sourcePath,
          bars: artifact.peaks.map((value) => Math.max(8, Math.round(value * 100))),
        }
      })
    })
  }, [extractedLayers, setPreviewLayers])

  const pickAudio = async (setPath: (path: string) => void) => {
    const result = await window.stemSlicer?.pickAudioFiles()
    if (!result || result.canceled || result.paths.length === 0) return
    setPath(result.paths[0])
    return result.paths[0]
  }

  const chooseScanFile = async () => {
    const path = await pickAudio(setScanFile)
    if (!path) return
    void scanJob.start({ source: path }).catch(() => undefined)
  }

  const runExtract = () => {
    if (extractJob.busy) {
      extractJob.cancel()
      return
    }
    if (!extractFile) return
    void extractJob.start({
      source: extractFile,
      targetBpmEnabled: extractBpmEnabled,
      targetBpm: extractBpm,
      targetKeyEnabled: extractKeyEnabled,
      targetKey: extractKey,
    }).catch(() => undefined)
  }

  const runConvert = () => {
    if (convertJob.busy) {
      convertJob.cancel()
      return
    }
    if (!convertFile) return
    void convertJob.start({
      source: convertFile,
      targetBpmEnabled: true,
      targetBpm: convertBpm,
      targetKeyEnabled: true,
      targetKey: convertKey,
    }).catch(() => undefined)
  }

  return (
    <div className="page-stack quick-tools-page">
      <PageHeader eyebrow="Workspace / Quick Tools" title="Quick tools" description="Choose one focused operation. Every accepted 1.9B option stays available inside its tool." />

      <section className="quick-tools-shell" aria-label="Quick tools workspace">
        <div className="quick-tool-tabs" role="group" aria-label="Choose a quick tool">
          {quickTools.map(({ id, label, description, icon: Icon }) => (
            <button
              key={id}
              id={`quick-tool-tab-${id}`}
              type="button"
              className="quick-tool-tab"
              data-tool={id}
              aria-pressed={activeTool === id}
              aria-controls={`quick-tool-panel-${id}`}
              onClick={() => selectTool(id)}
            >
              <span className="quick-tab-icon"><Icon aria-hidden="true" /></span>
              <span><strong>{label}</strong><small>{description}</small></span>
            </button>
          ))}
        </div>

        {activeTool === "extract" ? (
          <div id="quick-tool-panel-extract" className="quick-tool-panel extract-panel" role="region" aria-labelledby="quick-tool-tab-extract">
            <header className="quick-panel-heading">
              <div><span className="quick-panel-kicker">One loop · multiple layers</span><h2>Extract layers</h2></div>
              <span className="quick-panel-status">{extractJob.busy ? `${extractJob.percent}% · ${extractJob.message}` : `${previewLayers.length} layers`}</span>
            </header>

            <div className="quick-extract-controls">
              <button type="button" className="quick-file-source" onClick={() => pickAudio(setExtractFile)} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { const path = pathFromDrop(event); if (path) setExtractFile(path) }}>
                <span className="quick-source-icon"><Music2 aria-hidden="true" /></span>
                <span className="quick-source-copy"><strong>{extractFile ? basename(extractFile) : "Choose an MP3 loop"}</strong><small>{extractFile || "Drop a loop here or browse your files"}</small></span>
                <span className="quick-source-action">Browse loop</span>
              </button>

              <div className="quick-extract-settings" aria-label="Optional target transformation">
                <label className="quick-setting-card">
                  <span className="quick-setting-heading"><input type="checkbox" checked={extractBpmEnabled} onChange={(event) => setExtractBpmEnabled(event.target.checked)} /><b>Target BPM</b></span>
                  <Input aria-label="Quick Extract target BPM" type="number" min="40" max="300" value={extractBpm} disabled={!extractBpmEnabled} onChange={(event) => setExtractBpm(Number(event.target.value))} />
                </label>
                <div className="quick-setting-card quick-setting-key">
                  <label className="quick-setting-heading"><input type="checkbox" checked={extractKeyEnabled} onChange={(event) => setExtractKeyEnabled(event.target.checked)} /><b>Target key</b></label>
                  <Select id="quick-extract-key" label="Quick Extract target key" value={extractKey} onChange={setExtractKey} options={TARGET_KEY_FAMILIES} disabled={!extractKeyEnabled} className="inline-select" />
                </div>
              </div>

              <Button className="quick-run-button" onClick={runExtract} disabled={!extractJob.busy && !extractFile}>{extractJob.busy ? <X /> : <Sparkles />} {extractJob.busy ? "Cancel" : "Extract"}</Button>
            </div>

            <section className="generated-layers-section quick-extracted-layers-section" aria-labelledby="quick-extracted-layers-title">
              <header className="generate-layer-toolbar">
                <div><h2 id="quick-extracted-layers-title">Extracted layers</h2><span>{extractFile ? `${basename(extractFile)} selected` : "Cards appear here as each layer becomes available."}</span></div>
                <Button variant="outline" size="sm" disabled={previewLayers.length === 0} onClick={() => window.stemSlicer?.startFilesDrag(previewLayers.flatMap((layer) => layer.path ? [layer.path] : []))}><Layers3 /> Drag all</Button>
              </header>
              <div className="layer-scroll" tabIndex={0} aria-label="Extracted layer cards" aria-live="polite">
                {previewLayers.length > 0 ? <div className="layer-grid">{previewLayers.map((layer, index) => <LayerCard
                key={layer.id}
                layer={layer}
                variant="extract"
                progress={playback.progress}
                playing={playback.playing}
                mixActive={extractedMixActive}
                isMuted={playback.mode === "mix" && playback.mutedIds.has(layer.id)}
                isAudible={playback.mode === "mix" ? !playback.mutedIds.has(layer.id) : playback.soloId === layer.id}
                isSyncSolo={playback.syncSoloId === layer.id}
                onPlay={() => void playback.toggleLayer(layer.id)}
                onSynchronizedSolo={() => void playback.toggleSynchronizedSolo(layer.id)}
                onScrubStart={() => playback.beginScrub(layer.id)}
                onSeek={(nextProgress) => playback.previewScrub(layer.id, nextProgress)}
                onScrubEnd={playback.endScrub}
                onChange={(next) => setPreviewLayers((current) => current.map((item, itemIndex) => itemIndex === index ? next : item))}
                />)}</div> : <div className="quick-layer-empty">
                  <span className="quick-empty-icon"><Layers3 aria-hidden="true" /></span>
                  <strong>{extractJob.error || (extractJob.busy ? extractJob.message : "No extracted layers yet")}</strong>
                  <span>{extractJob.busy ? `${extractJob.percent}% complete` : "Choose a loop to create playable cards with waveform, MIDI drag and individual export."}</span>
                </div>}
              </div>
            </section>
          </div>
        ) : null}

        {activeTool === "scan" ? (
          <div id="quick-tool-panel-scan" className="quick-tool-panel scan-panel" role="region" aria-labelledby="quick-tool-tab-scan">
            <header className="quick-panel-heading">
              <div><span className="quick-panel-kicker">One loop · full musical readout</span><h2>Scan BPM and key</h2></div>
              <span className="quick-panel-status">{scanJob.busy ? `${scanJob.percent}% · ${scanJob.message}` : scanJob.error || (scanResult ? "Analysis complete" : scanFile ? "File selected" : "Ready to scan")}</span>
            </header>

            <div className="quick-scan-body">
              <button type="button" className="quick-file-source quick-file-source-tall" onClick={chooseScanFile} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { const path = pathFromDrop(event); if (!path) return; setScanFile(path); void scanJob.start({ source: path }).catch(() => undefined) }}>
                <span className="quick-source-icon"><ScanLine aria-hidden="true" /></span>
                <span className="quick-source-copy"><strong>{scanFile ? basename(scanFile) : "Choose one loop"}</strong>{scanFile ? null : <small>Drop a loop here or browse your files</small>}</span>
                <span className="quick-source-action">Browse loop</span>
              </button>

              <div className="quick-scan-analysis">
                <div className="quick-scan-metrics">
                  {[["BPM", scanResult ? String(scanResult.bpm) : "—", "Tempo"], ["Detected key", scanResult ? formatCamelotKey(scanResult.camelot, notation) : "—", "Top-1"], ["Relative key", scanResult ? formatCamelotKey(scanResult.camelot, notation, "relative") : "—", "Relationship"]].map(([label, value, detail]) => (
                    <div className="scan-metric" key={label}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
                  ))}
                </div>
                <div className="relative-modes">
                  <div className="relative-modes-heading"><span>Relative modes</span><small>Same notes · different centers</small></div>
                  <div className="relative-mode-grid">
                    {(scanResult ? scanResult.relativeModes.filter((_, index) => [1, 2, 3, 4, 6].includes(index)) : Array.from({ length: 5 }, (_, index) => ({ degreeMajor: ["II", "III", "IV", "V", "VII"][index], degreeMinor: "—", key: "—", mode: "—" }))).map((mode, index) => <div key={`${mode.mode}-${index}`}><span>{degreeReference === "Minor" ? mode.degreeMinor : mode.degreeMajor}</span><strong>{formatModePitch(mode.key, notation)}</strong><small>{mode.mode}</small></div>)}
                  </div>
                </div>
                <div className="quick-scan-details">
                  <div className="quick-scan-details-heading">
                    <div><span>Analysis details</span><small>Technical output from the 1.9B scan engine</small></div>
                    <span>{scanFile ? basename(scanFile) : "No file selected"}</span>
                  </div>
                  <div className="quick-scan-detail-grid">
                    {[
                      ["BPM confidence", scanResult?.bpmConfidence == null ? "—" : `${Math.round(scanResult.bpmConfidence * 100)}%`, "Model score"],
                      ["BPM source", scanResult?.bpmSource ?? "—", "Audio and filename decision"],
                      ["Camelot", scanResult?.camelot ?? "—", "Wheel notation"],
                      ["OpenKey", scanResult?.openKey ?? "—", "Harmonic mixing notation"],
                    ].map(([label, value, detail]) => (
                      <div key={label}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
                    ))}
                  </div>
                </div>
                <div className="quick-scan-options">
                  <SegmentedChoice label="Degree reference" value={degreeReference} options={["Major", "Minor"]} onChange={setDegreeReference} />
                  <SegmentedChoice label="Key notation" value={notation} options={["Sharps #", "Flats ♭"]} onChange={setNotation} />
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {activeTool === "convert" ? (
          <div id="quick-tool-panel-convert" className="quick-tool-panel convert-panel" role="region" aria-labelledby="quick-tool-tab-convert">
            <header className="quick-panel-heading">
              <div><span className="quick-panel-kicker">One loop · new BPM and key</span><h2>Convert audio</h2></div>
              <span className="quick-panel-status">{convertJob.busy ? `${convertJob.percent}% · ${convertJob.message}` : convertJob.error || (convertResult ? "1 conversion" : "0 conversions")}</span>
            </header>

            <div className="quick-convert-controls">
              <button type="button" className="quick-file-source" onClick={() => pickAudio(setConvertFile)} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { const path = pathFromDrop(event); if (path) setConvertFile(path) }}>
                <span className="quick-source-icon"><Repeat2 aria-hidden="true" /></span>
                <span className="quick-source-copy"><strong>{convertFile ? basename(convertFile) : "Choose one loop"}</strong><small>{convertFile || "Drop a loop here or browse your files"}</small></span>
                <span className="quick-source-action">Browse loop</span>
              </button>
              <label className="quick-convert-field"><span>Target BPM</span><Input aria-label="Quick Convert target BPM" type="number" min="40" max="300" value={convertBpm} onChange={(event) => setConvertBpm(Number(event.target.value))} /></label>
              <Select id="quick-convert-key" label="Target key" value={convertKey} onChange={setConvertKey} options={TARGET_KEY_FAMILIES} />
              <Button className="quick-run-button" onClick={runConvert} disabled={!convertJob.busy && !convertFile}>{convertJob.busy ? <X /> : <Repeat2 />} {convertJob.busy ? "Cancel" : "Convert"}</Button>
            </div>

            <div className="quick-convert-result" aria-live="polite">
              {convertResult ? <AudioArtifactCard artifact={convertResult.artifact} /> : <><span className="quick-empty-icon"><AudioLines aria-hidden="true" /></span>
              <div><strong>{convertJob.error || (convertJob.busy ? convertJob.message : "No converted file yet")}</strong><small>{convertJob.busy ? `${convertJob.percent}% complete` : "The converted result will remain playable and individually draggable."}</small></div>
              <div className="quick-result-actions"><Button variant="outline" size="sm" disabled>Open output folder</Button><Button variant="outline" size="sm" disabled>Manage files</Button></div></>}
            </div>
          </div>
        ) : null}
      </section>
    </div>
  )
}

function HistoryPlayButton({ entry, playing, onToggle }: { entry: HistoryEntry; playing: boolean; onToggle: () => void }) {
  return (
    <Button variant="outline" size="sm" onClick={onToggle} aria-label={`${playing ? "Pause" : "Play"} ${entry.recipe} generation`}>{playing ? <Pause /> : <Play className="play-glyph" />}</Button>
  )
}

function historyLayerId(entryId: string) {
  return `history-${entryId}`
}

function historyEntryToLayer(entry: HistoryEntry): GeneratedLayer {
  const referenceLayer = entry.layers.find((layer) => layer.bars.length > 0) ?? entry.layers[0]
  return {
    id: historyLayerId(entry.id),
    role: `${entry.recipe} combination`,
    file: `${entry.recipe} combination`,
    category: "History",
    bpm: entry.bpm,
    keyName: entry.keyName,
    octave: 0,
    volume: 100,
    duration: Math.max(0, ...entry.layers.map((layer) => layer.duration)),
    path: entry.generation.masterPath,
    bars: referenceLayer?.bars ?? INITIAL_LAYERS[0].bars,
  }
}

function HistoryView({ history, playback, onReopen, onTrash }: { history: HistoryEntry[]; playback: PlaybackClock; onReopen: (entry: HistoryEntry) => void; onTrash: (entry: HistoryEntry) => Promise<void> }) {

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Workspace / History" title="Generation history" description="Reopen previous combinations, compare generations and keep the stacks worth exporting." />
      {history.length ? (
        <div className="history-list">
          {history.map((entry) => (
            <Card key={entry.id} className="history-item">
              <CardContent>
                <span className="history-icon"><History /></span>
                <div><strong>{entry.recipe} combination</strong><small>{entry.createdAt} · {entry.layerCount} layers</small></div>
                <div className="history-spec"><Badge variant="secondary">{entry.recipe}</Badge><span>{entry.bpm} BPM</span><span>{entry.keyName}</span></div>
                <div className="history-actions">
                  <HistoryPlayButton entry={entry} playing={playback.playing && playback.mode === "solo" && playback.soloId === historyLayerId(entry.id)} onToggle={() => void playback.toggleLayer(historyLayerId(entry.id))} />
                  <Button variant="outline" size="sm" onClick={() => void window.stemSlicer?.revealPath(entry.generation.outputDirectory)}><FolderOpen /> Open</Button>
                  <Button variant="outline" className="history-reload" size="sm" onClick={() => onReopen(entry)}><RefreshCw /> Reload</Button>
                  <Button variant="outline" size="sm" draggable onClick={() => void window.stemSlicer?.revealPath(entry.generation.masterPath)} onDragStart={(event) => { event.preventDefault(); window.stemSlicer?.startFileDrag(entry.generation.masterPath) }}><Layers3 /> Drag</Button>
                  <Button variant="ghost" size="icon" className="history-trash" aria-label={`Move ${entry.recipe} generation to Trash`} title="Move generated folder to Trash" onClick={() => void onTrash(entry)}><Trash2 /></Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <EmptyState icon={History} title="No generation yet" description="Generate a combination and it will appear here with its musical constraints." action={<span className="empty-hint">Open Generate to create the first entry.</span>} />
      )}
    </div>
  )
}

function CloudView() {
  return (
    <div className="page-stack">
      <PageHeader eyebrow="Workspace / Connected Libraries" title="Mix trusted producer libraries" description="A future permission layer will let Generate combine your local catalogue with libraries explicitly shared by other producers." actions={<Badge variant="warning">WIP</Badge>} />
      <Card className="cloud-hero">
        <CardContent>
          <span className="cloud-symbol"><CloudCog /></span>
          <Badge variant="warning">Working in progress</Badge>
          <h2>Connected Libraries</h2>
          <p>Permission, identity, remote indexing and revocation will live here. No cloud connection exists in this prototype yet.</p>
          <Button variant="outline" disabled><Plus /> Invite a producer</Button>
        </CardContent>
      </Card>
    </div>
  )
}

function GlobalPlayer({ layers, playback, contextLabel }: { layers: GeneratedLayer[]; playback: PlaybackClock; contextLabel: string }) {
  const timelineScrubberRef = useRef<HTMLInputElement>(null)
  const soloLayer = layers.find((layer) => layer.id === playback.soloId)
  const audibleMixLayers = layers.filter((layer) => !playback.mutedIds.has(layer.id))
  const activeLayers = playback.playing
    ? playback.mode === "solo" && soloLayer
      ? [soloLayer]
      : playback.mode === "mix"
        ? audibleMixLayers
        : []
    : []
  const currentLayer = soloLayer ?? activeLayers[0] ?? layers[0]
  const mixPlaying = playback.playing && playback.mode === "mix"
  const syncEnabled = playback.syncEnabled
  const primaryPlaying = playback.playing && (syncEnabled ? playback.mode === "mix" : playback.mode === "solo")
  const timelineLayer = syncEnabled ? layers.find((layer) => layer.path) : soloLayer
  const duration = timelineLayer?.duration ?? currentLayer?.duration ?? 0
  const canPlayPrimary = syncEnabled ? layers.some((layer) => layer.path) : Boolean(playback.lastSoloId && soloLayer?.path)
  const activeFileNames = activeLayers.map((layer) => layer.file).join(" · ")
  const playerTitle = activeLayers.length === 1
    ? activeLayers[0].file
    : activeLayers.length > 1
      ? `${activeLayers.length} files playing`
      : "No file playing"
  const playerDetails = activeLayers.length === 1
    ? `${activeLayers[0].category} · ${activeLayers[0].bpm} BPM · ${activeLayers[0].keyName}`
    : activeLayers.length > 1
      ? activeFileNames
      : layers.length > 0
        ? "Choose a card or start synchronized play"
        : "No audio layers"
  const seekTimelineFromPointer = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!timelineLayer) return
    const bounds = event.currentTarget.getBoundingClientRect()
    if (bounds.width <= 0) return
    const nextProgress = (event.clientX - bounds.left) / bounds.width
    playback.previewScrub(timelineLayer.id, nextProgress)
  }

  return (
    <footer className="global-player app-no-drag" aria-label="Global audio preview">
      <div className="player-current">
        <span className="player-art"><AudioLines aria-hidden="true" /></span>
        <div>
          <strong title={activeFileNames || undefined}>{playerTitle}</strong>
          <small title={activeLayers.length > 1 ? activeFileNames : undefined}>{playerDetails}</small>
        </div>
        {playback.error ? <Badge variant="warning" title={playback.error}>Audio unavailable</Badge> : null}
      </div>
      <div className="player-core">
        <div className="player-controls">
          <button type="button" className={cn("player-key player-loop-key", playback.loopEnabled && "is-active")} disabled={!layers.some((layer) => layer.path)} onClick={() => void playback.toggleLoopMode()} aria-pressed={playback.loopEnabled} aria-label={playback.loopEnabled ? "Disable loop playback" : "Enable loop playback"}><Repeat2 aria-hidden="true" /></button>
          <button type="button" className={cn("player-key player-key-primary", primaryPlaying && "is-active")} disabled={!canPlayPrimary} onClick={() => void playback.togglePrimary()} aria-label={syncEnabled ? mixPlaying ? "Pause all layers" : "Play all layers" : primaryPlaying ? "Pause selected layer" : "Play selected layer"}>{primaryPlaying ? <Pause aria-hidden="true" /> : <Play className="play-glyph" aria-hidden="true" />}</button>
          <button type="button" className="player-key" disabled={!timelineLayer} onClick={playback.rewind} aria-label="Stop and return to beginning"><SkipBack aria-hidden="true" /></button>
        </div>
        <div className="player-timeline">
          <div
            className={cn("global-waveform-reader", !timelineLayer && "is-disabled")}
            onPointerDown={(event) => {
              if (!timelineLayer || event.button !== 0) return
              event.preventDefault()
              timelineScrubberRef.current?.focus({ preventScroll: true })
              playback.beginScrub(timelineLayer.id)
              event.currentTarget.setPointerCapture(event.pointerId)
              seekTimelineFromPointer(event)
            }}
            onPointerMove={(event) => {
              if (event.currentTarget.hasPointerCapture(event.pointerId)) seekTimelineFromPointer(event)
            }}
            onPointerUp={(event) => {
              if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
              event.currentTarget.releasePointerCapture(event.pointerId)
              void playback.endScrub()
            }}
            onPointerCancel={(event) => {
              if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
              void playback.endScrub()
            }}
          >
            <Waveform progress={timelineLayer ? playback.progress : 0} compact label={`${contextLabel} waveform`} />
            <input
              ref={timelineScrubberRef}
              className="global-waveform-scrubber"
              type="range"
              min="0"
              max="1000"
              disabled={!timelineLayer}
              value={Math.round((timelineLayer ? playback.progress : 0) * 1000)}
              aria-label={`Position de lecture ${contextLabel}`}
              tabIndex={-1}
              onChange={(event) => timelineLayer && playback.previewScrub(timelineLayer.id, Number(event.target.value) / 1000)}
            />
          </div>
          <span className="tabular">{((timelineLayer ? playback.progress : 0) * duration).toFixed(1)} / {duration.toFixed(1)} s</span>
        </div>
      </div>
      <label className="player-volume"><Volume2 aria-hidden="true" /><span className="sr-only">Preview volume</span><input type="range" min="0" max="100" value={playback.masterVolume} onChange={(event) => playback.setMasterVolume(Number(event.target.value))} /><output className="tabular">{playback.masterVolume}%</output></label>
    </footer>
  )
}

export function App() {
  const [activeView, setActiveView] = useState<ViewId>("generate")
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [library, setLibrary] = useState<LibraryOverview>(FALLBACK_LIBRARY)
  const [layers, setLayers] = useState(INITIAL_LAYERS)
  const [quickPreviewLayers, setQuickPreviewLayers] = useState<GeneratedLayer[]>([])
  const [activeQuickTool, setActiveQuickTool] = useState<QuickToolId>("extract")
  const [history, setHistory] = useState<HistoryEntry[]>(loadGenerateHistory)
  const [currentGenerationResult, setCurrentGenerationResult] = useState<GenerateResult | null>(null)
  const quickPreviewActive = activeView === "quick-tools" && activeQuickTool === "extract" && quickPreviewLayers.length > 0
  const stackPlayback = activeView === "generate" || quickPreviewActive
  const historyPlayerLayers = useMemo(() => history.map(historyEntryToLayer), [history])
  const playerLayers = useMemo(() => activeView === "history" ? historyPlayerLayers : quickPreviewActive ? quickPreviewLayers : layers, [activeView, historyPlayerLayers, layers, quickPreviewActive, quickPreviewLayers])
  const playback = usePlaybackClock(playerLayers, stackPlayback)
  const resetPlayback = playback.reset
  const mainRef = useRef<HTMLElement>(null)
  const initialViewRef = useRef(true)

  const addHistory = useCallback((entry: HistoryEntry) => {
    setHistory((items) => [entry, ...items.filter((item) => item.generation.outputDirectory !== entry.generation.outputDirectory)])
  }, [])

  const updateHistory = useCallback((generation: GenerateResult, updatedLayers: GeneratedLayer[]) => {
    setHistory((items) => items.map((item) => item.generation.outputDirectory === generation.outputDirectory
      ? { ...item, generation, layers: updatedLayers }
      : item))
  }, [])

  const refreshLibrary = useCallback(async () => {
    const overview = await window.stemSlicer?.getLibraryOverview()
    if (overview) setLibrary(overview)
  }, [])

  useEffect(() => {
    const api = window.stemSlicer
    if (!api) return
    void refreshLibrary()
  }, [refreshLibrary])

  useEffect(() => {
    try {
      window.localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(history))
    } catch {
      // History persistence is best-effort; generated files remain on disk.
    }
  }, [history])

  useEffect(() => {
    document.title = `${NAVIGATION.find((item) => item.id === activeView)?.label ?? "Stem Slicer"} · Stem Slicer Prototype`
    if (initialViewRef.current) {
      initialViewRef.current = false
      return
    }
    mainRef.current?.focus()
  }, [activeView])

  const navigateToView = useCallback((view: ViewId) => {
    if (view === activeView) return
    resetPlayback()
    setActiveView(view)
  }, [activeView, resetPlayback])

  const reopenHistory = (entry: HistoryEntry) => {
    playback.reset()
    setLayers(entry.layers)
    setCurrentGenerationResult(entry.generation)
    setActiveView("generate")
  }

  const trashHistory = async (entry: HistoryEntry) => {
    await window.stemSlicer?.trashPath(entry.generation.outputDirectory)
    setHistory((items) => items.filter((item) => item.id !== entry.id))
    if (currentGenerationResult?.outputDirectory === entry.generation.outputDirectory) {
      playback.reset()
      setCurrentGenerationResult(null)
      setLayers(INITIAL_LAYERS)
    }
  }

  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">Aller au contenu principal</a>
      <AppSidebar activeView={activeView} collapsed={sidebarCollapsed} onNavigate={navigateToView} onToggle={() => setSidebarCollapsed((value) => !value)} />
      <div className="app-workspace">
        <div className="window-dragbar app-drag-region">
          <span className="prototype-pill app-no-drag"><span /> Electron prototype</span>
        </div>
        <main id="main-content" tabIndex={-1} ref={mainRef} className={cn(activeView === "generate" && "generate-main", activeView === "quick-tools" && "quick-tools-main", activeView === "stem-slicer" && "stem-slicer-main")}>
          <div hidden={activeView !== "stem-slicer"}><StemSlicerView /></div>
          <div hidden={activeView !== "generate"}><GenerateView library={library} layers={layers} setLayers={setLayers} currentGenerationResult={currentGenerationResult} setCurrentGenerationResult={setCurrentGenerationResult} onAddHistory={addHistory} onUpdateHistory={updateHistory} onLibraryRefresh={refreshLibrary} playback={playback} /></div>
          <div hidden={activeView !== "quick-tools"}><QuickToolsView previewLayers={quickPreviewLayers} setPreviewLayers={setQuickPreviewLayers} playback={playback} onActiveToolChange={setActiveQuickTool} /></div>
          <div hidden={activeView !== "history"}><HistoryView history={history} playback={playback} onReopen={reopenHistory} onTrash={trashHistory} /></div>
          <div hidden={activeView !== "cloud"}><CloudView /></div>
        </main>
        <GlobalPlayer layers={playerLayers} playback={playback} contextLabel={activeView === "history" ? "History generation" : quickPreviewActive ? "Extracted stack" : "Generated stack"} />
      </div>
    </div>
  )
}
