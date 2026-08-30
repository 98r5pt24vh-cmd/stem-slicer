import { Dialog } from "@base-ui/react/dialog"
import { Popover } from "@base-ui/react/popover"
import { Select as BaseSelect } from "@base-ui/react/select"
import {
  AudioLines,
  Archive,
  AlertTriangle,
  ArrowRightLeft,
  ArrowDownWideNarrow,
  ArrowUpNarrowWide,
  Check,
  CheckSquare2,
  ChevronDown,
  ChevronLeft,
  CircleAlert,
  CircleX,
  Cloud,
  CloudCog,
  Dices,
  FolderOpen,
  ExternalLink,
  GripVertical,
  History,
  Instagram,
  Library as LibraryIcon,
  Layers3,
  ListFilter,
  Lock,
  LogIn,
  LogOut,
  Monitor,
  Music2,
  Pause,
  Pencil,
  Pin,
  Play,
  Plus,
  RefreshCw,
  Repeat2,
  RotateCcw,
  ScanLine,
  Scissors,
  ShieldCheck,
  Square,
  SkipBack,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  UploadCloud,
  Unlock,
  UserMinus,
  UserRound,
  UsersRound,
  Volume2,
  WandSparkles,
  X,
  type LucideIcon,
} from "lucide-react"
import { memo, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react"
import { flushSync } from "react-dom"

import { Waveform } from "@/components/waveform"
import { StudioWaveform } from "@/components/studio-waveform"
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
import { basename, cn, extractionFolderNameForSource, formatCount, formatDecimalBytes, joinPath, outputFolderNameError } from "@/lib/utils"
import { GENERATE_CATEGORY_OPTIONS, mergeGenerateCategories } from "@/lib/generate-categories"
import { createPlaybackProgressStore, type PlaybackProgressSource, type PlaybackProgressStore } from "@/lib/playback-progress"
import { quickFileToolFromDragHover } from "@/lib/quick-tool-drag"
import {
  parseConvertHistory,
  parseExtractionHistory,
  prependUniqueActivity,
  type ConvertHistoryEntry,
  type ExtractionHistoryEntry,
} from "@/lib/activity-history"
import { compactKeyFamilyLabel, keyFamilyForKey, keyFromFamily, normalizeKeyName, randomKeyOutsidePreviousFamily, TARGET_KEY_FAMILIES } from "@/lib/random-key"
import { studioLayerName } from "@/lib/source-loop-name"
import { createProducerIdentityResolver, generationDisplayName, PRIMARY_PRODUCER, producerMonogram, producersForLayers, provenanceForLayer, stripAudioExtension, uniqueProducerCredits, uniqueProducerNames } from "@/lib/source-provenance"
import { AUDIO_START_AHEAD_SECONDS, SharedWebAudioEngine, transportProgress } from "@/renderer/shared-web-audio-engine"
import type {
  AudioArtifact,
  AudioJobKind,
  AudioJobRequest,
  AudioJobResult,
  BatchJobResult,
  CategoryCorrection,
  CloudGenerationActivity,
  CloudLibrarySummary,
  CloudPublishEvent,
  CloudProfile,
  CloudState,
  GenerateResult,
  GenerationStorageUsage,
  EngineComponentState,
  EngineStatus,
  KeyIssueReport,
  LibraryIssueType,
  LibraryOverview,
  LibraryProducerSummary,
  LibrarySelectionSummary,
  ProducerIdentity,
  QuickConvertResult,
  QuickExtractResult,
  QuickScanResult,
  ReportKeyIssueRequest,
  SetLayerCategoryRequest,
  SourceLoopEditorData,
  SourceLoopEditorLayer,
  ViewId,
} from "@/shared/contracts"
import { editorTimelineSeconds, SourceLoopPreviewEngine } from "@/renderer/source-loop-preview-engine"

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
  sourceFile?: string
  sourceLoopId?: string
  sourceLoopName?: string
  producers?: string[]
  libraryRoot?: string
  sourceOrigin?: "local" | "cloud"
  cloudLayerId?: string
  cloudOwnerId?: string
  sourceSha256?: string
  sourceDetectedKey?: string
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
  generationNumber: number
  displayName: string
  producers: string[]
  createdAt: string
  createdAtIso?: string
  layerCount: number
  generation: GenerateResult
  layers: GeneratedLayer[]
  cloudRunId?: string
  exportedAt?: string
}

interface SourceLoopStudioRequest {
  libraryRoot: string
  sourceLoopId: string
  issueId: string
  issueActive: boolean
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

function CloudFillIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M7.1 19h10.95a4.45 4.45 0 0 0 .67-8.85 6.85 6.85 0 0 0-13.1-.82A4.9 4.9 0 0 0 7.1 19Z" />
    </svg>
  )
}

function SourceOriginIcon({ origin }: { origin: "local" | "cloud" }) {
  const label = origin === "cloud" ? "Cloud source" : "Local source"
  return (
    <span className={cn("source-origin-icon", `is-${origin}`)} role="img" aria-label={label} title={label}>
      {origin === "cloud" ? <CloudFillIcon /> : <Monitor aria-hidden="true" />}
    </span>
  )
}

type SlicerToolId = "slicer" | "extract" | "scan" | "convert"
type PlaybackContext = "generate" | "quick-extract" | "quick-convert" | "history"

const NAVIGATION: NavItem[] = [
  { id: "stem-slicer", label: "Slicer", icon: Layers3 },
  { id: "generate", label: "Generate", icon: Sparkles },
  { id: "history", label: "History", icon: History },
  { id: "library", label: "Review", icon: LibraryIcon },
  { id: "cloud", label: "Cloud", icon: Cloud, badge: "ALPHA" },
]

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

const INITIAL_LAYER_TEMPLATES: GeneratedLayer[] = [
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
    id: "pluck",
    role: "Pluck",
    file: "NRGY_129_Fm_Pluck_18.wav",
    category: "Pluck",
    bpm: 129,
    keyName: "F minor",
    octave: 0,
    volume: 61,
    duration: 7.44,
    alternateKey: "A♭ major",
    bars: [28, 34, 42, 47, 53, 58, 63, 68, 72, 75, 78, 81, 83, 85, 86, 87, 88, 88, 87, 86, 84, 81, 78, 74, 70, 65, 60, 55, 50, 45, 41, 37, 34, 32, 31, 30, 31, 33, 36, 40, 45, 51, 58, 65, 71, 76, 80, 82],
  },
]

const INITIAL_LAYERS: GeneratedLayer[] = [
  INITIAL_LAYER_TEMPLATES[3],
  INITIAL_LAYER_TEMPLATES[1],
  INITIAL_LAYER_TEMPLATES[0],
  INITIAL_LAYER_TEMPLATES[2],
  INITIAL_LAYER_TEMPLATES[4],
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
const EXTRACTION_HISTORY_STORAGE_KEY = "stem-slicer-electron.extraction-history.v1"
const CONVERT_HISTORY_STORAGE_KEY = "stem-slicer-electron.convert-history.v1"
const GENERATION_SEQUENCE_STORAGE_KEY = "stem-slicer-electron.generation-sequence.v1"
const COLLABORATOR_SETTINGS_STORAGE_KEY = "stem-slicer-electron.collaborator-settings.v1"
const PRODUCER_PROFILES_CHANGED_EVENT = "stem-slicer-producer-profiles-changed"
const CLOUD_STATE_CHANGED_EVENT = "stem-slicer-cloud-state-changed"
const CLOUD_ACTIVITY_CHANGED_EVENT = "stem-slicer-cloud-activity-changed"
const CLOUD_ACTIVITY_ERROR_EVENT = "stem-slicer-cloud-activity-error"
const CLOUD_REFRESH_INTERVAL_MS = 10_000

type ProducerSortDirection = "desc" | "asc"
type FiniteCollaboratorCreditCount = 1 | 2 | 3
type CollaboratorCreditCount = 0 | FiniteCollaboratorCreditCount
type GenerationSourcePool = "mixed" | "cloud-only" | "local-only"

const DEFAULT_COLLABORATOR_CREDIT_COUNTS: CollaboratorCreditCount[] = [1, 2]

function normalizedCreditCounts(values: unknown): CollaboratorCreditCount[] {
  if (!Array.isArray(values)) return []
  const normalized = [...new Set(values.map(Number).filter((value): value is CollaboratorCreditCount => value === 0 || value === 1 || value === 2 || value === 3))]
    .sort((left, right) => left - right)
  return normalized.includes(0) ? [0] : normalized
}

function creditCountsThrough(maximum: FiniteCollaboratorCreditCount): CollaboratorCreditCount[] {
  return ([1, 2, 3] as CollaboratorCreditCount[]).filter((count) => count <= maximum)
}

interface ProducerProfileSettings {
  avatarPath?: string
  avatarUrl?: string
  avatarRevision?: number
}

interface CollaboratorSettings {
  allowedProducers: string[] | null
  allowedCreditCounts: CollaboratorCreditCount[]
  requiredProducers: string[]
  requiredContributionPercent: number
  sourcePool: GenerationSourcePool
  pinnedProducers: string[]
  producerSortDirection: ProducerSortDirection
  profiles: Record<string, ProducerProfileSettings>
}

function loadCollaboratorSettings(): CollaboratorSettings {
  try {
    const raw = window.localStorage.getItem(COLLABORATOR_SETTINGS_STORAGE_KEY)
    if (!raw) return { allowedProducers: null, allowedCreditCounts: DEFAULT_COLLABORATOR_CREDIT_COUNTS, requiredProducers: [], requiredContributionPercent: 20, sourcePool: "mixed", pinnedProducers: [], producerSortDirection: "desc", profiles: {} }
    const parsed = JSON.parse(raw)
    const storedCreditCounts = normalizedCreditCounts(parsed.allowedCreditCounts)
    const storedCreditRange = storedCreditCounts.length > 0
      ? storedCreditCounts.includes(0)
        ? [0] as CollaboratorCreditCount[]
        : creditCountsThrough(Math.max(...storedCreditCounts) as FiniteCollaboratorCreditCount)
      : []
    const legacyMaximum = [0, 1, 2, 3].includes(Number(parsed.maxProducerCount)) ? Number(parsed.maxProducerCount) : null
    const legacyCreditCounts = legacyMaximum === 0
      ? [0] as CollaboratorCreditCount[]
      : legacyMaximum
        ? Array.from({ length: legacyMaximum }, (_, index) => index + 1) as CollaboratorCreditCount[]
        : DEFAULT_COLLABORATOR_CREDIT_COUNTS
    return {
      allowedProducers: Array.isArray(parsed.allowedProducers)
        ? parsed.allowedProducers.filter((value: unknown): value is string => typeof value === "string")
        : null,
      allowedCreditCounts: storedCreditRange.length > 0 ? storedCreditRange : legacyCreditCounts,
      requiredProducers: Array.isArray(parsed.requiredProducers)
        ? parsed.requiredProducers.filter((value: unknown): value is string => typeof value === "string")
        : [],
      requiredContributionPercent: Number.isFinite(Number(parsed.requiredContributionPercent))
        ? Math.min(100, Math.max(10, Math.round(Number(parsed.requiredContributionPercent) / 10) * 10))
        : Number(parsed.minimumLayersPerRequiredProducer) === 2 ? 40 : 20,
      sourcePool: parsed.sourcePool === "cloud-only" || parsed.sourcePool === "local-only" ? parsed.sourcePool : "mixed",
      pinnedProducers: Array.isArray(parsed.pinnedProducers)
        ? parsed.pinnedProducers.filter((value: unknown): value is string => typeof value === "string")
        : [],
      producerSortDirection: parsed.producerSortDirection === "asc" ? "asc" : "desc",
      profiles: parsed.profiles && typeof parsed.profiles === "object" ? parsed.profiles : {},
    }
  } catch {
    return { allowedProducers: null, allowedCreditCounts: DEFAULT_COLLABORATOR_CREDIT_COUNTS, requiredProducers: [], requiredContributionPercent: 20, sourcePool: "mixed", pinnedProducers: [], producerSortDirection: "desc", profiles: {} }
  }
}

function saveCollaboratorSettings(settings: CollaboratorSettings): void {
  window.localStorage.setItem(COLLABORATOR_SETTINGS_STORAGE_KEY, JSON.stringify(settings))
}

function loadGenerateHistory(): HistoryEntry[] {
  try {
    const stored = window.localStorage.getItem(HISTORY_STORAGE_KEY)
    if (!stored) return []
    const parsed = JSON.parse(stored)
    if (!Array.isArray(parsed)) return []
    const entries = parsed.filter((item) => item && typeof item === "object" && item.generation?.masterPath && Array.isArray(item.layers))
    return entries.map((item, index) => {
      const layers = item.layers.map((layer: GeneratedLayer) => {
        const provenance = provenanceForLayer(layer)
        return { ...layer, sourceLoopName: provenance.loopName, producers: provenance.producers, sourceOrigin: sourceOriginForLayer(layer) }
      })
      const fallbackNumber = Math.max(1, entries.length - index)
      const generationNumber = Number(item.generationNumber ?? item.generation?.generationNumber) || fallbackNumber
      const producers = Array.isArray(item.producers) && item.producers.length
        ? uniqueProducerNames(item.producers)
        : uniqueProducerNames(layers.flatMap((layer: GeneratedLayer) => provenanceForLayer(layer).producers))
      const primaryProducer = producers[0] || PRIMARY_PRODUCER
      const displayName = generationDisplayName(
        generationNumber,
        Number(item.bpm) || 140,
        String(item.keyName ?? item.generation?.targetKey ?? "A minor"),
        producers,
        primaryProducer,
      )
      return {
        ...item,
        recipe: "Generated",
        generationNumber,
        displayName,
        producers,
        generation: { ...item.generation, generationNumber, displayName, producers },
        layers,
      }
    })
  } catch {
    return []
  }
}

function loadGenerationSequence(): number {
  const stored = Number(window.localStorage.getItem(GENERATION_SEQUENCE_STORAGE_KEY))
  return Number.isFinite(stored) ? Math.max(0, Math.round(stored)) : 0
}

function loadExtractionHistory(): ExtractionHistoryEntry[] {
  return parseExtractionHistory(window.localStorage.getItem(EXTRACTION_HISTORY_STORAGE_KEY))
}

function loadConvertHistory(): ConvertHistoryEntry[] {
  return parseConvertHistory(window.localStorage.getItem(CONVERT_HISTORY_STORAGE_KEY))
}

function displayNameForGeneration(result: GenerateResult, layers: GeneratedLayer[], fallbackNumber = 1, primaryProducer = PRIMARY_PRODUCER): string {
  return generationDisplayName(
    result.generationNumber ?? fallbackNumber,
    result.targetBpm,
    result.targetKey,
    result.producers?.length ? result.producers : producersForLayers(layers, primaryProducer),
    primaryProducer,
  )
}

function sourceOriginForLayer(layer: Pick<GeneratedLayer, "sourceOrigin" | "sourcePath" | "sourceLoopId" | "libraryRoot">): "local" | "cloud" {
  if (layer.sourceOrigin === "cloud") return "cloud"
  const portableSourcePath = layer.sourcePath?.replaceAll("\\", "/")
  if (layer.sourceLoopId?.startsWith("cloud:") || layer.libraryRoot?.startsWith("cloud://") || portableSourcePath?.includes("/electron-prototype/cloud/audio/")) return "cloud"
  return "local"
}

function sourceOriginSummary(layers: GeneratedLayer[]): string {
  const cloud = layers.filter((layer) => sourceOriginForLayer(layer) === "cloud").length
  const local = Math.max(0, layers.length - cloud)
  if (cloud === 0) return `${local} local`
  if (local === 0) return `${cloud} cloud`
  return `${local} local + ${cloud} cloud`
}

function producerProfileFor(profiles: Record<string, ProducerProfileSettings>, producer: string): ProducerProfileSettings | undefined {
  return profiles[producer.toLowerCase()]
}

function ProducerAvatar({ producer, profile }: { producer: string; profile?: ProducerProfileSettings }) {
  const baseAvatarUrl = profile?.avatarUrl || (profile?.avatarPath ? window.stemSlicer?.mediaUrl(profile.avatarPath) : "")
  const avatarUrl = baseAvatarUrl && profile?.avatarRevision
    ? `${baseAvatarUrl}&revision=${encodeURIComponent(profile.avatarRevision)}`
    : baseAvatarUrl
  const [failedAvatarUrl, setFailedAvatarUrl] = useState("")
  return (
    <i title={producer}>
      {avatarUrl && failedAvatarUrl !== avatarUrl
        ? <img src={avatarUrl} alt="" onError={() => setFailedAvatarUrl(avatarUrl)} />
        : producerMonogram(producer)}
    </i>
  )
}

function ProducerAvatarStack({
  producers,
  profiles = loadCollaboratorSettings().profiles,
  toolbar = false,
}: {
  producers: string[]
  profiles?: Record<string, ProducerProfileSettings>
  toolbar?: boolean
}) {
  const visible = producers.length > 3 ? producers.slice(0, 2) : producers.slice(0, 3)
  const hiddenCount = Math.max(0, producers.length - visible.length)
  return (
    <span className={cn("producer-avatar-stack", toolbar && "is-toolbar")} aria-hidden="true">
      {visible.map((producer) => <ProducerAvatar key={producer} producer={producer} profile={producerProfileFor(profiles, producer)} />)}
      {hiddenCount > 0 ? <i className="is-overflow">+{hiddenCount}</i> : null}
    </span>
  )
}

function CollaboratorsDialog({
  producers,
  primaryProducer,
  cloudSourceCount,
  generationLayerCount,
  allowedProducers,
  allowedCreditCounts,
  requiredProducers,
  requiredContributionPercent,
  sourcePool,
  profiles,
  pinnedProducers,
  producerSortDirection,
  onAllowedProducersChange,
  onAllowAllProducers,
  onAllowedCreditCountsChange,
  onRequiredProducersChange,
  onRequiredContributionPercentChange,
  onSourcePoolChange,
  onPinnedProducersChange,
  onProducerSortDirectionChange,
  disabled,
}: {
  producers: LibraryProducerSummary[]
  primaryProducer: string
  cloudSourceCount: number
  generationLayerCount: number
  allowedProducers: string[]
  allowedCreditCounts: CollaboratorCreditCount[]
  requiredProducers: string[]
  requiredContributionPercent: number
  sourcePool: GenerationSourcePool
  profiles: Record<string, ProducerProfileSettings>
  pinnedProducers: string[]
  producerSortDirection: ProducerSortDirection
  onAllowedProducersChange: (producers: string[]) => void
  onAllowAllProducers: () => void
  onAllowedCreditCountsChange: (counts: CollaboratorCreditCount[]) => void
  onRequiredProducersChange: (producers: string[]) => void
  onRequiredContributionPercentChange: (percent: number) => void
  onSourcePoolChange: (sourcePool: GenerationSourcePool) => void
  onPinnedProducersChange: (producers: string[]) => void
  onProducerSortDirectionChange: (direction: ProducerSortDirection) => void
  disabled: boolean
}) {
  const allowedSet = new Set(allowedProducers.map((producer) => producer.toLowerCase()))
  const requiredSet = new Set(requiredProducers.map((producer) => producer.toLowerCase()))
  const pinnedSet = new Set(pinnedProducers.map((producer) => producer.toLowerCase()))
  const primaryProducerSummary = producers.find((producer) => producer.name.toLowerCase() === primaryProducer.toLowerCase())
  const selectableProducers = producers.filter((producer) => producer.name.toLowerCase() !== primaryProducer.toLowerCase())
  const anyCreditCount = allowedCreditCounts.includes(0)
  const maximumCreditCount = anyCreditCount
    ? null
    : Math.max(1, ...allowedCreditCounts) as FiniteCollaboratorCreditCount
  const selectedCreditOption: CollaboratorCreditCount = anyCreditCount ? 0 : maximumCreditCount ?? 1
  const collaborationEnabled = anyCreditCount || (maximumCreditCount ?? 1) > 1
  const maximumRequiredProducers = anyCreditCount ? Number.POSITIVE_INFINITY : Math.max(0, (maximumCreditCount ?? 1) - 1)
  const collaboratorSlotsFilled = Number.isFinite(maximumRequiredProducers)
    && requiredProducers.length >= maximumRequiredProducers
  const allowedExternalCount = selectableProducers.filter((producer) => allowedSet.has(producer.name.toLowerCase())).length
  const displayedProducers = collaboratorSlotsFilled
    ? selectableProducers.filter((producer) => allowedSet.has(producer.name.toLowerCase()))
    : selectableProducers
  const allSelectableAllowed = selectableProducers.length > 0
    && selectableProducers.every((producer) => allowedSet.has(producer.name.toLowerCase()))
  const toggleProducer = (producer: string, checked: boolean) => {
    if (producer.toLowerCase() === primaryProducer.toLowerCase()) return
    if (!checked && requiredSet.has(producer.toLowerCase())) {
      onRequiredProducersChange(requiredProducers.filter((item) => item.toLowerCase() !== producer.toLowerCase()))
    }
    onAllowedProducersChange(checked
      ? [...allowedProducers, producer]
      : allowedProducers.filter((item) => item.toLowerCase() !== producer.toLowerCase()))
  }
  const toggleRequired = (producer: string) => {
    const required = requiredSet.has(producer.toLowerCase())
    if (!required && maximumCreditCount === 1) {
      onAllowedCreditCountsChange(creditCountsThrough(2))
    }
    if (required) {
      onRequiredProducersChange(requiredProducers.filter((item) => item.toLowerCase() !== producer.toLowerCase()))
      return
    }
    const availableSlots = maximumCreditCount === 1 ? 1 : maximumRequiredProducers
    const nextRequired = [...requiredProducers.filter((item) => item.toLowerCase() !== producer.toLowerCase()), producer]
    onRequiredProducersChange(Number.isFinite(availableSlots) ? nextRequired.slice(-availableSlots) : nextRequired)
  }
  const setMaximumCreditCount = (count: CollaboratorCreditCount) => {
    if (count === 1 && requiredProducers.length > 0) {
      onRequiredProducersChange([])
      onAllowedProducersChange([primaryProducer])
    }
    if (count === 1 && sourcePool === "cloud-only") {
      onSourcePoolChange("mixed")
    }
    if (count > 1 && requiredProducers.length > count - 1) {
      onRequiredProducersChange(requiredProducers.slice(-(count - 1)))
    }
    onAllowedCreditCountsChange(count === 0 ? [0] : creditCountsThrough(count))
  }
  const togglePinned = (producer: string) => {
    const pinned = pinnedSet.has(producer.toLowerCase())
    onPinnedProducersChange(pinned
      ? pinnedProducers.filter((item) => item.toLowerCase() !== producer.toLowerCase())
      : [...pinnedProducers, producer])
  }
  const countOptions: Array<{ value: CollaboratorCreditCount; label: string; detail: string }> = [
    { value: 1, label: "Only me", detail: "No collaborator" },
    { value: 2, label: "+1 collaborator", detail: "Solo or duo" },
    { value: 3, label: "+2 collaborators", detail: "Up to three people" },
    { value: 0, label: "Any number", detail: "No credit limit" },
  ]
  const sourceOptions: Array<{ value: GenerationSourcePool; label: string; detail: string }> = [
    { value: "local-only", label: "This PC", detail: "Selected local libraries" },
    { value: "mixed", label: "PC + Cloud", detail: cloudSourceCount > 0 ? "Mix all enabled libraries" : "Cloud when connected" },
    { value: "cloud-only", label: "Cloud only", detail: cloudSourceCount > 0 ? `${cloudSourceCount} connected ${cloudSourceCount === 1 ? "friend" : "friends"}` : "Connect Cloud first" },
  ]
  const requiredLayerTarget = Math.min(
    generationLayerCount,
    Math.max(requiredProducers.length, Math.round(generationLayerCount * requiredContributionPercent / 100)),
  )
  const sourceSummary = sourcePool === "cloud-only"
    ? "Cloud only"
    : sourcePool === "local-only" || cloudSourceCount === 0
      ? "This PC"
      : "PC + Cloud"
  const minimumCreditCount = maximumCreditCount == null
    ? null
    : Math.min(maximumCreditCount, 1 + requiredProducers.length) as FiniteCollaboratorCreditCount
  const creditSummary = maximumCreditCount == null
    ? "any number of collaborators"
    : minimumCreditCount === maximumCreditCount
      ? `${maximumCreditCount === 1 ? "solo" : maximumCreditCount === 2 ? "duo" : "trio"} loops`
      : minimumCreditCount === 1 && maximumCreditCount === 3
        ? "solo, duo or trio loops"
        : `${minimumCreditCount === 1 ? "solo" : "duo"} or ${maximumCreditCount === 2 ? "duo" : "trio"} loops`
  const collaboratorSummary = requiredProducers.length > 0
    ? `${requiredProducers.length} always included`
    : allowedExternalCount > 0
      ? `${allowedExternalCount} optional ${allowedExternalCount === 1 ? "collaborator" : "collaborators"}`
      : "no external collaborator"
  const primaryLibrarySummary = primaryProducerSummary
    ? `${primaryProducerSummary.source === "cloud" ? "Cloud" : primaryProducerSummary.source === "mixed" ? "PC + Cloud" : "PC"} · ${formatCount(primaryProducerSummary.loopCount)} loops · ${formatCount(primaryProducerSummary.layerCount)} layers`
    : sourcePool === "cloud-only"
      ? "Cloud-only mode · your local library is not searched"
      : "No eligible local layers in this selection"
  const requiredNames = requiredProducers.join(", ")
  const remainingCollaboratorSlots = maximumCreditCount == null
    ? null
    : Math.max(0, maximumCreditCount - 1 - requiredProducers.length)
  const requiredPolicySummary = maximumCreditCount == null
    ? `${requiredNames} must appear. Any other allowed collaborators may join.`
    : maximumCreditCount === 2 && requiredProducers.length === 1
    ? `${requiredNames} is the only collaborator used in duo generations. Your solo loops remain available.`
    : remainingCollaboratorSlots === 0
      ? `${requiredNames} fills every collaborator slot. Other collaborators are excluded.`
      : `${requiredNames} must appear. ${remainingCollaboratorSlots} other allowed ${remainingCollaboratorSlots === 1 ? "collaborator" : "collaborators"} may join.`
  const toggleAllSelectable = () => {
    if (allSelectableAllowed) {
      onAllowedProducersChange(uniqueProducerCredits([primaryProducer, ...requiredProducers], primaryProducer))
      return
    }
    onAllowAllProducers()
  }

  return (
    <Dialog.Root>
      <Dialog.Trigger className="collaborators-trigger" disabled={disabled}>
        <UsersRound aria-hidden="true" /> Collaborators
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Backdrop className="dialog-backdrop" />
        <Dialog.Viewport className="dialog-viewport">
          <Dialog.Popup className="library-manager-dialog collaborators-dialog">
            <header className="library-manager-header">
              <div>
                <Dialog.Title>Collaborators</Dialog.Title>
                <Dialog.Description>Choose where layers come from and who may be credited on the final loop.</Dialog.Description>
              </div>
              <Dialog.Close className="dialog-close" aria-label="Close collaborators"><X /></Dialog.Close>
            </header>

            <div className="collaborators-content">
              <section className="collaborator-step" aria-labelledby="collaborator-source-pool-label">
                <div className="collaborator-step-heading">
                  <span aria-hidden="true">1</span>
                  <div>
                    <h3 id="collaborator-source-pool-label">Use audio from</h3>
                    <p>Choose the libraries Generate can search.</p>
                  </div>
                </div>
                <div className="collaborator-choice-grid" role="radiogroup" aria-labelledby="collaborator-source-pool-label">
                  {sourceOptions.map((option) => (
                    <label className={cn(sourcePool === option.value && "is-selected")} key={option.value}>
                      <input
                        type="radio"
                        name="generation-source-pool"
                        value={option.value}
                        checked={sourcePool === option.value}
                        disabled={option.value === "cloud-only" && cloudSourceCount === 0}
                        onChange={() => onSourcePoolChange(option.value)}
                      />
                      <strong>{option.label}</strong>
                      <small>{option.detail}</small>
                    </label>
                  ))}
                </div>
              </section>

              <section className="collaborator-step" aria-labelledby="collaborator-limit-label">
                <div className="collaborator-step-heading">
                    <span aria-hidden="true">2</span>
                    <div>
                      <h3 id="collaborator-limit-label">People on the final loop</h3>
                      <p>Choose a limit; “Always include” sets the minimum.</p>
                  </div>
                </div>
                <div className="collaborator-choice-grid is-team-size" role="radiogroup" aria-labelledby="collaborator-limit-label">
                  {countOptions.map((option) => (
                    <label className={cn(selectedCreditOption === option.value && "is-selected")} key={option.label}>
                      <input
                        type="radio"
                        name="maximum-generation-credits"
                        value={option.value}
                        checked={selectedCreditOption === option.value}
                        onChange={() => setMaximumCreditCount(option.value)}
                      />
                      <strong>{option.label}</strong>
                      <small>{option.detail}</small>
                    </label>
                  ))}
                </div>
              </section>

              <section className="collaborator-step collaborator-people" aria-labelledby="collaborator-people-label">
                <div className="collaborator-list-heading">
                  <div className="collaborator-step-heading">
                    <span aria-hidden="true">3</span>
                    <div>
                      <h3 id="collaborator-people-label">Who may contribute</h3>
                      <p>{collaborationEnabled ? `${allowedExternalCount} eligible · selected people may appear at random` : "Only me selected · no collaborator will be used"}</p>
                    </div>
                  </div>
                  {collaborationEnabled && !collaboratorSlotsFilled ? <div className="collaborator-list-tools">
                    {selectableProducers.length > 1 ? (
                      <button
                        type="button"
                        className="collaborator-sort-toggle"
                        onClick={() => onProducerSortDirectionChange(producerSortDirection === "desc" ? "asc" : "desc")}
                        aria-label={producerSortDirection === "desc" ? "Sort by fewest loops first" : "Sort by most loops first"}
                        title="Reverse loop-count order"
                      >
                        {producerSortDirection === "desc" ? <ArrowDownWideNarrow aria-hidden="true" /> : <ArrowUpNarrowWide aria-hidden="true" />}
                        {producerSortDirection === "desc" ? "Most first" : "Fewest first"}
                      </button>
                    ) : null}
                    {selectableProducers.length > 0 ? (
                      <button type="button" className="collaborator-select-all-toggle" onClick={toggleAllSelectable}>
                        {allSelectableAllowed ? <Square aria-hidden="true" /> : <CheckSquare2 aria-hidden="true" />}
                        {allSelectableAllowed ? (requiredProducers.length > 0 ? "Clear optional" : "Clear") : "Allow all"}
                      </button>
                    ) : null}
                  </div> : null}
                </div>

                <div className="collaborator-owner-row">
                  <ProducerAvatar producer={primaryProducer} profile={producerProfileFor(profiles, primaryProducer)} />
                  <span>
                    <strong>{primaryProducer}</strong>
                    <small>Primary producer · credited on every generated loop</small>
                    <small className="collaborator-owner-stats">{primaryLibrarySummary}</small>
                  </span>
                  <em>You</em>
                </div>

                {collaborationEnabled && requiredProducers.length > 0 ? (
                  <div className="collaborator-requirement">
                    <span>
                      <strong>Guaranteed share · {requiredNames}</strong>
                      <small>{requiredPolicySummary}</small>
                      <em>Target at least {requiredLayerTarget} of {generationLayerCount} layers</em>
                    </span>
                    <label>
                      <span className="sr-only">Target share from collaborators who are always included</span>
                      <input
                        type="range"
                        min="10"
                        max="100"
                        step="10"
                        value={requiredContributionPercent}
                        onChange={(event) => onRequiredContributionPercentChange(Number(event.target.value))}
                      />
                      <output>{requiredContributionPercent}%</output>
                    </label>
                  </div>
                ) : null}

                {!collaborationEnabled ? (
                  <p className="collaborator-empty">Choose “+1 collaborator” above to enable collaborators.</p>
                ) : <div className="collaborator-list" role="group" aria-label="Collaborators who may contribute">
                  {displayedProducers.map((producer, producerIndex) => {
                    const checked = allowedSet.has(producer.name.toLowerCase())
                    const required = requiredSet.has(producer.name.toLowerCase())
                    const pinned = pinnedSet.has(producer.name.toLowerCase())
                    const collaboratorInputId = `collaborator-${producerIndex}-${producer.name.replace(/[^a-z0-9_-]/gi, "-")}`
                    return (
                      <div className={cn("collaborator-row", checked && "is-selected")} key={producer.name}>
                        <label htmlFor={collaboratorInputId}>
                          <ProducerAvatar producer={producer.name} profile={producerProfileFor(profiles, producer.name)} />
                          <span>
                            <strong>{producer.name}</strong>
                            <small>{producer.source === "cloud" ? "Cloud · " : producer.source === "mixed" ? "PC + Cloud · " : "PC · "}{formatCount(producer.loopCount)} loops · {formatCount(producer.layerCount)} layers</small>
                          </span>
                        </label>
                        <button
                          type="button"
                          className={cn("producer-required-button", required && "is-active")}
                          disabled={
                            !checked
                            || (!required && maximumRequiredProducers > 0 && requiredProducers.length >= maximumRequiredProducers)
                          }
                          aria-pressed={required}
                          onClick={() => toggleRequired(producer.name)}
                          title={required ? `${producer.name} will be included every time` : `Always include ${producer.name}`}
                        >
                          Always include
                        </button>
                        <button
                          type="button"
                          className={cn("producer-pin-button", pinned && "is-active")}
                          aria-pressed={pinned}
                          aria-label={pinned ? `Unpin ${producer.name}` : `Pin ${producer.name}`}
                          title={pinned ? "Remove from pinned profiles" : "Keep at the top"}
                          onClick={() => togglePinned(producer.name)}
                        >
                          <Pin aria-hidden="true" />
                        </button>
                        <input
                          id={collaboratorInputId}
                          className="slicer-checkbox"
                          type="checkbox"
                          checked={checked}
                          disabled={!checked && collaboratorSlotsFilled}
                          aria-label={`Allow ${producer.name} to contribute`}
                          onChange={(event) => toggleProducer(producer.name, event.target.checked)}
                        />
                      </div>
                    )
                  })}
                  {displayedProducers.length === 0 ? (
                    <p className="collaborator-empty">No collaborator has eligible layers in these audio sources.</p>
                  ) : null}
                </div>}

              </section>
            </div>
            <footer className="library-manager-footer collaborator-footer">
              <p><Check aria-hidden="true" /><span><strong>{sourceSummary}</strong> · {creditSummary} · {collaboratorSummary}</span></p>
              <Dialog.Close className="dialog-done">Done</Dialog.Close>
            </footer>
          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

type PlaybackMode = "idle" | "solo" | "mix"

function usePlaybackClock(layers: GeneratedLayer[], stackPlayback: boolean) {
  const [playing, setPlaying] = useState(false)
  const [masterVolume, setMasterVolume] = useState(78)
  const [error, setError] = useState("")
  const [mode, setMode] = useState<PlaybackMode>(stackPlayback ? "mix" : "idle")
  const [soloId, setSoloId] = useState<string | null>(null)
  const [lastSoloId, setLastSoloId] = useState<string | null>(null)
  const [syncEnabled, setSyncEnabled] = useState(stackPlayback)
  const [loopEnabled, setLoopEnabled] = useState(true)
  const [mutedIds, setMutedIds] = useState<string[]>([])
  const [syncSoloId, setSyncSoloId] = useState<string | null>(null)
  const engineRef = useRef<SharedWebAudioEngine | null>(null)
  if (!engineRef.current) engineRef.current = new SharedWebAudioEngine()
  const playableIdsRef = useRef<string[]>([])
  const modeRef = useRef<PlaybackMode>(stackPlayback ? "mix" : "idle")
  const soloIdRef = useRef<string | null>(null)
  const lastSoloIdRef = useRef<string | null>(null)
  const syncEnabledRef = useRef(stackPlayback)
  const loopEnabledRef = useRef(true)
  const mutedIdsRef = useRef(new Set<string>())
  const syncSoloIdRef = useRef<string | null>(null)
  const playingRef = useRef(false)
  const progressStoreRef = useRef<PlaybackProgressStore | null>(null)
  if (!progressStoreRef.current) progressStoreRef.current = createPlaybackProgressStore()
  const progressSource = progressStoreRef.current
  const setProgress = progressSource.setProgress
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
      && stackPlayback
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
        gain: Math.max(0, Math.min(1.25, (layer?.volume ?? 100) / 100)),
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
  }, [commitLastSoloId, commitLoopEnabled, commitMode, commitMutedIds, commitPlaying, commitSyncEnabled, commitSyncSoloId, layerSourcesJson, stackPlayback])

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
  }, [commitLastSoloId, commitMode, commitMutedIds, commitPlaying, commitSyncEnabled, commitSyncSoloId, setProgress, stackPlayback])

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
  }, [commitPlaying, setProgress])

  const pausePlayback = useCallback(() => {
    const nextProgress = getCurrentProgress()
    playbackSessionRef.current += 1
    engineRef.current?.stop()
    positionRef.current = nextProgress
    setProgress(nextProgress)
    commitPlaying(false)
  }, [commitPlaying, getCurrentProgress, setProgress])

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
  }, [commitPlaying, getCurrentProgress, setProgress])

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
      setError("")
      return
    }
    await startPlayback(activeIds, startingMix ? 0 : positionRef.current)
  }, [commitMode, commitMutedIds, commitSyncSoloId, pausePlayback, setProgress, startPlayback])

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
  }, [commitLastSoloId, commitMode, commitMutedIds, commitSyncSoloId, pausePlayback, setProgress, startPlayback])

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
  }, [commitMode, commitMutedIds, commitPlaying, commitSyncEnabled, commitSyncSoloId, getCurrentProgress, setProgress, startPlayback])

  const setLayerMuted = useCallback((id: string, muted: boolean) => {
    if (!playableIdsRef.current.includes(id)) return
    const nextMutedIds = new Set(mutedIdsRef.current)
    if (muted) nextMutedIds.add(id)
    else nextMutedIds.delete(id)
    if (syncSoloIdRef.current === id) commitSyncSoloId(null)
    commitMutedIds(nextMutedIds)
  }, [commitMutedIds, commitSyncSoloId])

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
  }, [commitPlaying, setProgress])

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
    commitLoopEnabled(true)
    commitMutedIds(new Set())
    commitSyncSoloId(null)
    commitLastSoloId(null)
    commitMode(stackPlayback ? "mix" : "idle", null)
  }, [commitLastSoloId, commitLoopEnabled, commitMode, commitMutedIds, commitPlaying, commitSyncEnabled, commitSyncSoloId, setProgress, stackPlayback])

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
  }, [commitLastSoloId, commitMode, commitMutedIds, commitPlaying, getCurrentProgress, setProgress])

  const previewScrub = useCallback((id: string, nextProgress: number) => {
    const clampedProgress = Math.max(0, Math.min(nextProgress, 1))
    scrubTargetRef.current = { id, progress: clampedProgress }
    positionRef.current = clampedProgress
    setProgress(clampedProgress)
  }, [setProgress])

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
  }, [commitPlaying, setProgress, startPlayback])

  const mutedIdSet = useMemo(() => new Set(mutedIds), [mutedIds])
  return useMemo(() => ({
    playing,
    progressSource,
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
    setLayerMuted,
    stop,
    rewind,
    reset,
    masterVolume,
    setMasterVolume,
    error,
  }), [
    beginScrub,
    endScrub,
    error,
    lastSoloId,
    loopEnabled,
    masterVolume,
    mode,
    mutedIdSet,
    playing,
    previewScrub,
    progressSource,
    reset,
    setLayerMuted,
    soloId,
    stop,
    syncEnabled,
    syncSoloId,
    toggleLayer,
    toggleLoopMode,
    togglePrimary,
    toggleSynchronizedSolo,
    rewind,
  ])
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
  const cancelRequestedRef = useRef(false)

  useEffect(() => {
    const api = window.stemSlicer
    if (!api) return
    return api.onAudioJobEvent((event) => {
      if (event.kind !== kind) return
      if (jobIdRef.current && event.jobId !== jobIdRef.current) return
      if (!jobIdRef.current && !waitingRef.current) return
      jobIdRef.current = event.jobId
      if (event.type === "progress") {
        if (cancelRequestedRef.current) return
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
      cancelRequestedRef.current = false
      jobIdRef.current = ""
      if (event.type === "completed") {
        setState((current) => ({ ...current, busy: false, percent: 100, phase: "complete", message: event.message, result: event.result ?? null }))
      } else if (event.type === "cancelled") {
        setState((current) => ({ ...current, busy: false, phase: "cancelled", message: event.message, error: "" }))
      } else {
        setState((current) => ({ ...current, busy: false, phase: event.type, message: event.message, error: event.error ?? event.message }))
      }
    })
  }, [kind])

  const start = useCallback(async (request: AudioJobRequest, startingMessage = "Starting local engine…") => {
    const api = window.stemSlicer
    if (!api) throw new Error("Electron desktop API is unavailable.")
    waitingRef.current = true
    cancelRequestedRef.current = false
    jobIdRef.current = ""
    setState({
      ...EMPTY_AUDIO_JOB,
      busy: true,
      percent: kind === "generate" ? 1 : 0,
      phase: "starting",
      message: startingMessage,
    })
    try {
      const started = await api.startAudioJob(kind, request)
      jobIdRef.current = started.jobId
      setState((current) => ({ ...current, jobId: started.jobId }))
      if (cancelRequestedRef.current) await api.cancelAudioJob(started.jobId)
      return started.jobId
    } catch (error) {
      waitingRef.current = false
      cancelRequestedRef.current = false
      const message = error instanceof Error ? error.message : "The local engine could not start."
      setState({ ...EMPTY_AUDIO_JOB, error: message, message, phase: "failed" })
      throw error
    }
  }, [kind])

  const cancel = useCallback((message = "Cancelling…") => {
    if (!waitingRef.current || cancelRequestedRef.current) return
    cancelRequestedRef.current = true
    setState((current) => ({ ...current, busy: true, phase: "cancelling", message }))
    if (!jobIdRef.current) return
    void window.stemSlicer?.cancelAudioJob(jobIdRef.current).catch((error: unknown) => {
      waitingRef.current = false
      cancelRequestedRef.current = false
      const detail = error instanceof Error ? error.message : "The running job could not be cancelled."
      setState((current) => ({ ...current, busy: false, phase: "failed", message: detail, error: detail }))
    })
  }, [])

  return { ...state, start, cancel }
}

