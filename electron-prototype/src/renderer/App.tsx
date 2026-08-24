import {
  AudioLines,
  Check,
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
  Menu,
  Music2,
  Pause,
  Play,
  Plus,
  Radio,
  Repeat2,
  RotateCcw,
  ScanLine,
  Settings2,
  SkipBack,
  Sliders,
  SlidersHorizontal,
  Sparkle,
  Sparkles,
  Square,
  WandSparkles,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react"
import { useCallback, useEffect, useId, useRef, useState } from "react"

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
  seed: number
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

  return { playing, progress, setProgress, toggle, stop }
}

type PlaybackClock = ReturnType<typeof usePlaybackClock>

function Select({
  id,
  label,
  value,
  onChange,
  children,
  className,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  children: React.ReactNode
  className?: string
}) {
  return (
    <label className={cn("control-field", className)} htmlFor={id}>
      <span>{label}</span>
      <select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
        {children}
      </select>
    </label>
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
          onClick={() => onNavigate("generate")}
          aria-label="Ouvrir Generate"
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
          {collapsed ? <Menu /> : <ChevronLeft />}
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
            </button>
          )
        })}

        <p className="sidebar-group-label sidebar-cloud-label">Network</p>
        <button
          type="button"
          className={cn("nav-item", activeView === "cloud" && "is-active")}
          onClick={() => onNavigate("cloud")}
          aria-current={activeView === "cloud" ? "page" : undefined}
          aria-label={collapsed ? "Connected Libraries" : undefined}
          title={collapsed ? "Connected Libraries" : undefined}
        >
          <Cloud aria-hidden="true" />
          <span className="nav-label">Connected Libraries</span>
          <Badge variant="warning" className="nav-beta">Future</Badge>
        </button>
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
  tone,
  progress,
  playing,
  isAudible,
  onPlay,
  onChange,
}: {
  layer: GeneratedLayer
  tone: "green" | "yellow"
  progress: number
  playing: boolean
  isAudible: boolean
  onPlay: () => void
  onChange: (layer: GeneratedLayer) => void
}) {
  return (
    <Card className={cn("layer-card", `layer-tone-${tone}`, isAudible && "is-audible")} aria-label={`${layer.role}, ${layer.category}`}>
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
        <button
          type="button"
          className="waveform-button"
          onClick={onPlay}
          aria-label={playing && isAudible ? `Mettre ${layer.role} en pause` : `Lire ${layer.role} en solo`}
        >
          <span className="card-play-icon" aria-hidden="true">
            {playing && isAudible ? <Pause /> : <Play className="play-glyph" />}
          </span>
          <Waveform
            progress={isAudible ? progress : 0}
            label={`Forme d’onde de ${layer.role}`}
            bars={layer.bars}
          />
          <span className="wave-time tabular">
            {((isAudible ? progress : 0) * layer.duration).toFixed(1)} / {layer.duration.toFixed(1)} s
          </span>
        </button>

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
  const [seed, setSeed] = useState(734291)
  const [isGenerating, setIsGenerating] = useState(false)
  const [status, setStatus] = useState("Visual transport ready")
  const [selectionMessage, setSelectionMessage] = useState("")
  const allPlaying = playback.playing && soloId === null
  const largestCategoryCount = library.categories[0]?.count || 1

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
      const nextSeed = Math.floor(100000 + Math.random() * 899999)
      setSeed(nextSeed)
      setLayers((current) =>
        current.map((layer, index) => ({
          ...layer,
          file: layer.file.replace(/_\d+\.wav$/, `_${(nextSeed + index * 7) % 36 + 1}.wav`),
          bpm,
          keyName,
        })),
      )
      setStatus("4 prototype cards generated")
      setIsGenerating(false)
      onAddHistory({
        id: crypto.randomUUID(),
        seed: nextSeed,
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
          <Select id="target-key" label="Target key" value={keyName} onChange={setKeyName}>
            <option>F minor</option>
            <option>G minor</option>
            <option>A♭ major</option>
            <option>C minor</option>
            <option>D♭ major</option>
          </Select>
          <Select id="recipe" label="Recipe" value={recipe} onChange={setRecipe}>
            <option>Balanced</option>
            <option>Melodic</option>
            <option>Minimal</option>
            <option>Dense</option>
          </Select>
          <label className="control-field" htmlFor="generation-seed">
            <span>Seed</span>
            <div className="seed-control">
              <Input id="generation-seed" value={seed} readOnly className="tabular" />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Choisir une nouvelle seed"
                title="Nouvelle seed"
                onClick={() => setSeed(Math.floor(100000 + Math.random() * 899999))}
              >
                <RotateCcw />
              </Button>
            </div>
          </label>
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
              <h2 id="generate-catalogue-title">Layer catalogue</h2>
              <p><strong>{formatCount(library.totalLayers)}</strong> layers · {library.roots.length} libraries · {library.categories.length} categories</p>
            </div>
          </div>
          <Button size="sm" onClick={pickFolder}><Plus /> Add library</Button>
        </div>

        {selectionMessage ? <p className="catalogue-selection" role="status"><FolderOpen aria-hidden="true" /> {selectionMessage}</p> : null}

        <div className="catalogue-sources" aria-label="Indexed libraries">
          {library.roots.length > 0 ? library.roots.map((root) => (
            <button type="button" className="catalogue-source" key={root.path} title={root.path} onClick={() => window.stemSlicer?.revealPath(root.path)}>
              <FolderOpen aria-hidden="true" />
              <span>{root.name}</span>
              <small className="tabular">{formatCount(root.layerCount)}</small>
            </button>
          )) : <span className="catalogue-empty">No indexed library detected.</span>}
        </div>

        <div className="catalogue-distribution-heading">
          <strong>Category distribution</strong>
          <span>Automatic and manual labels in the active catalogue</span>
        </div>
        <div className="catalogue-distribution" aria-label="Category distribution">
          {library.categories.length > 0 ? library.categories.map((category) => (
            <div className="category-compact" key={category.name}>
              <span className="category-compact-meter" aria-hidden="true"><span style={{ width: `${Math.max(5, (category.count / largestCategoryCount) * 100)}%` }} /></span>
              <strong title={category.name}>{category.name}</strong>
              <small className="tabular">{formatCount(category.count)}</small>
            </div>
          )) : <p className="catalogue-empty">Category distribution becomes available with the Electron catalogue.</p>}
        </div>
      </section>

      <div className="layer-scroll" tabIndex={0} aria-label="Generated layer cards">
        <div className="layer-grid">
          {layers.map((layer, index) => (
            <LayerCard
              key={layer.id}
              layer={layer}
              tone={index % 2 === 0 ? "green" : "yellow"}
              progress={playback.progress}
              playing={playback.playing}
              isAudible={allPlaying || soloId === layer.id}
              onPlay={() => toggleSolo(layer.id)}
              onChange={(next) => setLayers((current) => current.map((item) => item.id === next.id ? next : item))}
            />
          ))}
        </div>

        <div className="generate-footer">
          <p><Check aria-hidden="true" /> Shared BPM and key constraints are active.</p>
          <Button variant="outline"><Layers3 /> Drag all</Button>
        </div>
      </div>
    </div>
  )
}

function StemSlicerView() {
  const [sourceFolder, setSourceFolder] = useState("")
  const [spaceEnabled, setSpaceEnabled] = useState(true)
  const [noSpaceEnabled, setNoSpaceEnabled] = useState(true)
  const [keyAnalysis, setKeyAnalysis] = useState(true)
  const [conversion, setConversion] = useState(false)

  const pickSourceFolder = async () => {
    const result = await window.stemSlicer?.pickLibraryFolder()
    if (!result || result.canceled || result.paths.length === 0) return
    setSourceFolder(result.paths[0])
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Workspace / Stem Slicer"
        title="Batch extraction, preserved from 1.9B"
        description="The Electron workspace keeps the accepted Space and NoSpace paths, key and BPM analysis, Bungee conversion, naming and DAW-ready outputs."
        actions={<Badge variant="warning">Engine adapter next</Badge>}
      />

      <div className="workflow-grid">
        <Card className="glass-panel workflow-card">
          <CardHeader>
            <div className="workflow-heading"><span>01</span><div><CardTitle>Source folder</CardTitle><CardDescription>Select the folder containing the MP3 loops to process.</CardDescription></div></div>
          </CardHeader>
          <CardContent>
            <button type="button" className="compact-drop" onClick={pickSourceFolder}>
              <FolderOpen aria-hidden="true" />
              <span><strong>{sourceFolder ? basename(sourceFolder) : "Choose a loop folder"}</strong><small>{sourceFolder || "Folder selection is handled natively by Electron."}</small></span>
            </button>
          </CardContent>
        </Card>

        <Card className="glass-panel workflow-card">
          <CardHeader>
            <div className="workflow-heading"><span>02</span><div><CardTitle>Extraction paths</CardTitle><CardDescription>Both validated detection paths remain independently selectable.</CardDescription></div></div>
          </CardHeader>
          <CardContent className="option-grid">
            <label className="toggle-tile"><input type="checkbox" checked={spaceEnabled} onChange={(event) => setSpaceEnabled(event.target.checked)} /><span><strong>Space</strong><small>Loops with separated layers</small></span></label>
            <label className="toggle-tile"><input type="checkbox" checked={noSpaceEnabled} onChange={(event) => setNoSpaceEnabled(event.target.checked)} /><span><strong>NoSpace</strong><small>Contiguous-layer inference</small></span></label>
            <label className="toggle-tile"><input type="checkbox" checked={keyAnalysis} onChange={(event) => setKeyAnalysis(event.target.checked)} /><span><strong>Key + BPM</strong><small>Accepted musical analysis</small></span></label>
            <label className="toggle-tile"><input type="checkbox" checked={conversion} onChange={(event) => setConversion(event.target.checked)} /><span><strong>Convert</strong><small>Bungee BPM and key conversion</small></span></label>
          </CardContent>
        </Card>

        <Card className="glass-panel workflow-card workflow-output">
          <CardHeader>
            <div className="workflow-heading"><span>03</span><div><CardTitle>Output</CardTitle><CardDescription>Naming and destinations remain compatible with the 1.9B workflow.</CardDescription></div></div>
          </CardHeader>
          <CardContent>
            <div className="feature-strip" aria-label="Preserved output features">
              <Badge variant="secondary">DAW naming</Badge>
              <Badge variant="secondary">Combined operations</Badge>
              <Badge variant="secondary">Output folders</Badge>
            </div>
            <div className="blocked-action">
              <Button className="hardware-button" disabled>Start batch</Button>
              <p>The accepted Python engine will be connected here before this action is enabled.</p>
            </div>
          </CardContent>
        </Card>
      </div>
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
  const [scanFile, setScanFile] = useState("")
  const [convertFile, setConvertFile] = useState("")
  const [extractFile, setExtractFile] = useState("")
  const [degreeReference, setDegreeReference] = useState("Major")
  const [notation, setNotation] = useState("Sharps #")
  const [convertBpm, setConvertBpm] = useState(120)
  const [convertKey, setConvertKey] = useState("C major / A minor")

  const pickAudio = async (setPath: (path: string) => void) => {
    const result = await window.stemSlicer?.pickAudioFiles()
    if (!result || result.canceled || result.paths.length === 0) return
    setPath(result.paths[0])
  }

  return (
    <div className="page-stack quick-tools-page">
      <PageHeader eyebrow="Workspace / Quick Tools" title="The complete 1.9B quick workflow" description="Quick Scan, Quick Convert and Quick Extract keep their original roles. Each engine will be reconnected behind this Electron surface rather than replaced by generic tools." />

      <section className="quick-workbench glass-panel tone-green quick-scan-workbench" aria-labelledby="quick-scan-title">
        <div className="quick-workbench-heading">
          <span className="tool-icon keycap-icon"><ScanLine aria-hidden="true" /></span>
          <div><h2 id="quick-scan-title">Quick Scan</h2><p>Detect BPM, key relationships, relative key and compatible modes from one loop.</p></div>
          <Badge variant="warning">1.9B engine to connect</Badge>
        </div>
        <div className="quick-scan-layout">
          <button type="button" className="compact-drop" onClick={() => pickAudio(setScanFile)}>
            <Music2 aria-hidden="true" /><span><strong>{scanFile ? basename(scanFile) : "Choose one audio file"}</strong><small>MP3, WAV, FLAC or AIFF</small></span>
          </button>
          <div className="quick-scan-results" aria-label="Quick Scan results">
            {[["BPM", "—"], ["Detected key", "—"], ["Relative key", "—"], ["Modes", "—"]].map(([label, value]) => <div key={label}><small>{label}</small><strong>{value}</strong></div>)}
          </div>
        </div>
        <div className="quick-options">
          <SegmentedChoice label="Degree reference" value={degreeReference} options={["Major", "Minor"]} onChange={setDegreeReference} />
          <SegmentedChoice label="Key notation" value={notation} options={["Sharps #", "Flats ♭"]} onChange={setNotation} />
          <p><CircleAlert aria-hidden="true" /> Results activate when the accepted key/BPM engine is connected.</p>
        </div>
      </section>

      <section className="quick-workbench glass-panel tone-yellow quick-convert-workbench" aria-labelledby="quick-convert-title">
        <div className="quick-workbench-heading">
          <span className="tool-icon keycap-icon orange"><SlidersHorizontal aria-hidden="true" /></span>
          <div><h2 id="quick-convert-title">Quick Convert</h2><p>Convert one loop to a selected BPM and relative major/minor key family.</p></div>
          <Badge variant="warning">Bungee adapter next</Badge>
        </div>
        <div className="quick-convert-layout">
          <button type="button" className="compact-drop" onClick={() => pickAudio(setConvertFile)}>
            <Repeat2 aria-hidden="true" /><span><strong>{convertFile ? basename(convertFile) : "Choose one loop"}</strong><small>Output remains individually draggable</small></span>
          </button>
          <label className="control-field"><span>Target BPM</span><Input type="number" min="40" max="300" value={convertBpm} onChange={(event) => setConvertBpm(Number(event.target.value))} /></label>
          <Select id="quick-convert-key" label="Target key" value={convertKey} onChange={setConvertKey}>
            <option>C major / A minor</option><option>D♭ major / B♭ minor</option><option>E♭ major / C minor</option><option>F major / D minor</option><option>G major / E minor</option>
          </Select>
          <div className="quick-storage"><span>0 conversions</span><button type="button" disabled>Open output</button><button type="button" disabled>Manage</button></div>
        </div>
      </section>

      <section className="quick-workbench glass-panel tone-green quick-extract-workbench" aria-labelledby="quick-extract-title">
        <div className="quick-workbench-heading">
          <span className="tool-icon keycap-icon red"><AudioLines aria-hidden="true" /></span>
          <div><h2 id="quick-extract-title">Quick Extract</h2><p>Incremental layer cards with playback, waveform, metadata and parallel MIDI.</p></div>
          <Badge variant="warning">Extraction adapter next</Badge>
        </div>
        <div className="quick-extract-layout">
          <button type="button" className="compact-drop" onClick={() => pickAudio(setExtractFile)}>
            <Plus aria-hidden="true" /><span><strong>{extractFile ? basename(extractFile) : "Choose one MP3 loop"}</strong><small>Cards appear incrementally during extraction</small></span>
          </button>
          <div className="extract-preview">
            <Sparkle aria-hidden="true" />
            <strong>Layer cards will appear here</strong>
            <span>Audio drag · MIDI drag · optional BPM/key conversion · Drag All</span>
          </div>
        </div>
        <div className="quick-storage"><span>0 extracts</span><button type="button" disabled>Open folder</button><button type="button" disabled>Manage</button></div>
      </section>
    </div>
  )
}

function HistoryView({ history }: { history: HistoryEntry[] }) {
  return (
    <div className="page-stack">
      <PageHeader eyebrow="Workspace / History" title="Generation history" description="Reopen a previous seed, compare recipes and keep the combinations worth exporting." actions={<Button variant="outline"><ListFilter /> Filter</Button>} />
      {history.length ? (
        <div className="history-list">
          {history.map((entry) => (
            <Card key={entry.id} className="history-item">
              <CardContent>
                <span className="history-icon"><History /></span>
                <div><strong>Seed <span className="tabular">{entry.seed}</span></strong><small>{entry.createdAt} · {entry.layerCount} layers</small></div>
                <div className="history-spec"><Badge variant="secondary">{entry.recipe}</Badge><span>{entry.bpm} BPM</span><span>{entry.keyName}</span></div>
                <Button variant="outline" size="sm">Reopen</Button>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <EmptyState icon={History} title="No generation yet" description="Generate a combination and it will appear here with its seed and musical constraints." action={<span className="empty-hint">Open Generate to create the first entry.</span>} />
      )}
    </div>
  )
}

function CloudView() {
  return (
    <div className="page-stack">
      <PageHeader eyebrow="Network / Connected Libraries" title="Mix trusted producer libraries" description="A future permission layer will let Generate combine your local catalogue with libraries explicitly shared by other producers." />
      <Card className="cloud-hero">
        <CardContent>
          <span className="cloud-symbol"><CloudCog /></span>
          <Badge variant="warning">Product direction</Badge>
          <h2>Connected Libraries</h2>
          <p>Permission, identity, remote indexing and revocation will live here. No cloud connection exists in this prototype yet.</p>
          <Button variant="outline" disabled><Plus /> Invite a producer</Button>
        </CardContent>
      </Card>
    </div>
  )
}

function TaskCenter({ library }: { library: LibraryOverview }) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const analyzedLayers = library.roots.reduce((sum, root) => sum + root.analyzedKeyCount, 0)
  const missingConfidence = Math.max(0, library.totalLayers - analyzedLayers)

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false)
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [open])

  return (
    <div className={cn("task-center app-no-drag", open && "is-open")}>
      <button type="button" className="task-trigger" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-controls={panelId}>
        <span className={cn("status-light", library.databaseDetected && "is-online")} />
        <span>{library.databaseDetected ? "Catalogue ready" : "Catalogue unavailable"}</span>
        <Badge variant={!library.databaseDetected || missingConfidence > 0 ? "warning" : "success"}>{formatCount(library.totalLayers)}</Badge>
      </button>
      {open ? (
        <div className="task-popover glass-panel" id={panelId} role="status">
          <div className="task-heading"><div><strong>Library activity</strong><small>Future scans will remain visible here while you work.</small></div><Button variant="ghost" size="icon" onClick={() => setOpen(false)} aria-label="Close activity"><X /></Button></div>
          <div className="task-body">
            <div className="task-title"><span><ScanLine aria-hidden="true" /></span><div><strong>1.9B catalogue</strong><small>{formatCount(library.totalLayers)} cached layers · no scan active</small></div><Badge variant={library.databaseDetected ? "success" : "warning"}>{library.databaseDetected ? "Ready" : "Offline"}</Badge></div>
            <div className="task-progress" aria-label={library.databaseDetected ? "Catalogue loading complete" : "Catalogue unavailable"} aria-valuemin={0} aria-valuemax={100} aria-valuenow={library.databaseDetected ? 100 : 0} role="progressbar"><span style={{ width: library.databaseDetected ? "100%" : "0%" }} /></div>
            {!library.databaseDetected ? <p><CircleAlert aria-hidden="true" /> The accepted cache is only available inside the Electron runtime.</p> : missingConfidence > 0 ? <p><CircleAlert aria-hidden="true" /> {formatCount(missingConfidence)} layers currently have no Top-2 confidence data.</p> : <p><Check aria-hidden="true" /> Key confidence metadata is available for the indexed catalogue.</p>}
          </div>
        </div>
      ) : null}
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
      if (event.metaKey || event.ctrlKey || event.altKey || event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return
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
          <TaskCenter library={library} />
        </div>
        <main id="main-content" tabIndex={-1} ref={mainRef} className={cn(activeView === "generate" && "generate-main")}>
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
