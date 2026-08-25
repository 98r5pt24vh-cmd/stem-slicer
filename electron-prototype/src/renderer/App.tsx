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
  Gauge,
  History,
  Layers3,
  ListFilter,
  LoaderCircle,
  Music2,
  Pause,
  Play,
  Plus,
  Radio,
  Repeat2,
  ScanLine,
  Settings2,
  SkipBack,
  Sliders,
  SlidersHorizontal,
  Sparkles,
  Square,
  WandSparkles,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

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
import type { LibraryOverview, ViewId } from "@/shared/contracts"

interface NavItem {
  id: ViewId
  label: string
  icon: LucideIcon
  shortcut?: string
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
  bars: number[]
}

interface HistoryEntry {
  id: string
  bpm: number
  keyName: string
  recipe: string
  createdAt: string
  layerCount: number
}

const NAVIGATION: NavItem[] = [
  { id: "stem-slicer", label: "Stem Slicer", icon: FolderCog, shortcut: "S" },
  { id: "quick-tools", label: "Quick Tools", icon: Wrench, shortcut: "Q" },
  { id: "generate", label: "Generate", icon: Sparkles, shortcut: "G" },
  { id: "history", label: "History", icon: History, shortcut: "H" },
  { id: "cloud", label: "Connected Libraries", icon: Cloud, badge: "WIP" },
]

const GENERATE_KEYS = [
  "C major", "C minor", "C♯ major", "C♯ minor", "D major", "D minor",
  "E♭ major", "E♭ minor", "E major", "E minor", "F major", "F minor",
  "F♯ major", "F♯ minor", "G major", "G minor", "A♭ major", "A♭ minor",
  "A major", "A minor", "B♭ major", "B♭ minor", "B major", "B minor",
]

const TARGET_KEY_FAMILIES = [
  "C major / A minor", "C♯ major / A♯ minor", "D major / B minor",
  "D♯ major / C minor", "E major / C♯ minor", "F major / D minor",
  "F♯ major / D♯ minor", "G major / E minor", "G♯ major / F minor",
  "A major / F♯ minor", "A♯ major / G minor", "B major / G♯ minor",
]

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