function AudioArtifactCard({ artifact, layer, playback }: { artifact: AudioArtifact; layer: GeneratedLayer; playback: PlaybackClock }) {
  const isCurrent = playback.mode === "solo" && playback.soloId === layer.id
  const playing = playback.playing && isCurrent
  const { scrubberRef, clockRef } = usePlaybackProgressElements(playback.progressSource, isCurrent, artifact.duration)
  const beginDrag = (event: React.DragEvent, path: string) => {
    event.preventDefault()
    window.stemSlicer?.startFileDrag(path)
  }
  const seekWaveformFromPointer = (event: React.PointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    if (bounds.width <= 0) return
    playback.previewScrub(layer.id, (event.clientX - bounds.left) / bounds.width)
  }

  return (
    <Card className={cn("layer-card layer-tone-convert convert-artifact-card", isCurrent && "is-audible")} title={playback.error || undefined}>
      <CardHeader>
        <div className="layer-heading">
          <CardTitle className="layer-category-static convert-category"><ArrowRightLeft aria-hidden="true" />Converted</CardTitle>
          <CardDescription className="truncate" title={artifact.name}>{artifact.displayName}</CardDescription>
        </div>
        <div className="convert-card-actions">
          <button type="button" className="layer-mini-action" draggable onDragStart={(event) => beginDrag(event, artifact.path)}><AudioLines aria-hidden="true" /><span>Audio</span></button>
          <button type="button" className="layer-mini-action location-button" onClick={() => void window.stemSlicer?.revealPath(artifact.path)}><FolderOpen aria-hidden="true" /><span>Location</span></button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="layer-transport">
          <button className="card-play-button" type="button" onClick={() => void playback.toggleLayer(layer.id)} aria-pressed={playing} aria-label={playing ? `Pause ${artifact.displayName}` : `Play ${artifact.displayName}`}>{playing ? <Pause aria-hidden="true" /> : <Play className="play-glyph" aria-hidden="true" />}</button>
          <div
            className="waveform-reader"
            onPointerDown={(event) => {
              if (event.button !== 0) return
              event.preventDefault()
              scrubberRef.current?.focus({ preventScroll: true })
              playback.beginScrub(layer.id)
              event.currentTarget.setPointerCapture(event.pointerId)
              seekWaveformFromPointer(event)
            }}
            onPointerMove={(event) => {
              if (event.currentTarget.hasPointerCapture(event.pointerId)) seekWaveformFromPointer(event)
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
            <Waveform progressSource={playback.progressSource} progressActive={isCurrent} label={`Waveform for ${artifact.displayName}`} bars={layer.bars} />
            <input ref={scrubberRef} className="waveform-scrubber" type="range" min="0" max="1000" defaultValue="0" aria-label={`Playback position for ${artifact.displayName}`} tabIndex={-1} onChange={(event) => playback.previewScrub(layer.id, Number(event.target.value) / 1000)} />
            <span ref={clockRef} className="wave-time tabular" aria-hidden="true">0.0 / {artifact.duration.toFixed(1)} s</span>
            <span className="wave-musical-info">
              <span className="wave-bpm tabular"><MetronomeIcon /> {artifact.bpm} BPM</span>
              <span className="wave-key"><Music2 aria-hidden="true" /> {artifact.key}</span>
            </span>
          </div>
        </div>
        {playback.error ? <p className="convert-playback-error" role="alert">{playback.error}</p> : null}
      </CardContent>
    </Card>
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
  optionLabel,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  options: string[]
  disabled?: boolean
  forceBelow?: boolean
  className?: string
  optionLabel?: (option: string) => string
}) {
  const labelId = `${id}-label`
  const items = options.map((option) => ({ label: optionLabel?.(option) ?? option, value: option }))
  return (
    <div className={cn("control-field", className)}>
      <span id={labelId}>{label}</span>
      <BaseSelect.Root
        id={id}
        items={items}
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
                    <BaseSelect.ItemText>{optionLabel?.(option) ?? option}</BaseSelect.ItemText>
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
  const [primaryProfile, setPrimaryProfile] = useState<ProducerProfileSettings | undefined>(() => (
    producerProfileFor(loadCollaboratorSettings().profiles, PRIMARY_PRODUCER)
  ))
  const [primaryProfileName, setPrimaryProfileName] = useState(PRIMARY_PRODUCER)
  const [applicationLogoUrl, setApplicationLogoUrl] = useState("")
  const [engineStatus, setEngineStatus] = useState<EngineStatus | null>(null)

  useEffect(() => {
    const api = window.stemSlicer
    if (!api) return
    let active = true
    const stopListening = api.onEngineStatus((status) => {
      if (active) setEngineStatus(status)
    })
    const refreshStatus = () => {
      void api.getEngineStatus()
        .then((status) => {
          if (active) setEngineStatus(status)
        })
        .catch(() => undefined)
    }
    const statusTimer = window.setInterval(refreshStatus, 1_500)
    void api.getEngineStatus()
      .then((status) => {
        if (!active) return
        setEngineStatus(status)
        setApplicationLogoUrl(api.mediaUrl(`${status.sourceRoot}/assets/app-icon.png`))
      })
      .catch(() => {
        if (active) setApplicationLogoUrl("")
      })
    return () => {
      active = false
      window.clearInterval(statusTimer)
      stopListening()
    }
  }, [])

  const retryEngines = useCallback(() => {
    const api = window.stemSlicer
    if (!api) return
    void api.retryEngine()
      .then(setEngineStatus)
      .catch(() => api.getEngineStatus().then(setEngineStatus).catch(() => undefined))
  }, [])

  const engineState = engineStatus?.state ?? "starting"
  const engineDisplayState = engineState === "idle" ? "starting" : engineState
  const engineLabel = engineDisplayState === "ready"
    ? "Engines ready"
    : engineDisplayState === "starting"
      ? "Starting engines…"
      : "Engine unavailable"
  const EngineIcon = engineDisplayState === "ready"
    ? Check
    : engineDisplayState === "starting"
      ? RefreshCw
      : AlertTriangle
  const componentLabels: Array<[keyof EngineStatus["components"], string]> = [
    ["musicalAnalysis", "Musical analysis"],
    ["midi", "MIDI"],
    ["categorization", "Categorization"],
  ]
  const componentStateLabel = (state: EngineComponentState) => ({
    idle: "Waiting",
    starting: "Starting…",
    ready: "Ready",
    failed: "Unavailable",
    unavailable: "Unavailable",
  })[state]

  useEffect(() => {
    const updateCloudProfile = (state?: CloudState) => {
      if (!state?.profile) return
      setPrimaryProfileName(state.profile.displayName)
      if (state.profile.avatarUrl) setPrimaryProfile({ avatarUrl: state.profile.avatarUrl })
    }
    void window.stemSlicer?.getCloudState().then(updateCloudProfile).catch(() => undefined)
    const listener = (event: Event) => updateCloudProfile((event as CustomEvent<CloudState>).detail)
    window.addEventListener(CLOUD_STATE_CHANGED_EVENT, listener)
    return () => window.removeEventListener(CLOUD_STATE_CHANGED_EVENT, listener)
  }, [])

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
          title={collapsed ? "Déplier la barre latérale" : "Slicer"}
        >
          {applicationLogoUrl
            ? <img src={applicationLogoUrl} alt="" />
            : <Layers3 aria-hidden="true" />}
        </button>
        <div className="sidebar-copy">
          <strong>Slicer</strong>
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

      <button
        type="button"
        className={cn("sidebar-profile app-no-drag", activeView === "profile" && "is-active")}
        onClick={() => onNavigate("profile")}
        aria-current={activeView === "profile" ? "page" : undefined}
        aria-label={`Open ${primaryProfileName} profile`}
        title={collapsed ? `${primaryProfileName} profile` : "Open profile"}
      >
        <span className="sidebar-profile-avatar"><ProducerAvatar producer={primaryProfileName} profile={primaryProfile} /></span>
        <span className="sidebar-copy">
          <strong>{primaryProfileName}</strong>
        </span>
        <Pencil aria-hidden="true" />
      </button>

      <div className="sidebar-footer">
        <Popover.Root>
          <Popover.Trigger
            className={cn("engine-status-trigger app-no-drag", `is-${engineDisplayState}`)}
            aria-label={`${engineLabel}. Open engine details.`}
            title={collapsed ? engineLabel : undefined}
          >
            <span className="engine-status-icon" aria-hidden="true">
              <EngineIcon />
            </span>
            <span className="sidebar-copy" role="status" aria-live="polite" aria-atomic="true">
              <strong>{engineLabel}</strong>
              <span>{engineDisplayState === "ready" ? "Local processing" : engineStatus?.message ?? "Preparing local processing"}</span>
            </span>
            <ChevronDown className="engine-status-chevron" aria-hidden="true" />
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Positioner className="engine-status-positioner" side="right" align="end" sideOffset={8}>
              <Popover.Popup className="engine-status-popover">
                <div className="engine-status-popover-header">
                  <Popover.Title>Engine status</Popover.Title>
                  <Popover.Description>{engineStatus?.message ?? "Preparing local processing."}</Popover.Description>
                </div>
                <ul className="engine-component-list">
                  {componentLabels.map(([component, label]) => {
                    const status = engineStatus?.components[component] ?? { state: "starting" as const, message: "Starting…" }
                    return (
                      <li key={component} className={cn("engine-component", `is-${status.state}`)} title={status.message}>
                        <span className="engine-component-indicator" aria-hidden="true" />
                        <span>{label}</span>
                        <strong>{componentStateLabel(status.state)}</strong>
                      </li>
                    )
                  })}
                </ul>
                {engineDisplayState === "failed" ? (
                  <Button type="button" variant="outline" size="sm" className="engine-retry" onClick={retryEngines}>
                    <RefreshCw aria-hidden="true" />
                    Retry engines
                  </Button>
                ) : null}
              </Popover.Popup>
            </Popover.Positioner>
          </Popover.Portal>
        </Popover.Root>
      </div>
    </aside>
  )
}

function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  titleActions,
}: {
  eyebrow: string
  title: string
  description: string
  actions?: React.ReactNode
  titleActions?: React.ReactNode
}) {
  return (
    <header className="page-header app-drag-region">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <div className="page-title-row">
          <h1>{title}</h1>
          {titleActions ? <div className="page-title-actions app-no-drag">{titleActions}</div> : null}
        </div>
        <p className="page-description">{description}</p>
      </div>
      {actions ? <div className="page-actions app-no-drag">{actions}</div> : null}
    </header>
  )
}

