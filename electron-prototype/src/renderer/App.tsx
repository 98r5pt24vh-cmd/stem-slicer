import {
  Activity,
  AudioLines,
  Check,
  ChevronLeft,
  CircleAlert,
  Cloud,
  CloudCog,
  Database,
  FolderOpen,
  Gauge,
  History,
  Layers3,
  Library,
  ListFilter,
  LoaderCircle,
  Menu,
  Music2,
  Pause,
  Play,
  Plus,
  Radio,
  RotateCcw,
  Search,
  Settings2,
  SkipBack,
  SlidersHorizontal,
  Sparkles,
  Square,
  WandSparkles,
  Wrench,
  X,
  Zap,
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
import type {
  AppEnvironment,
  LibraryOverview,
  MigrationModule,
  ViewId,
} from "@/shared/contracts"

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
  { id: "generate", label: "Generate", icon: Sparkles, shortcut: "G" },
  { id: "library", label: "Library", icon: Library, shortcut: "L" },
  { id: "quick-tools", label: "Quick Tools", icon: Wrench, shortcut: "Q" },
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
  totalLayers,
  onNavigate,
  onToggle,
}: {
  activeView: ViewId
  collapsed: boolean
  totalLayers: number
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
              {item.id === "library" && totalLayers > 0 ? (
                <span className="nav-count">{formatCount(totalLayers)}</span>
              ) : item.shortcut ? (
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
  progress,
  playing,
  isAudible,
  onPlay,
  onChange,
}: {
  layer: GeneratedLayer
  progress: number
  playing: boolean
  isAudible: boolean
  onPlay: () => void
  onChange: (layer: GeneratedLayer) => void
}) {
  return (
    <Card className={cn("layer-card", isAudible && "is-audible")} aria-label={`${layer.role}, ${layer.category}`}>
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
            {(progress * layer.duration).toFixed(1)} / {layer.duration.toFixed(1)} s
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
}: {
  library: LibraryOverview
  layers: GeneratedLayer[]
  setLayers: React.Dispatch<React.SetStateAction<GeneratedLayer[]>>
  onAddHistory: (entry: HistoryEntry) => void
}) {
  const [bpm, setBpm] = useState(129)
  const [keyName, setKeyName] = useState("F minor")
  const [recipe, setRecipe] = useState("Balanced")
  const [seed, setSeed] = useState(734291)
  const [isGenerating, setIsGenerating] = useState(false)
  const [status, setStatus] = useState("Visual transport ready")
  const [soloId, setSoloId] = useState<string | null>(null)
  const playback = usePlaybackClock(7.44)
  const allPlaying = playback.playing && soloId === null

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

  const toggleMix = () => {
    if (soloId !== null) {
      setSoloId(null)
      playback.stop()
      window.setTimeout(playback.toggle, 0)
      return
    }
    playback.toggle()
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
    <div className="page-stack">
      <PageHeader
        eyebrow="Workspace / Generate"
        title="Build a new layer stack"
        description="Shape the Generate workflow against the real 1.9B catalogue. Card selection and audio playback remain simulated in this first Electron pass."
        actions={
          <div className="library-status">
            <span className={cn("status-light", library.databaseDetected && !library.error && "is-online")} />
            <span>
              <strong>{formatCount(library.totalLayers)} layers</strong>
              <small>{library.databaseDetected ? "1.9B catalogue connected" : "Catalogue unavailable"}</small>
            </span>
          </div>
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
            <Button size="lg" onClick={handleGenerate} disabled={isGenerating}>
              {isGenerating ? <LoaderCircle className="animate-spin" /> : <WandSparkles />}
              {isGenerating ? "Generating…" : "Generate"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <section className="transport" aria-label="Transport synchronisé">
        <div className="transport-primary">
          <Button
            variant={allPlaying ? "success" : "secondary"}
            size="icon"
            onClick={toggleMix}
            aria-label={allPlaying ? "Mettre le mix en pause" : "Lire le mix"}
          >
            {allPlaying ? <Pause /> : <Play className="play-glyph" />}
          </Button>
          <Button variant="ghost" size="icon" onClick={playback.stop} aria-label="Arrêter la lecture">
            <Square />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => playback.setProgress(0)}
            aria-label="Revenir au début"
          >
            <SkipBack />
          </Button>
          <div className="transport-wave">
            <Waveform progress={playback.progress} compact label="Forme d’onde du mix" />
          </div>
          <span className="transport-time tabular">
            {(playback.progress * 7.44).toFixed(1)} / 7.4 s
          </span>
        </div>
        <div className="transport-state" aria-live="polite">
          <Activity aria-hidden="true" />
          <span>{soloId ? `Visual solo · ${layers.find((layer) => layer.id === soloId)?.role}` : allPlaying ? "Visual playback · all layers" : status}</span>
        </div>
      </section>

      <div className="layer-grid">
        {layers.map((layer) => (
          <LayerCard
            key={layer.id}
            layer={layer}
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
  )
}

function LibraryView({ library }: { library: LibraryOverview }) {
  const [query, setQuery] = useState("")
  const [selectionMessage, setSelectionMessage] = useState("")
  const filteredCategories = useMemo(
    () => library.categories.filter((category) => category.name.toLowerCase().includes(query.toLowerCase())),
    [library.categories, query],
  )

  const pickFolder = async () => {
    const result = await window.stemSlicer?.pickLibraryFolder()
    if (!result || result.canceled || result.paths.length === 0) return
    setSelectionMessage(`${basename(result.paths[0])} selected — scanning is not started automatically.`)
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Workspace / Library"
        title="Your layer catalogue"
        description="Inspect the real 1.9B catalogue. This Electron prototype never writes to the accepted cache."
        actions={<Button onClick={pickFolder}><Plus /> Add library</Button>}
      />

      {selectionMessage ? (
        <div className="notice" role="status"><FolderOpen /> {selectionMessage}</div>
      ) : null}

      <div className="metric-grid">
        <Card><CardContent className="metric"><Database /><span><strong>{formatCount(library.totalLayers)}</strong><small>Total layers</small></span></CardContent></Card>
        <Card><CardContent className="metric"><FolderOpen /><span><strong>{library.roots.length}</strong><small>Libraries</small></span></CardContent></Card>
        <Card><CardContent className="metric"><Layers3 /><span><strong>{library.categories.length}</strong><small>Detected categories</small></span></CardContent></Card>
        <Card><CardContent className="metric"><Zap /><span><strong>{formatCount(library.roots.reduce((sum, root) => sum + root.analyzedKeyCount, 0))}</strong><small>Top-1 / Top-2 analyzed</small></span></CardContent></Card>
      </div>

      <Card>
        <CardHeader>
          <div><CardTitle>Libraries</CardTitle><CardDescription>Paths are truncated visually but remain available as tooltips.</CardDescription></div>
          <Badge variant={library.error ? "warning" : "success"}>{library.error ? "Attention" : "Read-only connected"}</Badge>
        </CardHeader>
        <CardContent className="table-wrap">
          {library.roots.length > 0 ? (
            <table>
              <thead><tr><th>Name</th><th>Layers</th><th>Key analysis</th><th>Source</th></tr></thead>
              <tbody>
                {library.roots.map((root) => (
                  <tr key={root.path}>
                    <td><strong>{root.name}</strong></td>
                    <td className="tabular">{formatCount(root.layerCount)}</td>
                    <td>
                      {root.keyCoverage === "analyzed" ? (
                        <Badge variant="success"><Check /> {formatCount(root.analyzedKeyCount)} analyzed</Badge>
                      ) : (
                        <Badge variant="warning"><CircleAlert /> Confidence unavailable</Badge>
                      )}
                    </td>
                    <td><button className="path-button" title={root.path} onClick={() => window.stemSlicer?.revealPath(root.path)}>{root.path}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState icon={Database} title="No catalogue detected" description={library.error ?? "Connect the 1.9B catalogue to inspect its libraries."} action={<Button onClick={pickFolder}><FolderOpen /> Choose folder</Button>} />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div><CardTitle>Category distribution</CardTitle><CardDescription>Current automatic and manual labels, ordered by layer count.</CardDescription></div>
          <div className="search-field">
            <Search aria-hidden="true" />
            <Input aria-label="Rechercher une catégorie" placeholder="Search categories" value={query} onChange={(event) => setQuery(event.target.value)} />
            {query ? <button onClick={() => setQuery("")} aria-label="Effacer la recherche"><X /></button> : null}
          </div>
        </CardHeader>
        <CardContent>
          <div className="category-grid">
            {filteredCategories.map((category, index) => (
              <div className="category-row" key={category.name}>
                <span className="category-rank tabular">{String(index + 1).padStart(2, "0")}</span>
                <strong>{category.name}</strong>
                <span className="category-meter" aria-hidden="true"><span style={{ width: `${Math.max(4, (category.count / (library.categories[0]?.count || 1)) * 100)}%` }} /></span>
                <span className="tabular">{formatCount(category.count)}</span>
              </div>
            ))}
          </div>
          {filteredCategories.length === 0 ? <p className="empty-inline">No category matches “{query}”.</p> : null}
        </CardContent>
      </Card>
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

function QuickToolsView() {
  const [selectedFiles, setSelectedFiles] = useState<string[]>([])

  const pickAudio = async () => {
    const result = await window.stemSlicer?.pickAudioFiles()
    if (result && !result.canceled) setSelectedFiles(result.paths)
  }

  const tools = [
    { icon: AudioLines, name: "Stem Splitter", detail: "Separate vocals, drums, bass and instruments.", state: "Python adapter" },
    { icon: SlidersHorizontal, name: "Loop Slicer", detail: "Extract synchronized sections and named layers.", state: "Port queued" },
    { icon: Music2, name: "Audio to MIDI", detail: "Convert a complete monophonic audio file to MIDI.", state: "Python adapter" },
  ]

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Workspace / Quick Tools" title="Process audio without leaving the project" description="The Electron shell owns file selection and job state; engine adapters are connected behind typed contracts." />
      <button type="button" className="drop-zone" onClick={pickAudio}>
        <span className="drop-icon"><Plus /></span>
        <strong>{selectedFiles.length ? `${selectedFiles.length} file${selectedFiles.length > 1 ? "s" : ""} selected` : "Drop audio here or choose files"}</strong>
        <span>{selectedFiles.length ? selectedFiles.map(basename).join(" · ") : "WAV, AIFF, FLAC, MP3 or M4A"}</span>
      </button>
      <div className="tool-grid">
        {tools.map((tool) => {
          const Icon = tool.icon
          return (
            <Card key={tool.name} className="tool-card">
              <CardHeader><span className="tool-icon"><Icon /></span><Badge variant="secondary">{tool.state}</Badge></CardHeader>
              <CardContent><CardTitle>{tool.name}</CardTitle><CardDescription>{tool.detail}</CardDescription><Button variant="outline" disabled={selectedFiles.length === 0}>Configure</Button></CardContent>
            </Card>
          )
        })}
      </div>
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

function RuntimePanel({ modules, environment }: { modules: MigrationModule[]; environment?: AppEnvironment }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={cn("runtime-panel", open && "is-open")}>
      <button type="button" className="runtime-trigger" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <span className="status-light is-online" />
        <span>Electron runtime</span>
        <Badge variant="secondary">{modules.filter((module) => module.state !== "queued").length}/{modules.length}</Badge>
      </button>
      {open ? (
        <div className="runtime-popover">
          <div className="runtime-heading"><div><strong>Migration boundary</strong><small>Concrete module ownership</small></div><Button variant="ghost" size="icon" onClick={() => setOpen(false)} aria-label="Fermer"><X /></Button></div>
          <div className="runtime-list">
            {modules.map((module) => (
              <div key={module.id} className="runtime-row">
                <span className={cn("runtime-state", module.state)} aria-hidden="true" />
                <div><strong>{module.label}</strong><small>{module.detail}</small></div>
                <Badge variant={module.runtime === "TypeScript" ? "success" : module.runtime === "External binary" ? "warning" : "secondary"}>{module.runtime}</Badge>
              </div>
            ))}
          </div>
          {environment ? <p className="runtime-version tabular">Electron {environment.electronVersion} · Node {environment.nodeVersion} · {environment.architecture}</p> : null}
        </div>
      ) : null}
    </div>
  )
}

export function App() {
  const [activeView, setActiveView] = useState<ViewId>("generate")
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [library, setLibrary] = useState<LibraryOverview>(FALLBACK_LIBRARY)
  const [environment, setEnvironment] = useState<AppEnvironment>()
  const [modules, setModules] = useState<MigrationModule[]>([])
  const [layers, setLayers] = useState(INITIAL_LAYERS)
  const [history, setHistory] = useState<HistoryEntry[]>([])

  useEffect(() => {
    const api = window.stemSlicer
    if (!api) return
    void Promise.all([api.getLibraryOverview(), api.getEnvironment(), api.getMigrationModules()]).then(([overview, nextEnvironment, nextModules]) => {
      setLibrary(overview)
      setEnvironment(nextEnvironment)
      setModules(nextModules)
    })
  }, [])

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
      <AppSidebar activeView={activeView} collapsed={sidebarCollapsed} totalLayers={library.totalLayers} onNavigate={setActiveView} onToggle={() => setSidebarCollapsed((value) => !value)} />
      <div className="app-workspace">
        <div className="window-dragbar app-drag-region">
          <span className="prototype-pill app-no-drag"><span /> Live prototype</span>
          <RuntimePanel modules={modules} environment={environment} />
        </div>
        <main id="main-content" tabIndex={-1}>
          {activeView === "generate" ? <GenerateView library={library} layers={layers} setLayers={setLayers} onAddHistory={(entry) => setHistory((items) => [entry, ...items])} /> : null}
          {activeView === "library" ? <LibraryView library={library} /> : null}
          {activeView === "quick-tools" ? <QuickToolsView /> : null}
          {activeView === "history" ? <HistoryView history={history} /> : null}
          {activeView === "cloud" ? <CloudView /> : null}
        </main>
      </div>
    </div>
  )
}