function usePlaybackClock(duration: number) {
  const [playing, setPlaying] = useState(false)
  const [progress, setProgress] = useState(0)
  const startedAtRef = useRef(0)
  const startingProgressRef = useRef(0)

  useEffect(() => {
    if (!playing) return

    let frame = 0
    const tick = (now: number) => {
      const elapsed = (now - startedAtRef.current) / 1000
      const next = startingProgressRef.current + elapsed / duration
      if (next >= 1) {
        setProgress(0)
        setPlaying(false)
        return
      }
      setProgress(next)
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [duration, playing])

  const toggle = useCallback(() => {
    setPlaying((current) => {
      if (!current) {
        startingProgressRef.current = progress
        startedAtRef.current = performance.now()
      }
      return !current
    })
  }, [progress])

  const stop = useCallback(() => {
    setPlaying(false)
    setProgress(0)
  }, [])

  const seek = useCallback((nextProgress: number) => {
    const clampedProgress = Math.max(0, Math.min(nextProgress, 1))
    setProgress(clampedProgress)
    startingProgressRef.current = clampedProgress
    if (playing) startedAtRef.current = performance.now()
  }, [playing])

  return { playing, progress, seek, toggle, stop }
}

type PlaybackClock = ReturnType<typeof usePlaybackClock>

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
          title={collapsed ? "Déplier la barre latérale (⌘B)" : "Stem Slicer"}
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
          title={collapsed ? "Déplier (⌘B)" : "Replier (⌘B)"}
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
              {item.shortcut ? (
                <kbd>{item.shortcut}</kbd>
              ) : null}
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
  onPlay,
  onSeek,
  onChange,
}: {
  layer: GeneratedLayer
  progress: number
  playing: boolean
  isAudible: boolean
  onPlay: () => void
  onSeek: (progress: number) => void
  onChange: (layer: GeneratedLayer) => void
}) {
  return (
    <Card className={cn("layer-card", "layer-tone-spectral", isAudible && "is-audible")} aria-label={`${layer.role}, ${layer.category}`}>
      <CardHeader>
        <div className="layer-heading">
          <div className="layer-index">{layer.role.slice(0, 1)}</div>
          <div className="min-w-0">
            <CardTitle>{layer.role}</CardTitle>
            <CardDescription className="truncate" title={layer.file}>
              {layer.file}
            </CardDescription>
          </div>
        </div>
        <Badge variant="secondary">{layer.category}</Badge>
      </CardHeader>
      <CardContent>
        <div className="layer-transport">
          <button
            type="button"
            className="card-play-button"
            onClick={onPlay}
            aria-label={playing && isAudible ? `Mettre ${layer.role} en pause` : `Lire ${layer.role} en solo`}
          >
            {playing && isAudible ? <Pause /> : <Play className="play-glyph" />}
          </button>
          <div className="waveform-reader">
            <Waveform
              progress={isAudible ? progress : 0}
              label={`Forme d’onde de ${layer.role}`}
              bars={layer.bars}
            />
            <input
              className="waveform-scrubber"
              type="range"
              min="0"
              max="1000"
              value={Math.round((isAudible ? progress : 0) * 1000)}
              aria-label={`Position de lecture de ${layer.role}`}
              onChange={(event) => onSeek(Number(event.target.value) / 1000)}
            />
            <span className="wave-time tabular" aria-hidden="true">
              {((isAudible ? progress : 0) * layer.duration).toFixed(1)} / {layer.duration.toFixed(1)} s
            </span>
          </div>
        </div>

        <div className="layer-metadata">
          <span><Gauge aria-hidden="true" /> {layer.bpm} BPM</span>
          <span><Music2 aria-hidden="true" /> {layer.keyName}</span>
          {layer.alternateKey ? (
            <span title="Deuxième clé probable"><Radio aria-hidden="true" /> {layer.alternateKey}</span>
          ) : (
            <span className="muted" title="Aucune seconde clé mesurée"><CircleAlert aria-hidden="true" /> Top-2 unavailable</span>
          )}
        </div>

        <div className="layer-controls">
          <label>
            <span>Volume</span>
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
          <label>
            <span>Octave</span>
            <select
              aria-label={`Octave de ${layer.role}`}
              value={layer.octave}
              onChange={(event) => onChange({ ...layer, octave: Number(event.target.value) })}
            >
              <option value="-2">−2</option>
              <option value="-1">−1</option>
              <option value="0">0</option>
              <option value="1">+1</option>
              <option value="2">+2</option>
            </select>
          </label>
          <Button variant="outline" size="sm" aria-label={`Exporter ${layer.role}`}>
            <Layers3 /> Export
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
}: {
  library: LibraryOverview
  selectedPaths: string[]
  selectedLayerCount: number
  selectedCategoryCount: number
  selectionMessage: string
  onSelectedPathsChange: React.Dispatch<React.SetStateAction<string[]>>
  onAddFolder: () => Promise<void>
}) {
  const selectedSet = new Set(selectedPaths)
  const toggleLibrary = (path: string, checked: boolean) => {
    onSelectedPathsChange((current) => checked
      ? Array.from(new Set([...current, path]))
      : current.filter((item) => item !== path))
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
  onAddHistory,
  playback,
  soloId,
  setSoloId,
}: {
  library: LibraryOverview
  layers: GeneratedLayer[]
  setLayers: React.Dispatch<React.SetStateAction<GeneratedLayer[]>>
  onAddHistory: (entry: HistoryEntry) => void
  playback: PlaybackClock
  soloId: string | null
  setSoloId: React.Dispatch<React.SetStateAction<string | null>>
}) {
  const [bpm, setBpm] = useState(129)
  const [keyName, setKeyName] = useState("F minor")
  const [recipe, setRecipe] = useState("Balanced")
  const [isGenerating, setIsGenerating] = useState(false)
  const [status, setStatus] = useState("Visual transport ready")
  const [selectionMessage, setSelectionMessage] = useState("")
  const [selectedLibraryPaths, setSelectedLibraryPaths] = useState<string[]>([])
  const knownLibraryPathsRef = useRef<Set<string>>(new Set())
  const allPlaying = playback.playing && soloId === null
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

  const pickFolder = async () => {
    const result = await window.stemSlicer?.pickLibraryFolder()
    if (!result || result.canceled || result.paths.length === 0) return
    setSelectionMessage(`${basename(result.paths[0])} selected — scanning is not started automatically.`)
  }

  const handleGenerate = () => {
    if (isGenerating) return
    playback.stop()
    setIsGenerating(true)
    setStatus("Assembling a new combination…")
    window.setTimeout(() => {
      setLayers((current) =>
        current.map((layer) => ({
          ...layer,
          file: layer.file.replace(/_\d+\.wav$/, `_${Math.floor(Math.random() * 36) + 1}.wav`),
          bpm,
          keyName,
        })),
      )
      setStatus(`${layers.length} prototype cards generated`)
      setIsGenerating(false)
      onAddHistory({
        id: crypto.randomUUID(),
        bpm,
        keyName,
        recipe,
        createdAt: new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" }).format(new Date()),
        layerCount: layers.length,
      })
    }, 850)
  }

  const toggleSolo = (id: string) => {
    if (soloId === id && playback.playing) {
      playback.toggle()
      return
    }
    playback.stop()
    setSoloId(id)
    window.setTimeout(playback.toggle, 0)
  }

  const addLayerCard = () => {
    setLayers((current) => {
      const layerNumber = current.length + 1
      const waveformTemplate = INITIAL_LAYERS[current.length % INITIAL_LAYERS.length]
      return [...current, {
        id: `extra-${Date.now()}`,
        role: `Layer ${layerNumber}`,
        file: "Select a source layer",
        category: "Unassigned",
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
          <Select id="target-key" label="Target key" value={keyName} onChange={setKeyName} options={GENERATE_KEYS} forceBelow />
          <Select id="recipe" label="Recipe" value={recipe} onChange={setRecipe} options={["Balanced", "Melodic", "Minimal", "Dense"]} forceBelow />
          <div className="generate-action">
            <span className="sr-only" aria-live="polite">{status}</span>
          <Button className="hardware-button generate-hardware" size="lg" onClick={handleGenerate} disabled={isGenerating}>
              {isGenerating ? <LoaderCircle className="animate-spin" /> : <WandSparkles />}
              {isGenerating ? "Generating…" : "Generate"}
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
          <Button variant="outline" size="sm"><Layers3 /> Drag all</Button>
        </header>

        <div className="layer-scroll" tabIndex={0} aria-label="Generated layer cards">
          <div className="layer-grid">
            {layers.map((layer) => (
              <LayerCard
                key={layer.id}
                layer={layer}
                progress={playback.progress}
                playing={playback.playing}
                isAudible={allPlaying || soloId === layer.id}
                onPlay={() => toggleSolo(layer.id)}
                onSeek={(nextProgress) => {
                  if (!allPlaying && soloId !== layer.id) setSoloId(layer.id)
                  playback.seek(nextProgress)
                }}
                onChange={(next) => setLayers((current) => current.map((item) => item.id === next.id ? next : item))}
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
  type BatchStepId = "source" | "extract" | "key" | "convert"

  const [sourceFolder, setSourceFolder] = useState("")
  const [outputFolder, setOutputFolder] = useState("/Users/nrgy/Documents/Stem Slicer/Extracted Layers/Loop Pack Name")
  const [activeStep, setActiveStep] = useState<BatchStepId>("source")
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
  const stepRefs = useRef<Array<HTMLButtonElement | null>>([])

  const batchSteps: Array<{ id: BatchStepId; label: string; description: string; icon: LucideIcon }> = [
    { id: "source", label: "Source", description: sourceFolder ? basename(sourceFolder) : "Choose a loop folder", icon: FolderOpen },
    { id: "extract", label: "Extraction", description: layerExtraction ? "Enabled" : "Disabled", icon: Layers3 },
    { id: "key", label: "Key & naming", description: keyAnalysis ? "Enabled" : "Disabled", icon: ScanLine },
    { id: "convert", label: "Conversion", description: conversion ? "Enabled" : "Disabled", icon: Repeat2 },
  ]

  const enabledOperationCount = [layerExtraction, keyAnalysis, conversion].filter(Boolean).length
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

  const moveToken = (token: string, direction: -1 | 1) => {
    setNameTokens((current) => {
      const from = current.indexOf(token)
      const to = Math.max(0, Math.min(current.length - 1, from + direction))
      if (from === to) return current
      const next = [...current]
      next.splice(from, 1)
      next.splice(to, 0, token)
      return next
    })
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

  const moveBetweenSteps = (currentIndex: number, key: string) => {
    let nextIndex = currentIndex
    if (key === "ArrowRight") nextIndex = (currentIndex + 1) % batchSteps.length
    if (key === "ArrowLeft") nextIndex = (currentIndex - 1 + batchSteps.length) % batchSteps.length
    if (key === "Home") nextIndex = 0
    if (key === "End") nextIndex = batchSteps.length - 1
    if (nextIndex === currentIndex) return
    const nextStep = batchSteps[nextIndex]
    setActiveStep(nextStep.id)
    stepRefs.current[nextIndex]?.focus()
  }

  return (
    <div className="page-stack stem-slicer-page">
      <PageHeader
        eyebrow="Workspace / Stem Slicer"
        title="Stem Slicer"
        description="Configure one batch from its source folder through extraction, key naming and conversion."
      />

      <section className="batch-workflow-shell" aria-label="Stem Slicer batch workflow">
        <div className="batch-step-tabs" role="tablist" aria-label="Batch configuration steps">
          {batchSteps.map(({ id, label, description, icon: Icon }, index) => (
            <button
              key={id}
              ref={(element) => { stepRefs.current[index] = element }}
              id={`batch-step-tab-${id}`}
              type="button"
              role="tab"
              className="batch-step-tab"
              data-step={id}
              aria-selected={activeStep === id}
              aria-controls={`batch-step-panel-${id}`}
              tabIndex={activeStep === id ? 0 : -1}
              onClick={() => setActiveStep(id)}
              onKeyDown={(event) => {
                if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
                event.preventDefault()
                moveBetweenSteps(index, event.key)
              }}
            >
              <span className="batch-step-number" aria-hidden="true">{index + 1}</span>
              <span className="batch-step-icon"><Icon aria-hidden="true" /></span>
              <span><strong>{label}</strong><small>{description}</small></span>
            </button>
          ))}
        </div>

        {activeStep === "source" ? (
          <div id="batch-step-panel-source" className="batch-step-panel batch-source-panel" role="tabpanel" aria-labelledby="batch-step-tab-source">
            <header className="batch-panel-heading">
              <div><span className="batch-panel-kicker">Batch input</span><h2>Choose the source folder</h2></div>
              <span className="batch-panel-status">{sourceFolder ? "Source selected" : "Source required"}</span>
            </header>
            <div className="batch-source-layout">
              <button type="button" className="batch-folder-drop" onClick={pickSourceFolder}>
                <span className="batch-folder-icon"><FolderOpen aria-hidden="true" /></span>
                <span><strong>{sourceFolder ? basename(sourceFolder) : "Choose a loop folder"}</strong><small>{sourceFolder || "Drop a folder here or browse your files"}</small></span>
                <span className="batch-browse-action">Browse folder</span>
              </button>
              <div className="batch-plan-card">
                <div className="batch-plan-heading"><Settings2 aria-hidden="true" /><div><h3>Batch plan</h3><span>Current configuration before processing</span></div></div>
                <dl>
                  <div><dt>Source</dt><dd title={sourceFolder || undefined}>{sourceFolder ? basename(sourceFolder) : "Not selected"}</dd></div>
                  <div><dt>Operations</dt><dd>{enabledOperationCount} enabled</dd></div>
                  <div><dt>Output</dt><dd>{layerExtraction ? basename(outputFolder) : "Configured per operation"}</dd></div>
                  <div><dt>Original files</dt><dd>{keyDestination === "Rename originals" ? "Rename enabled" : "Preserved"}</dd></div>
                </dl>
              </div>
            </div>
          </div>
        ) : null}

        {activeStep === "extract" ? (
          <div id="batch-step-panel-extract" className={cn("batch-step-panel batch-extract-panel", !layerExtraction && "is-disabled")} role="tabpanel" aria-labelledby="batch-step-tab-extract">
            <header className="batch-panel-heading">
              <div><span className="batch-panel-kicker">Operation 1</span><h2>Extract layers</h2><p>Extract every detected layer from each loop in the source folder.</p></div>
              <div className="batch-operation-toggle"><span>{layerExtraction ? "Enabled" : "Disabled"}</span><OperationSwitch checked={layerExtraction} onChange={setLayerExtraction} label="Enable layer extraction" accent="red" /></div>
            </header>
            <div className="batch-extract-layout">
              <div className="batch-operation-hero">
                <span className="batch-operation-icon"><Layers3 aria-hidden="true" /></span>
                <div><strong>Layer extraction</strong><small>Each source loop produces a set of individually playable layers.</small></div>
                <span className="batch-operation-state">{sourceFolder ? basename(sourceFolder) : "Waiting for a source folder"}</span>
              </div>
              <div className="batch-output-card">
                <div className="batch-output-heading"><span>Output location</span><small>Extracted layers are written to this folder.</small></div>
                <div className="batch-output-path"><FolderOpen aria-hidden="true" /><strong title={outputFolder}>{outputFolder}</strong></div>
                <div className="batch-output-actions"><Button variant="outline" size="sm" onClick={pickOutputFolder}>Change folder</Button><Button variant="outline" size="sm" onClick={() => void window.stemSlicer?.revealPath(outputFolder)}>Open folder</Button></div>
              </div>
            </div>
          </div>
        ) : null}

        {activeStep === "key" ? (
          <div id="batch-step-panel-key" className={cn("batch-step-panel batch-key-panel", !keyAnalysis && "is-disabled")} role="tabpanel" aria-labelledby="batch-step-tab-key">
            <header className="batch-panel-heading">
              <div><span className="batch-panel-kicker">Operation 2</span><h2>Analyze keys and name files</h2><p>Choose the musical relationship and the exact output naming order.</p></div>
              <div className="batch-operation-toggle"><span>{keyAnalysis ? "Enabled" : "Disabled"}</span><OperationSwitch checked={keyAnalysis} onChange={setKeyAnalysis} label="Enable key analysis" accent="yellow" /></div>
            </header>
            <div className="batch-key-settings">
              <div className="batch-key-choice-row">
                <SegmentedChoice label="Key mode" value={keyMode} options={["Detected", "Relative minor", "Relative major"]} onChange={setKeyMode} />
                <SegmentedChoice label="Key notation" value={keyNotation} options={["Sharps #", "Flats ♭"]} onChange={setKeyNotation} />
              </div>
              <div className="batch-naming-card">
                <div className="batch-naming-heading"><div><span>Output name structure</span><small>Drag the tokens or use the arrow keys to reorder them.</small></div><strong>{nameTokens.length} fields</strong></div>
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
                      onKeyDown={(event) => {
                        if (event.key === "ArrowLeft") { event.preventDefault(); moveToken(token, -1) }
                        if (event.key === "ArrowRight") { event.preventDefault(); moveToken(token, 1) }
                      }}
                      aria-label={`${token}, position ${index + 1} of ${nameTokens.length}. Use left and right arrows to reorder.`}
                    >
                      <span aria-hidden="true">⠿</span>{token}
                    </button>
                  ))}
                </div>
              </div>
              <div className="batch-key-footer">
                <SegmentedChoice label="Destination" value={keyDestination} options={["Copy to analyzed loops", "Rename originals"]} onChange={setKeyDestination} />
                <div className="batch-name-preview"><span>Filename preview</span><strong>{namePreview}</strong></div>
              </div>
            </div>
          </div>
        ) : null}

        {activeStep === "convert" ? (
          <div id="batch-step-panel-convert" className={cn("batch-step-panel batch-convert-panel", !conversion && "is-disabled")} role="tabpanel" aria-labelledby="batch-step-tab-convert">
            <header className="batch-panel-heading">
              <div><span className="batch-panel-kicker">Operation 3</span><h2>Convert BPM and key</h2><p>Convert extracted layers, or every source loop when extraction is disabled.</p></div>
              <div className="batch-operation-toggle"><span>{conversion ? "Enabled" : "Disabled"}</span><OperationSwitch checked={conversion} onChange={setConversion} label="Enable BPM and key conversion" accent="orange" /></div>
            </header>
            <div className="batch-convert-layout">
              <label className="batch-target-card">
                <span className="batch-target-heading"><input type="checkbox" checked={targetBpmEnabled} onChange={(event) => setTargetBpmEnabled(event.target.checked)} /><b>Target BPM</b></span>
                <Input aria-label="Stem Slicer target BPM" type="number" min="40" max="300" value={targetBpm} disabled={!targetBpmEnabled} onChange={(event) => setTargetBpm(Number(event.target.value))} />
                <small>Preserves the loop duration relationship while retiming the audio.</small>
              </label>
              <div className="batch-target-card">
                <label className="batch-target-heading"><input type="checkbox" checked={targetKeyEnabled} onChange={(event) => setTargetKeyEnabled(event.target.checked)} /><b>Target key</b></label>
                <Select id="stem-target-key" label="Stem Slicer target key" value={targetKey} onChange={setTargetKey} options={TARGET_KEY_FAMILIES} disabled={!targetKeyEnabled} className="inline-select" />
                <small>Applies the selected major and minor key family.</small>
              </div>
              <div className="batch-convert-route">
                <Repeat2 aria-hidden="true" />
                <div><span>Conversion input</span><strong>{layerExtraction ? "Extracted layers" : "Source loops"}</strong><small>Determined by the Extraction operation.</small></div>
              </div>
            </div>
          </div>
        ) : null}

        <div className="batch-process-bar" aria-label="Batch process status">
          <div className="batch-process-copy"><span>Process status</span><strong>{sourceFolder ? `${basename(sourceFolder)} ready` : "Choose a source folder to begin"}</strong></div>
          <div className="batch-operation-summary" aria-label={`${enabledOperationCount} operations enabled`}>
            <span data-enabled={layerExtraction}>Extract</span><span data-enabled={keyAnalysis}>Key</span><span data-enabled={conversion}>Convert</span>
          </div>
          <div className="batch-progress"><span /></div>
          <div className="batch-process-stats"><span>0 files</span><span>0 complete</span><span>0 errors</span></div>
          <Button className="hardware-button" disabled>Process loops</Button>
        </div>
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

function QuickToolsView() {
  type QuickToolId = "extract" | "scan" | "convert"

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
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([])

  const pickAudio = async (setPath: (path: string) => void) => {
    const result = await window.stemSlicer?.pickAudioFiles()
    if (!result || result.canceled || result.paths.length === 0) return
    setPath(result.paths[0])
  }

  const moveBetweenTools = (currentIndex: number, key: string) => {
    let nextIndex = currentIndex
    if (key === "ArrowRight") nextIndex = (currentIndex + 1) % quickTools.length
    if (key === "ArrowLeft") nextIndex = (currentIndex - 1 + quickTools.length) % quickTools.length
    if (key === "Home") nextIndex = 0
    if (key === "End") nextIndex = quickTools.length - 1
    if (nextIndex === currentIndex) return
    const nextTool = quickTools[nextIndex]
    setActiveTool(nextTool.id)
    tabRefs.current[nextIndex]?.focus()
  }

  return (
    <div className="page-stack quick-tools-page">
      <PageHeader eyebrow="Workspace / Quick Tools" title="Quick tools" description="Choose one focused operation. Every accepted 1.9B option stays available inside its tool." />

      <section className="quick-tools-shell" aria-label="Quick tools workspace">
        <div className="quick-tool-tabs" role="tablist" aria-label="Choose a quick tool">
          {quickTools.map(({ id, label, description, icon: Icon }, index) => (
            <button
              key={id}
              ref={(element) => { tabRefs.current[index] = element }}
              id={`quick-tool-tab-${id}`}
              type="button"
              role="tab"
              className="quick-tool-tab"
              data-tool={id}
              aria-selected={activeTool === id}
              aria-controls={`quick-tool-panel-${id}`}
              tabIndex={activeTool === id ? 0 : -1}
              onClick={() => setActiveTool(id)}
              onKeyDown={(event) => {
                if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
                event.preventDefault()
                moveBetweenTools(index, event.key)
              }}
            >
              <span className="quick-tab-icon"><Icon aria-hidden="true" /></span>
              <span><strong>{label}</strong><small>{description}</small></span>
            </button>
          ))}
        </div>

        {activeTool === "extract" ? (
          <div id="quick-tool-panel-extract" className="quick-tool-panel extract-panel" role="tabpanel" aria-labelledby="quick-tool-tab-extract">
            <header className="quick-panel-heading">
              <div><span className="quick-panel-kicker">One loop · multiple layers</span><h2>Extract layers</h2></div>
              <div className="quick-panel-actions"><span className="quick-panel-status">0 layers</span><Button variant="outline" size="sm" disabled><Layers3 /> Drag all</Button></div>
            </header>

            <div className="quick-extract-controls">
              <button type="button" className="quick-file-source" onClick={() => pickAudio(setExtractFile)}>
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

              <Button className="quick-run-button" disabled><Sparkles /> Extract</Button>
            </div>

            <div className="quick-results-heading">
              <div><h3>Extracted layers</h3><span>Cards appear here as each layer becomes available.</span></div>
              <span>{extractFile ? `${basename(extractFile)} selected` : "Waiting for one source loop"}</span>
            </div>
            <div className="quick-layer-area" aria-live="polite">
              <div className="quick-layer-empty">
                <span className="quick-empty-icon"><Layers3 aria-hidden="true" /></span>
                <strong>No extracted layers yet</strong>
                <span>Choose a loop to create playable cards with waveform, MIDI drag and individual export.</span>
              </div>
            </div>
          </div>
        ) : null}

        {activeTool === "scan" ? (
          <div id="quick-tool-panel-scan" className="quick-tool-panel scan-panel" role="tabpanel" aria-labelledby="quick-tool-tab-scan">
            <header className="quick-panel-heading">
              <div><span className="quick-panel-kicker">One loop · full musical readout</span><h2>Scan BPM and key</h2></div>
              <span className="quick-panel-status">{scanFile ? "File selected" : "Ready to scan"}</span>
            </header>

            <div className="quick-scan-body">
              <button type="button" className="quick-file-source quick-file-source-tall" onClick={() => pickAudio(setScanFile)}>
                <span className="quick-source-icon"><ScanLine aria-hidden="true" /></span>
                <span className="quick-source-copy"><strong>{scanFile ? basename(scanFile) : "Choose one loop"}</strong><small>{scanFile || "Drop a loop here or browse your files"}</small></span>
                <span className="quick-source-action">Browse loop</span>
              </button>

              <div className="quick-scan-analysis">
                <div className="quick-scan-metrics">
                  {[["BPM", "—", "Tempo"], ["Detected key", "—", "Top-1"], ["Relative key", "—", "Relationship"]].map(([label, value, detail]) => (
                    <div className="scan-metric" key={label}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
                  ))}
                </div>
                <div className="relative-modes">
                  <div className="relative-modes-heading"><span>Relative modes</span><small>Same notes · different centers</small></div>
                  <div className="relative-mode-grid">
                    {["I", "II", "III", "IV", "V"].map((degree) => <div key={degree}><span>{degree}</span><strong>—</strong><small>—</small></div>)}
                  </div>
                </div>
                <div className="quick-scan-details">
                  <div className="quick-scan-details-heading">
                    <div><span>Analysis details</span><small>Technical output from the 1.9B scan engine</small></div>
                    <span>{scanFile ? basename(scanFile) : "No file selected"}</span>
                  </div>
                  <div className="quick-scan-detail-grid">
                    {[
                      ["BPM confidence", "—", "Model score"],
                      ["BPM source", "—", "Audio and filename decision"],
                      ["Camelot", "—", "Wheel notation"],
                      ["OpenKey", "—", "Harmonic mixing notation"],
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
          <div id="quick-tool-panel-convert" className="quick-tool-panel convert-panel" role="tabpanel" aria-labelledby="quick-tool-tab-convert">
            <header className="quick-panel-heading">
              <div><span className="quick-panel-kicker">One loop · new BPM and key</span><h2>Convert audio</h2></div>
              <span className="quick-panel-status">0 conversions</span>
            </header>

            <div className="quick-convert-controls">
              <button type="button" className="quick-file-source" onClick={() => pickAudio(setConvertFile)}>
                <span className="quick-source-icon"><Repeat2 aria-hidden="true" /></span>
                <span className="quick-source-copy"><strong>{convertFile ? basename(convertFile) : "Choose one loop"}</strong><small>{convertFile || "Drop a loop here or browse your files"}</small></span>
                <span className="quick-source-action">Browse loop</span>
              </button>
              <label className="quick-convert-field"><span>Target BPM</span><Input aria-label="Quick Convert target BPM" type="number" min="40" max="300" value={convertBpm} onChange={(event) => setConvertBpm(Number(event.target.value))} /></label>
              <Select id="quick-convert-key" label="Target key" value={convertKey} onChange={setConvertKey} options={TARGET_KEY_FAMILIES} />
              <Button className="quick-run-button" disabled><Repeat2 /> Convert</Button>
            </div>

            <div className="quick-convert-result" aria-live="polite">
              <span className="quick-empty-icon"><AudioLines aria-hidden="true" /></span>
              <div><strong>No converted file yet</strong><small>The converted result will remain playable and individually draggable.</small></div>
              <div className="quick-result-actions"><Button variant="outline" size="sm" disabled>Open output folder</Button><Button variant="outline" size="sm" disabled>Manage files</Button></div>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  )
}

function HistoryView({ history }: { history: HistoryEntry[] }) {
  return (
    <div className="page-stack">
      <PageHeader eyebrow="Workspace / History" title="Generation history" description="Reopen previous combinations, compare recipes and keep the stacks worth exporting." actions={<Button variant="outline"><ListFilter /> Filter</Button>} />
      {history.length ? (
        <div className="history-list">
          {history.map((entry) => (
            <Card key={entry.id} className="history-item">
              <CardContent>
                <span className="history-icon"><History /></span>
                <div><strong>{entry.recipe} combination</strong><small>{entry.createdAt} · {entry.layerCount} layers</small></div>
                <div className="history-spec"><Badge variant="secondary">{entry.recipe}</Badge><span>{entry.bpm} BPM</span><span>{entry.keyName}</span></div>
                <Button variant="outline" size="sm">Reopen</Button>
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

function GlobalPlayer({ layers, playback, soloId, setSoloId }: { layers: GeneratedLayer[]; playback: PlaybackClock; soloId: string | null; setSoloId: React.Dispatch<React.SetStateAction<string | null>> }) {
  const [volume, setVolume] = useState(78)
  const currentLayer = layers.find((layer) => layer.id === soloId) ?? layers[0]
  const allPlaying = playback.playing && soloId === null

  const toggleMix = () => {
    if (soloId !== null) {
      setSoloId(null)
      playback.stop()
      window.setTimeout(playback.toggle, 0)
      return
    }
    playback.toggle()
  }

  return (
    <footer className="global-player app-no-drag" aria-label="Global audio preview">
      <div className="player-current">
        <span className="player-art"><AudioLines aria-hidden="true" /></span>
        <div><strong>{soloId ? currentLayer?.role : "Generated stack"}</strong><small>{currentLayer ? `${currentLayer.bpm} BPM · ${currentLayer.keyName}` : "No generated layers"}</small></div>
        <Badge variant="secondary">Visual preview</Badge>
      </div>
      <div className="player-core">
        <div className="player-controls">
          <button type="button" className="player-key" onClick={playback.stop} aria-label="Return to start"><SkipBack aria-hidden="true" /></button>
          <button type="button" className={cn("player-key player-key-primary", playback.playing && "is-active")} onClick={toggleMix} aria-label={allPlaying ? "Pause all layers" : "Play all layers"}>{allPlaying ? <Pause aria-hidden="true" /> : <Play className="play-glyph" aria-hidden="true" />}</button>
          <button type="button" className="player-key" onClick={playback.stop} aria-label="Stop preview"><Square aria-hidden="true" /></button>
        </div>
        <div className="player-timeline"><Waveform progress={playback.progress} compact label="Generated stack waveform" /><span className="tabular">{(playback.progress * 7.44).toFixed(1)} / 7.4 s</span></div>
      </div>
      <label className="player-volume"><Sliders aria-hidden="true" /><span className="sr-only">Preview volume</span><input type="range" min="0" max="100" value={volume} onChange={(event) => setVolume(Number(event.target.value))} /><output className="tabular">{volume}%</output></label>
    </footer>
  )
}

export function App() {
  const [activeView, setActiveView] = useState<ViewId>("generate")
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [library, setLibrary] = useState<LibraryOverview>(FALLBACK_LIBRARY)
  const [layers, setLayers] = useState(INITIAL_LAYERS)
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [soloId, setSoloId] = useState<string | null>(null)
  const playback = usePlaybackClock(7.44)
  const mainRef = useRef<HTMLElement>(null)
  const initialViewRef = useRef(true)

  useEffect(() => {
    const api = window.stemSlicer
    if (!api) return
    void api.getLibraryOverview().then(setLibrary)
  }, [])

  useEffect(() => {
    document.title = `${NAVIGATION.find((item) => item.id === activeView)?.label ?? "Stem Slicer"} · Stem Slicer Prototype`
    if (initialViewRef.current) {
      initialViewRef.current = false
      return
    }
    mainRef.current?.focus()
  }, [activeView])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "b") {
        event.preventDefault()
        setSidebarCollapsed((value) => !value)
        return
      }
      if (event.metaKey || event.ctrlKey || event.altKey || event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement || event.target instanceof HTMLButtonElement || event.target instanceof HTMLTextAreaElement) return
      const item = NAVIGATION.find((entry) => entry.shortcut?.toLowerCase() === event.key.toLowerCase())
      if (item) setActiveView(item.id)
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [])

  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">Aller au contenu principal</a>
      <AppSidebar activeView={activeView} collapsed={sidebarCollapsed} onNavigate={setActiveView} onToggle={() => setSidebarCollapsed((value) => !value)} />
      <div className="app-workspace">
        <div className="window-dragbar app-drag-region">
          <span className="prototype-pill app-no-drag"><span /> Electron prototype</span>
        </div>
        <main id="main-content" tabIndex={-1} ref={mainRef} className={cn(activeView === "generate" && "generate-main", activeView === "quick-tools" && "quick-tools-main", activeView === "stem-slicer" && "stem-slicer-main")}>
          {activeView === "stem-slicer" ? <StemSlicerView /> : null}
          {activeView === "generate" ? <GenerateView library={library} layers={layers} setLayers={setLayers} onAddHistory={(entry) => setHistory((items) => [entry, ...items])} playback={playback} soloId={soloId} setSoloId={setSoloId} /> : null}
          {activeView === "quick-tools" ? <QuickToolsView /> : null}
          {activeView === "history" ? <HistoryView history={history} /> : null}
          {activeView === "cloud" ? <CloudView /> : null}
        </main>
        <GlobalPlayer layers={layers} playback={playback} soloId={soloId} setSoloId={setSoloId} />
      </div>
    </div>
  )
}