function WrongLayerAction({
  layer,
  active,
  activeIssueType,
  disabled,
  onReportIssue,
  onCorrectCategory,
  onRestore,
}: {
  layer: GeneratedLayer
  active: boolean
  activeIssueType?: LibraryIssueType
  disabled: boolean
  onReportIssue: (issueType: LibraryIssueType) => void | Promise<void>
  onCorrectCategory: (category: string) => void | Promise<void>
  onRestore: () => void | Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [quarantineReason, setQuarantineReason] = useState<LibraryIssueType | null>(null)
  const [wrongCategory, setWrongCategory] = useState(false)
  const [category, setCategory] = useState(layer.category)

  const run = async () => {
    setSaving(true)
    setError("")
    try {
      if (active) await onRestore()
      else {
        if (wrongCategory) await onCorrectCategory(category)
        if (quarantineReason) await onReportIssue(quarantineReason)
      }
      setOpen(false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to save this correction.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen)
        setError("")
        if (nextOpen) {
          setQuarantineReason(null)
          setWrongCategory(false)
          setCategory(layer.category)
        }
      }}
    >
      <Dialog.Trigger
        className={cn("layer-mini-action layer-wrong-action", active && "is-active")}
        disabled={disabled}
        aria-pressed={active}
        aria-label={active ? `La loop source de ${layer.role} est exclue` : `Signaler une erreur sur ${layer.role}`}
        title={active
          ? `${activeIssueType === "wrong-slice" ? "Wrong slice" : "Wrong key"} — source loop quarantined`
          : "Wrong — report a slice, key or category error"}
      >
        <CircleAlert aria-hidden="true" /><span>Wrong</span>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Backdrop className="dialog-backdrop" />
        <Dialog.Viewport className="dialog-viewport">
          <Dialog.Popup className="confirmation-dialog wrong-layer-dialog">
            <span className="confirmation-dialog-icon"><CircleAlert aria-hidden="true" /></span>
            <Dialog.Title>{active ? "This source loop is quarantined" : "What is wrong with this layer?"}</Dialog.Title>
            <Dialog.Description>{active
              ? `${layer.sourceFile ?? layer.file} is currently excluded from future generations because of a ${activeIssueType === "wrong-slice" ? "slice" : "key"} issue.`
              : "Select the incorrect information. Category corrections are saved immediately; a wrong slice or key quarantines the complete source loop."}</Dialog.Description>
            {!active ? (
              <div className="wrong-layer-options">
                <label className={cn("wrong-layer-option", quarantineReason === "wrong-key" && "is-selected")}>
                  <input
                    type="checkbox"
                    checked={quarantineReason === "wrong-key"}
                    onChange={(event) => setQuarantineReason(event.target.checked ? "wrong-key" : null)}
                  />
                  <span><strong>Wrong key</strong><small>Exclude every indexed layer from this source loop.</small></span>
                </label>
                <label className={cn("wrong-layer-option", quarantineReason === "wrong-slice" && "is-selected")}>
                  <input
                    type="checkbox"
                    checked={quarantineReason === "wrong-slice"}
                    onChange={(event) => setQuarantineReason(event.target.checked ? "wrong-slice" : null)}
                  />
                  <span><strong>Wrong slice</strong><small>Quarantine the complete source loop and add it to extraction review.</small></span>
                </label>
                <label className={cn("wrong-layer-option", wrongCategory && "is-selected")}>
                  <input type="checkbox" checked={wrongCategory} onChange={(event) => setWrongCategory(event.target.checked)} />
                  <span><strong>Wrong category</strong><small>Choose the category that should drive future generations.</small></span>
                </label>
                {wrongCategory ? <Select id={`wrong-category-${layer.id}`} label="Correct category" value={category} onChange={setCategory} options={GENERATE_CATEGORY_OPTIONS} forceBelow /> : null}
                {quarantineReason ? <p className="wrong-layer-warning"><AlertTriangle aria-hidden="true" /> Every matching card from this source loop will stop and disappear after confirmation.</p> : null}
              </div>
            ) : null}
            {error ? <p className="dialog-inline-error" role="alert">{error}</p> : null}
            <footer>
              <Dialog.Close className="dialog-cancel" disabled={saving}>Cancel</Dialog.Close>
              <Button
                variant={active || quarantineReason ? "destructive" : "default"}
                disabled={saving || (!active && !quarantineReason && (!wrongCategory || category === layer.category))}
                onClick={() => void run()}
              >
                {active ? <Check aria-hidden="true" /> : <CircleAlert aria-hidden="true" />}
                {saving ? "Saving…" : active ? "Restore source loop" : quarantineReason ? "Save and quarantine loop" : "Save category"}
              </Button>
            </footer>
          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function usePlaybackProgressElements(
  progressSource: PlaybackProgressSource,
  progressActive: boolean,
  duration: number,
) {
  const scrubberRef = useRef<HTMLInputElement>(null)
  const clockRef = useRef<HTMLSpanElement>(null)
  const lastClockTextRef = useRef("")

  useEffect(() => {
    const applyProgress = () => {
      const progress = progressActive ? progressSource.getProgress() : 0
      if (scrubberRef.current) scrubberRef.current.value = String(Math.round(progress * 1000))
      const clockText = `${(progress * duration).toFixed(1)} / ${duration.toFixed(1)} s`
      if (clockRef.current && clockText !== lastClockTextRef.current) {
        clockRef.current.textContent = clockText
        lastClockTextRef.current = clockText
      }
    }

    applyProgress()
    return progressSource.subscribe(applyProgress)
  }, [duration, progressActive, progressSource])

  return { scrubberRef, clockRef }
}

function LayerCard({
  layer,
  primaryProducer = PRIMARY_PRODUCER,
  progressSource,
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
  onToggleLibraryIssue,
  onCorrectCategory,
  onToggleLock,
  onRemove,
  onExport,
  categoryOptions,
  canRemove,
  updating = false,
  libraryIssueActive = false,
  libraryIssueType,
  variant = "generate",
}: {
  layer: GeneratedLayer
  primaryProducer?: string
  progressSource: PlaybackProgressSource
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
  onToggleLibraryIssue?: (issueType?: LibraryIssueType) => void | Promise<void>
  onCorrectCategory?: (category: string) => void | Promise<void>
  onToggleLock?: () => void
  onRemove?: () => void
  onExport?: () => void
  categoryOptions?: string[]
  canRemove?: boolean
  updating?: boolean
  libraryIssueActive?: boolean
  libraryIssueType?: LibraryIssueType
  variant?: "generate" | "extract"
}) {
  const isGenerateCard = variant === "generate"
  const provenance = layer.identity
    ? provenanceForLayer(layer, primaryProducer)
    : { loopName: "Ready to generate", producers: [primaryProducer] }
  const sourceOrigin = layer.identity || layer.sourcePath ? sourceOriginForLayer(layer) : null
  const progressActive = mixActive || isAudible
  const { scrubberRef: waveformScrubberRef, clockRef: waveformClockRef } = usePlaybackProgressElements(
    progressSource,
    progressActive,
    layer.duration,
  )
  const seekWaveformFromPointer = (event: React.PointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    if (bounds.width <= 0) return
    onSeek((event.clientX - bounds.left) / bounds.width)
  }
  const beginDrag = (event: React.DragEvent, path: string | undefined) => {
    if (!path) return
    event.preventDefault()
    onExport?.()
    window.stemSlicer?.startFileDrag(path)
  }

  return (
    <Card className={cn("layer-card", isGenerateCard ? "layer-tone-spectral" : "layer-tone-extract", !isGenerateCard && "is-extract", isAudible && "is-audible", isMuted && "is-muted", isSyncSolo && "is-sync-solo", libraryIssueActive && "has-key-issue")} aria-label={`${layer.category}, ${provenance.loopName}, ${provenance.producers.join(", ")}`}>
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
          {isGenerateCard ? (
            <div className="layer-provenance">
              <strong className="truncate" title={stripAudioExtension(layer.sourceFile ?? layer.file)}>{provenance.loopName}</strong>
              <span className="layer-producer-credit" aria-label={`Producers: ${provenance.producers.join(", ")}`}>
                <ProducerAvatarStack producers={provenance.producers} />
                <span className="truncate">{provenance.producers.join(", ")}</span>
                {sourceOrigin ? <SourceOriginIcon origin={sourceOrigin} /> : null}
              </span>
            </div>
          ) : (
            <CardDescription className="truncate" title={layer.file}>{stripAudioExtension(layer.file)}</CardDescription>
          )}
        </div>
        {isGenerateCard ? <div className="layer-card-actions">
          <WrongLayerAction
            layer={layer}
            active={libraryIssueActive}
            activeIssueType={libraryIssueType}
            disabled={!layer.identity || !layer.sourcePath || !layer.sourceLoopId || !layer.libraryRoot || updating}
            onReportIssue={(issueType) => onToggleLibraryIssue?.(issueType)}
            onCorrectCategory={(category) => onCorrectCategory?.(category)}
            onRestore={() => onToggleLibraryIssue?.()}
          />
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
              progressSource={progressSource}
              progressActive={progressActive}
              label={`Forme d’onde de ${layer.role}`}
              bars={layer.bars}
            />
            <input
              ref={waveformScrubberRef}
              className="waveform-scrubber"
              type="range"
              min="0"
              max="1000"
              defaultValue="0"
              aria-label={`Position de lecture de ${layer.role}`}
              tabIndex={-1}
              onChange={(event) => onSeek(Number(event.target.value) / 1000)}
            />
            <span ref={waveformClockRef} className="wave-time tabular" aria-hidden="true">0.0 / {layer.duration.toFixed(1)} s</span>
            <span className="wave-musical-info">
              <span className="wave-bpm tabular"><MetronomeIcon /> {layer.bpm} BPM</span>
              <span className="wave-key"><Music2 aria-hidden="true" /> {layer.keyName}</span>
            </span>
          </div>
        </div>

        <div className="layer-controls">
          <label className="layer-volume-control">
            <Volume2 aria-hidden="true" />
            <span className="volume-range">
              <input
                type="range"
                min="0"
                max="125"
                value={layer.volume}
                aria-label={`Volume de ${layer.role}`}
                onChange={(event) => onChange({ ...layer, volume: Number(event.target.value) })}
              />
              <span className="volume-unity-marker" aria-hidden="true" />
            </span>
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
            title={layer.midiPath ? "Drag MIDI or view its location" : "MIDI unavailable"}
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
            title={layer.path ? "Drag audio or view its location" : "Render this layer before exporting it"}
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

function sourceLoopKey(libraryRoot: string | undefined, sourceLoopId: string | undefined) {
  return libraryRoot && sourceLoopId ? `${libraryRoot}\0${sourceLoopId}` : ""
}

function libraryScanErrorMessage(error: string): string {
  const validationPrefix = "InvalidLayerLibraryFolderError:"
  return error.startsWith(validationPrefix)
    ? error.slice(validationPrefix.length).trim()
    : `Scan failed · ${error}`
}

interface PendingLibraryScan {
  root: string
  name: string
  state: "checking" | "scanning" | "cancelling" | "finishing" | "cancelled" | "failed"
  percent: number
}

function pendingLibraryScanLabel(scan: PendingLibraryScan, alreadyIndexed = false): string {
  if (scan.state === "checking") return "Checking…"
  if (scan.state === "scanning") return `Scanning ${scan.percent}%`
  if (scan.state === "cancelling") return "Cancelling…"
  if (scan.state === "finishing") return "Finishing…"
  if (scan.state === "cancelled") return "Cancelled"
  return alreadyIndexed ? "Scan failed" : "Not added"
}

function LibraryManager({
  library,
  selectedPaths,
  selectedLayerCount,
  selectedCategoryCount,
  selectionMessage,
  selectionError,
  scanBusy,
  pendingScan,
  onSelectedPathsChange,
  onAddFolder,
  onCancelScan,
  onDismissPendingScan,
  onRemoveFolder,
}: {
  library: LibraryOverview
  selectedPaths: string[]
  selectedLayerCount: number
  selectedCategoryCount: number
  selectionMessage: string
  onSelectedPathsChange: React.Dispatch<React.SetStateAction<string[]>>
  selectionError: boolean
  scanBusy: boolean
  pendingScan: PendingLibraryScan | null
  onAddFolder: (root?: string) => Promise<void>
  onCancelScan: () => void
  onDismissPendingScan: () => void
  onRemoveFolder: (libraryRoot: string) => Promise<void>
}) {
  const selectedSet = new Set(selectedPaths)
  const pendingRootAlreadyIndexed = Boolean(
    pendingScan && library.roots.some((root) => root.path === pendingScan.root),
  )
  const [removingPath, setRemovingPath] = useState<string | null>(null)
  const [dropActive, setDropActive] = useState(false)
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
          <Dialog.Popup
            className={cn("library-manager-dialog", dropActive && "is-drop-active")}
            aria-busy={scanBusy}
            onDragEnter={(event) => {
              event.preventDefault()
              if (!scanBusy) setDropActive(true)
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropActive(false)
            }}
            onDrop={(event) => {
              const root = pathFromDrop(event)
              setDropActive(false)
              if (root && !scanBusy) void onAddFolder(root)
            }}
          >
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
              {pendingScan && !pendingRootAlreadyIndexed ? (
                <div className={cn("library-manager-row", "is-pending", pendingScan.state === "failed" && "is-error")}>
                  <div className="library-manager-pending-card">
                    <RefreshCw aria-hidden="true" />
                    <span>
                      <strong>{pendingScan.name}</strong>
                      <small title={pendingScan.root}>{pendingScan.root}</small>
                    </span>
                    <output className="library-scan-status tabular">
                      {pendingLibraryScanLabel(pendingScan)}
                    </output>
                  </div>
                  <button type="button" className="library-reveal" aria-label={`Location of ${pendingScan.name}`} title="Location" onClick={() => window.stemSlicer?.revealPath(pendingScan.root)}>
                    <FolderOpen aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="library-remove"
                    aria-label={`Dismiss ${pendingScan.name} scan status`}
                    title={scanBusy ? "Cancel the scan before dismissing it" : "Dismiss scan status"}
                    disabled={scanBusy}
                    onClick={onDismissPendingScan}
                  >
                    <X aria-hidden="true" />
                  </button>
                </div>
              ) : null}
              {library.roots.length > 0 ? library.roots.map((root) => {
                const checked = selectedSet.has(root.path)
                const rootPendingScan = pendingScan?.root === root.path ? pendingScan : null
                return (
                  <div className={cn("library-manager-row", checked && "is-selected", rootPendingScan && "has-scan-status", rootPendingScan?.state === "failed" && "is-error")} key={root.path}>
                    <label>
                      <input type="checkbox" checked={checked} disabled={scanBusy && Boolean(rootPendingScan)} onChange={(event) => toggleLibrary(root.path, event.target.checked)} />
                      <span>
                        <strong>{root.name}</strong>
                        <small title={root.path}>{root.path}</small>
                      </span>
                      <output className={cn("tabular", rootPendingScan && "library-scan-status")}>
                        {rootPendingScan ? pendingLibraryScanLabel(rootPendingScan, true) : formatCount(root.layerCount)}
                      </output>
                    </label>
                    <button type="button" className="library-reveal" aria-label={`Location of ${root.name}`} title="Location" onClick={() => window.stemSlicer?.revealPath(root.path)}>
                      <FolderOpen aria-hidden="true" />
                    </button>
                    {rootPendingScan && !scanBusy ? (
                      <button type="button" className="library-remove" aria-label={`Dismiss ${root.name} scan status`} title="Dismiss scan status" onClick={onDismissPendingScan}>
                        <X aria-hidden="true" />
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="library-remove"
                        aria-label={`Retirer ${root.name} du catalogue`}
                        title={scanBusy ? "Wait for the current scan to finish" : "Retirer uniquement l’index — le dossier audio reste intact"}
                        disabled={scanBusy || removingPath === root.path}
                        onClick={() => void removeFolder(root.path)}
                      >
                        <Trash2 aria-hidden="true" />
                      </button>
                    )}
                  </div>
                )
              }) : pendingScan && !pendingRootAlreadyIndexed ? null : <p className="library-manager-empty">No indexed library is available yet.</p>}
            </div>

            <p
              className={cn("library-manager-notice", selectionError && "is-error")}
              role={selectionError ? "alert" : "status"}
              aria-live={selectionError ? "assertive" : "polite"}
              aria-atomic="true"
            >
              <FolderOpen aria-hidden="true" />
              {selectionMessage || "Drop a folder anywhere in this window, or choose Add folder."}
            </p>

            <footer className="library-manager-footer">
              {scanBusy ? (
                <Button
                  variant="outline"
                  className="cancel-library-scan"
                  disabled={pendingScan?.state === "cancelling"}
                  onClick={onCancelScan}
                >
                  <X aria-hidden="true" />
                  {pendingScan?.state === "cancelling" ? "Cancelling…" : "Cancel scan"}
                </Button>
              ) : (
                <Button variant="outline" onClick={() => void onAddFolder()}><Plus aria-hidden="true" /> Add folder</Button>
              )}
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
  onMarkCurrentGenerationExported,
  keyIssues,
  onReportKeyIssue,
  onSetKeyIssueActive,
  onLibraryRefresh,
  onCategoryCorrectionsRefresh,
  nextGenerationNumber,
  playback,
}: {
  library: LibraryOverview
  layers: GeneratedLayer[]
  setLayers: React.Dispatch<React.SetStateAction<GeneratedLayer[]>>
  currentGenerationResult: GenerateResult | null
  setCurrentGenerationResult: React.Dispatch<React.SetStateAction<GenerateResult | null>>
  onAddHistory: (entry: HistoryEntry) => void
  onUpdateHistory: (generation: GenerateResult, layers: GeneratedLayer[]) => void
  onMarkCurrentGenerationExported: (generation: GenerateResult) => void
  keyIssues: KeyIssueReport[]
  onReportKeyIssue: (request: ReportKeyIssueRequest) => Promise<void>
  onSetKeyIssueActive: (issueId: string, active: boolean) => Promise<void>
  onLibraryRefresh: () => Promise<void>
  onCategoryCorrectionsRefresh: () => Promise<void>
  nextGenerationNumber: number
  playback: PlaybackClock
}) {
  const initialCollaboratorSettings = useMemo(loadCollaboratorSettings, [])
  const [bpm, setBpm] = useState(140)
  const [keyName, setKeyName] = useState("F minor")
  const [randomKeyEnabled, setRandomKeyEnabled] = useState(true)
  const [status, setStatus] = useState("Local Generate engine ready")
  const [selectionMessage, setSelectionMessage] = useState("")
  const [pendingLibraryRoot, setPendingLibraryRoot] = useState("")
  const [currentSeed, setCurrentSeed] = useState<number | null>(null)
  const [previousSeed, setPreviousSeed] = useState<number | null>(null)
  const [recipeDirty, setRecipeDirty] = useState(false)
  const [selectedLibraryPaths, setSelectedLibraryPaths] = useState<string[]>([])
  const [libraryProducers, setLibraryProducers] = useState<LibraryProducerSummary[]>([])
  const [localSelectionSummary, setLocalSelectionSummary] = useState<LibrarySelectionSummary>({ layerCount: 0, loopCount: 0, categories: [] })
  const [selectionSummaryLoading, setSelectionSummaryLoading] = useState(false)
  const [cloudState, setCloudState] = useState<CloudState>({ configured: false, projectUrl: "", authenticated: false, connections: [], libraries: [] })
  const primaryProducer = cloudState.profile?.displayName.trim() || PRIMARY_PRODUCER
  const [configuredAllowedProducers, setConfiguredAllowedProducers] = useState<string[] | null>(initialCollaboratorSettings.allowedProducers)
  const [allowedCreditCounts, setAllowedCreditCounts] = useState<CollaboratorCreditCount[]>(initialCollaboratorSettings.allowedCreditCounts)
  const [requiredProducers, setRequiredProducers] = useState(initialCollaboratorSettings.requiredProducers)
  const [requiredContributionPercent, setRequiredContributionPercent] = useState(initialCollaboratorSettings.requiredContributionPercent)
  const [sourcePool, setSourcePool] = useState<GenerationSourcePool>(initialCollaboratorSettings.sourcePool)
  const [pinnedProducers, setPinnedProducers] = useState(initialCollaboratorSettings.pinnedProducers)
  const [producerSortDirection, setProducerSortDirection] = useState<ProducerSortDirection>(initialCollaboratorSettings.producerSortDirection)
  const [producerProfiles, setProducerProfiles] = useState<Record<string, ProducerProfileSettings>>(initialCollaboratorSettings.profiles)
  const knownLibraryPathsRef = useRef<Set<string>>(new Set())
  const handledGenerationRef = useRef("")
  const handledUpdateRef = useRef("")
  const handledScanRef = useRef("")
  const currentGenerationDirectoryRef = useRef("")
  const generateJob = useAudioJob("generate")
  const generateUpdateJob = useAudioJob("generate-update")
  const libraryScanJob = useAudioJob("library-scan")
  const pendingLibraryScan: PendingLibraryScan | null = pendingLibraryRoot
    ? {
        root: pendingLibraryRoot,
        name: basename(pendingLibraryRoot),
        state: libraryScanJob.phase === "cancelling"
          ? "cancelling"
          : libraryScanJob.busy && (libraryScanJob.phase === "starting" || libraryScanJob.phase === "checking")
            ? "checking"
            : libraryScanJob.busy
              ? "scanning"
              : libraryScanJob.phase === "complete"
                ? "finishing"
              : libraryScanJob.phase === "cancelled"
                ? "cancelled"
                : "failed",
        percent: libraryScanJob.percent,
      }
    : null
  const generationResult = generateJob.result as GenerateResult | null
  const generationUpdateResult = generateUpdateJob.result as GenerateResult | null
  const mixActive = playback.mode === "mix"
  const activeKeyIssues = keyIssues.filter((issue) => issue.active)
  const activeKeyIssueBySource = new Map(
    activeKeyIssues.map((issue) => [sourceLoopKey(issue.libraryRoot, issue.sourceLoopId), issue]),
  )
  const enabledCloudLibraries = cloudState.libraries.filter((item) => !item.own && item.status === "ready" && item.enabledForGenerate)
  const hasEnabledCloudLibrary = enabledCloudLibraries.length > 0
  const cloudSourceCount = new Set(enabledCloudLibraries.map((item) => item.owner.displayName.toLowerCase())).size
  const producerIdentities = useMemo<ProducerIdentity[]>(() => {
    const profilesById = new Map<string, CloudProfile>()
    const profiles = [
      cloudState.profile,
      ...cloudState.connections.filter((connection) => connection.status === "accepted").map((connection) => connection.profile),
      ...cloudState.libraries.map((item) => item.owner),
    ].filter((profile): profile is CloudProfile => Boolean(profile))
    for (const profile of profiles) profilesById.set(profile.id, profile)
    return [...profilesById.values()].map((profile) => ({
      canonicalName: profile.displayName,
      aliases: [profile.handle, ...profile.aliases],
    }))
  }, [cloudState.connections, cloudState.libraries, cloudState.profile])
  const producerIdentityResolver = useMemo(
    () => createProducerIdentityResolver(producerIdentities, primaryProducer),
    [primaryProducer, producerIdentities],
  )
  const availableProducers = useMemo(() => {
    const byName = new Map<string, LibraryProducerSummary>()
    for (const producer of libraryProducers) {
      byName.set(producer.name.toLowerCase(), {
        ...producer,
        loopCountsByCreditCount: { ...producer.loopCountsByCreditCount },
        layerCountsByCreditCount: { ...producer.layerCountsByCreditCount },
        libraryRoots: [...producer.libraryRoots],
        source: producer.source ?? "local",
        localLoopCount: producer.loopCount,
        localLayerCount: producer.layerCount,
        localLoopCountsByCreditCount: { ...producer.loopCountsByCreditCount },
        localLayerCountsByCreditCount: { ...producer.layerCountsByCreditCount },
        cloudLoopCount: 0,
        cloudLayerCount: 0,
        cloudLoopCountsByCreditCount: {},
        cloudLayerCountsByCreditCount: {},
      })
    }
    for (const item of cloudState.libraries.filter((library) => !library.own && library.status === "ready" && library.enabledForGenerate)) {
      const key = item.owner.displayName.toLowerCase()
      const existing = byName.get(key)
      if (existing) {
        existing.loopCount += item.loopCount
        existing.layerCount += item.layerCount
        existing.loopCountsByCreditCount["2"] = (existing.loopCountsByCreditCount["2"] ?? 0) + item.loopCount
        existing.layerCountsByCreditCount["2"] = (existing.layerCountsByCreditCount["2"] ?? 0) + item.layerCount
        existing.libraryRoots.push(`cloud://${item.id}`)
        existing.source = existing.source === "cloud" ? "cloud" : "mixed"
        existing.cloudLoopCount = (existing.cloudLoopCount ?? 0) + item.loopCount
        existing.cloudLayerCount = (existing.cloudLayerCount ?? 0) + item.layerCount
        existing.cloudLoopCountsByCreditCount = { ...(existing.cloudLoopCountsByCreditCount ?? {}), "2": (existing.cloudLoopCountsByCreditCount?.["2"] ?? 0) + item.loopCount }
        existing.cloudLayerCountsByCreditCount = { ...(existing.cloudLayerCountsByCreditCount ?? {}), "2": (existing.cloudLayerCountsByCreditCount?.["2"] ?? 0) + item.layerCount }
      } else {
        byName.set(key, {
          name: item.owner.displayName,
          loopCount: item.loopCount,
          layerCount: item.layerCount,
          loopCountsByCreditCount: { "2": item.loopCount },
          layerCountsByCreditCount: { "2": item.layerCount },
          libraryRoots: [`cloud://${item.id}`],
          source: "cloud",
          localLoopCount: 0,
          localLayerCount: 0,
          localLoopCountsByCreditCount: {},
          localLayerCountsByCreditCount: {},
          cloudLoopCount: item.loopCount,
          cloudLayerCount: item.layerCount,
          cloudLoopCountsByCreditCount: { "2": item.loopCount },
          cloudLayerCountsByCreditCount: { "2": item.layerCount },
        })
      }
    }
    return [...byName.values()]
  }, [cloudState.libraries, libraryProducers])
  const producerOptions = useMemo(() => {
    const activeLibraryRoots = new Set(selectedLibraryPaths)
    const relevant = availableProducers.filter((producer) => {
      if (producer.name.toLowerCase() === primaryProducer.toLowerCase()) return sourcePool !== "cloud-only"
      if (sourcePool === "cloud-only") return (producer.cloudLayerCount ?? 0) > 0
      if (sourcePool === "local-only") {
        return (producer.localLayerCount ?? 0) > 0 && (
          selectedLibraryPaths.length === 0
          || producer.libraryRoots.some((root) => !root.startsWith("cloud://") && activeLibraryRoots.has(root))
        )
      }
      return selectedLibraryPaths.length === 0
        || producer.libraryRoots.some((root) => root.startsWith("cloud://") || activeLibraryRoots.has(root))
    })
    const withPrimary = sourcePool === "cloud-only"
      ? relevant
      : relevant.some((producer) => producer.name.toLowerCase() === primaryProducer.toLowerCase())
      ? relevant
      : [{ name: primaryProducer, layerCount: 0, loopCount: 0, loopCountsByCreditCount: {}, layerCountsByCreditCount: {}, libraryRoots: selectedLibraryPaths }, ...relevant]
    const matchingMode = withPrimary
      .map((producer) => {
        const loopCounts = sourcePool === "cloud-only"
          ? producer.cloudLoopCountsByCreditCount ?? {}
          : sourcePool === "local-only"
            ? producer.localLoopCountsByCreditCount ?? {}
            : producer.loopCountsByCreditCount
        const layerCounts = sourcePool === "cloud-only"
          ? producer.cloudLayerCountsByCreditCount ?? {}
          : sourcePool === "local-only"
            ? producer.localLayerCountsByCreditCount ?? {}
            : producer.layerCountsByCreditCount
        return {
          ...producer,
          source: sourcePool === "cloud-only" ? "cloud" as const : sourcePool === "local-only" ? "local" as const : producer.source,
          loopCount: allowedCreditCounts.includes(0)
            ? Object.values(loopCounts).reduce((sum, count) => sum + count, 0)
            : allowedCreditCounts.reduce<number>((sum, count) => sum + (loopCounts[String(count)] ?? 0), 0),
          layerCount: allowedCreditCounts.includes(0)
            ? Object.values(layerCounts).reduce((sum, count) => sum + count, 0)
            : allowedCreditCounts.reduce<number>((sum, count) => sum + (layerCounts[String(count)] ?? 0), 0),
        }
      })
      .filter((producer) => (
        producer.name.toLowerCase() === primaryProducer.toLowerCase()
        || producer.loopCount > 0
      ))
    const pinned = new Set(pinnedProducers.map((producer) => producerIdentityResolver.canonicalize(producer).toLowerCase()))
    return matchingMode.sort((left, right) => {
      const leftPinned = pinned.has(left.name.toLowerCase()) ? 1 : 0
      const rightPinned = pinned.has(right.name.toLowerCase()) ? 1 : 0
      const countOrder = producerSortDirection === "desc"
        ? right.loopCount - left.loopCount
        : left.loopCount - right.loopCount
      return rightPinned - leftPinned || countOrder || left.name.localeCompare(right.name)
    })
  }, [allowedCreditCounts, availableProducers, pinnedProducers, primaryProducer, producerIdentityResolver, producerSortDirection, selectedLibraryPaths, sourcePool])
  const configuredProducerPool = useMemo(() => {
    const configured = configuredAllowedProducers == null
      ? new Set(producerOptions.map((producer) => producer.name.toLowerCase()))
      : new Set(configuredAllowedProducers.map((producer) => producerIdentityResolver.canonicalize(producer).toLowerCase()))
    const allowed = producerOptions
      .map((producer) => producer.name)
      .filter((producer) => producer.toLowerCase() === primaryProducer.toLowerCase() || configured.has(producer.toLowerCase()))
    return uniqueProducerCredits([primaryProducer, ...allowed], primaryProducer)
  }, [configuredAllowedProducers, primaryProducer, producerIdentityResolver, producerOptions])
  const activeRequiredProducers = useMemo(() => {
    const available = new Set(producerOptions.map((producer) => producer.name.toLowerCase()))
    return [...new Set(requiredProducers.map((producer) => producerIdentityResolver.canonicalize(producer)))]
      .filter((producer) => available.has(producer.toLowerCase()))
  }, [producerIdentityResolver, producerOptions, requiredProducers])
  const allowedProducers = useMemo(() => {
    if (allowedCreditCounts.includes(0)) return configuredProducerPool
    const maximumExternalSlots = Math.max(0, ...allowedCreditCounts) - 1
    if (activeRequiredProducers.length < maximumExternalSlots) return configuredProducerPool
    return uniqueProducerCredits([primaryProducer, ...activeRequiredProducers.slice(0, maximumExternalSlots)], primaryProducer)
  }, [activeRequiredProducers, allowedCreditCounts, configuredProducerPool, primaryProducer])
  const localOverviewSelectionSummary = useMemo<LibrarySelectionSummary>(() => {
    const selectedRoots = new Set(selectedLibraryPaths)
    const roots = library.roots.filter((root) => selectedRoots.has(root.path))
    const allRootsSelected = roots.length > 0 && roots.length === library.roots.length
    const primaryProducerSummary = libraryProducers.find((producer) => producer.name.toLowerCase() === primaryProducer.toLowerCase())
    return {
      layerCount: roots.reduce((sum, root) => sum + root.layerCount, 0),
      loopCount: allRootsSelected ? primaryProducerSummary?.loopCount ?? 0 : 0,
      categories: mergeGenerateCategories(...roots.map((root) => root.categories)),
    }
  }, [library.roots, libraryProducers, primaryProducer, selectedLibraryPaths])
  useEffect(() => {
    let cancelled = false
    if (selectedLibraryPaths.length === 0) {
      setLocalSelectionSummary({ layerCount: 0, loopCount: 0, categories: [] })
      setSelectionSummaryLoading(false)
      return () => { cancelled = true }
    }
    const getSelectionSummary = window.stemSlicer?.getLibrarySelectionSummary
    setLocalSelectionSummary(localOverviewSelectionSummary)
    if (!getSelectionSummary) {
      setSelectionSummaryLoading(false)
      return () => { cancelled = true }
    }
    setSelectionSummaryLoading(true)
    void getSelectionSummary({
      libraryRoots: selectedLibraryPaths,
      allowedProducers,
      allowedCreditCounts,
      primaryProducer,
      producerIdentities,
    }).then((summary) => {
      if (!cancelled && summary) setLocalSelectionSummary(summary)
    }).catch(() => {
      if (!cancelled) setLocalSelectionSummary(localOverviewSelectionSummary)
    }).finally(() => {
      if (!cancelled) setSelectionSummaryLoading(false)
    })
    return () => { cancelled = true }
  }, [allowedCreditCounts, allowedProducers, localOverviewSelectionSummary, primaryProducer, producerIdentities, selectedLibraryPaths])
  const allowedProducerKeys = new Set(allowedProducers.map((producer) => producer.toLowerCase()))
  const cloudCreditLimitAllowsCollaborators = allowedCreditCounts.includes(0) || Math.max(1, ...allowedCreditCounts) >= 2
  const selectedCloudLibraries = sourcePool === "local-only" || !cloudCreditLimitAllowsCollaborators
    ? []
    : enabledCloudLibraries.filter((item) => allowedProducerKeys.has(item.owner.displayName.toLowerCase()))
  const localSelectionEnabled = sourcePool !== "cloud-only"
  const localSelectedLayerCount = localSelectionEnabled ? localSelectionSummary.layerCount : 0
  const localSelectedLoopCount = localSelectionEnabled ? localSelectionSummary.loopCount : 0
  const cloudSelectedLayerCount = selectedCloudLibraries.reduce((sum, item) => sum + item.layerCount, 0)
  const cloudSelectedLoopCount = selectedCloudLibraries.reduce((sum, item) => sum + item.loopCount, 0)
  const selectedLayerCount = localSelectedLayerCount + cloudSelectedLayerCount
  const selectedLoopCount = localSelectedLoopCount + cloudSelectedLoopCount
  const selectedCategories = mergeGenerateCategories(
    localSelectionEnabled ? localSelectionSummary.categories : [],
    ...selectedCloudLibraries.map((item) => item.categories ?? []),
  )
  const largestCategoryCount = selectedCategories[0]?.count || 1
  const producerProfilesWithCloud = useMemo(() => {
    const merged = { ...producerProfiles }
    const profiles = [
      cloudState.profile,
      ...cloudState.connections.map((connection) => connection.profile),
      ...cloudState.libraries.map((item) => item.owner),
    ].filter((profile): profile is CloudProfile => Boolean(profile))
    for (const profile of profiles) {
      if (!profile.avatarUrl) continue
      const avatar = { avatarUrl: profile.avatarUrl }
      merged[profile.displayName.toLowerCase()] = avatar
      for (const alias of profile.aliases) merged[alias.toLowerCase()] = avatar
    }
    return merged
  }, [cloudState.connections, cloudState.libraries, cloudState.profile, producerProfiles])

  useEffect(() => {
    let cancelled = false
    void window.stemSlicer?.getLibraryProducers(primaryProducer, selectedLibraryPaths, producerIdentities).then((producers) => {
      if (!cancelled) setLibraryProducers(producers)
    }).catch(() => {
      if (!cancelled) setLibraryProducers([])
    })
    return () => { cancelled = true }
  }, [library.databasePath, library.totalLayers, primaryProducer, producerIdentities, selectedLibraryPaths])

  useEffect(() => {
    let cancelled = false
    void window.stemSlicer?.getCloudState().then((state) => {
      if (!cancelled && state) setCloudState(state)
    }).catch(() => undefined)
    const updateCloudState = (event: Event) => {
      const state = (event as CustomEvent<CloudState>).detail
      if (state) setCloudState(state)
    }
    window.addEventListener(CLOUD_STATE_CHANGED_EVENT, updateCloudState)
    return () => {
      cancelled = true
      window.removeEventListener(CLOUD_STATE_CHANGED_EVENT, updateCloudState)
    }
  }, [])

  useEffect(() => {
    const updateProfiles = (event: Event) => {
      const profiles = (event as CustomEvent<Record<string, ProducerProfileSettings>>).detail
      if (profiles) setProducerProfiles(profiles)
    }
    window.addEventListener(PRODUCER_PROFILES_CHANGED_EVENT, updateProfiles)
    return () => window.removeEventListener(PRODUCER_PROFILES_CHANGED_EVENT, updateProfiles)
  }, [])

  useEffect(() => {
    saveCollaboratorSettings({
      allowedProducers: configuredAllowedProducers,
      allowedCreditCounts,
      requiredProducers,
      requiredContributionPercent,
      sourcePool,
      pinnedProducers,
      producerSortDirection,
      profiles: producerProfiles,
    })
  }, [allowedCreditCounts, configuredAllowedProducers, pinnedProducers, producerProfiles, producerSortDirection, requiredContributionPercent, requiredProducers, sourcePool])

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
      sourceFile: artifact.sourceFile,
      sourceLoopId: artifact.sourceLoopId,
      sourceLoopName: artifact.sourceLoopName,
      producers: artifact.producers,
      libraryRoot: artifact.libraryRoot,
      sourceOrigin: artifact.sourceOrigin ?? sourceOriginForLayer(artifact),
      cloudLayerId: artifact.cloudLayerId,
      cloudOwnerId: artifact.cloudOwnerId,
      sourceSha256: artifact.sourceSha256,
      sourceDetectedKey: artifact.sourceDetectedKey,
      identity: artifact.identity,
      sourceKeyRank: artifact.sourceKeyRank ?? 1,
      octave: artifact.octave ?? 0,
      locked: artifact.locked ?? false,
      bars: artifact.peaks.map((peak) => Math.max(8, Math.round(peak * 100))),
    }))
    setLayers(nextLayers)
    const elapsedLabel = generationResult.elapsedSeconds ? ` in ${generationResult.elapsedSeconds.toFixed(1)}s` : ""
    setStatus(`${generationResult.layers.length} real layers generated${elapsedLabel}`)
    const generationNumber = generationResult.generationNumber ?? nextGenerationNumber
    const producers = generationResult.producers?.length ? generationResult.producers : producersForLayers(nextLayers, primaryProducer)
    const displayName = displayNameForGeneration(generationResult, nextLayers, generationNumber, primaryProducer)
    onAddHistory({
      id: crypto.randomUUID(),
      bpm: generationResult.targetBpm,
      keyName: generationResult.targetKey,
      recipe: "Generated",
      generationNumber,
      displayName,
      producers,
      createdAt: new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" }).format(new Date()),
      createdAtIso: new Date().toISOString(),
      layerCount: generationResult.layers.length,
      generation: generationResult,
      layers: nextLayers,
    })
  }, [generationResult, nextGenerationNumber, onAddHistory, playback, primaryProducer, setCurrentGenerationResult, setLayers])

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
        sourceFile: artifact.sourceFile ?? previous?.sourceFile,
        sourceLoopId: artifact.sourceLoopId ?? previous?.sourceLoopId,
        sourceLoopName: artifact.sourceLoopName ?? previous?.sourceLoopName,
        producers: artifact.producers ?? previous?.producers,
        libraryRoot: artifact.libraryRoot ?? previous?.libraryRoot,
        sourceOrigin: artifact.sourceOrigin ?? previous?.sourceOrigin ?? sourceOriginForLayer(artifact),
        cloudLayerId: artifact.cloudLayerId ?? previous?.cloudLayerId,
        cloudOwnerId: artifact.cloudOwnerId ?? previous?.cloudOwnerId,
        sourceSha256: artifact.sourceSha256 ?? previous?.sourceSha256,
        sourceDetectedKey: artifact.sourceDetectedKey ?? previous?.sourceDetectedKey,
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
    void onLibraryRefresh().finally(() => setPendingLibraryRoot(""))
  }, [libraryScanJob.result, onLibraryRefresh])

  useEffect(() => {
    if (libraryScanJob.busy) {
      const progress = libraryScanJob.percent > 0 ? ` · ${libraryScanJob.percent}%` : ""
      setSelectionMessage(`${libraryScanJob.message}${progress}`)
      return
    }
    if (libraryScanJob.phase === "cancelled" && pendingLibraryRoot) {
      setSelectionMessage(`${basename(pendingLibraryRoot)} · scan cancelled · catalogue unchanged`)
      return
    }
    if (libraryScanJob.error) setSelectionMessage(libraryScanErrorMessage(libraryScanJob.error))
  }, [libraryScanJob.busy, libraryScanJob.error, libraryScanJob.message, libraryScanJob.percent, libraryScanJob.phase, pendingLibraryRoot])

  const pickFolder = async (droppedRoot?: string) => {
    if (libraryScanJob.busy) return
    let root = droppedRoot
    if (!root) {
      const result = await window.stemSlicer?.pickLibraryFolder()
      if (!result || result.canceled || result.paths.length === 0) return
      root = result.paths[0]
    }
    setPendingLibraryRoot(root)
    setSelectionMessage(`${basename(root)} · preparing scan…`)
    void libraryScanJob.start(
      { root, databasePath: library.databasePath },
      `Preparing ${basename(root)}…`,
    ).catch(() => undefined)
  }

  const cancelLibraryScan = () => {
    libraryScanJob.cancel("Cancelling library scan…")
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
    if (sourcePool === "cloud-only" && !hasEnabledCloudLibrary) {
      setStatus("Enable at least one shared Cloud library before Generate.")
      return
    }
    if (sourcePool !== "cloud-only" && selectedLibraryPaths.length === 0) {
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
    let generationKey = keyName
    if (randomKeyEnabled && seedOverride == null) {
      const previousGenerationKey = currentGenerationResult?.targetKey ?? keyName
      const randomFamily = keyFamilyForKey(randomKeyOutsidePreviousFamily(previousGenerationKey))
      generationKey = keyFromFamily(randomFamily, keyName)
      setKeyName(generationKey)
    }
    const engineGenerationKey = normalizeKeyName(generationKey)
    const seed = seedOverride ?? crypto.getRandomValues(new Uint32Array(1))[0]
    if (currentSeed !== seed) {
      setPreviousSeed(currentSeed)
      setCurrentSeed(seed)
    }
    setStatus(randomKeyEnabled && seedOverride == null
      ? `Random key · ${generationKey} · selecting and rendering real layers…`
      : "Selecting and rendering real layers…")
    void generateJob.start(
      {
        databasePath: library.databasePath,
        libraryRoots: selectedLibraryPaths,
        categories: requestedCategories,
        targetBpm: bpm,
        targetKey: engineGenerationKey,
        primaryProducer,
        seed,
        generationNumber: nextGenerationNumber,
        bars: 8,
        sourcePool,
        allowedProducers,
        allowedCreditCounts,
        requiredProducers: activeRequiredProducers,
        requiredContributionPercent,
        producerIdentities,
        lockedIdentitiesBySlot: layers.map((layer) => layer.locked && layer.identity ? layer.identity : null),
        excludedIdentities: seedOverride == null
          ? layers.filter((layer) => !layer.locked && layer.identity).map((layer) => layer.identity as string)
          : [],
        excludedSourceLoops: activeKeyIssues.map((issue) => ({
          libraryRoot: issue.libraryRoot,
          sourceLoopId: issue.sourceLoopId,
        })),
      },
      sourcePool === "local-only"
        ? "Preparing PC catalogue…"
        : sourcePool === "cloud-only"
          ? "Preparing Cloud libraries…"
          : "Preparing PC and Cloud libraries…",
    ).catch(() => undefined)
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

  const toggleLayerLock = (slotIndex: number) => {
    setLayers((current) => current.map((layer, index) => index === slotIndex ? { ...layer, locked: !layer.locked } : layer))
  }

  const toggleLibraryIssue = async (slotIndex: number, issueType?: LibraryIssueType) => {
    const layer = layers[slotIndex]
    if (!layer) return
    const issue = activeKeyIssueBySource.get(sourceLoopKey(layer.libraryRoot, layer.sourceLoopId))
    try {
      if (issue) {
        await onSetKeyIssueActive(issue.id, false)
        playback.setLayerMuted(layer.id, false)
        setStatus(`Source loop restored: ${layer.sourceFile ?? layer.file}`)
        return
      }
      if (
        !layer.libraryRoot
        || !layer.sourceLoopId
        || !layer.identity
        || !layer.sourcePath
        || !currentGenerationResult?.outputDirectory
      ) {
        setStatus("This card does not expose enough source metadata to report the source loop.")
        return
      }
      if (!issueType) throw new Error("Choose whether the source loop has a key or slice issue.")
      await onReportKeyIssue({
        issueType,
        libraryRoot: layer.libraryRoot,
        sourceLoopId: layer.sourceLoopId,
        reportedIdentity: layer.identity,
        reportedPath: layer.sourcePath,
        reportedFile: layer.sourceFile ?? basename(layer.sourcePath),
        detectedKey: layer.sourceDetectedKey || "Unknown",
        targetKey: currentGenerationResult.targetKey,
        generationOutputDirectory: currentGenerationResult.outputDirectory,
      })
      const rejectedSource = sourceLoopKey(layer.libraryRoot, layer.sourceLoopId)
      const rejectedLayers = layers.filter((item) => sourceLoopKey(item.libraryRoot, item.sourceLoopId) === rejectedSource)
      const remainingLayers = layers.filter((item) => sourceLoopKey(item.libraryRoot, item.sourceLoopId) !== rejectedSource)
      for (const rejected of rejectedLayers) playback.setLayerMuted(rejected.id, true)
      setLayers(remainingLayers)
      onUpdateHistory(currentGenerationResult, remainingLayers)
      setRecipeDirty(true)
      setStatus(`${issueType === "wrong-slice" ? "Wrong slice" : "Wrong key"} reported · ${rejectedLayers.length} card${rejectedLayers.length === 1 ? "" : "s"} removed and the complete source loop quarantined`)
    } catch (error) {
      const message = error instanceof Error ? error.message : "The library issue could not be saved."
      setStatus(message)
      throw error
    }
  }

  const correctLayerCategory = async (slotIndex: number, category: string) => {
    const layer = layers[slotIndex]
    if (!layer?.libraryRoot || !layer.sourceLoopId || !layer.identity || !layer.sourcePath) {
      throw new Error("This card does not expose enough source metadata to correct its category.")
    }
    const request: SetLayerCategoryRequest = {
      libraryRoot: layer.libraryRoot,
      sourceLoopId: layer.sourceLoopId,
      identity: layer.identity,
      path: layer.sourcePath,
      category,
    }
    const corrected = await window.stemSlicer?.setLayerCategory(request)
    if (!corrected) throw new Error("The desktop category-feedback service is unavailable.")
    const nextLayers = layers.map((item, index) => index === slotIndex
      ? { ...item, category: corrected.category, role: corrected.category, locked: false }
      : item)
    setLayers(nextLayers)
    if (currentGenerationResult) onUpdateHistory(currentGenerationResult, nextLayers)
    setRecipeDirty(true)
    setStatus(`Category validated · ${layer.sourceFile ?? layer.file} is now ${corrected.category}`)
    await onLibraryRefresh()
    await onCategoryCorrectionsRefresh()
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
        eyebrow="Workspace"
        title="Generate New Loops"
        description="Choose a BPM and key, then generate new loops."
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
          <div className="target-key-control">
            <Select id="target-key" label="Target key" value={keyFamilyForKey(keyName)} onChange={(family) => setKeyName(keyFromFamily(family, keyName))} options={TARGET_KEY_FAMILIES} optionLabel={compactKeyFamilyLabel} className="key-family-select" forceBelow />
            <button
              type="button"
              className={cn("random-key-toggle", randomKeyEnabled && "is-active")}
              aria-disabled={generateJob.busy}
              aria-pressed={randomKeyEnabled}
              aria-label={randomKeyEnabled ? "Disable random key for new generations" : "Enable random key for new generations"}
              title={generateJob.busy
                ? `Current generation in progress — Random key remains ${randomKeyEnabled ? "enabled" : "disabled"}`
                : randomKeyEnabled
                ? "Random key enabled — each new generation avoids the previous relative-key family"
                : "Randomize the key on each new generation"}
              onClick={() => {
                if (generateJob.busy) return
                const nextEnabled = !randomKeyEnabled
                setRandomKeyEnabled(nextEnabled)
                setStatus(nextEnabled ? "Random key enabled" : "Random key disabled")
              }}
            >
              <Dices aria-hidden="true" />
            </button>
          </div>
          <div className="generate-action">
            <span className="sr-only" aria-live="polite">{generateJob.error || (generateJob.busy ? generateJob.message : status)}</span>
            <ProducerAvatarStack producers={allowedProducers} profiles={producerProfilesWithCloud} toolbar />
            <CollaboratorsDialog
              producers={producerOptions}
              primaryProducer={primaryProducer}
              cloudSourceCount={cloudSourceCount}
              generationLayerCount={Math.max(1, layers.length)}
              allowedProducers={allowedProducers}
              allowedCreditCounts={allowedCreditCounts}
              requiredProducers={activeRequiredProducers}
              requiredContributionPercent={requiredContributionPercent}
              profiles={producerProfilesWithCloud}
              pinnedProducers={pinnedProducers}
              producerSortDirection={producerSortDirection}
              sourcePool={sourcePool}
              disabled={generateJob.busy}
              onAllowedProducersChange={(nextProducers) => {
                setConfiguredAllowedProducers(uniqueProducerCredits(nextProducers, primaryProducer))
                const allowed = new Set(nextProducers.map((producer) => producer.toLowerCase()))
                setRequiredProducers((current) => current.filter((producer) => allowed.has(producer.toLowerCase())))
                setLayers((current) => current.map((layer) => ({ ...layer, locked: false })))
                setRecipeDirty(true)
                setStatus("Collaborator pool updated")
              }}
              onAllowAllProducers={() => {
                setConfiguredAllowedProducers(null)
                setLayers((current) => current.map((layer) => ({ ...layer, locked: false })))
                setRecipeDirty(true)
                setStatus("All matching collaborators enabled")
              }}
              onAllowedCreditCountsChange={(nextCounts) => {
                setAllowedCreditCounts(nextCounts)
                const maximumRequired = nextCounts.includes(0) ? Number.POSITIVE_INFINITY : Math.max(...nextCounts) - 1
                setRequiredProducers((current) => current.slice(0, maximumRequired))
                setLayers((current) => current.map((layer) => ({ ...layer, locked: false })))
                setRecipeDirty(true)
                setStatus(nextCounts.includes(0)
                  ? "Any collaborator count enabled"
                  : `${nextCounts.map((count) => count === 1 ? "Solo" : count === 2 ? "Duo" : "Trio").join(" + ")} generations enabled`)
              }}
              onRequiredProducersChange={(nextProducers) => {
                setRequiredProducers(nextProducers)
                setLayers((current) => current.map((layer) => ({ ...layer, locked: false })))
                setRecipeDirty(true)
                setStatus(nextProducers.length > 0 ? "Required collaborator rule updated" : "Collaborators are allowed but not forced")
              }}
              onRequiredContributionPercentChange={(percent) => {
                setRequiredContributionPercent(percent)
                setLayers((current) => current.map((layer) => ({ ...layer, locked: false })))
                setRecipeDirty(true)
                setStatus(`Required collaborator share set to ${percent}%`)
              }}
              onSourcePoolChange={(nextSourcePool) => {
                setSourcePool(nextSourcePool)
                if (nextSourcePool === "cloud-only") {
                  setAllowedCreditCounts((current) => current.includes(0)
                    ? [0]
                    : creditCountsThrough(Math.max(2, ...current) as FiniteCollaboratorCreditCount))
                  setConfiguredAllowedProducers(null)
                }
                setLayers((current) => current.map((layer) => ({ ...layer, locked: false })))
                setRecipeDirty(true)
                setStatus(nextSourcePool === "cloud-only"
                  ? "Cloud-only source pool enabled"
                  : nextSourcePool === "local-only"
                    ? "PC-only source pool enabled"
                    : "PC and Cloud source pool enabled")
              }}
              onPinnedProducersChange={setPinnedProducers}
              onProducerSortDirectionChange={setProducerSortDirection}
            />
            <Button variant="outline" className="previous-seed-button" size="sm" disabled={generateJob.busy || libraryScanJob.busy || previousSeed == null} onClick={() => previousSeed != null && handleGenerate(previousSeed)} title={previousSeed == null ? "No previous seed yet" : `Generate seed ${previousSeed}`}><RotateCcw /> Previous</Button>
          <Button className="hardware-button generate-hardware" size="lg" onClick={() => handleGenerate()} disabled={libraryScanJob.busy || (!generateJob.busy && (selectionSummaryLoading || selectedLayerCount === 0 || (sourcePool === "cloud-only" ? !hasEnabledCloudLibrary : selectedLibraryPaths.length === 0)))}>
              {generateJob.busy ? <X /> : libraryScanJob.busy ? <RefreshCw aria-hidden="true" /> : <WandSparkles />}
              {generateJob.busy ? `${generateJob.percent}% · Cancel` : libraryScanJob.busy ? `Scan ${libraryScanJob.percent}%` : "Generate"}
            </Button>
          </div>
          {generateJob.error ? <p className="generate-feedback is-error" role="alert">{generateJob.error}</p> : null}
        </CardContent>
      </Card>

      <section className="generate-catalogue glass-panel" aria-labelledby="generate-catalogue-title">
        <div className="catalogue-toolbar">
          <div className="catalogue-heading">
            <span className="catalogue-icon" aria-hidden="true"><Layers3 /></span>
            <div>
              <h2 id="generate-catalogue-title">Layer library</h2>
              <p>Categories available to the current Generate selection</p>
            </div>
          </div>
          <div className="catalogue-actions">
            <div className="catalogue-layer-count" aria-label={`${formatCount(selectedLoopCount)} loops and ${formatCount(selectedLayerCount)} layers selected for Generate`}>
              <strong className="tabular">{formatCount(selectedLayerCount)} {selectedLayerCount === 1 ? "layer" : "layers"}</strong>
              <span className="tabular">{formatCount(selectedLoopCount)} {selectedLoopCount === 1 ? "loop" : "loops"}</span>
            </div>
            <LibraryManager
              library={library}
              selectedPaths={selectedLibraryPaths}
              selectedLayerCount={localSelectionSummary.layerCount}
              selectedCategoryCount={mergeGenerateCategories(localSelectionSummary.categories).length}
              selectionMessage={selectionMessage}
              selectionError={libraryScanJob.phase === "failed"}
              scanBusy={libraryScanJob.busy}
              pendingScan={pendingLibraryScan}
              onSelectedPathsChange={setSelectedLibraryPaths}
              onAddFolder={pickFolder}
              onCancelScan={cancelLibraryScan}
              onDismissPendingScan={() => {
                setPendingLibraryRoot("")
                setSelectionMessage("")
              }}
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
          )) : <p className="catalogue-empty">{selectedLibraryPaths.length === 0
            ? "Select at least one indexed library to view its categories."
            : "No layers match the current library and collaborator filters."}</p>}
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
              onMarkCurrentGenerationExported(currentGenerationResult)
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
                primaryProducer={primaryProducer}
                progressSource={playback.progressSource}
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
                onToggleLibraryIssue={(issueType) => toggleLibraryIssue(index, issueType)}
                onCorrectCategory={(category) => correctLayerCategory(index, category)}
                onToggleLock={() => toggleLayerLock(index)}
                onRemove={() => removeLayerCard(index)}
                onExport={() => currentGenerationResult && onMarkCurrentGenerationExported(currentGenerationResult)}
                categoryOptions={selectedCategories.map((category) => category.name)}
                canRemove={layers.length > 1}
                updating={generateUpdateJob.busy}
                libraryIssueActive={activeKeyIssueBySource.has(sourceLoopKey(layer.libraryRoot, layer.sourceLoopId))}
                libraryIssueType={activeKeyIssueBySource.get(sourceLoopKey(layer.libraryRoot, layer.sourceLoopId))?.issueType}
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

