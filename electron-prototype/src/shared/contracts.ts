export type ViewId =
  | "stem-slicer"
  | "generate"
  | "quick-tools"
  | "history"
  | "cloud"

export type KeyCoverage = "analyzed" | "unavailable"

export interface AppEnvironment {
  platform: string
  architecture: string
  electronVersion: string
  nodeVersion: string
  prototypeCachePath: string
  acceptedCachePath: string
  acceptedCacheAccess: "read-only"
}

export interface LibraryRootSummary {
  path: string
  name: string
  layerCount: number
  analyzedKeyCount: number
  keyCoverage: KeyCoverage
  categories: CategorySummary[]
}

export interface CategorySummary {
  name: string
  count: number
}

export interface LibraryOverview {
  databaseDetected: boolean
  databasePath: string
  totalLayers: number
  roots: LibraryRootSummary[]
  categories: CategorySummary[]
  error?: string
}

export interface MigrationModule {
  id: string
  label: string
  runtime: "TypeScript" | "External binary" | "Python adapter"
  state: "native" | "connected" | "queued"
  detail: string
}

export interface AudioSelection {
  canceled: boolean
  paths: string[]
}

export type AudioJobKind =
  | "batch"
  | "quick-scan"
  | "quick-extract"
  | "quick-convert"
  | "library-scan"
  | "generate"
  | "generate-update"

export interface BatchJobRequest {
  sourceFolder: string
  outputFolder: string
  extractionEnabled: boolean
  keyAnalysisEnabled: boolean
  conversionEnabled: boolean
  keyMode: "detected" | "relative_minor" | "relative_major"
  accidentals: "sharps" | "flats"
  destinationMode: "copy_to_output" | "rename_in_place"
  tokenOrder: string[]
  targetBpmEnabled: boolean
  targetBpm: number
  targetKeyEnabled: boolean
  targetKey: string
}

export interface QuickScanJobRequest {
  source: string
}

export interface QuickExtractJobRequest {
  source: string
  targetBpmEnabled: boolean
  targetBpm: number
  targetKeyEnabled: boolean
  targetKey: string
}

export interface QuickConvertJobRequest {
  source: string
  targetBpmEnabled: boolean
  targetBpm: number
  targetKeyEnabled: boolean
  targetKey: string
}

export interface GenerateJobRequest {
  databasePath: string
  libraryRoots: string[]
  categories: string[]
  targetBpm: number
  targetKey: string
  seed: number
  bars?: number
  lockedIdentitiesBySlot?: Array<string | null>
  excludedIdentities?: string[]
}

export interface GenerateUpdateJobRequest {
  outputDirectory: string
  identity: string
  slotIndex: number
  update: "octave" | "source-key"
  octave?: -1 | 0 | 1
  sourceKeyRank?: 1 | 2
}

export interface LibraryScanJobRequest {
  root: string
  databasePath: string
}

export type AudioJobRequest =
  | BatchJobRequest
  | QuickScanJobRequest
  | QuickExtractJobRequest
  | QuickConvertJobRequest
  | LibraryScanJobRequest
  | GenerateJobRequest
  | GenerateUpdateJobRequest

export interface AudioArtifact {
  path: string
  name: string
  displayName: string
  bpm: number
  key: string
  duration: number
  bytes: number
  peaks: number[]
  midiPath?: string
  category?: string
  alternateKey?: string
  sourcePath?: string
  identity?: string
  sourceKeyRank?: 1 | 2
  octave?: -1 | 0 | 1
}

export interface QuickScanResult {
  source: string
  bpm: number
  detectedKey: string
  relativeKey: string
  camelot: string
  openKey: string
  bpmConfidence: number | null
  bpmSource: string
  relativeModes: Array<{
    degreeMajor: string
    degreeMinor: string
    key: string
    mode: string
  }>
  raw: Record<string, unknown>
}

export interface BatchJobResult {
  outputFolder: string
  files: number
  outputs: string[]
  failures: Array<{ source: string; message: string }>
}

export interface QuickExtractResult {
  outputFolder: string
  layers: AudioArtifact[]
  elapsedSeconds: number
}

export interface QuickConvertResult {
  outputFolder: string
  artifact: AudioArtifact
  sourceBpm: number
  sourceKey: string
  targetBpm: number
  targetKey: string
  elapsedSeconds: number
}

export interface GenerateResult {
  outputDirectory: string
  masterPath: string
  manifestPath: string
  seed: number
  targetBpm: number
  targetKey: string
  layers: AudioArtifact[]
}

export interface LibraryScanResult {
  root: string
  totalFiles: number
  added: number
  updated: number
  unchanged: number
  removed: number
  issues: number
}

export type AudioJobResult =
  | BatchJobResult
  | QuickScanResult
  | QuickExtractResult
  | QuickConvertResult
  | LibraryScanResult
  | GenerateResult

export interface AudioJobStart {
  jobId: string
}

export interface AudioJobEvent {
  jobId: string
  kind: AudioJobKind
  type: "progress" | "artifact" | "completed" | "failed" | "cancelled"
  message: string
  phase?: string
  current?: number
  total?: number
  percent?: number
  artifact?: AudioArtifact
  result?: AudioJobResult
  error?: string
}

export interface EngineStatus {
  available: boolean
  state: "ready" | "starting" | "unavailable"
  pythonPath: string
  sourceRoot: string
  message: string
}

export interface StemSlicerDesktopApi {
  getEnvironment: () => Promise<AppEnvironment>
  getLibraryOverview: () => Promise<LibraryOverview>
  getMigrationModules: () => Promise<MigrationModule[]>
  getEngineStatus: () => Promise<EngineStatus>
  pickLibraryFolder: () => Promise<AudioSelection>
  pickAudioFiles: () => Promise<AudioSelection>
  startAudioJob: (kind: AudioJobKind, request: AudioJobRequest) => Promise<AudioJobStart>
  cancelAudioJob: (jobId: string) => Promise<void>
  onAudioJobEvent: (listener: (event: AudioJobEvent) => void) => () => void
  pathForFile: (file: File) => string
  revealPath: (path: string) => Promise<void>
  startFileDrag: (path: string) => void
  startFilesDrag: (paths: string[]) => void
  mediaUrl: (path: string) => string
}