function StemSlicerView({ embedded = false, onExtractionCompleted }: { embedded?: boolean; onExtractionCompleted: (entry: ExtractionHistoryEntry) => void }) {
  const [sourceFolder, setSourceFolder] = useState("")
  const [outputRoot, setOutputRoot] = useState("")
  const [outputFolderName, setOutputFolderName] = useState("")
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
  const outputNameError = outputFolderNameError(outputFolderName)
  const showOutputNameError = Boolean(sourceFolder && outputNameError)
  const outputFolder = outputRoot && !outputNameError ? joinPath(outputRoot, outputFolderName.trim()) : ""
  const currentBatchResult = batchResult?.outputFolder === outputFolder ? batchResult : null
  const batchErrorCount = batchJob.busy
    ? (batchJob.error ? 1 : 0)
    : currentBatchResult?.failures.length ?? (batchJob.error ? 1 : 0)
  const batchCompletedSuccessfully = Boolean(
    currentBatchResult
    && !batchJob.busy
    && !batchJob.error
    && batchJob.percent >= 100
    && batchErrorCount === 0,
  )
  const batchStatusMessage = batchJob.error || (batchJob.busy
    ? batchJob.message
    : currentBatchResult
      ? `${currentBatchResult.outputs.length} audio ${currentBatchResult.outputs.length === 1 ? "file" : "files"} ready`
      : sourceFolder
        ? `${basename(sourceFolder)} ready`
        : "Choose a source folder to begin")

  useEffect(() => {
    let active = true
    void window.stemSlicer?.getEnvironment()
      .then((environment) => {
        if (active && environment) setOutputRoot(environment.defaultExtractionRootPath)
      })
      .catch(() => undefined)
    return () => {
      active = false
    }
  }, [])
  const previewValues: Record<string, string> = {
    Key: keyNotation === "Sharps #" ? "A♯m" : "B♭m",
    "Loop name": "CALLMEUR3",
    BPM: "137",
    "Prod name": "+NRGY_L1",
  }
  const namePreview = `${nameTokens.map((token) => previewValues[token]).join(" ")}.mp3`

  useEffect(() => {
    if (!batchResult || !layerExtraction || !sourceFolder) return
    onExtractionCompleted({
      id: `folder:${batchResult.outputFolder}`,
      mode: "folder",
      sourcePath: sourceFolder,
      outputFolder: batchResult.outputFolder,
      createdAt: new Date().toISOString(),
      sourceFileCount: batchResult.files,
      outputCount: batchResult.outputs.length,
      outputs: batchResult.outputs,
    })
  }, [batchResult, layerExtraction, onExtractionCompleted, sourceFolder])

  const pickSourceFolder = async () => {
    const result = await window.stemSlicer?.pickLibraryFolder()
    if (!result || result.canceled || result.paths.length === 0) return
    selectSourceFolder(result.paths[0])
  }

  const selectSourceFolder = (path: string) => {
    setSourceFolder(path)
    setOutputFolderName(extractionFolderNameForSource(path))
  }

  const pickOutputRoot = async () => {
    const result = await window.stemSlicer?.pickLibraryFolder()
    if (!result || result.canceled || result.paths.length === 0) return
    setOutputRoot(result.paths[0])
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
    if (!sourceFolder || !outputFolder || enabledOperationCount === 0) return
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
    <div className={cn("page-stack stem-slicer-page", embedded && "is-embedded")}>
      {!embedded ? <PageHeader
        eyebrow="Workspace"
        title="Slicer"
        description="Configure one batch from its source folder through extraction, key naming and conversion."
      /> : null}

      <section className="batch-workflow-shell unified-batch-workflow" aria-label="Slicer batch workflow">
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
              if (path) selectSourceFolder(path)
            }}
          >
            <span><strong>{sourceFolder ? basename(sourceFolder) : "Choose a loop folder"}</strong><small>{sourceFolder || "Drop a folder here or browse your files"}</small></span>
            <span>Browse folder</span>
          </button>
          <div className="unified-pipeline-route is-source-route" aria-label={`${enabledOperationCount} operations enabled`}>
            <span data-enabled={layerExtraction}><Layers3 aria-hidden="true" />Extract</span>
            <i aria-hidden="true" />
            <span data-enabled={keyAnalysis}><ScanLine aria-hidden="true" />Key & naming</span>
            <i aria-hidden="true" />
            <span data-enabled={conversion}><Repeat2 aria-hidden="true" />Convert</span>
          </div>
        </section>

        <section className="unified-pipeline-surface" aria-label="Slicer operations">
          <div className="unified-operations-grid">
          <section className={cn("unified-operation-card operation-extract", !layerExtraction && "is-disabled")} aria-labelledby="extract-operation-title">
            <header className="unified-operation-header">
              <span className="unified-operation-number">01</span>
              <span className="unified-operation-icon"><Layers3 aria-hidden="true" /></span>
              <div><h3 id="extract-operation-title">Layer extraction</h3><p>Extract every detected layer from each source loop.</p></div>
              <div className="unified-operation-toggle"><span>{layerExtraction ? "On" : "Off"}</span><OperationSwitch checked={layerExtraction} onChange={setLayerExtraction} label="Enable layer extraction" accent="red" /></div>
            </header>
            <div className="unified-operation-body">
              <label className="unified-output-name">
                <span>Output folder name</span>
                <Input
                  aria-invalid={showOutputNameError}
                  value={outputFolderName}
                  placeholder="Choose a source folder first"
                  onChange={(event) => setOutputFolderName(event.target.value)}
                />
                {showOutputNameError ? <small role="alert">{outputNameError}</small> : null}
              </label>
              <div className="unified-output-label"><span>Output location</span><small>Destination for extracted layers</small></div>
              <div className="unified-output-path"><FolderOpen aria-hidden="true" /><strong title={outputFolder || outputRoot}>{outputFolder || outputRoot || "Loading default location…"}</strong></div>
              <div className="unified-output-actions"><Button variant="outline" size="sm" onClick={pickOutputRoot}>Change location</Button><Button className="location-button" variant="outline" size="sm" disabled={!outputRoot} onClick={() => void window.stemSlicer?.revealPath(outputRoot)}><FolderOpen aria-hidden="true" />Location</Button></div>
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
                      <GripVertical className="naming-token-grip" aria-hidden="true" />
                      <span>{token}</span>
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
              <div className="unified-target-grid">
                <label className="unified-target-field">
                  <span className="unified-target-heading"><input type="checkbox" checked={targetBpmEnabled} onChange={(event) => setTargetBpmEnabled(event.target.checked)} /><b>Target BPM</b></span>
                  <Input aria-label="Slicer target BPM" type="number" min="40" max="300" value={targetBpm} disabled={!targetBpmEnabled} onChange={(event) => setTargetBpm(Number(event.target.value))} />
                </label>
                <div className="unified-target-field">
                  <label className="unified-target-heading"><input type="checkbox" checked={targetKeyEnabled} onChange={(event) => setTargetKeyEnabled(event.target.checked)} /><b>Target key</b></label>
                  <Select id="stem-target-key" label="Slicer target key" value={targetKey} onChange={setTargetKey} options={TARGET_KEY_FAMILIES} optionLabel={compactKeyFamilyLabel} disabled={!targetKeyEnabled} className="inline-select key-family-select" />
                </div>
              </div>
              <div className="unified-convert-route"><Repeat2 aria-hidden="true" /><div><span>Conversion input</span><strong>{layerExtraction ? "Extracted layers" : "Source loops"}</strong><small>Automatically follows the extraction setting.</small></div></div>
            </div>
          </section>
          </div>

          <div className="batch-process-bar" aria-labelledby="batch-process-status-heading">
            <div className="batch-process-copy">
              <h3 id="batch-process-status-heading">Process status</h3>
            </div>
            <div className="batch-process-progress">
              <div className="batch-process-stats">
                <span role="status" title={batchStatusMessage}>{batchStatusMessage}</span>
                <span className="batch-process-result">
                  {batchCompletedSuccessfully ? <Check className="batch-process-complete" aria-hidden="true" /> : null}
                  {batchJob.percent}% · {batchErrorCount} {batchErrorCount === 1 ? "error" : "errors"}
                </span>
              </div>
              <div className="batch-progress" role="progressbar" aria-label="Batch progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={batchJob.percent} aria-valuetext={`${batchJob.percent}% complete`}><span style={{ transform: `scaleX(${Math.max(0, Math.min(batchJob.percent, 100)) / 100})` }} /></div>
            </div>
            <div className="batch-process-actions">
              <Button className="hardware-button" aria-label={batchJob.busy ? "Cancel batch processing" : "Start batch processing"} onClick={processBatch} disabled={!batchJob.busy && (!sourceFolder || !outputFolder || enabledOperationCount === 0)}>{batchJob.busy ? "Cancel" : "Start"}</Button>
            </div>
            <div className="batch-process-meta">
              <button
                type="button"
                className="batch-process-location location-button"
                disabled={!currentBatchResult || batchJob.busy}
                title={currentBatchResult?.outputFolder || outputFolder}
                onClick={() => currentBatchResult && void window.stemSlicer?.revealPath(currentBatchResult.outputFolder)}
              >
                <span><FolderOpen aria-hidden="true" />Location</span>
                <strong>{currentBatchResult ? basename(currentBatchResult.outputFolder) : outputFolder ? basename(outputFolder) : "Waiting for source"}</strong>
              </button>
              <div><span>Operations</span><strong>{enabledOperationCount} enabled</strong></div>
              <div><span>Originals</span><strong>{keyDestination === "Rename originals" ? "Rename" : "Preserved"}</strong></div>
            </div>
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
  activeTool,
  previewLayers,
  setPreviewLayers,
  convertLayer,
  setConvertLayer,
  playback,
  onActiveToolChange,
  onExtractionCompleted,
  onConvertCompleted,
}: {
  activeTool: SlicerToolId
  previewLayers: GeneratedLayer[]
  setPreviewLayers: React.Dispatch<React.SetStateAction<GeneratedLayer[]>>
  convertLayer: GeneratedLayer | null
  setConvertLayer: (layer: GeneratedLayer | null) => void
  playback: PlaybackClock
  onActiveToolChange: (tool: SlicerToolId) => void
  onExtractionCompleted: (entry: ExtractionHistoryEntry) => void
  onConvertCompleted: (entry: ConvertHistoryEntry) => void
}) {
  const quickTools: Array<{ id: SlicerToolId; label: string; description: string; icon: LucideIcon }> = [
    { id: "slicer", label: "Slicer", description: "Process a complete loop folder", icon: Layers3 },
    { id: "extract", label: "Quick Extract", description: "Split one loop into playable layers", icon: AudioLines },
    { id: "scan", label: "Quick Scan", description: "Read BPM, key and relative modes", icon: ScanLine },
    { id: "convert", label: "Quick Convert", description: "Retune and time-stretch one loop", icon: ArrowRightLeft },
  ]

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

  useEffect(() => {
    if (!extractResult || !extractFile) return
    onExtractionCompleted({
      id: `single:${extractResult.outputFolder}`,
      mode: "single",
      sourcePath: extractFile,
      outputFolder: extractResult.outputFolder,
      createdAt: new Date().toISOString(),
      sourceFileCount: 1,
      outputCount: extractResult.layers.length,
      outputs: extractResult.layers.map((layer) => layer.path),
      outputBytes: extractResult.layers.reduce((sum, layer) => sum + layer.bytes, 0),
      elapsedSeconds: extractResult.elapsedSeconds,
    })
  }, [extractFile, extractResult, onExtractionCompleted])

  useEffect(() => {
    if (!convertResult || !convertFile) return
    onConvertCompleted({
      id: `convert:${convertResult.artifact.path}`,
      sourcePath: convertFile,
      outputFolder: convertResult.outputFolder,
      createdAt: new Date().toISOString(),
      artifact: convertResult.artifact,
      sourceBpm: convertResult.sourceBpm,
      sourceKey: convertResult.sourceKey,
      targetBpm: convertResult.targetBpm,
      targetKey: convertResult.targetKey,
      elapsedSeconds: convertResult.elapsedSeconds,
    })
    const artifact = convertResult.artifact
    setConvertLayer({
      id: `quick-convert-${artifact.path}`,
      role: "Converted loop",
      file: artifact.name,
      category: "Converted",
      bpm: artifact.bpm,
      keyName: artifact.key || "—",
      octave: 0,
      volume: 78,
      duration: artifact.duration,
      path: artifact.path,
      sourcePath: artifact.sourcePath,
      bars: artifact.peaks.map((value) => Math.max(8, Math.round(value * 100))),
    })
  }, [convertFile, convertResult, onConvertCompleted, setConvertLayer])

  const selectTool = (tool: SlicerToolId) => {
    if (tool === activeTool) return
    onActiveToolChange(tool)
  }

  const selectToolFromFileDrag = (event: React.DragEvent<HTMLButtonElement>, hoveredTool: SlicerToolId) => {
    const fileTool = quickFileToolFromDragHover(hoveredTool, Array.from(event.dataTransfer.types))
    if (!fileTool) return false
    event.preventDefault()
    event.dataTransfer.dropEffect = "copy"
    if (fileTool !== activeTool) {
      flushSync(() => onActiveToolChange(fileTool))
    }
    return true
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
    setConvertLayer(null)
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
      <div className="quick-tools-topbar">
        <PageHeader eyebrow="Workspace" title="Slicer" description="Process complete folders or choose a focused tool for one loop." />
        <div className="quick-tool-tabs" role="group" aria-label="Choose a Slicer tool">
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
              onDragEnter={(event) => selectToolFromFileDrag(event, id)}
              onDragOver={(event) => selectToolFromFileDrag(event, id)}
              onDrop={(event) => {
                if (quickFileToolFromDragHover(id, Array.from(event.dataTransfer.types))) event.preventDefault()
              }}
            >
              <span className="quick-tab-icon"><Icon aria-hidden="true" /></span>
              <span><strong>{label}</strong><small>{description}</small></span>
            </button>
          ))}
        </div>
      </div>

      <section className="quick-tools-shell" aria-label="Slicer workspace">
        <div hidden={activeTool !== "slicer"} id="quick-tool-panel-slicer" className="slicer-tool-panel" role="region" aria-labelledby="quick-tool-tab-slicer">
          <StemSlicerView embedded onExtractionCompleted={onExtractionCompleted} />
        </div>

        {activeTool === "extract" ? (
          <div id="quick-tool-panel-extract" className="quick-tool-panel extract-panel" role="region" aria-labelledby="quick-tool-tab-extract">
            <header className="quick-panel-heading">
              <div className="quick-panel-heading-copy"><span className="quick-panel-kicker">One loop · multiple layers</span><h2>Extract layers</h2></div>
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
                  <Select id="quick-extract-key" label="Quick Extract target key" value={extractKey} onChange={setExtractKey} options={TARGET_KEY_FAMILIES} optionLabel={compactKeyFamilyLabel} disabled={!extractKeyEnabled} className="inline-select key-family-select" />
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
                progressSource={playback.progressSource}
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
              <div className="quick-panel-heading-copy"><span className="quick-panel-kicker">One loop · full musical readout</span><h2>Scan BPM and key</h2></div>
              <span className="quick-panel-status">{scanJob.busy ? `${scanJob.percent}% · ${scanJob.message}` : scanJob.error || (scanResult ? "Analysis complete" : scanFile ? "File selected" : "Ready to scan")}</span>
            </header>

            <div className="quick-scan-body">
              <div className="quick-scan-source-column">
                <button type="button" className="quick-file-source quick-file-source-tall" onClick={chooseScanFile} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { const path = pathFromDrop(event); if (!path) return; setScanFile(path); void scanJob.start({ source: path }).catch(() => undefined) }}>
                  <span className="quick-source-icon"><ScanLine aria-hidden="true" /></span>
                  <span className="quick-source-copy"><strong>{scanFile ? basename(scanFile) : "Choose one loop"}</strong>{scanFile ? null : <small>Drop a loop here or browse your files</small>}</span>
                  <span className="quick-source-action">Browse loop</span>
                </button>
                <div className="quick-scan-options">
                  <SegmentedChoice label="Degree reference" value={degreeReference} options={["Major", "Minor"]} onChange={setDegreeReference} />
                  <SegmentedChoice label="Key notation" value={notation} options={["Sharps #", "Flats ♭"]} onChange={setNotation} />
                </div>
              </div>

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
                    <div><span>Analysis details</span><small>Technical output from the local scan engine</small></div>
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
              </div>
            </div>
          </div>
        ) : null}

        {activeTool === "convert" ? (
          <div id="quick-tool-panel-convert" className="quick-tool-panel convert-panel" role="region" aria-labelledby="quick-tool-tab-convert">
            <header className="quick-panel-heading">
              <div className="quick-panel-heading-copy"><span className="quick-panel-kicker">One loop · new BPM and key</span><h2>Convert audio</h2></div>
              <span className="quick-panel-status">{convertJob.busy ? `${convertJob.percent}% · ${convertJob.message}` : convertJob.error || (convertResult ? "1 conversion" : "0 conversions")}</span>
            </header>

            <div className="quick-convert-controls">
              <button type="button" className="quick-file-source" onClick={() => pickAudio(setConvertFile)} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { const path = pathFromDrop(event); if (path) setConvertFile(path) }}>
                <span className="quick-source-icon"><ArrowRightLeft aria-hidden="true" /></span>
                <span className="quick-source-copy"><strong>{convertFile ? basename(convertFile) : "Choose one loop"}</strong><small>{convertFile || "Drop a loop here or browse your files"}</small></span>
                <span className="quick-source-action">Browse loop</span>
              </button>
              <label className="quick-convert-field"><span>Target BPM</span><Input aria-label="Quick Convert target BPM" type="number" min="40" max="300" value={convertBpm} onChange={(event) => setConvertBpm(Number(event.target.value))} /></label>
              <Select id="quick-convert-key" label="Target key" value={convertKey} onChange={setConvertKey} options={TARGET_KEY_FAMILIES} optionLabel={compactKeyFamilyLabel} className="key-family-select" />
              <Button className="quick-run-button" onClick={runConvert} disabled={!convertJob.busy && !convertFile}>{convertJob.busy ? <X /> : <ArrowRightLeft />} {convertJob.busy ? "Cancel" : "Convert"}</Button>
            </div>

            {convertResult && convertLayer ? <div className="quick-convert-result" aria-live="polite"><AudioArtifactCard artifact={convertResult.artifact} layer={convertLayer} playback={playback} /></div> : null}
          </div>
        ) : null}
      </section>
    </div>
  )
}

function HistoryPlayButton({ entry, playing, onToggle }: { entry: HistoryEntry; playing: boolean; onToggle: () => void }) {
  return (
    <Button variant="outline" size="sm" onClick={onToggle} aria-label={`${playing ? "Pause" : "Play"} ${entry.displayName}`}>{playing ? <Pause /> : <Play className="play-glyph" />}</Button>
  )
}

function historyLayerId(entryId: string) {
  return `history-${entryId}`
}

function historyEntryToLayer(entry: HistoryEntry): GeneratedLayer {
  const referenceLayer = entry.layers.find((layer) => layer.bars.length > 0) ?? entry.layers[0]
  return {
    id: historyLayerId(entry.id),
    role: entry.displayName,
    file: entry.displayName,
    category: "History",
    bpm: entry.bpm,
    keyName: entry.keyName,
    octave: 0,
    volume: 100,
    duration: Math.max(0, ...entry.layers.map((layer) => layer.duration)),
    path: entry.generation.masterPath,
    producers: entry.producers,
    bars: referenceLayer?.bars ?? INITIAL_LAYERS[0].bars,
  }
}

const EDITOR_BEATS = 32

function snapEditorBeat(value: number, minimum: number, maximum: number) {
  const lower = Math.ceil(minimum * 4) / 4
  const upper = Math.max(lower, Math.floor(maximum * 4) / 4)
  return Math.max(lower, Math.min(upper, Math.round(value * 4) / 4))
}

function formatEditorClock(progress: number, bpm: number) {
  const elapsed = progress * editorTimelineSeconds(bpm)
  const minutes = Math.floor(elapsed / 60)
  const seconds = Math.floor(elapsed % 60)
  const milliseconds = Math.floor((elapsed % 1) * 1000)
  return `${minutes}:${String(seconds).padStart(2, "0")}.${String(milliseconds).padStart(3, "0")}`
}

function formatEditorPosition(progress: number) {
  const totalBeats = Math.min(EDITOR_BEATS - 0.001, Math.max(0, progress * EDITOR_BEATS))
  const bar = Math.floor(totalBeats / 4) + 1
  const beat = Math.floor(totalBeats % 4) + 1
  const quarter = Math.floor((totalBeats % 1) * 4) + 1
  return `${String(bar).padStart(2, "0")}.${beat}.${quarter}`
}

function SourceLoopStudio({
  active,
  libraryRoot,
  sourceLoopId,
  issueId,
  issueActive = false,
  onSetKeyIssueActive,
  onSaved,
  onClose,
}: {
  active: boolean
  libraryRoot: string
  sourceLoopId: string
  issueId: string
  issueActive?: boolean
  onSetKeyIssueActive?: (issueId: string, active: boolean) => Promise<void>
  onSaved: (editor: SourceLoopEditorData) => void | Promise<void>
  onClose: () => void
}) {
  const [draft, setDraft] = useState<SourceLoopEditorData | null>(null)
  const [peaks, setPeaks] = useState<Map<string, number[]>>(() => new Map())
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [playing, setPlaying] = useState(false)
  const [loopEnabled, setLoopEnabled] = useState(true)
  const [soloIdentity, setSoloIdentity] = useState<string | undefined>()
  const [mutedIdentities, setMutedIdentities] = useState<Set<string>>(() => new Set())
  const [excludedIdentities, setExcludedIdentities] = useState<Set<string>>(() => new Set())
  const [trackVolumes, setTrackVolumes] = useState<Map<string, number>>(() => new Map())
  const [selectedIdentity, setSelectedIdentity] = useState<string | undefined>()
  const [expandedTrackNameIdentity, setExpandedTrackNameIdentity] = useState<string | undefined>()
  const [progress, setProgress] = useState(0)
  const progressRef = useRef(0)
  const engineRef = useRef<SourceLoopPreviewEngine | null>(null)
  const animationRef = useRef<number | null>(null)
  const scrubResumeRef = useRef(false)

  useEffect(() => {
    progressRef.current = progress
  }, [progress])

  const activeLayers = useMemo(
    () => draft?.layers.filter((layer) => !excludedIdentities.has(layer.identity)) ?? [],
    [draft, excludedIdentities],
  )

  const pausePreview = useCallback(() => {
    engineRef.current?.stop()
    if (animationRef.current !== null) cancelAnimationFrame(animationRef.current)
    animationRef.current = null
    setPlaying(false)
  }, [])

  useEffect(() => {
    const api = window.stemSlicer
    if (!api || !libraryRoot || !sourceLoopId) {
      setError("The desktop source-loop editor is unavailable.")
      setLoading(false)
      return
    }
    let cancelled = false
    const engine = new SourceLoopPreviewEngine()
    engineRef.current = engine
    setLoading(true)
    setError("")
    setDraft(null)
    setPeaks(new Map())
    setMutedIdentities(new Set())
    setExcludedIdentities(new Set())
    setTrackVolumes(new Map())
    setSoloIdentity(undefined)
    setExpandedTrackNameIdentity(undefined)
    setLoopEnabled(true)
    setProgress(0)
    void api.getSourceLoopEditor(libraryRoot, sourceLoopId)
      .then(async (editor) => {
        if (cancelled) return
        setDraft(editor)
        setSelectedIdentity(editor.layers[0]?.identity)
        setTrackVolumes(new Map(editor.layers.map((layer) => [layer.identity, 100])))
        try {
          const nextPeaks = await engine.prepare(editor.layers)
          if (!cancelled) setPeaks(nextPeaks)
        } catch (reason) {
          if (!cancelled) setError(reason instanceof Error ? reason.message : "Waveform previews are unavailable.")
        }
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Unable to open the source loop editor.")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
      if (animationRef.current !== null) cancelAnimationFrame(animationRef.current)
      animationRef.current = null
      void engine.close()
      if (engineRef.current === engine) engineRef.current = null
    }
  }, [libraryRoot, sourceLoopId])

  const startPreview = useCallback(async (requestedStartProgress?: number, requestedLoopEnabled = loopEnabled) => {
    if (!draft || !engineRef.current) return
    pausePreview()
    setError("")
    try {
      const duration = editorTimelineSeconds(draft.bpm)
      const startProgress = requestedStartProgress ?? progressRef.current
      const effectiveProgress = startProgress >= 0.9999 ? 0 : Math.max(0, startProgress)
      const start = await engineRef.current.play(activeLayers, draft.bpm, {
        mutedIdentities,
        soloIdentity,
        startOffset: effectiveProgress * duration,
        loopEnabled: requestedLoopEnabled,
        trackVolumes,
      })
      setPlaying(true)
      const tick = () => {
        const engine = engineRef.current
        if (!engine) return
        const elapsed = Math.max(0, engine.currentTime - start.startedAt)
        const playheadSeconds = start.startOffset + elapsed
        if (!requestedLoopEnabled && playheadSeconds >= start.duration) {
          engine.stop()
          animationRef.current = null
          setProgress(1)
          setPlaying(false)
          return
        }
        setProgress(requestedLoopEnabled
          ? (playheadSeconds % start.duration) / start.duration
          : Math.min(1, playheadSeconds / start.duration))
        animationRef.current = requestAnimationFrame(tick)
      }
      animationRef.current = requestAnimationFrame(tick)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to preview this source loop.")
      pausePreview()
    }
  }, [activeLayers, draft, loopEnabled, mutedIdentities, pausePreview, soloIdentity, trackVolumes])

  useEffect(() => {
    if (active) return
    pausePreview()
  }, [active, pausePreview])

  useEffect(() => {
    if (!active) return
    const handleStudioSpace = (event: KeyboardEvent) => {
      if (event.code !== "Space" || event.repeat) return
      const target = event.target instanceof HTMLElement ? event.target : null
      if (target?.closest("input, textarea, select, [contenteditable='true'], [role='textbox'], [role='combobox'], [role='listbox']")) return
      event.preventDefault()
      event.stopPropagation()
      if (playing) pausePreview()
      else void startPreview()
    }
    document.addEventListener("keydown", handleStudioSpace, true)
    return () => document.removeEventListener("keydown", handleStudioSpace, true)
  }, [active, pausePreview, playing, startPreview])

  const patchLayer = (identity: string, update: Partial<SourceLoopEditorLayer>) => {
    setDraft((current) => current ? {
      ...current,
      layers: current.layers.map((layer) => layer.identity === identity ? { ...layer, ...update } : layer),
    } : current)
  }

  const updateLayer = (identity: string, update: Partial<SourceLoopEditorLayer>) => {
    pausePreview()
    patchLayer(identity, update)
  }

  const pointerProgress = (event: React.PointerEvent<HTMLElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    if (bounds.width <= 0) return progress
    return Math.max(0, Math.min(0.9999, (event.clientX - bounds.left) / bounds.width))
  }

  const beginTimelineScrub = (event: React.PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return
    event.preventDefault()
    scrubResumeRef.current = playing
    if (playing) pausePreview()
    event.currentTarget.setPointerCapture(event.pointerId)
    setProgress(pointerProgress(event))
  }

  const moveTimelineScrub = (event: React.PointerEvent<HTMLElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) setProgress(pointerProgress(event))
  }

  const endTimelineScrub = (event: React.PointerEvent<HTMLElement>) => {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
    const next = pointerProgress(event)
    event.currentTarget.releasePointerCapture(event.pointerId)
    setProgress(next)
    const shouldResume = scrubResumeRef.current
    scrubResumeRef.current = false
    if (shouldResume) void startPreview(next)
  }

  const toggleMute = (identity: string) => {
    setMutedIdentities((current) => {
      const next = new Set(current)
      if (next.has(identity)) next.delete(identity)
      else next.add(identity)
      engineRef.current?.updateMix(next, soloIdentity, trackVolumes)
      return next
    })
  }

  const toggleSolo = (identity: string) => {
    const nextSolo = soloIdentity === identity ? undefined : identity
    setSoloIdentity(nextSolo)
    engineRef.current?.updateMix(mutedIdentities, nextSolo, trackVolumes)
  }

  const updateTrackVolume = (identity: string, volume: number) => {
    setTrackVolumes((current) => {
      const next = new Map(current)
      next.set(identity, volume)
      engineRef.current?.updateMix(mutedIdentities, soloIdentity, next)
      return next
    })
  }

  const excludeLayer = (identity: string) => {
    if (activeLayers.length <= 1) {
      setError("Keep at least one layer in the source loop.")
      return
    }
    pausePreview()
    setError("")
    setExcludedIdentities((current) => new Set(current).add(identity))
    setMutedIdentities((current) => {
      const next = new Set(current)
      next.delete(identity)
      return next
    })
    if (soloIdentity === identity) setSoloIdentity(undefined)
    if (expandedTrackNameIdentity === identity) setExpandedTrackNameIdentity(undefined)
    if (selectedIdentity === identity) {
      setSelectedIdentity(activeLayers.find((layer) => layer.identity !== identity)?.identity)
    }
  }

  const undoLayerExclusions = () => {
    pausePreview()
    setExcludedIdentities(new Set())
    setError("")
  }

  const toggleLoop = () => {
    const nextLoopEnabled = !loopEnabled
    const shouldResume = playing
    const resumeAt = progress
    pausePreview()
    setLoopEnabled(nextLoopEnabled)
    if (shouldResume) void startPreview(resumeAt, nextLoopEnabled)
  }

  const save = async () => {
    if (!draft) return
    pausePreview()
    setSaving(true)
    setError("")
    try {
      const api = window.stemSlicer
      if (!api) throw new Error("The desktop source-loop editor is unavailable.")
      const saved = await api.saveSourceLoopEdit({
        libraryRoot: draft.libraryRoot,
        sourceLoopId: draft.sourceLoopId,
        bpm: draft.bpm,
        keyName: draft.keyName,
        layers: activeLayers.map((layer) => ({
          identity: layer.identity,
          category: layer.category,
          offsetBeats: layer.offsetBeats,
          trimStartBeats: layer.trimStartBeats,
          trimEndBeats: layer.trimEndBeats,
        })),
        excludedIdentities: [...excludedIdentities],
      })
      setDraft(saved)
      setExcludedIdentities(new Set())
      if (issueActive && issueId && onSetKeyIssueActive) await onSetKeyIssueActive(issueId, false)
      await onSaved(saved)
      onClose()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to save the source loop edits.")
    } finally {
      setSaving(false)
    }
  }

  const dialogSlug = (issueId || sourceLoopId || "source-loop").replace(/[^a-z0-9_-]/gi, "-")

  return (
    <section className="source-loop-studio" aria-labelledby="source-loop-studio-title">
      <header className="source-loop-editor-header app-drag-region">
        <button type="button" className="source-loop-studio-back app-no-drag" onClick={onClose}>
          <ChevronLeft aria-hidden="true" /><span>Library</span>
        </button>
        <div className="source-loop-studio-title">
          <p className="eyebrow">Workspace</p>
          <h1 id="source-loop-studio-title">{sourceLoopId || "Source loop"}</h1>
          <p>Edit the indexed layers directly on the timeline. Source audio remains untouched.</p>
        </div>
        <Badge variant="secondary">8 bars</Badge>
      </header>

      {loading ? <div className="source-loop-editor-loading" role="status"><span className="spinner" /> Loading indexed layers…</div> : null}
      {draft ? (
        <>
          <section className="source-loop-editor-toolbar" aria-label="Loop settings and preview transport">
                  <div className="mini-daw-project-settings">
                    <Select id={`source-loop-key-${dialogSlug}`} label="Key / relative" value={keyFamilyForKey(draft.keyName)} onChange={(family) => { pausePreview(); setDraft({ ...draft, keyName: keyFromFamily(family, draft.keyName) }) }} options={TARGET_KEY_FAMILIES} optionLabel={compactKeyFamilyLabel} className="key-family-select" forceBelow />
                  </div>
                  <div className="mini-daw-transport">
                    <div className="player-controls">
                      <button type="button" className={cn("player-key player-loop-key", loopEnabled && "is-active")} aria-pressed={loopEnabled} aria-label={loopEnabled ? "Disable loop playback" : "Enable loop playback"} onClick={toggleLoop}><Repeat2 aria-hidden="true" /></button>
                      <button type="button" className={cn("player-key player-key-primary", playing && "is-active")} aria-label={playing ? "Pause preview" : "Play preview"} onClick={() => playing ? pausePreview() : void startPreview()}>
                        {playing ? <Pause aria-hidden="true" /> : <Play className="play-glyph" aria-hidden="true" />}
                      </button>
                      <button type="button" className="player-key" aria-label="Stop and return to beginning" onClick={() => { pausePreview(); setProgress(0) }}><SkipBack aria-hidden="true" /></button>
                    </div>
                    <span className="mini-daw-time" aria-live="off"><b>{formatEditorClock(progress, draft.bpm)}</b><i>{formatEditorPosition(progress)}</i></span>
                    <label className="mini-daw-number-field"><span>BPM</span><Input type="number" min="40" max="300" value={draft.bpm} onChange={(event) => { pausePreview(); setDraft({ ...draft, bpm: Number(event.target.value) }) }} /></label>
                  </div>
                </section>

                <section className="mini-daw" aria-label="Eight-bar source loop timeline">
                  <div className="mini-daw-ruler">
                    <div className="mini-daw-track-list-header"><SlidersHorizontal aria-hidden="true" /><span>Tracks</span><small>{activeLayers.length}</small></div>
                    <div
                      className="mini-daw-timeline-ruler"
                      role="slider"
                      tabIndex={0}
                      aria-label="Timeline playhead"
                      aria-valuemin={0}
                      aria-valuemax={EDITOR_BEATS}
                      aria-valuenow={Math.round(progress * EDITOR_BEATS * 4) / 4}
                      aria-valuetext={`Bar and beat ${formatEditorPosition(progress)}`}
                      onKeyDown={(event) => {
                        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
                        event.preventDefault()
                        pausePreview()
                        const step = event.shiftKey ? 4 / EDITOR_BEATS : 0.25 / EDITOR_BEATS
                        setProgress(event.key === "Home" ? 0 : event.key === "End" ? 0.9999 : Math.max(0, Math.min(0.9999, progress + (event.key === "ArrowRight" ? step : -step))))
                      }}
                      onPointerDown={beginTimelineScrub}
                      onPointerMove={moveTimelineScrub}
                      onPointerUp={endTimelineScrub}
                      onPointerCancel={endTimelineScrub}
                    >
                      {Array.from({ length: 9 }, (_, index) => <i key={index} style={{ insetInlineStart: `${index * 12.5}%` }}>{index < 8 ? index + 1 : "End"}</i>)}
                    </div>
                  </div>
                  <div className="mini-daw-tracks">
                    {activeLayers.map((layer, index) => {
                      const sourceBeats = Math.max(0.25, layer.duration * draft.bpm / 60)
                      const usableBeats = Math.max(0.25, sourceBeats - layer.trimStartBeats - layer.trimEndBeats)
                      const visibleBeats = Math.max(0.25, Math.min(usableBeats, EDITOR_BEATS - layer.offsetBeats))
                      const left = Math.min(100, layer.offsetBeats / EDITOR_BEATS * 100)
                      const width = Math.max(1, visibleBeats / EDITOR_BEATS * 100)
                      const layerPeaks = peaks.get(layer.identity)
                      const isSolo = soloIdentity === layer.identity
                      const isMuted = mutedIdentities.has(layer.identity)
                      const isSelected = selectedIdentity === layer.identity
                      const trackVolume = trackVolumes.get(layer.identity) ?? 100
                      const displayName = studioLayerName({
                        file: layer.file,
                        bpm: draft.bpm,
                        keyName: draft.keyName,
                        layerIndex: layer.layerIndex ?? index + 1,
                      })
                      const nameTooltipId = `studio-track-name-${dialogSlug}-${index}`
                      const sourceWaveWidth = sourceBeats / visibleBeats * 100
                      const sourceWaveOffset = -layer.trimStartBeats / visibleBeats * 100
                      const maximumOffset = Math.max(0, EDITOR_BEATS - usableBeats)
                      return (
                        <article className={cn("mini-daw-track", isSolo && "is-solo", isMuted && "is-muted", isSelected && "is-selected")} key={layer.identity} aria-label={`Track ${index + 1}: ${layer.file}`}>
                          <div className="mini-daw-track-meta">
                            <span className="mini-daw-track-number">{String(index + 1).padStart(2, "0")}</span>
                            <div className="mini-daw-track-head">
                              <div className="mini-daw-track-name">
                                <button
                                  type="button"
                                  className="mini-daw-track-copy"
                                  aria-expanded={expandedTrackNameIdentity === layer.identity}
                                  aria-controls={nameTooltipId}
                                  onClick={() => setExpandedTrackNameIdentity((current) => current === layer.identity ? undefined : layer.identity)}
                                >
                                  <strong>{displayName.loopName}</strong>
                                  <small>{displayName.layerLabel}</small>
                                </button>
                                <span id={nameTooltipId} className={cn("mini-daw-track-name-tooltip", expandedTrackNameIdentity === layer.identity && "is-open")}>
                                  <strong>{displayName.fullLabel}</strong>
                                  <small>{layer.duration.toFixed(1)} s</small>
                                </span>
                              </div>
                              <div className="mini-daw-track-mix">
                                <button type="button" className={cn(isMuted && "is-active")} aria-pressed={isMuted} aria-label={`${isMuted ? "Unmute" : "Mute"} ${displayName.fullLabel}`} onClick={() => toggleMute(layer.identity)}>M</button>
                                <button type="button" className={cn(isSolo && "is-active")} aria-pressed={isSolo} aria-label={`${isSolo ? "Disable solo for" : "Solo"} ${displayName.fullLabel}`} onClick={() => toggleSolo(layer.identity)}>S</button>
                              </div>
                            </div>
                            <button
                              type="button"
                              className="mini-daw-track-remove"
                              disabled={saving || activeLayers.length <= 1}
                              aria-label={`Exclude ${displayName.fullLabel} from the library when changes are saved`}
                              title={activeLayers.length <= 1 ? "A source loop must keep at least one layer" : "Exclude this layer on save"}
                              onClick={() => excludeLayer(layer.identity)}
                            >
                              <X aria-hidden="true" />
                            </button>
                            <div className="mini-daw-track-strip">
                              <div className="mini-daw-track-category"><LayerCategorySelect id={`editor-category-${layer.identity}`} value={layer.category} options={GENERATE_CATEGORY_OPTIONS} disabled={saving} onChange={(category) => updateLayer(layer.identity, { category })} /></div>
                              <label className="mini-daw-track-volume" title={`Volume ${trackVolume}%`}>
                                <span className="sr-only">Volume for {displayName.fullLabel}</span>
                                <input type="range" min="0" max="125" value={trackVolume} onChange={(event) => updateTrackVolume(layer.identity, Number(event.target.value))} />
                              </label>
                            </div>
                          </div>
                          <div
                            className="mini-daw-lane"
                            onPointerDown={beginTimelineScrub}
                            onPointerMove={moveTimelineScrub}
                            onPointerUp={endTimelineScrub}
                            onPointerCancel={endTimelineScrub}
                          >
                            <span className="mini-daw-playhead" style={{ insetInlineStart: `${progress * 100}%` }} aria-hidden="true" />
                            <div
                              className={cn("mini-daw-clip", isSelected && "is-selected")}
                              style={{ insetInlineStart: `${left}%`, width: `${width}%` }}
                              role="group"
                              tabIndex={0}
                              aria-label={`${layer.file} audio clip, starts at beat ${layer.offsetBeats}. Use Left and Right arrows to move it.`}
                              onKeyDown={(event) => {
                                if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
                                event.preventDefault()
                                const step = event.shiftKey ? 1 : 0.25
                                const nextOffset = event.key === "Home"
                                  ? 0
                                  : event.key === "End"
                                    ? maximumOffset
                                    : snapEditorBeat(layer.offsetBeats + (event.key === "ArrowRight" ? step : -step), 0, maximumOffset)
                                updateLayer(layer.identity, { offsetBeats: nextOffset })
                              }}
                              onPointerDown={(event) => {
                                if (event.button !== 0) return
                                event.preventDefault()
                                event.stopPropagation()
                                pausePreview()
                                setSelectedIdentity(layer.identity)
                                const clip = event.currentTarget
                                const lane = clip.parentElement?.getBoundingClientRect()
                                if (!lane || lane.width <= 0) return
                                const initialX = event.clientX
                                const initialOffset = layer.offsetBeats
                                clip.setPointerCapture(event.pointerId)
                                const move = (moveEvent: PointerEvent) => {
                                  const deltaBeats = (moveEvent.clientX - initialX) / lane.width * EDITOR_BEATS
                                  patchLayer(layer.identity, { offsetBeats: snapEditorBeat(initialOffset + deltaBeats, 0, maximumOffset) })
                                }
                                const end = () => {
                                  clip.removeEventListener("pointermove", move)
                                  clip.removeEventListener("pointerup", end)
                                  clip.removeEventListener("pointercancel", end)
                                }
                                clip.addEventListener("pointermove", move)
                                clip.addEventListener("pointerup", end)
                                clip.addEventListener("pointercancel", end)
                              }}
                            >
                              <button
                                type="button"
                                className="mini-daw-trim-handle is-start"
                                aria-label={`Trim the start of ${layer.file}`}
                                aria-valuemin={0}
                                aria-valuemax={Math.max(0, sourceBeats - layer.trimEndBeats - 0.25)}
                                aria-valuenow={layer.trimStartBeats}
                                aria-orientation="horizontal"
                                role="slider"
                                onKeyDown={(event) => {
                                  if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return
                                  event.preventDefault()
                                  event.stopPropagation()
                                  const requested = event.key === "ArrowRight" ? 0.25 : -0.25
                                  const delta = snapEditorBeat(requested, -Math.min(layer.trimStartBeats, layer.offsetBeats), sourceBeats - layer.trimStartBeats - layer.trimEndBeats - 0.25)
                                  updateLayer(layer.identity, { trimStartBeats: layer.trimStartBeats + delta, offsetBeats: layer.offsetBeats + delta })
                                }}
                                onPointerDown={(event) => {
                                  event.preventDefault()
                                  event.stopPropagation()
                                  pausePreview()
                                  setSelectedIdentity(layer.identity)
                                  const handle = event.currentTarget
                                  const lane = handle.closest(".mini-daw-lane")?.getBoundingClientRect()
                                  if (!lane || lane.width <= 0) return
                                  const initialX = event.clientX
                                  const initialTrim = layer.trimStartBeats
                                  const initialOffset = layer.offsetBeats
                                  handle.setPointerCapture(event.pointerId)
                                  const move = (moveEvent: PointerEvent) => {
                                    const requested = Math.round(((moveEvent.clientX - initialX) / lane.width * EDITOR_BEATS) * 4) / 4
                                    const delta = snapEditorBeat(requested, -Math.min(initialTrim, initialOffset), sourceBeats - initialTrim - layer.trimEndBeats - 0.25)
                                    patchLayer(layer.identity, { trimStartBeats: initialTrim + delta, offsetBeats: initialOffset + delta })
                                  }
                                  const end = () => {
                                    handle.removeEventListener("pointermove", move)
                                    handle.removeEventListener("pointerup", end)
                                    handle.removeEventListener("pointercancel", end)
                                  }
                                  handle.addEventListener("pointermove", move)
                                  handle.addEventListener("pointerup", end)
                                  handle.addEventListener("pointercancel", end)
                                }}
                              />
                              <div className="mini-daw-wave-viewport" aria-hidden="true">
                                <div
                                  className="mini-daw-wave-content"
                                  style={{ insetInlineStart: `${sourceWaveOffset}%`, width: `${sourceWaveWidth}%` }}
                                >
                                  <StudioWaveform peaks={layerPeaks} />
                                </div>
                              </div>
                              <span className="mini-daw-clip-label">{layer.category}</span>
                              <button
                                type="button"
                                className="mini-daw-trim-handle is-end"
                                aria-label={`Trim the end of ${layer.file}`}
                                aria-valuemin={Math.max(0, sourceBeats - layer.trimStartBeats - (EDITOR_BEATS - layer.offsetBeats))}
                                aria-valuemax={Math.max(0, sourceBeats - layer.trimStartBeats - 0.25)}
                                aria-valuenow={layer.trimEndBeats}
                                aria-orientation="horizontal"
                                role="slider"
                                onKeyDown={(event) => {
                                  if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return
                                  event.preventDefault()
                                  event.stopPropagation()
                                  const minimumTrim = Math.max(0, sourceBeats - layer.trimStartBeats - (EDITOR_BEATS - layer.offsetBeats))
                                  const nextTrim = snapEditorBeat(layer.trimEndBeats + (event.key === "ArrowLeft" ? 0.25 : -0.25), minimumTrim, sourceBeats - layer.trimStartBeats - 0.25)
                                  updateLayer(layer.identity, { trimEndBeats: nextTrim })
                                }}
                                onPointerDown={(event) => {
                                  event.preventDefault()
                                  event.stopPropagation()
                                  pausePreview()
                                  setSelectedIdentity(layer.identity)
                                  const handle = event.currentTarget
                                  const lane = handle.closest(".mini-daw-lane")?.getBoundingClientRect()
                                  if (!lane || lane.width <= 0) return
                                  const initialX = event.clientX
                                  const initialTrim = layer.trimEndBeats
                                  const minimumTrim = Math.max(0, sourceBeats - layer.trimStartBeats - (EDITOR_BEATS - layer.offsetBeats))
                                  handle.setPointerCapture(event.pointerId)
                                  const move = (moveEvent: PointerEvent) => {
                                    const delta = Math.round(((moveEvent.clientX - initialX) / lane.width * EDITOR_BEATS) * 4) / 4
                                    patchLayer(layer.identity, { trimEndBeats: snapEditorBeat(initialTrim - delta, minimumTrim, sourceBeats - layer.trimStartBeats - 0.25) })
                                  }
                                  const end = () => {
                                    handle.removeEventListener("pointermove", move)
                                    handle.removeEventListener("pointerup", end)
                                    handle.removeEventListener("pointercancel", end)
                                  }
                                  handle.addEventListener("pointermove", move)
                                  handle.addEventListener("pointerup", end)
                                  handle.addEventListener("pointercancel", end)
                                }}
                              />
                            </div>
                          </div>
                        </article>
                      )
                    })}
                  </div>
          </section>
        </>
      ) : null}

      {error ? <p className="dialog-inline-error source-loop-editor-error" role="alert">{error}</p> : null}
      <footer className="source-loop-editor-footer">
        <div className="source-loop-editor-footer-status">
          {excludedIdentities.size > 0 ? (
            <span role="status">
              <CircleAlert aria-hidden="true" />
              {excludedIdentities.size} layer{excludedIdentities.size === 1 ? "" : "s"} will be excluded from the library. Source files stay untouched.
              <button type="button" disabled={saving} onClick={undoLayerExclusions}><RotateCcw aria-hidden="true" /> Undo</button>
            </span>
          ) : (
            <span><Check aria-hidden="true" /> Clips snap to ¼ beat. Mute only affects preview; × excludes a layer on save.</span>
          )}
        </div>
        <div className="source-loop-editor-footer-actions">
          <button type="button" className="dialog-cancel" disabled={saving} onClick={onClose}>Cancel</button>
          <Button disabled={!draft || saving || loading} onClick={() => void save()}><Check aria-hidden="true" /> {saving ? "Saving edits…" : issueActive ? "Save and restore loop" : "Save changes"}</Button>
        </div>
      </footer>
    </section>
  )
}

function HistoryView({
  history,
  extractionHistory,
  convertHistory,
  playback,
  onReopen,
  onTrashGenerated,
  onTrashExtractions,
  onTrashConversions,
  onMarkExported,
  onTogglePlayback,
}: {
  history: HistoryEntry[]
  extractionHistory: ExtractionHistoryEntry[]
  convertHistory: ConvertHistoryEntry[]
  playback: PlaybackClock
  onReopen: (entry: HistoryEntry) => void
  onTrashGenerated: (entries: HistoryEntry[]) => Promise<void>
  onTrashExtractions: (entries: ExtractionHistoryEntry[]) => Promise<void>
  onTrashConversions: (entries: ConvertHistoryEntry[]) => Promise<void>
  onMarkExported: (entry: HistoryEntry) => void
  onTogglePlayback: (entry: HistoryEntry) => void
}) {
  type HistorySection = "generate" | "extract" | "convert"
  type SectionId = "all" | HistorySection
  const historySections: HistorySection[] = ["generate", "extract", "convert"]
  const [activeSection, setActiveSection] = useState<SectionId>("all")
  const [selectedBySection, setSelectedBySection] = useState<Record<HistorySection, Set<string>>>(() => ({
    generate: new Set(),
    extract: new Set(),
    convert: new Set(),
  }))
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState("")
  const [storageUsage, setStorageUsage] = useState<Record<HistorySection, GenerationStorageUsage | null>>({ generate: null, extract: null, convert: null })
  const [storageError, setStorageError] = useState<Record<HistorySection, string>>({ generate: "", extract: "", convert: "" })
  const itemIds = useMemo<Record<HistorySection, string[]>>(() => ({
    generate: history.map((entry) => entry.id),
    extract: extractionHistory.map((entry) => entry.id),
    convert: convertHistory.map((entry) => entry.id),
  }), [convertHistory, extractionHistory, history])
  const visibleSections: HistorySection[] = activeSection === "all" ? historySections : [activeSection]
  const visibleItemCount = visibleSections.reduce((sum, section) => sum + itemIds[section].length, 0)
  const selectedCount = visibleSections.reduce((sum, section) => sum + itemIds[section].filter((id) => selectedBySection[section].has(id)).length, 0)
  const allSelected = visibleItemCount > 0 && selectedCount === visibleItemCount

  const refreshStorageUsage = useCallback(async () => {
    const api = window.stemSlicer
    if (!api) return
    const requests: Array<[HistorySection, Promise<GenerationStorageUsage>]> = [
      ["generate", api.getGenerationStorageUsage()],
      ["extract", api.getHistoryStorageUsage(extractionHistory.map((entry) => entry.outputFolder))],
      ["convert", api.getHistoryStorageUsage(convertHistory.map((entry) => entry.outputFolder))],
    ]
    const results = await Promise.all(requests.map(async ([section, request]) => {
      try {
        return { section, usage: await request, error: "" }
      } catch (reason) {
        return { section, usage: null, error: reason instanceof Error ? reason.message : "Storage is unavailable." }
      }
    }))
    setStorageUsage((current) => ({ ...current, ...Object.fromEntries(results.map((result) => [result.section, result.usage])) }))
    setStorageError((current) => ({ ...current, ...Object.fromEntries(results.map((result) => [result.section, result.error])) }))
  }, [convertHistory, extractionHistory])

  useEffect(() => {
    setSelectedBySection((current) => ({
      generate: new Set([...current.generate].filter((id) => itemIds.generate.includes(id))),
      extract: new Set([...current.extract].filter((id) => itemIds.extract.includes(id))),
      convert: new Set([...current.convert].filter((id) => itemIds.convert.includes(id))),
    }))
    void refreshStorageUsage()
  }, [itemIds, refreshStorageUsage])

  const toggleSelected = (section: HistorySection, entryId: string, selected: boolean) => {
    setSelectedBySection((current) => {
      const next = new Set(current[section])
      if (selected) next.add(entryId)
      else next.delete(entryId)
      return { ...current, [section]: next }
    })
  }

  const toggleAll = () => {
    setSelectedBySection((current) => Object.fromEntries(historySections.map((section) => [
      section,
      visibleSections.includes(section) ? (allSelected ? new Set() : new Set(itemIds[section])) : current[section],
    ])) as Record<HistorySection, Set<string>>)
  }

  const deleteSelection = async () => {
    if (selectedCount === 0) return
    setDeleting(true)
    setDeleteError("")
    try {
      const selectedGenerations = history.filter((entry) => selectedBySection.generate.has(entry.id))
      const selectedExtractions = extractionHistory.filter((entry) => selectedBySection.extract.has(entry.id))
      const selectedConversions = convertHistory.filter((entry) => selectedBySection.convert.has(entry.id))
      if (selectedGenerations.length > 0) await onTrashGenerated(selectedGenerations)
      if (selectedExtractions.length > 0) await onTrashExtractions(selectedExtractions)
      if (selectedConversions.length > 0) await onTrashConversions(selectedConversions)
      setSelectedBySection({ generate: new Set(), extract: new Set(), convert: new Set() })
      setDeleteOpen(false)
    } catch (reason) {
      setDeleteError(reason instanceof Error ? reason.message : "Unable to move the selected history outputs to Trash.")
    } finally {
      setDeleting(false)
    }
  }

  const sectionMeta = ({
    all: { title: "All activity", description: "Generated stacks, extraction jobs and conversions share one review surface.", countLabel: visibleItemCount === 1 ? "item" : "items" },
    generate: { title: "Generations", description: "Previously rendered stacks remain available here.", countLabel: history.length === 1 ? "generation" : "generations" },
    extract: { title: "Extractions", description: "Quick Extract jobs and full folder batches share one timeline with a distinct source type.", countLabel: extractionHistory.length === 1 ? "extraction" : "extractions" },
    convert: { title: "Quick Convert", description: "Completed one-file conversions remain easy to locate or drag back into your workflow.", countLabel: convertHistory.length === 1 ? "conversion" : "conversions" },
  } satisfies Record<SectionId, { title: string; description: string; countLabel: string }>)[activeSection]
  const activeUsage = activeSection === "all"
    ? historySections.reduce<GenerationStorageUsage | null>((total, section) => {
      const usage = storageUsage[section]
      if (!usage) return total
      return {
        bytes: (total?.bytes ?? 0) + usage.bytes,
        folders: (total?.folders ?? 0) + usage.folders,
        files: (total?.files ?? 0) + usage.files,
      }
    }, null)
    : storageUsage[activeSection]
  const activeStorageError = activeSection === "all"
    ? historySections.map((section) => storageError[section]).filter(Boolean).join(" ")
    : storageError[activeSection]

  return (
    <div className={cn("page-stack history-page", activeSection === "all" && "is-all")}>
      <PageHeader
        eyebrow="Workspace"
        title="Activity history"
        description="Reopen, export or remove generated loops, extraction jobs and conversions from one consistent workspace."
        titleActions={<Button className="location-button" variant="outline" size="sm" onClick={() => void window.stemSlicer?.openHistoryRoot()}><FolderOpen aria-hidden="true" /> Location</Button>}
      />

      <div className="workspace-filter-bar" role="group" aria-label="Filter activity history">
        {([
          { id: "all" as const, label: "All", icon: ListFilter, count: history.length + extractionHistory.length + convertHistory.length },
          { id: "generate" as const, label: "Generate", icon: Sparkles, count: history.length },
          { id: "extract" as const, label: "Extract", icon: Scissors, count: extractionHistory.length },
          { id: "convert" as const, label: "Convert", icon: Repeat2, count: convertHistory.length },
        ]).map(({ id, label, icon: Icon, count }) => (
          <button
            key={id}
            type="button"
            aria-pressed={activeSection === id}
            className="workspace-filter-chip"
            data-section={id}
            onClick={() => setActiveSection(id)}
          >
            <Icon aria-hidden="true" />
            <span>{label}</span>
            <b className="tabular">{count}</b>
          </button>
        ))}
      </div>

      <div className="history-section-heading app-no-drag">
        <div>
          <div className="history-title-line">
            <h2>{sectionMeta.title}</h2>
            <span>{formatCount(visibleItemCount)} {sectionMeta.countLabel}</span>
            <span title={activeStorageError || (activeUsage ? `${activeUsage.files} files` : "Calculating storage")}>{activeUsage ? formatDecimalBytes(activeUsage.bytes) : "…"}</span>
          </div>
          <p>{sectionMeta.description}</p>
        </div>
        <div className="history-selection-actions" aria-live="polite">
          <span>{selectedCount > 0 ? `${selectedCount} selected` : "Nothing selected"}</span>
          <Button variant="outline" size="sm" disabled={visibleItemCount === 0} aria-pressed={allSelected} onClick={toggleAll}>
            {allSelected ? <Square aria-hidden="true" /> : <CheckSquare2 aria-hidden="true" />}
            {allSelected ? "Clear selection" : "Select all"}
          </Button>
          <Button variant="destructive" size="sm" disabled={selectedCount === 0} onClick={() => setDeleteOpen(true)}>
            <Trash2 aria-hidden="true" /> Move selected to Trash
          </Button>
        </div>
      </div>

      <div className="history-panels">
      {activeSection === "all" || activeSection === "generate" ? <section id="history-panel-generate" className="history-panel">
      {history.length ? (
        <div className="history-list">
          {history.map((entry) => {
            const credits = uniqueProducerNames(entry.producers)
            return (
              <Card key={entry.id} className={cn("history-item", selectedBySection.generate.has(entry.id) && "is-selected")}>
                <CardContent>
                  <label className="history-select-control">
                    <input
                      type="checkbox"
                      checked={selectedBySection.generate.has(entry.id)}
                      onChange={(event) => toggleSelected("generate", entry.id, event.target.checked)}
                    />
                    <span className="sr-only">Select {entry.displayName} from {entry.createdAt}</span>
                  </label>
                  <span className="history-icon"><History aria-hidden="true" /></span>
                  <details className="history-generation-details">
                    <summary>
                      <span><strong>{entry.displayName}</strong><small>{entry.createdAt} · {entry.layerCount} layers · {sourceOriginSummary(entry.layers)}</small></span>
                      <ChevronDown aria-hidden="true" />
                    </summary>
                    <div className="history-source-breakdown">
                      <p>Source attribution</p>
                      <ul>
                        {entry.layers.map((layer, index) => {
                          const provenance = provenanceForLayer(layer)
                          return (
                            <li key={`${entry.id}-${layer.identity ?? layer.id}-${index}`}>
                              <span className="history-source-index tabular">{String(index + 1).padStart(2, "0")}</span>
                              <ProducerAvatarStack producers={provenance.producers} />
                              <span className="history-source-copy">
                                <strong title={stripAudioExtension(layer.sourceFile ?? layer.file)}>{provenance.loopName}</strong>
                                <small>{provenance.producers.join(", ")}</small>
                              </span>
                              <SourceOriginIcon origin={sourceOriginForLayer(layer)} />
                              <Badge variant="secondary">{layer.category}</Badge>
                            </li>
                          )
                        })}
                      </ul>
                    </div>
                  </details>
                  <div className="history-spec">
                    <span className="history-credit-line" title={credits.join(", ")}>
                      <ProducerAvatarStack producers={credits} />
                      {credits.join(", ")}
                    </span>
                    <span>{entry.bpm} BPM</span>
                    <span>{entry.keyName}</span>
                  </div>
                  <div className="history-actions">
                    <HistoryPlayButton entry={entry} playing={playback.playing && playback.mode === "solo" && playback.soloId === historyLayerId(entry.id)} onToggle={() => onTogglePlayback(entry)} />
                    <Button className="location-button" variant="outline" size="sm" onClick={() => void window.stemSlicer?.revealPath(entry.generation.outputDirectory)}><FolderOpen aria-hidden="true" /> Location</Button>
                    <Button variant="outline" className="history-reload" size="sm" onClick={() => onReopen(entry)}><RefreshCw aria-hidden="true" /> Reload</Button>
                    <Button variant="outline" size="sm" draggable onClick={() => void window.stemSlicer?.revealPath(entry.generation.masterPath)} onDragStart={(event) => { event.preventDefault(); onMarkExported(entry); window.stemSlicer?.startFileDrag(entry.generation.masterPath) }}><AudioLines aria-hidden="true" /> Drag</Button>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      ) : (
        <EmptyState icon={History} title="No generation yet" description="Generated loops will appear here with their source attribution and producer credits." action={<span className="empty-hint">Open Generate to create the first entry.</span>} />
      )}
      </section> : null}

      {activeSection === "all" || activeSection === "extract" ? <section id="history-panel-extract" className="history-panel">
        {extractionHistory.length > 0 ? <div className="activity-history-list">
          {extractionHistory.map((entry) => (
            <Card key={entry.id} className={cn("activity-history-item", selectedBySection.extract.has(entry.id) && "is-selected")}>
              <CardContent>
                <label className="history-select-control activity-select-control">
                  <input type="checkbox" checked={selectedBySection.extract.has(entry.id)} onChange={(event) => toggleSelected("extract", entry.id, event.target.checked)} />
                  <span className="sr-only">Select extraction {basename(entry.sourcePath)}</span>
                </label>
                <span className={cn("activity-history-icon", entry.mode === "folder" && "is-folder")}>
                  {entry.mode === "folder" ? <FolderOpen aria-hidden="true" /> : <Music2 aria-hidden="true" />}
                </span>
                <div className="activity-history-copy">
                  <strong title={entry.sourcePath}>{basename(entry.sourcePath)}</strong>
                  <small>{new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(entry.createdAt))} · {entry.mode === "folder" ? `${formatCount(entry.sourceFileCount)} source files` : "1 source loop"}</small>
                </div>
                <Badge variant={entry.mode === "folder" ? "warning" : "secondary"}>{entry.mode === "folder" ? "Folder extraction" : "Quick Extract"}</Badge>
                <div className="activity-history-metrics">
                  <span><b>{formatCount(entry.outputCount)}</b> outputs</span>
                  {entry.elapsedSeconds != null ? <span><b>{entry.elapsedSeconds.toFixed(1)} s</b> elapsed</span> : null}
                </div>
                <div className="activity-history-actions">
                  <Button className="location-button" variant="outline" size="sm" onClick={() => void window.stemSlicer?.revealPath(entry.outputFolder)}><FolderOpen aria-hidden="true" /> Location</Button>
                  {entry.outputs.length > 0 ? <Button variant="outline" size="sm" onClick={() => window.stemSlicer?.startFilesDrag(entry.outputs)}><AudioLines aria-hidden="true" /> Drag</Button> : null}
                </div>
              </CardContent>
            </Card>
          ))}
        </div> : <EmptyState icon={Scissors} title="No extraction history yet" description="Quick Extract results and completed folder extractions will appear here automatically." action={<span className="empty-hint">Run an extraction to create the first entry.</span>} />}
      </section> : null}

      {activeSection === "all" || activeSection === "convert" ? <section id="history-panel-convert" className="history-panel">
        {convertHistory.length > 0 ? <div className="activity-history-list">
          {convertHistory.map((entry) => (
            <Card key={entry.id} className={cn("activity-history-item", selectedBySection.convert.has(entry.id) && "is-selected")}>
              <CardContent>
                <label className="history-select-control activity-select-control">
                  <input type="checkbox" checked={selectedBySection.convert.has(entry.id)} onChange={(event) => toggleSelected("convert", entry.id, event.target.checked)} />
                  <span className="sr-only">Select conversion {basename(entry.sourcePath)}</span>
                </label>
                <span className="activity-history-icon is-convert"><Repeat2 aria-hidden="true" /></span>
                <div className="activity-history-copy">
                  <strong title={entry.sourcePath}>{basename(entry.sourcePath)}</strong>
                  <small>{new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(entry.createdAt))} · {entry.elapsedSeconds.toFixed(1)} s</small>
                </div>
                {entry.recovered ? <Badge variant="secondary">Existing output</Badge> : <div className="activity-convert-route">
                  <span>{entry.sourceBpm} BPM · {entry.sourceKey || "—"}</span>
                  <ChevronDown aria-hidden="true" />
                  <b>{entry.targetBpm} BPM · {entry.targetKey}</b>
                </div>}
                <div className="activity-history-metrics">{entry.artifact.duration > 0 ? <span><b>{entry.artifact.duration.toFixed(1)} s</b> audio</span> : null}<span><b>{formatDecimalBytes(entry.artifact.bytes)}</b> file</span></div>
                <div className="activity-history-actions">
                  <Button className="location-button" variant="outline" size="sm" onClick={() => void window.stemSlicer?.revealPath(entry.artifact.path)}><FolderOpen aria-hidden="true" /> Location</Button>
                  <Button variant="outline" size="sm" draggable onDragStart={(event) => { event.preventDefault(); window.stemSlicer?.startFileDrag(entry.artifact.path) }}><AudioLines aria-hidden="true" /> Drag</Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div> : <EmptyState icon={Repeat2} title="No conversion history yet" description="Completed Quick Convert files will appear here automatically." action={<span className="empty-hint">Open Slicer to convert the first loop.</span>} />}
      </section> : null}
      {activeSection === "all" && visibleItemCount === 0 ? <EmptyState icon={History} title="No activity yet" description="Generated loops, extraction jobs and conversions will appear in this timeline." action={<span className="empty-hint">Create an output to add the first item.</span>} /> : null}
      </div>

      <Dialog.Root open={deleteOpen} onOpenChange={(open) => { setDeleteOpen(open); if (!open) setDeleteError("") }}>
        <Dialog.Portal>
          <Dialog.Backdrop className="dialog-backdrop" />
          <Dialog.Viewport className="dialog-viewport">
            <Dialog.Popup className="confirmation-dialog destructive-confirmation-dialog">
              <span className="confirmation-dialog-icon"><Trash2 aria-hidden="true" /></span>
              <Dialog.Title>Move {selectedCount} {selectedCount === 1 ? "history output" : "history outputs"} to Trash?</Dialog.Title>
              <Dialog.Description>
                The selected Slicer output folders and their audio files will move to the macOS Trash. Indexed source libraries remain untouched.
              </Dialog.Description>
              {deleteError ? <p className="dialog-inline-error" role="alert">{deleteError}</p> : null}
              <footer>
                <Dialog.Close className="dialog-cancel" disabled={deleting}>Cancel</Dialog.Close>
                <Button variant="destructive" disabled={deleting} onClick={() => void deleteSelection()}>
                  <Trash2 aria-hidden="true" /> {deleting ? "Moving…" : "Move outputs to Trash"}
                </Button>
              </footer>
            </Dialog.Popup>
          </Dialog.Viewport>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  )
}

function LibraryIssueList({
  issues,
  selectedIds,
  onToggleSelected,
  onSetKeyIssueActive,
}: {
  issues: KeyIssueReport[]
  selectedIds: Set<string>
  onToggleSelected: (issueId: string, selected: boolean) => void
  onSetKeyIssueActive: (issueId: string, active: boolean) => Promise<void>
}) {
  if (issues.length === 0) return <p className="key-issues-empty">No correction has been reported in this section yet.</p>

  return (
    <div className="key-issue-list">
      {issues.map((issue) => (
        <Card key={issue.id} className={cn("key-issue-item", issue.active && "is-active", selectedIds.has(issue.id) && "is-selected")}>
          <CardContent>
            <span className={cn("key-issue-icon", issue.issueType === "wrong-slice" && "is-wrong-slice")}>
              {issue.issueType === "wrong-slice" ? <Scissors aria-hidden="true" /> : <CircleAlert aria-hidden="true" />}
            </span>
            <div className="key-issue-copy">
              <strong title={issue.reportedPath}>{issue.reportedFile}</strong>
              <small title={issue.sourceLoopId}>Source loop · {issue.sourceLoopId}</small>
              <details>
                <summary>{issue.affectedLayers.length} associated layer{issue.affectedLayers.length === 1 ? "" : "s"}</summary>
                <ul>
                  {issue.affectedLayers.map((layer) => (
                    <li key={`${issue.id}-${layer.path}`}><span title={layer.path}>{layer.file}</span><b>{layer.detectedKey}</b></li>
                  ))}
                </ul>
              </details>
            </div>
            <div className="key-issue-spec">
              <Badge variant={issue.active ? "warning" : "secondary"}>{issue.active ? "Quarantined" : "Restored"}</Badge>
              <span>{issue.issueType === "wrong-slice" ? "Wrong cut" : `Detected · ${issue.detectedKey}`}</span>
              <span>{issue.issueType === "wrong-slice" ? "Extraction review" : `Generated in · ${issue.targetKey}`}</span>
            </div>
            <div className="key-issue-actions">
              <Button className="location-button" variant="outline" size="sm" onClick={() => void window.stemSlicer?.revealPath(issue.reportedPath)}><FolderOpen aria-hidden="true" /> Location</Button>
              <Button variant={issue.active ? "outline" : "ghost"} size="sm" onClick={() => void onSetKeyIssueActive(issue.id, !issue.active)}>
                {issue.active ? <Check aria-hidden="true" /> : <CircleX aria-hidden="true" />}
                {issue.active ? "Restore" : "Exclude again"}
              </Button>
              <label className="library-history-select">
                <input type="checkbox" checked={selectedIds.has(issue.id)} onChange={(event) => onToggleSelected(issue.id, event.target.checked)} />
                <span className="sr-only">Select {issue.reportedFile} report</span>
              </label>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function LibraryView({
  keyIssues,
  categoryCorrections,
  onSetKeyIssueActive,
  onDismissKeyIssue,
  onDismissCategoryCorrections,
  onEditSourceLoop,
}: {
  keyIssues: KeyIssueReport[]
  categoryCorrections: CategoryCorrection[]
  onSetKeyIssueActive: (issueId: string, active: boolean) => Promise<void>
  onDismissKeyIssue: (issueId: string) => Promise<void>
  onDismissCategoryCorrections: (identities: string[]) => Promise<void>
  onEditSourceLoop: (request: SourceLoopStudioRequest) => void
}) {
  type CorrectionSection = "wrong-key" | "wrong-category" | "wrong-cut"
  type ReviewFilter = "all" | CorrectionSection
  const correctionSections: CorrectionSection[] = ["wrong-key", "wrong-category", "wrong-cut"]
  const [activeSection, setActiveSection] = useState<ReviewFilter>("all")
  const [selectedBySection, setSelectedBySection] = useState<Record<CorrectionSection, Set<string>>>(() => ({
    "wrong-key": new Set(),
    "wrong-category": new Set(),
    "wrong-cut": new Set(),
  }))
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [issueError, setIssueError] = useState("")
  const wrongKeyIssues = useMemo(() => keyIssues.filter((issue) => issue.issueType === "wrong-key"), [keyIssues])
  const wrongCutIssues = useMemo(() => keyIssues.filter((issue) => issue.issueType === "wrong-slice"), [keyIssues])
  const correctionIds = useMemo<Record<CorrectionSection, string[]>>(() => ({
    "wrong-key": wrongKeyIssues.map((issue) => issue.id),
    "wrong-category": categoryCorrections.map((correction) => correction.identity),
    "wrong-cut": wrongCutIssues.map((issue) => issue.id),
  }), [categoryCorrections, wrongCutIssues, wrongKeyIssues])
  const visibleCorrectionSections: CorrectionSection[] = activeSection === "all" ? correctionSections : [activeSection]
  const availableCorrectionCount = visibleCorrectionSections.reduce((sum, section) => sum + correctionIds[section].length, 0)
  const selectedCorrectionCount = visibleCorrectionSections.reduce((sum, section) => sum + correctionIds[section].filter((id) => selectedBySection[section].has(id)).length, 0)
  const allCorrectionsSelected = availableCorrectionCount > 0 && selectedCorrectionCount === availableCorrectionCount

  useEffect(() => {
    setSelectedBySection((current) => ({
      "wrong-key": new Set([...current["wrong-key"]].filter((id) => correctionIds["wrong-key"].includes(id))),
      "wrong-category": new Set([...current["wrong-category"]].filter((id) => correctionIds["wrong-category"].includes(id))),
      "wrong-cut": new Set([...current["wrong-cut"]].filter((id) => correctionIds["wrong-cut"].includes(id))),
    }))
  }, [correctionIds])

  const toggleCorrectionSelected = (section: CorrectionSection, id: string, selected: boolean) => {
    setSelectedBySection((current) => {
      const next = new Set(current[section])
      if (selected) next.add(id)
      else next.delete(id)
      return { ...current, [section]: next }
    })
  }

  const dismissSelectedCorrections = async () => {
    if (selectedCorrectionCount === 0) return
    setDeleting(true)
    setIssueError("")
    try {
      const categoryIds = [...selectedBySection["wrong-category"]]
      if (categoryIds.length > 0) await onDismissCategoryCorrections(categoryIds)
      for (const section of ["wrong-key", "wrong-cut"] as const) {
        for (const issueId of selectedBySection[section]) await onDismissKeyIssue(issueId)
      }
      setSelectedBySection({ "wrong-key": new Set(), "wrong-category": new Set(), "wrong-cut": new Set() })
      setDeleteOpen(false)
    } catch (reason) {
      setIssueError(reason instanceof Error ? reason.message : "Unable to archive the selected review items.")
    } finally {
      setDeleting(false)
    }
  }

  const correctionSectionDetails: Record<ReviewFilter, { title: string; description: string; status: string }> = {
    all: {
      title: "Review queue",
      description: "Filter retained key, category and cut feedback without changing its source data.",
      status: `${availableCorrectionCount} items`,
    },
    "wrong-key": {
      title: "Wrong key history",
      description: "Review reported key mismatches without mixing them into activity history.",
      status: `${wrongKeyIssues.filter((issue) => issue.active).length} active`,
    },
    "wrong-category": {
      title: "Wrong category history",
      description: "Every validated manual category remains traceable and editable from its source loop.",
      status: `${categoryCorrections.length} saved`,
    },
    "wrong-cut": {
      title: "Wrong cut history",
      description: "Review local extraction reports. Studio is reserved for category edits.",
      status: `${wrongCutIssues.filter((issue) => issue.active).length} active`,
    },
  }
  const activeCorrectionDetails = correctionSectionDetails[activeSection]

  return (
    <div className="page-stack library-page">
      <PageHeader eyebrow="Workspace" title="Review" description="Review local catalogue feedback without mixing corrections into activity history or Cloud management." />

      <div className="workspace-filter-bar" role="group" aria-label="Filter review items">
        {([
          { id: "all" as const, label: "All", icon: ListFilter, count: wrongKeyIssues.length + categoryCorrections.length + wrongCutIssues.length },
          { id: "wrong-key" as const, label: "Wrong key", icon: CircleAlert, count: wrongKeyIssues.length },
          { id: "wrong-category" as const, label: "Wrong category", icon: Layers3, count: categoryCorrections.length },
          { id: "wrong-cut" as const, label: "Wrong cut", icon: Scissors, count: wrongCutIssues.length },
        ]).map(({ id, label, icon: Icon, count }) => (
          <button
            key={id}
            type="button"
            aria-pressed={activeSection === id}
            className="workspace-filter-chip"
            data-section={id}
            onClick={() => setActiveSection(id)}
          >
            <Icon aria-hidden="true" />
            <span>{label}</span>
            <b className="tabular">{count}</b>
          </button>
        ))}
      </div>

      <section className="library-correction-panel">
        <div className="history-section-heading library-correction-heading">
          <div><h2>{activeCorrectionDetails.title}</h2><p>{activeCorrectionDetails.description}</p></div>
          <div className="library-selection-toolbar app-no-drag">
            <span>{selectedCorrectionCount > 0 ? `${selectedCorrectionCount} selected` : activeCorrectionDetails.status}</span>
            <Button
              variant="outline"
              size="sm"
              disabled={availableCorrectionCount === 0}
              aria-pressed={allCorrectionsSelected}
              onClick={() => setSelectedBySection((current) => Object.fromEntries(correctionSections.map((section) => [
                section,
                visibleCorrectionSections.includes(section) ? (allCorrectionsSelected ? new Set() : new Set(correctionIds[section])) : current[section],
              ])) as Record<CorrectionSection, Set<string>>)}
            >
              {allCorrectionsSelected ? <Square aria-hidden="true" /> : <CheckSquare2 aria-hidden="true" />}
              {allCorrectionsSelected ? "Clear selection" : "Select all"}
            </Button>
            <Button variant="outline" size="sm" disabled={selectedCorrectionCount === 0} onClick={() => setDeleteOpen(true)}>
              <Archive aria-hidden="true" /> Archive selected
            </Button>
          </div>
        </div>

        <div className="review-unified-list">
        {visibleCorrectionSections.includes("wrong-key") && wrongKeyIssues.length > 0 ? (
          <LibraryIssueList
            issues={wrongKeyIssues}
            selectedIds={selectedBySection["wrong-key"]}
            onToggleSelected={(id, selected) => toggleCorrectionSelected("wrong-key", id, selected)}
            onSetKeyIssueActive={onSetKeyIssueActive}
          />
        ) : null}
        {visibleCorrectionSections.includes("wrong-category") && categoryCorrections.length > 0 ? <div className="category-correction-list library-category-correction-list">
          {categoryCorrections.map((correction) => {
            const provenance = provenanceForLayer({ sourceFile: correction.filename, sourceLoopId: correction.sourceLoopId })
            const relatedIssue = keyIssues.find((issue) => sourceLoopKey(issue.libraryRoot, issue.sourceLoopId) === sourceLoopKey(correction.libraryRoot, correction.sourceLoopId))
            return (
              <Card key={correction.identity} className={cn("category-correction-item", selectedBySection["wrong-category"].has(correction.identity) && "is-selected")}>
                <CardContent>
                  <span className="category-correction-icon"><Check aria-hidden="true" /></span>
                  <div className="category-correction-copy"><strong title={stripAudioExtension(correction.filename)}>{provenance.loopName}</strong><small>{provenance.producers.join(", ")}</small></div>
                  <div className="category-correction-change"><span>{correction.previousCategory || "Unassigned"}</span><ChevronDown aria-hidden="true" /><b>{correction.correctedCategory}</b></div>
                  <time dateTime={correction.validatedAt}>{new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(correction.validatedAt))}</time>
                  <div className="category-correction-actions">
                    <Button className="location-button" variant="outline" size="sm" onClick={() => void window.stemSlicer?.revealPath(correction.path)}><FolderOpen aria-hidden="true" /> Location</Button>
                    <Button variant="outline" size="sm" onClick={() => onEditSourceLoop({ libraryRoot: correction.libraryRoot, sourceLoopId: correction.sourceLoopId, issueId: relatedIssue?.id ?? "", issueActive: relatedIssue?.active ?? false })}><Pencil aria-hidden="true" /> Studio</Button>
                    <label className="library-history-select">
                      <input type="checkbox" checked={selectedBySection["wrong-category"].has(correction.identity)} onChange={(event) => toggleCorrectionSelected("wrong-category", correction.identity, event.target.checked)} />
                      <span className="sr-only">Select {provenance.loopName} correction</span>
                    </label>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div> : null}
        {visibleCorrectionSections.includes("wrong-cut") && wrongCutIssues.length > 0 ? (
          <LibraryIssueList
            issues={wrongCutIssues}
            selectedIds={selectedBySection["wrong-cut"]}
            onToggleSelected={(id, selected) => toggleCorrectionSelected("wrong-cut", id, selected)}
            onSetKeyIssueActive={onSetKeyIssueActive}
          />
        ) : null}
        {availableCorrectionCount === 0 ? <p className="key-issues-empty">No retained feedback matches this filter.</p> : null}
        </div>
      </section>

      {issueError ? <p className="dialog-inline-error" role="alert">{issueError}</p> : null}

      <Dialog.Root open={deleteOpen} onOpenChange={(open) => { if (!deleting) setDeleteOpen(open) }}>
        <Dialog.Portal>
          <Dialog.Backdrop className="dialog-backdrop" />
          <Dialog.Viewport className="dialog-viewport">
            <Dialog.Popup className="confirmation-dialog">
              <span className="confirmation-dialog-icon"><Archive aria-hidden="true" /></span>
              <Dialog.Title>Archive {selectedCorrectionCount} {selectedCorrectionCount === 1 ? "review item" : "review items"}?</Dialog.Title>
              <Dialog.Description>
                Archived items leave Review, while source audio, category corrections, quarantines and retained feedback stay unchanged.
              </Dialog.Description>
              {issueError ? <p className="dialog-inline-error" role="alert">{issueError}</p> : null}
              <footer>
                <Dialog.Close className="dialog-cancel" disabled={deleting}>Cancel</Dialog.Close>
                <Button disabled={deleting} onClick={() => void dismissSelectedCorrections()}>
                  <Archive aria-hidden="true" /> {deleting ? "Archiving…" : "Archive items"}
                </Button>
              </footer>
            </Dialog.Popup>
          </Dialog.Viewport>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  )
}

const EMPTY_CLOUD_STATE: CloudState = {
  configured: false,
  projectUrl: "",
  authenticated: false,
  connections: [],
  libraries: [],
}

type CloudSection = "profile" | "producers" | "libraries" | "activity"

function cloudErrorMessage(reason: unknown, fallback: string): string {
  const candidate = reason instanceof Error
    ? reason.message
    : reason && typeof reason === "object" && "message" in reason
      ? reason.message
      : ""
  const rawMessage = typeof candidate === "string" ? candidate : ""
  const message = rawMessage.replace(/^Error invoking remote method '[^']+':\s*(?:Error:\s*)?/i, "").trim()
  return message && !/^(?:<none>|none|null|undefined|\[object Object\])$/i.test(message) ? message : fallback
}

function formatCloudActivityDate(value: string): string {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return value
  return new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)
}

function CloudProfileAvatar({ profile, large = false }: { profile?: CloudProfile; large?: boolean }) {
  const [failedUrl, setFailedUrl] = useState("")
  const avatarUrl = profile?.avatarUrl || ""
  return (
    <span className={cn("cloud-profile-mark", large && "is-large")} aria-hidden="true">
      {avatarUrl && failedUrl !== avatarUrl
        ? <img src={avatarUrl} alt="" onError={() => setFailedUrl(avatarUrl)} />
        : <span className="cloud-profile-mark-fallback">{producerMonogram(profile?.displayName ?? "Producer")}</span>}
    </span>
  )
}

function CloudView({ library, section, embedded = false, generationHistory = [] }: { library: LibraryOverview; section: CloudSection; embedded?: boolean; generationHistory?: HistoryEntry[] }) {
  const [activeCloudSection, setActiveCloudSection] = useState<Exclude<CloudSection, "profile">>(section === "profile" ? "producers" : section)
  const [cloud, setCloud] = useState<CloudState>(EMPTY_CLOUD_STATE)
  const [cloudActivity, setCloudActivity] = useState<CloudGenerationActivity[]>([])
  const [activityError, setActivityError] = useState("")
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [authMode, setAuthMode] = useState<"sign-in" | "sign-up">("sign-in")
  const [projectUrl, setProjectUrl] = useState("")
  const [publishableKey, setPublishableKey] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [handle, setHandle] = useState("")
  const [displayName, setDisplayName] = useState("+NRGY")
  const [friendHandle, setFriendHandle] = useState("")
  const [publishEvent, setPublishEvent] = useState<CloudPublishEvent | null>(null)
  const [profileHandle, setProfileHandle] = useState("")
  const [profileDisplayName, setProfileDisplayName] = useState("")
  const [profileBio, setProfileBio] = useState("")
  const [profileInstagram, setProfileInstagram] = useState("")
  const [profileAliases, setProfileAliases] = useState("")
  const [profileAvatarFilePath, setProfileAvatarFilePath] = useState("")
  const [sharedLibrarySortDirection, setSharedLibrarySortDirection] = useState<"asc" | "desc">("asc")
  const [pinnedSharedLibraryIds, setPinnedSharedLibraryIds] = useState<Set<string>>(new Set())
  const [pinnedProducerIds, setPinnedProducerIds] = useState<Set<string>>(new Set())
  const [libraryToRemove, setLibraryToRemove] = useState<CloudLibrarySummary | null>(null)
  const [removingLibraryIds, setRemovingLibraryIds] = useState<Set<string>>(new Set())
  const [connectionToRemoveId, setConnectionToRemoveId] = useState("")
  const [connectionRemovalError, setConnectionRemovalError] = useState("")
  const [libraryAccessTargetId, setLibraryAccessTargetId] = useState("")
  const [libraryAccessError, setLibraryAccessError] = useState("")
  const sharedSelectAllRef = useRef<HTMLInputElement>(null)
  const cloudRefreshInFlightRef = useRef<Promise<void> | null>(null)
  const cloudProfileId = cloud.profile?.id ?? ""
  const currentSection: CloudSection = section === "profile" ? "profile" : activeCloudSection

  useEffect(() => {
    if (section !== "profile") setActiveCloudSection(section)
  }, [section])

  const refreshActivity = useCallback(async () => {
    try {
      const activity = await window.stemSlicer?.getCloudGenerationActivity()
      setCloudActivity(activity ?? [])
      setActivityError("")
    } catch (reason) {
      setActivityError(cloudErrorMessage(reason, "Cloud activity is temporarily unavailable."))
    }
  }, [])

  const refresh = useCallback(async (): Promise<void> => {
    if (cloudRefreshInFlightRef.current) return cloudRefreshInFlightRef.current
    const pending = (async () => {
      const state = await window.stemSlicer?.getCloudState()
      if (!state) return
      setCloud(state)
      window.dispatchEvent(new CustomEvent(CLOUD_STATE_CHANGED_EVENT, { detail: state }))
      if (state.authenticated) await refreshActivity()
      else {
        setCloudActivity([])
        setActivityError("")
      }
    })()
    cloudRefreshInFlightRef.current = pending
    try {
      await pending
    } finally {
      if (cloudRefreshInFlightRef.current === pending) cloudRefreshInFlightRef.current = null
    }
  }, [refreshActivity])

  useEffect(() => {
    let cancelled = false
    void refresh()
      .catch((reason) => { if (!cancelled) setError(cloudErrorMessage(reason, "Cloud is unavailable.")) })
      .finally(() => { if (!cancelled) setLoading(false) })
    const unsubscribe = window.stemSlicer?.onCloudPublishEvent((event) => {
      if (event.type === "completed") {
        setPublishEvent(null)
        setNotice(event.message)
        void refresh()
      } else if (event.type === "failed") {
        setPublishEvent(event)
        setError(cloudErrorMessage(new Error(event.error || ""), "Cloud upload stopped. Check your connection, then retry the library."))
        void refresh()
      } else {
        setPublishEvent(event)
      }
    })
    return () => {
      cancelled = true
      unsubscribe?.()
    }
  }, [refresh])

  useEffect(() => {
    const synchronize = () => {
      void refresh().catch((reason) => setError(cloudErrorMessage(reason, "Cloud synchronization is unavailable.")))
    }
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") synchronize()
    }
    const interval = window.setInterval(synchronize, CLOUD_REFRESH_INTERVAL_MS)
    window.addEventListener("focus", synchronize)
    document.addEventListener("visibilitychange", onVisibilityChange)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener("focus", synchronize)
      document.removeEventListener("visibilitychange", onVisibilityChange)
    }
  }, [refresh])

  useEffect(() => {
    const onActivityChanged = () => { void refreshActivity() }
    const onActivityError = (event: Event) => {
      setActivityError(cloudErrorMessage((event as CustomEvent<unknown>).detail, "Cloud could not record this generation."))
    }
    window.addEventListener(CLOUD_ACTIVITY_CHANGED_EVENT, onActivityChanged)
    window.addEventListener(CLOUD_ACTIVITY_ERROR_EVENT, onActivityError)
    return () => {
      window.removeEventListener(CLOUD_ACTIVITY_CHANGED_EVENT, onActivityChanged)
      window.removeEventListener(CLOUD_ACTIVITY_ERROR_EVENT, onActivityError)
    }
  }, [refreshActivity])

  useEffect(() => {
    if (currentSection === "activity" && cloud.authenticated) void refreshActivity()
  }, [cloud.authenticated, currentSection, refreshActivity])

  useEffect(() => {
    if (!cloud.profile) return
    setProfileHandle(cloud.profile.handle)
    setProfileDisplayName(cloud.profile.displayName)
    setProfileBio(cloud.profile.bio ?? "")
    setProfileInstagram(cloud.profile.instagramHandle ?? "")
    setProfileAliases(cloud.profile.aliases.join(", "))
    setProfileAvatarFilePath("")
  }, [cloud.profile])

  useEffect(() => {
    if (!notice) return
    const timeout = window.setTimeout(() => setNotice(""), 3600)
    return () => window.clearTimeout(timeout)
  }, [notice])

  useEffect(() => {
    if (!cloudProfileId) {
      setPinnedSharedLibraryIds(new Set())
      setPinnedProducerIds(new Set())
      return
    }
    try {
      const storedIds = JSON.parse(window.localStorage.getItem(`slicer.cloud.pinned-libraries.${cloudProfileId}`) ?? "[]")
      setPinnedSharedLibraryIds(new Set(Array.isArray(storedIds) ? storedIds.map(String) : []))
    } catch {
      setPinnedSharedLibraryIds(new Set())
    }
    try {
      const storedIds = JSON.parse(window.localStorage.getItem(`slicer.cloud.pinned-producers.${cloudProfileId}`) ?? "[]")
      setPinnedProducerIds(new Set(Array.isArray(storedIds) ? storedIds.map(String) : []))
    } catch {
      setPinnedProducerIds(new Set())
    }
  }, [cloudProfileId])

  const perform = async (action: () => Promise<CloudState | undefined>) => {
    setBusy(true)
    setError("")
    setNotice("")
    try {
      const state = await action()
      if (state) {
        setCloud(state)
        window.dispatchEvent(new CustomEvent(CLOUD_STATE_CHANGED_EVENT, { detail: state }))
        if (state.message) setNotice(state.message)
      }
    } catch (reason) {
      setError(cloudErrorMessage(reason, "The Cloud request failed."))
      void refresh().catch(() => undefined)
    } finally {
      setBusy(false)
    }
  }

  const configure = (event: React.FormEvent) => {
    event.preventDefault()
    void perform(() => window.stemSlicer?.configureCloud({ projectUrl, publishableKey }) ?? Promise.resolve(undefined))
  }

  const authenticate = (event: React.FormEvent) => {
    event.preventDefault()
    if (authMode === "sign-up") {
      void perform(() => window.stemSlicer?.cloudSignUp({ email, password, handle, displayName }) ?? Promise.resolve(undefined))
    } else {
      void perform(() => window.stemSlicer?.cloudSignIn({ email, password }) ?? Promise.resolve(undefined))
    }
  }

  const requestConnection = (event: React.FormEvent) => {
    event.preventDefault()
    void perform(async () => {
      const state = await window.stemSlicer?.cloudConnect(friendHandle)
      if (state) {
        setFriendHandle("")
        setNotice(`Connection request sent to @${friendHandle.trim().toLowerCase()}.`)
      }
      return state
    })
  }

  const publishLibrary = async (root: string) => {
    setError("")
    setNotice("")
    setPublishEvent({ jobId: "starting", type: "progress", message: "Preparing Cloud upload…", percent: 0 })
    try {
      await window.stemSlicer?.cloudPublishLibrary(root)
    } catch (reason) {
      setError(cloudErrorMessage(reason, "The Cloud upload could not start."))
      setPublishEvent(null)
    }
  }

  const pickProfileAvatar = async () => {
    setError("")
    try {
      const result = await window.stemSlicer?.pickImageFile()
      if (!result || result.canceled || !result.paths[0]) return
      setProfileAvatarFilePath(result.paths[0])
    } catch (reason) {
      setError(cloudErrorMessage(reason, "Unable to prepare this profile image."))
    }
  }

  const saveProfile = (event: React.FormEvent) => {
    event.preventDefault()
    const aliases = profileAliases
      .split(/[,\n]/)
      .map((alias) => alias.trim())
      .filter(Boolean)
    void perform(() => window.stemSlicer?.cloudUpdateProfile({
      handle: profileHandle,
      displayName: profileDisplayName,
      bio: profileBio,
      instagramHandle: profileInstagram,
      aliases,
      avatarFilePath: profileAvatarFilePath || undefined,
    }) ?? Promise.resolve(undefined))
  }

  const toggleSharedLibraryPin = (libraryId: string) => {
    setPinnedSharedLibraryIds((currentIds) => {
      const nextIds = new Set(currentIds)
      if (nextIds.has(libraryId)) nextIds.delete(libraryId)
      else nextIds.add(libraryId)
      if (cloudProfileId) {
        window.localStorage.setItem(`slicer.cloud.pinned-libraries.${cloudProfileId}`, JSON.stringify([...nextIds]))
      }
      return nextIds
    })
  }

  const toggleProducerPin = (producerId: string) => {
    setPinnedProducerIds((currentIds) => {
      const nextIds = new Set(currentIds)
      if (nextIds.has(producerId)) nextIds.delete(producerId)
      else nextIds.add(producerId)
      if (cloudProfileId) {
        window.localStorage.setItem(`slicer.cloud.pinned-producers.${cloudProfileId}`, JSON.stringify([...nextIds]))
      }
      return nextIds
    })
  }

  const removeCloudLibrary = async (targetLibrary: CloudLibrarySummary) => {
    const removedLibraryId = targetLibrary.id
    setLibraryToRemove(null)
    setRemovingLibraryIds((currentIds) => new Set(currentIds).add(removedLibraryId))
    setError("")
    setNotice("")
    try {
      const state = await window.stemSlicer?.cloudRemoveLibrary(removedLibraryId)
      if (state) {
        setCloud(state)
        window.dispatchEvent(new CustomEvent(CLOUD_STATE_CHANGED_EVENT, { detail: state }))
        if (state.message) setNotice(state.message)
      }
      setPublishEvent((current) => (
        current?.type === "progress" || (current?.library && current.library.id !== removedLibraryId)
          ? current
          : null
      ))
    } catch (reason) {
      setError(cloudErrorMessage(reason, "The Cloud library could not be removed."))
      void refresh()
    } finally {
      setRemovingLibraryIds((currentIds) => {
        const nextIds = new Set(currentIds)
        nextIds.delete(removedLibraryId)
        return nextIds
      })
    }
  }

  const removeTrustedProducer = async () => {
    if (!connectionToRemoveId) return
    const connection = cloud.connections.find((item) => item.id === connectionToRemoveId)
    if (!connection) return
    setBusy(true)
    setConnectionRemovalError("")
    setError("")
    setNotice("")
    try {
      const state = await window.stemSlicer?.cloudRemoveConnection(connection.id)
      if (state) {
        setCloud(state)
        window.dispatchEvent(new CustomEvent(CLOUD_STATE_CHANGED_EVENT, { detail: state }))
        if (state.message) setNotice(state.message)
      }
      setPinnedProducerIds((currentIds) => {
        const nextIds = new Set(currentIds)
        nextIds.delete(connection.profile.id)
        if (cloudProfileId) {
          window.localStorage.setItem(`slicer.cloud.pinned-producers.${cloudProfileId}`, JSON.stringify([...nextIds]))
        }
        return nextIds
      })
      setConnectionToRemoveId("")
    } catch (reason) {
      setConnectionRemovalError(cloudErrorMessage(reason, "The trusted producer could not be removed."))
    } finally {
      setBusy(false)
    }
  }

  const setLibraryProducerAccess = async (libraryId: string, producerId: string, allowed: boolean) => {
    setBusy(true)
    setLibraryAccessError("")
    setError("")
    setNotice("")
    try {
      const state = await window.stemSlicer?.cloudSetLibraryProducerAccess(libraryId, producerId, allowed)
      if (state) {
        setCloud(state)
        window.dispatchEvent(new CustomEvent(CLOUD_STATE_CHANGED_EVENT, { detail: state }))
        if (state.message) setNotice(state.message)
      }
    } catch (reason) {
      setLibraryAccessError(cloudErrorMessage(reason, "Library access could not be updated."))
    } finally {
      setBusy(false)
    }
  }

  const acceptedConnections = cloud.connections.filter((connection) => connection.status === "accepted")
  const pendingConnections = cloud.connections.filter((connection) => connection.status === "pending")
  const sortedAcceptedConnections = [...acceptedConnections].sort((left, right) => {
    const pinDifference = Number(pinnedProducerIds.has(right.profile.id)) - Number(pinnedProducerIds.has(left.profile.id))
    if (pinDifference !== 0) return pinDifference
    return left.profile.displayName.localeCompare(right.profile.displayName, undefined, { numeric: true, sensitivity: "base" })
  })
  const ownLibraries = cloud.libraries.filter((item) => item.own)
  const sharedLibraries = cloud.libraries.filter((item) => !item.own && item.status === "ready")
  const ownLibraryNames = new Set(ownLibraries.map((item) => item.name))
  const unpublishedRoots = library.roots.filter((root) => !ownLibraryNames.has(root.name))
  const sharedOwnLibraries = ownLibraries.filter((item) => item.status === "ready")
  const publishedLayerCount = sharedOwnLibraries.reduce((sum, item) => sum + item.layerCount, 0)
  const publishedLoopCount = sharedOwnLibraries.reduce((sum, item) => sum + item.loopCount, 0)
  const localAvatarPreview = profileAvatarFilePath ? window.stemSlicer?.mediaUrl(profileAvatarFilePath) : ""
  const readySharedLibraries = sharedLibraries
  const enabledReadyLibraryCount = readySharedLibraries.filter((item) => item.enabledForGenerate).length
  const allReadyLibrariesEnabled = readySharedLibraries.length > 0 && enabledReadyLibraryCount === readySharedLibraries.length
  const someReadyLibrariesEnabled = enabledReadyLibraryCount > 0 && !allReadyLibrariesEnabled
  const sortedSharedLibraries = [...sharedLibraries].sort((left, right) => {
    const pinDifference = Number(pinnedSharedLibraryIds.has(right.id)) - Number(pinnedSharedLibraryIds.has(left.id))
    if (pinDifference !== 0) return pinDifference
    const nameOrder = left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" })
    return sharedLibrarySortDirection === "asc" ? nameOrder : -nameOrder
  })
  const localCloudHistory = generationHistory.filter((entry) => entry.layers.some((layer) => sourceOriginForLayer(layer) === "cloud"))
  const recordedCloudRunIds = new Set(cloudActivity.map((entry) => entry.id))
  const localOnlyCloudHistory = localCloudHistory.filter((entry) => !entry.cloudRunId || !recordedCloudRunIds.has(entry.cloudRunId))
  const connectionToRemove = cloud.connections.find((connection) => connection.id === connectionToRemoveId) ?? null
  const libraryAccessTarget = ownLibraries.find((item) => item.id === libraryAccessTargetId) ?? null

  useEffect(() => {
    if (sharedSelectAllRef.current) sharedSelectAllRef.current.indeterminate = someReadyLibrariesEnabled
  }, [currentSection, someReadyLibrariesEnabled])

  const setAllReadyLibrariesEnabled = (enabled: boolean) => {
    void perform(async () => {
      let state: CloudState | undefined
      for (const item of readySharedLibraries) {
        if (item.enabledForGenerate === enabled) continue
        state = await window.stemSlicer?.cloudSetLibraryEnabled(item.id, enabled)
      }
      return state ?? cloud
    })
  }

  return (
    <div className={cn("page-stack cloud-page", embedded && "is-embedded")}>
      {!embedded ? <PageHeader
        eyebrow="Workspace"
        title={currentSection === "profile" ? "Your Producer Profile" : "Cloud"}
        description={currentSection === "profile"
          ? "Edit the identity, credits and public details that follow your Cloud libraries."
          : "Connect producers, share libraries and review Cloud activity."}
      /> : null}

      {error ? <p className="cloud-inline-message is-error" role="alert"><CircleAlert aria-hidden="true" />{error}</p> : null}
      {notice ? <p className="cloud-inline-message" role="status"><Check aria-hidden="true" />{notice}</p> : null}

      {loading ? (
        <Card className="cloud-hero"><CardContent><CloudCog aria-hidden="true" /><p>Loading Cloud configuration…</p></CardContent></Card>
      ) : !cloud.configured ? (
        <Card className="cloud-setup-card">
          <CardHeader>
            <span className="cloud-symbol"><CloudCog aria-hidden="true" /></span>
            <div><CardTitle>Connect the test project</CardTitle><CardDescription>Use only the Project URL and publishable key from Supabase. Never paste a secret key here.</CardDescription></div>
          </CardHeader>
          <CardContent>
            <form className="cloud-form cloud-config-form" onSubmit={configure}>
              <label><span>Project URL</span><Input type="url" value={projectUrl} onChange={(event) => setProjectUrl(event.target.value)} placeholder="https://project-ref.supabase.co" required /></label>
              <label><span>Publishable key</span><Input type="password" value={publishableKey} onChange={(event) => setPublishableKey(event.target.value)} placeholder="sb_publishable_…" required /></label>
              <Button type="submit" disabled={busy}><Cloud aria-hidden="true" />{busy ? "Connecting…" : "Connect project"}</Button>
            </form>
          </CardContent>
        </Card>
      ) : !cloud.authenticated ? (
        <Card className="cloud-setup-card cloud-auth-card">
          <CardHeader>
            <span className="cloud-symbol"><UsersRound aria-hidden="true" /></span>
            <div><CardTitle>{authMode === "sign-in" ? "Sign in to Cloud" : "Create a producer account"}</CardTitle><CardDescription>{cloud.projectUrl.replace(/^https?:\/\//, "")} · encrypted local session</CardDescription></div>
          </CardHeader>
          <CardContent>
            <div className="cloud-auth-switch" role="group" aria-label="Cloud account action">
              <button type="button" className={cn(authMode === "sign-in" && "is-active")} onClick={() => setAuthMode("sign-in")}>Sign in</button>
              <button type="button" className={cn(authMode === "sign-up" && "is-active")} onClick={() => setAuthMode("sign-up")}>Create account</button>
            </div>
            {cloud.testAccounts?.length ? (
              <div className="cloud-alpha-accounts" aria-label="Local alpha accounts">
                <span>Ready-to-test accounts</span>
                <div>
                  {cloud.testAccounts.map((account) => (
                    <Button
                      key={account.id}
                      type="button"
                      variant="outline"
                      disabled={busy}
                      onClick={() => void perform(() => window.stemSlicer?.cloudSignInTestAccount(account.id) ?? Promise.resolve(undefined))}
                    >
                      <UserRound aria-hidden="true" /> Use {account.displayName}
                    </Button>
                  ))}
                </div>
                <small>Passwords stay encrypted or protected in the local alpha cache and never reach the interface.</small>
              </div>
            ) : null}
            <form className="cloud-form" onSubmit={authenticate}>
              {authMode === "sign-up" ? (
                <div className="cloud-form-pair">
                  <label><span>Producer name</span><Input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="+NRGY" required /></label>
                  <label><span>Handle</span><Input value={handle} onChange={(event) => setHandle(event.target.value)} placeholder="nrgy-test" minLength={3} required /></label>
                </div>
              ) : null}
              <div className="cloud-form-pair">
                <label><span>Email</span><Input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
                <label><span>Password</span><Input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={6} required /></label>
              </div>
              <Button type="submit" disabled={busy}>{authMode === "sign-in" ? <LogIn aria-hidden="true" /> : <Plus aria-hidden="true" />}{busy ? "Please wait…" : authMode === "sign-in" ? "Sign in" : "Create producer"}</Button>
            </form>
          </CardContent>
        </Card>
      ) : (
        <>
          {currentSection === "profile" ? (
            <section className="cloud-account-bar cloud-profile-account-bar glass-panel">
              <div className="cloud-account-identity"><strong>{cloud.profile?.displayName}</strong><span>@{cloud.profile?.handle} · {cloud.userEmail}</span></div>
              <Button variant="outline" size="sm" disabled={busy} onClick={() => void perform(() => window.stemSlicer?.cloudSignOut() ?? Promise.resolve(undefined))}><LogOut aria-hidden="true" /> Sign out</Button>
            </section>
          ) : (
            <div className="workspace-filter-bar cloud-account-nav" role="group" aria-label="Cloud sections">
              {([
                { id: "producers" as const, label: "Producers", icon: UsersRound, count: acceptedConnections.length },
                { id: "libraries" as const, label: "Libraries", icon: LibraryIcon, count: cloud.libraries.length },
                { id: "activity" as const, label: "Activity", icon: History, count: cloudActivity.length + localOnlyCloudHistory.length },
              ]).map(({ id, label, icon: Icon, count }) => (
                <button key={id} type="button" className="workspace-filter-chip" aria-pressed={activeCloudSection === id} onClick={() => setActiveCloudSection(id)}>
                  <Icon aria-hidden="true" />
                  <span>{label}</span>
                  <b className="tabular">{count}</b>
                </button>
              ))}
            </div>
          )}

          {currentSection === "profile" ? (
            <div className="cloud-profile-layout">
              <Card className="cloud-panel cloud-profile-card">
                <section className="cloud-profile-preview" aria-labelledby="cloud-profile-preview-title">
                  <div className="cloud-profile-identity">
                    {cloud.profile ? (
                      <button type="button" className="cloud-profile-avatar-edit" aria-label="Change profile photo" title="Change profile photo" onClick={() => void pickProfileAvatar()}>
                        <CloudProfileAvatar large profile={{ ...cloud.profile, avatarUrl: localAvatarPreview || cloud.profile.avatarUrl }} />
                        <span className="cloud-profile-avatar-edit-icon" aria-hidden="true"><Pencil /></span>
                      </button>
                    ) : null}
                    <div>
                      <span className="cloud-profile-kicker">Slicer producer</span>
                      <h2 id="cloud-profile-preview-title">{profileDisplayName || cloud.profile?.displayName}</h2>
                      <p>@{profileHandle || cloud.profile?.handle}</p>
                    </div>
                  </div>
                  <p className={cn("cloud-profile-bio", !profileBio && "is-empty")}>{profileBio || "Add a short bio so trusted producers know your sound and what you are building."}</p>
                  <div className="cloud-profile-links">
                    {profileInstagram ? (
                      <button type="button" onClick={() => void window.stemSlicer?.openExternalUrl(`https://instagram.com/${profileInstagram.replace(/^@/, "")}`)}>
                        <Instagram aria-hidden="true" /> @{profileInstagram.replace(/^@/, "")} <ExternalLink aria-hidden="true" />
                      </button>
                    ) : <span><Instagram aria-hidden="true" /> No Instagram added</span>}
                  </div>
                  <div className="cloud-aliases" aria-label="Producer aliases">
                    <span>Credited aliases</span>
                    <div>{profileAliases.split(/[,\n]/).map((alias) => alias.trim()).filter(Boolean).map((alias) => <i key={alias}>{alias}</i>)}</div>
                    {!profileAliases.trim() ? <small>Add every producer name used in your loop filenames to merge those credits into this profile.</small> : null}
                  </div>
                  <dl className="cloud-profile-stats">
                    <div><dt>Connections</dt><dd>{acceptedConnections.length}</dd></div>
                    <div><dt>Published loops</dt><dd>{formatCount(publishedLoopCount)}</dd></div>
                    <div><dt>Published layers</dt><dd>{formatCount(publishedLayerCount)}</dd></div>
                  </dl>
                </section>

                <section className="cloud-profile-editor" aria-labelledby="cloud-profile-editor-title">
                  <header className="cloud-profile-editor-heading">
                    <h2 id="cloud-profile-editor-title">Edit profile</h2>
                    <p>Changes appear in the preview and follow your shared libraries and generation credits.</p>
                  </header>
                  <form className="cloud-form" onSubmit={saveProfile}>
                    <div className="cloud-form-pair">
                      <label><span>Producer name</span><Input value={profileDisplayName} onChange={(event) => setProfileDisplayName(event.target.value)} maxLength={64} required /></label>
                      <label><span>Cloud handle</span><Input value={profileHandle} onChange={(event) => setProfileHandle(event.target.value)} minLength={3} maxLength={32} required /></label>
                    </div>
                    <label><span>Bio</span><textarea value={profileBio} onChange={(event) => setProfileBio(event.target.value)} maxLength={280} placeholder="Sound, placements, and the collaborators you want to meet." /><small>{profileBio.length}/280</small></label>
                    <div className="cloud-form-pair">
                      <label><span>Instagram</span><Input value={profileInstagram} onChange={(event) => setProfileInstagram(event.target.value)} placeholder="nrgyloops" maxLength={30} /></label>
                      <label><span>Producer aliases</span><Input value={profileAliases} onChange={(event) => setProfileAliases(event.target.value)} placeholder="XT, T-Next Is Here" /><small>Add every producer name used in your loop filenames. Slicer merges matching PC and Cloud credits into this profile. Separate aliases with commas.</small></label>
                    </div>
                    <footer className="cloud-profile-form-footer">
                      <Button type="submit" disabled={busy}><Check aria-hidden="true" />{busy ? "Saving…" : "Save profile"}</Button>
                    </footer>
                  </form>
                </section>
              </Card>
            </div>
          ) : null}

          {currentSection === "producers" || currentSection === "activity" ? (
            <div className="cloud-network-grid is-single-section">
              <Card className="cloud-panel cloud-producers-panel" hidden={currentSection !== "producers"}>
                <CardHeader><div><CardTitle>Trusted producers</CardTitle><CardDescription>Connect by handle. Both producers must accept before private libraries become available.</CardDescription></div><Badge>{acceptedConnections.length} connected</Badge></CardHeader>
                <CardContent>
                  <form className="cloud-connect-form" onSubmit={requestConnection}>
                    <label htmlFor="cloud-friend-handle"><span>Producer handle</span><Input id="cloud-friend-handle" value={friendHandle} onChange={(event) => setFriendHandle(event.target.value)} placeholder="producer-handle" required /></label>
                    <Button type="submit" variant="outline" disabled={busy}><UsersRound aria-hidden="true" /> Send request</Button>
                  </form>
                  <div className="cloud-connection-list">
                    {pendingConnections.map((connection) => (
                      <div className="cloud-list-row cloud-producer-row" key={connection.id}>
                        <CloudProfileAvatar profile={connection.profile} />
                        <span><strong>{connection.profile.displayName}</strong><small>@{connection.profile.handle} · {connection.direction === "incoming" ? "wants to connect" : "request sent"}</small></span>
                        <div className="cloud-producer-actions">
                          {connection.direction === "incoming" ? <Button size="sm" onClick={() => void perform(() => window.stemSlicer?.cloudAcceptConnection(connection.id) ?? Promise.resolve(undefined))}>Accept request</Button> : <Badge variant="warning">Pending</Badge>}
                          <button
                            type="button"
                            className="cloud-producer-remove"
                            aria-label={connection.direction === "incoming" ? `Decline request from ${connection.profile.displayName}` : `Cancel request to ${connection.profile.displayName}`}
                            title={connection.direction === "incoming" ? "Decline request" : "Cancel request"}
                            onClick={() => { setConnectionRemovalError(""); setConnectionToRemoveId(connection.id) }}
                          >
                            <X aria-hidden="true" />
                          </button>
                        </div>
                      </div>
                    ))}
                    {sortedAcceptedConnections.map((connection) => (
                      <div className={cn("cloud-list-row cloud-producer-row is-accepted", pinnedProducerIds.has(connection.profile.id) && "is-pinned")} key={connection.id}>
                        <CloudProfileAvatar profile={connection.profile} />
                        {connection.profile.instagramHandle ? (
                          <button
                            type="button"
                            className="cloud-producer-instagram"
                            aria-label={`Open ${connection.profile.displayName} on Instagram`}
                            title="Open Instagram profile"
                            onClick={() => void window.stemSlicer?.openExternalUrl(`https://instagram.com/${connection.profile.instagramHandle}`)}
                          >
                            <Instagram aria-hidden="true" />
                          </button>
                        ) : null}
                        <span className="cloud-producer-copy">
                          <strong>{connection.profile.displayName}</strong>
                          <small>@{connection.profile.handle}{connection.profile.aliases.length ? ` · ${connection.profile.aliases.join(", ")}` : ""}</small>
                          {connection.profile.bio ? <em>{connection.profile.bio}</em> : null}
                        </span>
                        <button
                          type="button"
                          className="cloud-producer-pin"
                          aria-pressed={pinnedProducerIds.has(connection.profile.id)}
                          aria-label={`${pinnedProducerIds.has(connection.profile.id) ? "Unpin" : "Pin"} ${connection.profile.displayName}`}
                          title={pinnedProducerIds.has(connection.profile.id) ? "Unpin producer" : "Pin producer"}
                          onClick={() => toggleProducerPin(connection.profile.id)}
                        >
                          <Pin aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          className="cloud-producer-remove"
                          aria-label={`Remove ${connection.profile.displayName} from trusted producers`}
                          title="Remove producer"
                          onClick={() => { setConnectionRemovalError(""); setConnectionToRemoveId(connection.id) }}
                        >
                          <UserMinus aria-hidden="true" />
                        </button>
                      </div>
                    ))}
                    {cloud.connections.length === 0 ? <p className="cloud-empty-copy">Connect a trusted producer to share private libraries and preserve credits.</p> : null}
                  </div>
                </CardContent>
              </Card>

              <Card className="cloud-panel cloud-activity-panel" hidden={currentSection !== "activity"}>
                <CardHeader><div><CardTitle>Cloud activity</CardTitle><CardDescription>See who generated with shared layers. Local exports are marked when audio leaves Slicer.</CardDescription></div><Badge>{cloudActivity.length + localOnlyCloudHistory.length} events</Badge></CardHeader>
                <CardContent>
                  {activityError ? <p className="cloud-activity-error" role="status"><CircleAlert aria-hidden="true" />{activityError}</p> : null}
                  <div className="cloud-activity-list">
                    {cloudActivity.map((activity) => {
                      const createdHere = activity.createdBy.id === cloud.profile?.id
                      const outsideContributors = activity.contributors.filter((producer) => producer.id !== activity.createdBy.id)
                      const ownedSourceCount = activity.sources.filter((source) => source.sourceOwner.id === cloud.profile?.id).length
                      const localHistoryEntry = generationHistory.find((entry) => entry.cloudRunId === activity.id)
                      const activityTitle = createdHere
                        ? `You generated with ${outsideContributors.map((producer) => producer.displayName).join(", ") || "your Cloud library"}`
                        : ownedSourceCount > 0
                          ? `${activity.createdBy.displayName} used your shared layers`
                          : `${activity.createdBy.displayName} generated with ${outsideContributors.map((producer) => producer.displayName).join(", ") || "Cloud layers"}`
                      return (
                        <article className="cloud-activity-row" key={activity.id}>
                          <CloudProfileAvatar profile={activity.createdBy} />
                          <div>
                            <strong>{activityTitle}</strong>
                            <small>{formatCloudActivityDate(activity.createdAt)} · {activity.sources.length} Cloud layers · {activity.targetBpm} BPM · {activity.targetKey}</small>
                            {!createdHere ? <span>{ownedSourceCount} of your layers contributed</span> : null}
                          </div>
                          <Badge variant={localHistoryEntry?.exportedAt ? "success" : "secondary"}>{localHistoryEntry?.exportedAt ? "Exported" : "Generated"}</Badge>
                        </article>
                      )
                    })}
                    {localOnlyCloudHistory.map((entry) => {
                      const cloudLayers = entry.layers.filter((layer) => sourceOriginForLayer(layer) === "cloud")
                      const signedInProducer = cloud.profile?.displayName.trim() || PRIMARY_PRODUCER
                      const contributors = uniqueProducerNames(cloudLayers.flatMap((layer) => provenanceForLayer(layer, signedInProducer).producers), signedInProducer)
                        .filter((producer) => producer.toLocaleLowerCase() !== signedInProducer.toLocaleLowerCase())
                      const contributorName = contributors.join(", ") || "a connected producer"
                      const contributorProfile: CloudProfile = {
                        id: `local-${contributorName}`,
                        handle: contributorName.toLocaleLowerCase().replace(/[^a-z0-9]+/g, "-") || "cloud",
                        displayName: contributorName,
                        aliases: [],
                      }
                      const savedDate = entry.createdAtIso ? formatCloudActivityDate(entry.createdAtIso) : `Saved at ${entry.createdAt}`
                      return (
                        <article className="cloud-activity-row" key={`local-${entry.id}`}>
                          <CloudProfileAvatar profile={contributorProfile} />
                          <div><strong>This PC used Cloud layers from {contributorName}</strong><small>{savedDate} · {cloudLayers.length} Cloud layers · {entry.bpm} BPM · {entry.keyName}</small></div>
                          <Badge variant={entry.exportedAt ? "success" : "secondary"}>{entry.exportedAt ? "Exported" : "Generated"}</Badge>
                        </article>
                      )
                    })}
                    {cloudActivity.length === 0 && localOnlyCloudHistory.length === 0 ? <p className="cloud-empty-copy">Cloud generation activity will appear here after a shared layer is selected.</p> : null}
                  </div>
                </CardContent>
              </Card>
            </div>
          ) : null}

          {currentSection === "libraries" ? (
            <div className="cloud-grid">
              <Card className="cloud-panel">
                <CardHeader><div><CardTitle>Your Cloud libraries</CardTitle><CardDescription>Pause sharing without reuploading, or remove Cloud files permanently. Local folders always stay untouched.</CardDescription></div></CardHeader>
                <CardContent>
                  <div className="cloud-library-list">
                    {ownLibraries.map((item) => {
                      const sharing = item.status === "ready"
                      const paused = item.status === "archived"
                      const removing = removingLibraryIds.has(item.id)
                      const localRoot = library.roots.find((root) => root.name === item.name)
                      const statusLabel = sharing ? "Shared" : paused ? "Paused" : item.status === "uploading" ? "Publishing" : "Upload failed"
                      return (
                        <div className={cn("cloud-list-row cloud-library-row", sharing && "is-shared", paused && "is-paused", removing && "is-removing")} key={item.id}>
                          <span className="cloud-owner-library-copy">
                            <strong title={item.name}>{item.name}</strong>
                            <small>{formatCount(item.loopCount)} loops · {formatCount(item.layerCount)} layers · {formatDecimalBytes(item.totalBytes)} stored</small>
                            {!sharing && !paused ? <Badge className="cloud-library-status" variant="secondary">{statusLabel}</Badge> : null}
                          </span>
                          <div className="cloud-owner-library-actions">
                            {removing ? (
                              <span className="cloud-library-removing" role="status" aria-label={`Removing ${item.name} from Cloud`}>
                                <Trash2 aria-hidden="true" />
                                <span aria-hidden="true">Removing</span>
                                <span className="cloud-library-removing-dots" aria-hidden="true"><i /><i /><i /></span>
                              </span>
                            ) : <div className="cloud-owner-library-buttons">
                              <Button
                                type="button"
                                className="cloud-library-icon-action"
                                variant="outline"
                                size="sm"
                                disabled={busy || acceptedConnections.length === 0}
                                aria-label={`Manage access to ${item.name}`}
                                title="Manage access"
                                onClick={() => { setLibraryAccessError(""); setLibraryAccessTargetId(item.id) }}
                              >
                                <ShieldCheck aria-hidden="true" />
                              </Button>
                              {sharing || paused ? (
                                <Button
                                  type="button"
                                  className="cloud-library-icon-action"
                                  variant="outline"
                                  size="sm"
                                  disabled={busy}
                                  aria-label={`${paused ? "Resume" : "Pause"} sharing ${item.name}`}
                                  title={paused ? "Resume sharing" : "Pause sharing"}
                                  onClick={() => void perform(() => window.stemSlicer?.cloudSetLibrarySharing(item.id, paused) ?? Promise.resolve(undefined))}
                                >
                                  {paused ? <RefreshCw aria-hidden="true" /> : <Pause aria-hidden="true" />}
                                </Button>
                              ) : null}
                              {(item.status === "failed" || item.status === "uploading") && localRoot ? (
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  disabled={publishEvent?.type === "progress"}
                                  onClick={() => void publishLibrary(localRoot.path)}
                                >
                                  <RefreshCw aria-hidden="true" /> {item.status === "failed" ? "Retry upload" : "Resume upload"}
                                </Button>
                              ) : null}
                              <Button
                                type="button"
                                className="cloud-library-icon-action is-destructive"
                                variant="outline"
                                size="sm"
                                disabled={busy || item.status === "uploading"}
                                aria-label={`Remove ${item.name} from Cloud`}
                                title="Remove from Cloud"
                                onClick={() => setLibraryToRemove(item)}
                              >
                                <Trash2 aria-hidden="true" />
                              </Button>
                            </div>}
                          </div>
                        </div>
                      )
                    })}
                    {unpublishedRoots.map((root) => (
                      <div className="cloud-list-row cloud-library-row" key={root.path}>
                        <span><strong>{root.name}</strong><small>{formatCount(root.layerCount)} indexed layers · only on this PC</small></span>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={Boolean(publishEvent && publishEvent.type === "progress")}
                          aria-label={`Share ${root.name} to Cloud`}
                          title="Share to Cloud"
                          onClick={() => void publishLibrary(root.path)}
                        >
                          <span>Share</span><UploadCloud aria-hidden="true" />
                        </Button>
                      </div>
                    ))}
                    {ownLibraries.length === 0 && unpublishedRoots.length === 0 ? <p className="cloud-empty-copy">Index a small test folder in Generate before publishing it.</p> : null}
                  </div>
                  {publishEvent && publishEvent.type !== "completed" ? (
                    <div className={cn("cloud-upload-progress", publishEvent.type === "failed" && "is-error")}>
                      <span><strong>{publishEvent.message}</strong><small>{publishEvent.current != null && publishEvent.total ? `${publishEvent.current}/${publishEvent.total} files` : "Private Cloud transfer"}</small></span>
                      <output>{publishEvent.percent ?? 0}%</output>
                      <i aria-hidden="true"><i style={{ width: `${publishEvent.percent ?? 0}%` }} /></i>
                    </div>
                  ) : null}
                </CardContent>
              </Card>

              <Card className="cloud-panel cloud-shared-panel">
                <CardHeader><div><CardTitle>Libraries available to Generate</CardTitle><CardDescription>Choose which libraries from connected producers Generate may use.</CardDescription></div><Badge variant={sharedLibraries.some((item) => item.enabledForGenerate) ? "success" : "warning"}>{sharedLibraries.filter((item) => item.enabledForGenerate).length} enabled</Badge></CardHeader>
                <CardContent>
                  {sharedLibraries.length > 0 ? (
                    <div className="cloud-library-toolbar">
                      <button
                        type="button"
                        className="cloud-library-sort-control"
                        aria-label={`Sort libraries by name ${sharedLibrarySortDirection === "asc" ? "descending" : "ascending"}`}
                        onClick={() => setSharedLibrarySortDirection((direction) => direction === "asc" ? "desc" : "asc")}
                      >
                        {sharedLibrarySortDirection === "asc" ? <ArrowUpNarrowWide aria-hidden="true" /> : <ArrowDownWideNarrow aria-hidden="true" />}
                        Name {sharedLibrarySortDirection === "asc" ? "A–Z" : "Z–A"}
                      </button>
                      <label className="cloud-select-all-control">
                        <span>{allReadyLibrariesEnabled ? "Clear all" : "Select all"}</span>
                        <input
                          className="slicer-checkbox"
                          ref={sharedSelectAllRef}
                          type="checkbox"
                          checked={allReadyLibrariesEnabled}
                          aria-checked={someReadyLibrariesEnabled ? "mixed" : allReadyLibrariesEnabled}
                          disabled={readySharedLibraries.length === 0 || busy}
                          onChange={(event) => setAllReadyLibrariesEnabled(event.target.checked)}
                        />
                      </label>
                    </div>
                  ) : null}
                  <div className="cloud-shared-grid">
                    {sortedSharedLibraries.map((item) => {
                      const libraryInputId = `cloud-library-${item.id.replace(/[^a-z0-9_-]/gi, "-")}`
                      return (
                        <div className={cn("cloud-shared-library", item.enabledForGenerate && "is-enabled", pinnedSharedLibraryIds.has(item.id) && "is-pinned")} key={item.id}>
                          <label className="cloud-shared-library-main" htmlFor={libraryInputId}>
                            <CloudProfileAvatar profile={item.owner} />
                            <span><strong>{item.name}</strong><small>{item.owner.displayName} · {formatCount(item.loopCount)} loops · {formatCount(item.layerCount)} layers · {formatDecimalBytes(item.totalBytes)}</small></span>
                          </label>
                          <button
                            type="button"
                            className="cloud-library-pin"
                            aria-pressed={pinnedSharedLibraryIds.has(item.id)}
                            aria-label={`${pinnedSharedLibraryIds.has(item.id) ? "Unpin" : "Pin"} ${item.name}`}
                            onClick={() => toggleSharedLibraryPin(item.id)}
                          >
                            <Pin aria-hidden="true" />
                          </button>
                          <input
                            id={libraryInputId}
                            className="slicer-checkbox"
                            type="checkbox"
                            checked={item.enabledForGenerate}
                            disabled={item.status !== "ready" || busy}
                            aria-label={`${item.enabledForGenerate ? "Disable" : "Enable"} ${item.name} for Generate`}
                            onChange={(event) => void perform(() => window.stemSlicer?.cloudSetLibraryEnabled(item.id, event.target.checked) ?? Promise.resolve(undefined))}
                          />
                        </div>
                      )
                    })}
                  </div>
                  {sharedLibraries.length === 0 ? <p className="cloud-empty-copy">Shared libraries from connected producers will appear here.</p> : null}
                </CardContent>
              </Card>
            </div>
          ) : null}

          <Dialog.Root
            open={Boolean(connectionToRemove)}
            onOpenChange={(open) => {
              if (!open && !busy) {
                setConnectionToRemoveId("")
                setConnectionRemovalError("")
              }
            }}
          >
            <Dialog.Portal>
              <Dialog.Backdrop className="dialog-backdrop" />
              <Dialog.Viewport className="dialog-viewport">
                <Dialog.Popup className="confirmation-dialog destructive-confirmation-dialog">
                  <span className="confirmation-dialog-icon"><UserMinus aria-hidden="true" /></span>
                  <Dialog.Title>{connectionToRemove?.status === "accepted" ? `Remove ${connectionToRemove.profile.displayName}?` : connectionToRemove?.direction === "incoming" ? `Decline ${connectionToRemove.profile.displayName}'s request?` : `Cancel request to ${connectionToRemove?.profile.displayName}?`}</Dialog.Title>
                  <Dialog.Description>
                    {connectionToRemove?.status === "accepted"
                      ? "Library access is removed immediately in both directions. Local files and producer profiles remain unchanged."
                      : "The pending connection request is removed. You can send a new request later."}
                  </Dialog.Description>
                  {connectionRemovalError ? <p className="dialog-inline-error" role="alert">{connectionRemovalError}</p> : null}
                  <footer>
                    <Dialog.Close className="dialog-cancel" disabled={busy}>Cancel</Dialog.Close>
                    <Button variant="destructive" disabled={busy} onClick={() => void removeTrustedProducer()}>
                      <UserMinus aria-hidden="true" /> {busy ? "Removing…" : connectionToRemove?.status === "accepted" ? "Remove producer" : connectionToRemove?.direction === "incoming" ? "Decline request" : "Cancel request"}
                    </Button>
                  </footer>
                </Dialog.Popup>
              </Dialog.Viewport>
            </Dialog.Portal>
          </Dialog.Root>

          <Dialog.Root
            open={Boolean(libraryAccessTarget)}
            onOpenChange={(open) => {
              if (!open && !busy) {
                setLibraryAccessTargetId("")
                setLibraryAccessError("")
              }
            }}
          >
            <Dialog.Portal>
              <Dialog.Backdrop className="dialog-backdrop" />
              <Dialog.Viewport className="dialog-viewport">
                <Dialog.Popup className="confirmation-dialog cloud-access-dialog">
                  <span className="confirmation-dialog-icon"><ShieldCheck aria-hidden="true" /></span>
                  <Dialog.Title>Manage access to {libraryAccessTarget?.name}</Dialog.Title>
                  <Dialog.Description>Choose which trusted producers can use this library in Generate. Other shared libraries are unaffected.</Dialog.Description>
                  <div className="cloud-access-list">
                    {sortedAcceptedConnections.map((connection) => {
                      const allowed = !libraryAccessTarget?.blockedProducerIds.includes(connection.profile.id)
                      return (
                        <label key={connection.id}>
                          <CloudProfileAvatar profile={connection.profile} />
                          <span><strong>{connection.profile.displayName}</strong><small>@{connection.profile.handle}</small></span>
                          <input
                            className="slicer-checkbox"
                            type="checkbox"
                            checked={allowed}
                            disabled={busy}
                            aria-label={`${allowed ? "Revoke" : "Allow"} ${connection.profile.displayName}'s access to ${libraryAccessTarget?.name ?? "this library"}`}
                            onChange={(event) => libraryAccessTarget && void setLibraryProducerAccess(libraryAccessTarget.id, connection.profile.id, event.target.checked)}
                          />
                        </label>
                      )
                    })}
                    {sortedAcceptedConnections.length === 0 ? <p className="cloud-empty-copy">Connect a trusted producer before managing library access.</p> : null}
                  </div>
                  {libraryAccessError ? <p className="dialog-inline-error" role="alert">{libraryAccessError}</p> : null}
                  <footer>
                    <Button disabled={busy} onClick={() => { setLibraryAccessTargetId(""); setLibraryAccessError("") }}>Done</Button>
                  </footer>
                </Dialog.Popup>
              </Dialog.Viewport>
            </Dialog.Portal>
          </Dialog.Root>

          <Dialog.Root
            open={Boolean(libraryToRemove)}
            onOpenChange={(open) => {
              if (!open) {
                setLibraryToRemove(null)
              }
            }}
          >
            <Dialog.Portal>
              <Dialog.Backdrop className="dialog-backdrop" />
              <Dialog.Viewport className="dialog-viewport">
                <Dialog.Popup className="confirmation-dialog destructive-confirmation-dialog">
                  <span className="confirmation-dialog-icon"><Trash2 aria-hidden="true" /></span>
                  <Dialog.Title>Remove {libraryToRemove?.name} from Cloud?</Dialog.Title>
                  <Dialog.Description>
                    This permanently deletes {libraryToRemove ? formatCount(libraryToRemove.layerCount) : "the"} uploaded layers and frees their Cloud storage. The local folder and indexed library on this PC remain unchanged.
                  </Dialog.Description>
                  <footer>
                    <Dialog.Close className="dialog-cancel">Cancel</Dialog.Close>
                    <Button variant="destructive" onClick={() => libraryToRemove && void removeCloudLibrary(libraryToRemove)}>
                      <Trash2 aria-hidden="true" /> Remove from Cloud
                    </Button>
                  </footer>
                </Dialog.Popup>
              </Dialog.Viewport>
            </Dialog.Portal>
          </Dialog.Root>
        </>
      )}
    </div>
  )
}

function ScrollingPlayerTitle({ title }: { title: string }) {
  const viewportRef = useRef<HTMLElement>(null)
  const textRef = useRef<HTMLSpanElement>(null)
  const [overflowDistance, setOverflowDistance] = useState(0)

  useEffect(() => {
    const viewport = viewportRef.current
    const text = textRef.current
    if (!viewport || !text) return

    const measure = () => {
      const nextDistance = Math.max(0, Math.ceil(text.scrollWidth - viewport.clientWidth))
      setOverflowDistance((currentDistance) => currentDistance === nextDistance ? currentDistance : nextDistance)
    }
    measure()

    const resizeObserver = new ResizeObserver(measure)
    resizeObserver.observe(viewport)
    resizeObserver.observe(text)
    return () => resizeObserver.disconnect()
  }, [title])

  const scrolling = overflowDistance > 1
  const style = scrolling
    ? {
        "--player-title-shift": `-${overflowDistance}px`,
        "--player-title-duration": `${Math.max(5, overflowDistance / 24 + 3)}s`,
      } as CSSProperties
    : undefined

  return (
    <strong ref={viewportRef} className={cn("player-title", scrolling && "is-overflowing")} style={style}>
      <span ref={textRef}>{title}</span>
    </strong>
  )
}

function GlobalPlayer({ layers, playback, contextLabel, displayName }: { layers: GeneratedLayer[]; playback: PlaybackClock; contextLabel: string; displayName?: string }) {
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
  const { scrubberRef: timelineScrubberRef, clockRef: timelineClockRef } = usePlaybackProgressElements(
    playback.progressSource,
    Boolean(timelineLayer),
    duration,
  )
  const generatedName = displayName?.trim()
  const playerTitle = generatedName
    || (activeLayers.length === 1 ? stripAudioExtension(activeLayers[0].file) : "No generation loaded")
  const referenceLayer = activeLayers[0] ?? layers[0]
  const playerDetails = generatedName && referenceLayer
    ? `${layers.length} layer${layers.length === 1 ? "" : "s"} · ${referenceLayer.bpm} BPM · ${referenceLayer.keyName}`
    : activeLayers.length === 1
      ? `${activeLayers[0].category} · ${activeLayers[0].bpm} BPM · ${activeLayers[0].keyName}`
      : "Generate a loop to start the synchronized preview"
  const seekTimelineFromPointer = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!timelineLayer) return
    const bounds = event.currentTarget.getBoundingClientRect()
    if (bounds.width <= 0) return
    const nextProgress = (event.clientX - bounds.left) / bounds.width
    playback.previewScrub(timelineLayer.id, nextProgress)
  }

  return (
    <footer className="global-player app-drag-region" aria-label="Global audio preview">
      <div className="player-current app-no-drag" title={playerTitle}>
        <span className="player-art"><AudioLines aria-hidden="true" /></span>
        <div>
          <ScrollingPlayerTitle title={playerTitle} />
          <small>{playerDetails}</small>
        </div>
        {playback.error ? <Badge variant="warning" title={playback.error}>Audio unavailable</Badge> : null}
      </div>
      <div className="player-core app-no-drag">
        <div className="player-controls">
          <button type="button" className={cn("player-key player-loop-key", playback.loopEnabled && "is-active")} onClick={() => void playback.toggleLoopMode()} aria-pressed={playback.loopEnabled} aria-label={playback.loopEnabled ? "Disable loop playback" : "Enable loop playback"}><Repeat2 aria-hidden="true" /></button>
          <button type="button" className={cn("player-key player-key-primary", primaryPlaying && "is-active")} onClick={() => void playback.togglePrimary()} aria-label={syncEnabled ? mixPlaying ? "Pause all layers" : "Play all layers" : primaryPlaying ? "Pause selected layer" : "Play selected layer"}>{primaryPlaying ? <Pause aria-hidden="true" /> : <Play className="play-glyph" aria-hidden="true" />}</button>
          <button type="button" className="player-key" onClick={playback.rewind} aria-label="Stop and return to beginning"><SkipBack aria-hidden="true" /></button>
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
            <Waveform progressSource={playback.progressSource} progressActive={Boolean(timelineLayer)} compact label={`${contextLabel} waveform`} />
            <input
              ref={timelineScrubberRef}
              className="global-waveform-scrubber"
              type="range"
              min="0"
              max="1000"
              disabled={!timelineLayer}
              defaultValue="0"
              aria-label={`Position de lecture ${contextLabel}`}
              tabIndex={-1}
              onChange={(event) => timelineLayer && playback.previewScrub(timelineLayer.id, Number(event.target.value) / 1000)}
            />
          </div>
          <span ref={timelineClockRef} className="tabular">0.0 / {duration.toFixed(1)} s</span>
        </div>
      </div>
      <label className="player-volume app-no-drag"><Volume2 aria-hidden="true" /><span className="sr-only">Preview volume</span><span className="volume-range"><input type="range" min="0" max="125" value={playback.masterVolume} onChange={(event) => playback.setMasterVolume(Number(event.target.value))} /><span className="volume-unity-marker" aria-hidden="true" /></span><output className="tabular">{playback.masterVolume}%</output></label>
    </footer>
  )
}

const StableQuickToolsView = memo(QuickToolsView)
const StableGenerateView = memo(GenerateView)
const StableHistoryView = memo(HistoryView)
const StableLibraryView = memo(LibraryView)
const StableCloudView = memo(CloudView)
const StableGlobalPlayer = memo(GlobalPlayer)

export function App() {
  const [activeView, setActiveView] = useState<ViewId>("generate")
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [library, setLibrary] = useState<LibraryOverview>(FALLBACK_LIBRARY)
  const [layers, setLayers] = useState(INITIAL_LAYERS)
  const [quickPreviewLayers, setQuickPreviewLayers] = useState<GeneratedLayer[]>([])
  const [quickConvertLayer, setQuickConvertLayer] = useState<GeneratedLayer | null>(null)
  const [activeSlicerTool, setActiveSlicerTool] = useState<SlicerToolId>("slicer")
  const [history, setHistory] = useState<HistoryEntry[]>(loadGenerateHistory)
  const [extractionHistory, setExtractionHistory] = useState<ExtractionHistoryEntry[]>(loadExtractionHistory)
  const [convertHistory, setConvertHistory] = useState<ConvertHistoryEntry[]>(loadConvertHistory)
  const [generationSequence, setGenerationSequence] = useState(loadGenerationSequence)
  const [keyIssues, setKeyIssues] = useState<KeyIssueReport[]>([])
  const [categoryCorrections, setCategoryCorrections] = useState<CategoryCorrection[]>([])
  const [studioSource, setStudioSource] = useState<SourceLoopStudioRequest | null>(null)
  const [currentGenerationResult, setCurrentGenerationResult] = useState<GenerateResult | null>(null)
  const [playbackContext, setPlaybackContext] = useState<PlaybackContext>("generate")
  const [historyPlaybackLayerId, setHistoryPlaybackLayerId] = useState<string | null>(null)
  const [pendingHistoryPlaybackId, setPendingHistoryPlaybackId] = useState<string | null>(null)
  const studioActive = activeView === "library" && studioSource !== null
  const historyPlayerLayers = useMemo(() => {
    if (!historyPlaybackLayerId) return []
    const entry = history.find((item) => historyLayerId(item.id) === historyPlaybackLayerId)
    return entry ? [historyEntryToLayer(entry)] : []
  }, [history, historyPlaybackLayerId])
  const playerLayers = useMemo(() => {
    if (playbackContext === "history") return historyPlayerLayers
    if (playbackContext === "quick-extract") return quickPreviewLayers
    if (playbackContext === "quick-convert") return quickConvertLayer ? [quickConvertLayer] : []
    return layers
  }, [historyPlayerLayers, layers, playbackContext, quickConvertLayer, quickPreviewLayers])
  const stackPlayback = playbackContext !== "history" && playbackContext !== "quick-convert"
  const playback = usePlaybackClock(playerLayers, stackPlayback)
  const resetPlayback = playback.reset
  const mainRef = useRef<HTMLElement>(null)
  const initialViewRef = useRef(true)
  const activeGenerationPathRef = useRef(currentGenerationResult?.outputDirectory ?? "")
  const nextGenerationNumber = Math.max(generationSequence, 0, ...history.map((entry) => entry.generationNumber)) + 1
  const currentGenerationDisplayName = currentGenerationResult
    ? displayNameForGeneration(currentGenerationResult, layers, Math.max(1, nextGenerationNumber - 1))
    : undefined
  const historyPlaybackName = playbackContext === "history"
    ? history.find((entry) => historyLayerId(entry.id) === historyPlaybackLayerId)?.displayName
    : undefined
  const updateQuickConvertLayer = useCallback((nextLayer: GeneratedLayer | null) => {
    setQuickConvertLayer(nextLayer)
    if (nextLayer) setPlaybackContext("quick-convert")
  }, [])

  const addHistory = useCallback((entry: HistoryEntry) => {
    setHistory((items) => [entry, ...items.filter((item) => item.generation.outputDirectory !== entry.generation.outputDirectory)])
    setGenerationSequence((current) => Math.max(current, entry.generationNumber))
    const sources = entry.layers.flatMap((layer, slotIndex) => (
      layer.cloudLayerId && layer.cloudOwnerId && layer.sourceSha256 && layer.sourceLoopId
        ? [{
            slotIndex,
            cloudLayerId: layer.cloudLayerId,
            cloudOwnerId: layer.cloudOwnerId,
            sourceSha256: layer.sourceSha256,
            sourceLoopId: layer.sourceLoopId,
            category: layer.category,
          }]
        : []
    ))
    if (sources.length > 0) {
      void window.stemSlicer?.cloudRecordGeneration({
        seed: entry.generation.seed,
        targetBpm: entry.bpm,
        targetKey: entry.keyName,
        layerCount: entry.layerCount,
        sources,
      }).then((cloudRunId) => {
        if (cloudRunId) {
          setHistory((items) => items.map((item) => item.generation.outputDirectory === entry.generation.outputDirectory ? { ...item, cloudRunId } : item))
        }
        window.dispatchEvent(new Event(CLOUD_ACTIVITY_CHANGED_EVENT))
      }).catch((reason) => {
        window.dispatchEvent(new CustomEvent(CLOUD_ACTIVITY_ERROR_EVENT, { detail: reason }))
      })
    }
  }, [])

  const updateHistory = useCallback((generation: GenerateResult, updatedLayers: GeneratedLayer[]) => {
    setHistory((items) => items.map((item) => item.generation.outputDirectory === generation.outputDirectory
      ? { ...item, generation, layers: updatedLayers }
      : item))
  }, [])

  const addExtractionHistory = useCallback((entry: ExtractionHistoryEntry) => {
    setExtractionHistory((items) => prependUniqueActivity(items, entry, (item) => `${item.mode}:${item.outputFolder}`).slice(0, 100))
  }, [])

  const addConvertHistory = useCallback((entry: ConvertHistoryEntry) => {
    setConvertHistory((items) => prependUniqueActivity(items, entry, (item) => item.artifact.path).slice(0, 100))
  }, [])

  const markHistoryExported = useCallback((entry: HistoryEntry) => {
    const exportedAt = new Date().toISOString()
    setHistory((items) => items.map((item) => item.generation.outputDirectory === entry.generation.outputDirectory ? { ...item, exportedAt } : item))
  }, [])

  const markCurrentGenerationExported = useCallback((generation: GenerateResult) => {
    const exportedAt = new Date().toISOString()
    setHistory((items) => items.map((item) => item.generation.outputDirectory === generation.outputDirectory ? { ...item, exportedAt } : item))
  }, [])

  const refreshLibrary = useCallback(async () => {
    const overview = await window.stemSlicer?.getLibraryOverview()
    if (overview) setLibrary(overview)
  }, [])

  const refreshKeyIssues = useCallback(async () => {
    const issues = await window.stemSlicer?.getKeyIssueReports()
    if (issues) setKeyIssues(issues)
  }, [])

  const refreshCategoryCorrections = useCallback(async () => {
    const corrections = await window.stemSlicer?.getCategoryCorrections()
    if (corrections) setCategoryCorrections(corrections)
  }, [])

  const refreshQuickActivityHistory = useCallback(async () => {
    const snapshot = await window.stemSlicer?.getQuickActivityHistory()
    if (!snapshot) return
    setExtractionHistory((current) => {
      const identities = new Set(current.map((entry) => `${entry.mode}:${entry.outputFolder}`))
      return [...current, ...snapshot.extractions.filter((entry) => !identities.has(`${entry.mode}:${entry.outputFolder}`))]
        .sort((left, right) => right.createdAt.localeCompare(left.createdAt))
        .slice(0, 100)
    })
    setConvertHistory((current) => {
      const identities = new Set(current.map((entry) => entry.artifact.path))
      return [...current, ...snapshot.conversions.filter((entry) => !identities.has(entry.artifact.path))]
        .sort((left, right) => right.createdAt.localeCompare(left.createdAt))
        .slice(0, 100)
    })
  }, [])

  const reportKeyIssue = useCallback(async (request: ReportKeyIssueRequest) => {
    const issues = await window.stemSlicer?.reportKeyIssue(request)
    if (!issues) throw new Error("The desktop key-feedback service is unavailable.")
    setKeyIssues(issues)
  }, [])

  const updateKeyIssueState = useCallback(async (issueId: string, active: boolean) => {
    const issues = await window.stemSlicer?.setKeyIssueActive(issueId, active)
    if (!issues) throw new Error("The desktop key-feedback service is unavailable.")
    setKeyIssues(issues)
  }, [])

  const dismissKeyIssue = useCallback(async (issueId: string) => {
    const issues = await window.stemSlicer?.dismissKeyIssueReport(issueId)
    if (!issues) throw new Error("The desktop key-feedback service is unavailable.")
    setKeyIssues(issues)
  }, [])

  const dismissCategoryCorrectionHistory = useCallback(async (identities: string[]) => {
    const corrections = await window.stemSlicer?.dismissCategoryCorrections(identities)
    if (!corrections) throw new Error("The desktop category-correction service is unavailable.")
    setCategoryCorrections(corrections)
  }, [])

  useEffect(() => {
    const api = window.stemSlicer
    if (!api) return
    void refreshLibrary()
    void refreshKeyIssues()
    void refreshCategoryCorrections()
    void refreshQuickActivityHistory()
  }, [refreshCategoryCorrections, refreshKeyIssues, refreshLibrary, refreshQuickActivityHistory])

  useEffect(() => {
    try {
      window.localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(history))
    } catch {
      // History persistence is best-effort; generated files remain on disk.
    }
  }, [history])

  useEffect(() => {
    try {
      window.localStorage.setItem(EXTRACTION_HISTORY_STORAGE_KEY, JSON.stringify(extractionHistory))
    } catch {
      // Completed files stay on disk even if renderer history cannot be persisted.
    }
  }, [extractionHistory])

  useEffect(() => {
    try {
      window.localStorage.setItem(CONVERT_HISTORY_STORAGE_KEY, JSON.stringify(convertHistory))
    } catch {
      // Completed files stay on disk even if renderer history cannot be persisted.
    }
  }, [convertHistory])

  useEffect(() => {
    try {
      window.localStorage.setItem(GENERATION_SEQUENCE_STORAGE_KEY, String(generationSequence))
    } catch {
      // Rendered filenames still retain their generation number if local storage is unavailable.
    }
  }, [generationSequence])

  useEffect(() => {
    const activeLabel = activeView === "profile" ? "Profile" : NAVIGATION.find((item) => item.id === activeView)?.label ?? "Slicer"
    document.title = `${studioActive ? "Studio" : activeLabel} · Slicer`
    if (initialViewRef.current) {
      initialViewRef.current = false
      return
    }
    mainRef.current?.focus()
  }, [activeView, studioActive])

  useEffect(() => {
    if (!pendingHistoryPlaybackId || playbackContext !== "history") return
    const targetId = pendingHistoryPlaybackId
    setPendingHistoryPlaybackId(null)
    void playback.toggleLayer(targetId)
  }, [pendingHistoryPlaybackId, playback, playbackContext])

  useEffect(() => {
    const nextPath = currentGenerationResult?.outputDirectory ?? ""
    if (!nextPath || nextPath === activeGenerationPathRef.current) return
    activeGenerationPathRef.current = nextPath
    setPlaybackContext("generate")
  }, [currentGenerationResult])

  useEffect(() => {
    if (activeView === "generate") {
      setPlaybackContext("generate")
      return
    }
    if (activeView !== "stem-slicer") return
    if (activeSlicerTool === "extract" && quickPreviewLayers.length > 0) {
      setPlaybackContext("quick-extract")
    } else if (activeSlicerTool === "convert" && quickConvertLayer) {
      setPlaybackContext("quick-convert")
    }
  }, [activeSlicerTool, activeView, quickConvertLayer, quickPreviewLayers.length])

  useEffect(() => {
    if (studioActive) return
    const blockSpaceActivation = (event: KeyboardEvent) => {
      if (event.code !== "Space") return
      const target = event.target instanceof HTMLElement ? event.target : null
      if (target?.closest("input, textarea, select, [contenteditable='true'], [role='textbox'], [role='combobox'], [role='listbox']")) return
      event.preventDefault()
      event.stopPropagation()
    }
    document.addEventListener("keydown", blockSpaceActivation, true)
    return () => document.removeEventListener("keydown", blockSpaceActivation, true)
  }, [studioActive])

  const navigateToView = useCallback((view: ViewId) => {
    if (view === activeView) return
    if (view !== "library") setStudioSource(null)
    setActiveView(view)
  }, [activeView])

  const openSourceLoopStudio = useCallback((request: SourceLoopStudioRequest) => {
    resetPlayback()
    setStudioSource(request)
  }, [resetPlayback])

  const closeSourceLoopStudio = useCallback(() => {
    setStudioSource(null)
  }, [])

  const toggleHistoryPlayback = useCallback((entry: HistoryEntry) => {
    const targetId = historyLayerId(entry.id)
    if (playbackContext === "history" && historyPlaybackLayerId === targetId) {
      void playback.toggleLayer(targetId)
      return
    }
    playback.reset()
    setHistoryPlaybackLayerId(targetId)
    setPendingHistoryPlaybackId(targetId)
    setPlaybackContext("history")
  }, [historyPlaybackLayerId, playback, playbackContext])

  const reopenHistory = useCallback((entry: HistoryEntry) => {
    playback.reset()
    setLayers(entry.layers)
    setCurrentGenerationResult(entry.generation)
    setActiveView("generate")
  }, [playback])

  const trashHistoryEntries = useCallback(async (entries: HistoryEntry[]) => {
    playback.reset()
    const api = window.stemSlicer
    if (!api) throw new Error("The desktop Trash service is unavailable.")
    const movedIds = new Set<string>()
    const failures: string[] = []
    for (const entry of entries) {
      try {
        await api.trashHistoryPath({ kind: "generate", targetPath: entry.generation.outputDirectory })
        movedIds.add(entry.id)
      } catch {
        failures.push(entry.recipe)
      }
    }
    setHistory((items) => items.filter((item) => !movedIds.has(item.id)))
    if (entries.some((entry) => currentGenerationResult?.outputDirectory === entry.generation.outputDirectory)) {
      setCurrentGenerationResult(null)
      setLayers(INITIAL_LAYERS)
    }
    if (failures.length > 0) {
      throw new Error(`${failures.length} generation${failures.length === 1 ? "" : "s"} could not be moved to Trash.`)
    }
  }, [currentGenerationResult?.outputDirectory, playback])

  const trashExtractionEntries = useCallback(async (entries: ExtractionHistoryEntry[]) => {
    const api = window.stemSlicer
    if (!api) throw new Error("The desktop Trash service is unavailable.")
    const movedIds = new Set<string>()
    const failures: string[] = []
    for (const entry of entries) {
      try {
        await api.trashHistoryPath({ kind: "extract", targetPath: entry.outputFolder })
        movedIds.add(entry.id)
      } catch {
        failures.push(basename(entry.sourcePath))
      }
    }
    setExtractionHistory((items) => items.filter((item) => !movedIds.has(item.id)))
    if (failures.length > 0) throw new Error(`${failures.length} extraction output${failures.length === 1 ? "" : "s"} could not be moved to Trash.`)
  }, [])

  const trashConvertEntries = useCallback(async (entries: ConvertHistoryEntry[]) => {
    const api = window.stemSlicer
    if (!api) throw new Error("The desktop Trash service is unavailable.")
    const movedIds = new Set<string>()
    const failures: string[] = []
    for (const entry of entries) {
      try {
        await api.trashHistoryPath({ kind: "convert", targetPath: entry.outputFolder })
        movedIds.add(entry.id)
      } catch {
        failures.push(basename(entry.sourcePath))
      }
    }
    setConvertHistory((items) => items.filter((item) => !movedIds.has(item.id)))
    if (failures.length > 0) throw new Error(`${failures.length} conversion output${failures.length === 1 ? "" : "s"} could not be moved to Trash.`)
  }, [])

  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">Aller au contenu principal</a>
      <AppSidebar activeView={activeView} collapsed={sidebarCollapsed} onNavigate={navigateToView} onToggle={() => setSidebarCollapsed((value) => !value)} />
      <div className="app-workspace">
        <main id="main-content" tabIndex={-1} ref={mainRef} className={cn(activeView === "generate" && "generate-main", activeView === "stem-slicer" && "quick-tools-main", activeView === "history" && "history-main", activeView === "library" && !studioActive && "library-main", activeView === "cloud" && "cloud-main", activeView === "profile" && "profile-main", studioActive && "studio-main")}>
          <div className={cn("workspace-view-slicer", activeView === "stem-slicer" && "is-active")} aria-hidden={activeView !== "stem-slicer"}><StableQuickToolsView activeTool={activeSlicerTool} previewLayers={quickPreviewLayers} setPreviewLayers={setQuickPreviewLayers} convertLayer={quickConvertLayer} setConvertLayer={updateQuickConvertLayer} playback={playback} onActiveToolChange={setActiveSlicerTool} onExtractionCompleted={addExtractionHistory} onConvertCompleted={addConvertHistory} /></div>
          <div hidden={activeView !== "generate"}><StableGenerateView library={library} layers={layers} setLayers={setLayers} currentGenerationResult={currentGenerationResult} setCurrentGenerationResult={setCurrentGenerationResult} onAddHistory={addHistory} onUpdateHistory={updateHistory} onMarkCurrentGenerationExported={markCurrentGenerationExported} keyIssues={keyIssues} onReportKeyIssue={reportKeyIssue} onSetKeyIssueActive={updateKeyIssueState} onLibraryRefresh={refreshLibrary} onCategoryCorrectionsRefresh={refreshCategoryCorrections} nextGenerationNumber={nextGenerationNumber} playback={playback} /></div>
          <div hidden={activeView !== "history"}><StableHistoryView history={history} extractionHistory={extractionHistory} convertHistory={convertHistory} playback={playback} onReopen={reopenHistory} onTrashGenerated={trashHistoryEntries} onTrashExtractions={trashExtractionEntries} onTrashConversions={trashConvertEntries} onMarkExported={markHistoryExported} onTogglePlayback={toggleHistoryPlayback} /></div>
          <div hidden={activeView !== "library"} className={cn("library-workspace", studioActive && "is-studio")}>
            <div hidden={studioActive}><StableLibraryView keyIssues={keyIssues} categoryCorrections={categoryCorrections} onSetKeyIssueActive={updateKeyIssueState} onDismissKeyIssue={dismissKeyIssue} onDismissCategoryCorrections={dismissCategoryCorrectionHistory} onEditSourceLoop={openSourceLoopStudio} /></div>
            {studioSource ? <SourceLoopStudio active={studioActive} {...studioSource} onSetKeyIssueActive={updateKeyIssueState} onSaved={async () => { await refreshLibrary(); await refreshCategoryCorrections() }} onClose={closeSourceLoopStudio} /> : null}
          </div>
          <div hidden={activeView !== "cloud" && activeView !== "profile"}>
            <StableCloudView library={library} section={activeView === "profile" ? "profile" : "producers"} generationHistory={history} />
          </div>
        </main>
        {!studioActive ? <StableGlobalPlayer layers={playerLayers} playback={playback} contextLabel={playbackContext === "history" ? "History generation" : playbackContext === "quick-extract" ? "Extracted stack" : playbackContext === "quick-convert" ? "Converted loop" : "Generated stack"} displayName={playbackContext === "generate" ? currentGenerationDisplayName : playbackContext === "quick-convert" ? stripAudioExtension(quickConvertLayer?.file ?? "") : historyPlaybackName} /> : null}
      </div>
    </div>
  )
}
