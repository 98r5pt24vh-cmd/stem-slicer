export type ViewId =
  | "stem-slicer"
  | "generate"
  | "quick-tools"
  | "history"
  | "library"
  | "cloud"
  | "profile"

export type KeyCoverage = "analyzed" | "unavailable"

export interface AppEnvironment {
  platform: string
  architecture: string
  electronVersion: string
  nodeVersion: string
  prototypeCachePath: string
  acceptedCachePath: string
  acceptedCacheAccess: "read-only"
  defaultExtractionOutputPath: string
}

export interface GenerationStorageUsage {
  bytes: number
  folders: number
  files: number
}

export type HistoryOutputKind = "generate" | "extract" | "convert"

export interface TrashHistoryOutputRequest {
  kind: HistoryOutputKind
  targetPath: string
}

export interface CloudProfile {
  id: string
  handle: string
  displayName: string
  avatarPath?: string
  avatarUrl?: string
  bio?: string
  instagramHandle?: string
  aliases: string[]
  openToCollaborate: boolean
}

export interface CloudConnection {
  id: string
  status: "pending" | "accepted" | "declined"
  direction: "incoming" | "outgoing"
  profile: CloudProfile
  createdAt: string
}

export interface CloudLibrarySummary {
  id: string
  name: string
  owner: CloudProfile
  status: "uploading" | "ready" | "failed" | "archived"
  layerCount: number
  loopCount: number
  totalBytes: number
  own: boolean
  enabledForGenerate: boolean
  updatedAt: string
  categories?: CategorySummary[]
}

export interface CloudTestAccount {
  id: string
  handle: string
  displayName: string
}

export interface CloudState {
  configured: boolean
  projectUrl: string
  authenticated: boolean
  userEmail?: string
  profile?: CloudProfile
  connections: CloudConnection[]
  libraries: CloudLibrarySummary[]
  testAccounts?: CloudTestAccount[]
  message?: string
}

export interface CloudGenerationSource {
  slotIndex: number
  sourceOwner: CloudProfile
  sourceLoopId: string
  category: string
}

export interface CloudGenerationActivity {
  id: string
  createdBy: CloudProfile
  contributors: CloudProfile[]
  seed: number
  targetBpm: number
  targetKey: string
  layerCount: number
  createdAt: string
  sources: CloudGenerationSource[]
}

export interface CloudGenerationRecordRequest {
  seed: number
  targetBpm: number
  targetKey: string
  layerCount: number
  sources: Array<{
    slotIndex: number
    cloudLayerId: string
    cloudOwnerId: string
    sourceSha256: string
    sourceLoopId: string
    category: string
  }>
}

export interface ConfigureCloudRequest {
  projectUrl: string
  publishableKey: string
}

export interface CloudCredentialsRequest {
  email: string
  password: string
}

export interface CloudSignUpRequest extends CloudCredentialsRequest {
  handle: string
  displayName: string
}

export interface CloudProfileUpdateRequest {
  handle: string
  displayName: string
  bio: string
  instagramHandle: string
  aliases: string[]
  openToCollaborate: boolean
  avatarFilePath?: string
}

export interface CloudPublishStart {
  jobId: string
}

export interface CloudPublishEvent {
  jobId: string
  type: "progress" | "completed" | "failed"
  message: string
  current?: number
  total?: number
  percent?: number
  library?: CloudLibrarySummary
  error?: string
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

export interface LibraryProducerSummary {
  name: string
  layerCount: number
  loopCount: number
  loopCountsByCreditCount: Record<string, number>
  layerCountsByCreditCount: Record<string, number>
  libraryRoots: string[]
  source?: "local" | "cloud" | "mixed"
  localLayerCount?: number
  localLoopCount?: number
  localLoopCountsByCreditCount?: Record<string, number>
  localLayerCountsByCreditCount?: Record<string, number>
  cloudLayerCount?: number
  cloudLoopCount?: number
  cloudLoopCountsByCreditCount?: Record<string, number>
  cloudLayerCountsByCreditCount?: Record<string, number>
}

export interface LibrarySelectionSummaryRequest {
  libraryRoots: string[]
  allowedProducers: string[]
  allowedCreditCounts: number[]
}

export interface LibrarySelectionSummary {
  layerCount: number
  loopCount: number
  categories: CategorySummary[]
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
  generationNumber: number
  bars?: number
  sourcePool?: "mixed" | "cloud-only" | "local-only"
  allowedProducers?: string[]
  allowedCreditCounts?: number[]
  requiredProducers?: string[]
  requiredContributionPercent?: number
  lockedIdentitiesBySlot?: Array<string | null>
  excludedIdentities?: string[]
  excludedSourceLoops?: Array<{
    libraryRoot: string
    sourceLoopId: string
  }>
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
  octave?: -1 | 0 | 1
  locked?: boolean
}

export interface ExtractionHistoryEntry {
  id: string
  mode: "single" | "folder"
  sourcePath: string
  outputFolder: string
  createdAt: string
  sourceFileCount: number
  outputCount: number
  outputs: string[]
  outputBytes?: number
  elapsedSeconds?: number
}

export interface ConvertHistoryEntry {
  id: string
  sourcePath: string
  outputFolder: string
  createdAt: string
  artifact: AudioArtifact
  sourceBpm: number
  sourceKey: string
  targetBpm: number
  targetKey: string
  elapsedSeconds: number
  recovered?: boolean
}

export interface QuickActivityHistorySnapshot {
  extractions: ExtractionHistoryEntry[]
  conversions: ConvertHistoryEntry[]
}

export interface KeyIssueAffectedLayer {
  identity: string
  path: string
  file: string
  detectedKey: string
}

export type LibraryIssueType = "wrong-key" | "wrong-slice"

export interface KeyIssueReport {
  id: string
  issueType: LibraryIssueType
  libraryRoot: string
  sourceLoopId: string
  reportedIdentity: string
  reportedPath: string
  reportedFile: string
  detectedKey: string
  targetKey: string
  generationOutputDirectory: string
  createdAt: string
  resolvedAt?: string
  active: boolean
  affectedLayers: KeyIssueAffectedLayer[]
}

export interface CategoryCorrection {
  identity: string
  libraryRoot: string
  sourceLoopId: string
  path: string
  filename: string
  previousCategory?: string
  correctedCategory: string
  validatedAt: string
}

export interface ReportKeyIssueRequest {
  issueType: LibraryIssueType
  libraryRoot: string
  sourceLoopId: string
  reportedIdentity: string
  reportedPath: string
  reportedFile: string
  detectedKey: string
  targetKey: string
  generationOutputDirectory: string
}

export interface SourceLoopEditorLayer {
  identity: string
  path: string
  file: string
  layerIndex?: number
  category: string
  duration: number
  offsetBeats: number
  trimStartBeats: number
  trimEndBeats: number
}

export interface SourceLoopEditorData {
  libraryRoot: string
  sourceLoopId: string
  bpm: number
  keyName: string
  layers: SourceLoopEditorLayer[]
}

export interface SourceLoopLayerEdit {
  identity: string
  category: string
  offsetBeats: number
  trimStartBeats: number
  trimEndBeats: number
}

export interface SaveSourceLoopEditRequest {
  libraryRoot: string
  sourceLoopId: string
  bpm: number
  keyName: string
  layers: SourceLoopLayerEdit[]
  excludedIdentities?: string[]
}

export interface SetLayerCategoryRequest {
  libraryRoot: string
  sourceLoopId: string
  identity: string
  path: string
  category: string
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
  generationNumber?: number
  displayName?: string
  producers?: string[]
  elapsedSeconds?: number
  selectionSeconds?: number
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

export type EngineState = "idle" | "starting" | "ready" | "failed" | "unavailable"

export type EngineComponentState = EngineState | "on-demand"

export interface EngineComponentStatus {
  state: EngineComponentState
  message: string
}

export interface EngineStatus {
  available: boolean
  state: EngineState
  pythonPath: string
  sourceRoot: string
  message: string
  components: {
    musicalAnalysis: EngineComponentStatus
    midi: EngineComponentStatus
    categorization: EngineComponentStatus
  }
}

export interface StemSlicerDesktopApi {
  getEnvironment: () => Promise<AppEnvironment>
  getGenerationStorageUsage: () => Promise<GenerationStorageUsage>
  getHistoryStorageUsage: (paths: string[]) => Promise<GenerationStorageUsage>
  getQuickActivityHistory: () => Promise<QuickActivityHistorySnapshot>
  openHistoryRoot: () => Promise<void>
  trashHistoryPath: (request: TrashHistoryOutputRequest) => Promise<void>
  getLibraryOverview: () => Promise<LibraryOverview>
  getLibraryProducers: () => Promise<LibraryProducerSummary[]>
  getLibrarySelectionSummary: (request: LibrarySelectionSummaryRequest) => Promise<LibrarySelectionSummary>
  removeLibraryRoot: (libraryRoot: string) => Promise<LibraryOverview>
  getKeyIssueReports: () => Promise<KeyIssueReport[]>
  getCategoryCorrections: () => Promise<CategoryCorrection[]>
  dismissCategoryCorrections: (identities: string[]) => Promise<CategoryCorrection[]>
  reportKeyIssue: (request: ReportKeyIssueRequest) => Promise<KeyIssueReport[]>
  setKeyIssueActive: (issueId: string, active: boolean) => Promise<KeyIssueReport[]>
  dismissKeyIssueReport: (issueId: string) => Promise<KeyIssueReport[]>
  getSourceLoopEditor: (libraryRoot: string, sourceLoopId: string) => Promise<SourceLoopEditorData>
  saveSourceLoopEdit: (request: SaveSourceLoopEditRequest) => Promise<SourceLoopEditorData>
  setLayerCategory: (request: SetLayerCategoryRequest) => Promise<SourceLoopEditorLayer>
  getMigrationModules: () => Promise<MigrationModule[]>
  getEngineStatus: () => Promise<EngineStatus>
  retryEngine: () => Promise<EngineStatus>
  onEngineStatus: (listener: (status: EngineStatus) => void) => () => void
  getCloudState: () => Promise<CloudState>
  configureCloud: (request: ConfigureCloudRequest) => Promise<CloudState>
  cloudSignUp: (request: CloudSignUpRequest) => Promise<CloudState>
  cloudSignIn: (request: CloudCredentialsRequest) => Promise<CloudState>
  cloudSignInTestAccount: (accountId: string) => Promise<CloudState>
  cloudSignOut: () => Promise<CloudState>
  cloudUpdateProfile: (request: CloudProfileUpdateRequest) => Promise<CloudState>
  cloudConnect: (handle: string) => Promise<CloudState>
  cloudAcceptConnection: (connectionId: string) => Promise<CloudState>
  cloudPublishLibrary: (libraryRoot: string) => Promise<CloudPublishStart>
  cloudSetLibraryEnabled: (libraryId: string, enabled: boolean) => Promise<CloudState>
  cloudSetLibrarySharing: (libraryId: string, sharing: boolean) => Promise<CloudState>
  cloudRemoveLibrary: (libraryId: string) => Promise<CloudState>
  cloudRecordGeneration: (request: CloudGenerationRecordRequest) => Promise<string | undefined>
  getCloudGenerationActivity: () => Promise<CloudGenerationActivity[]>
  onCloudPublishEvent: (listener: (event: CloudPublishEvent) => void) => () => void
  pickLibraryFolder: () => Promise<AudioSelection>
  pickAudioFiles: () => Promise<AudioSelection>
  pickImageFile: () => Promise<AudioSelection>
  openExternalUrl: (url: string) => Promise<void>
  startAudioJob: (kind: AudioJobKind, request: AudioJobRequest) => Promise<AudioJobStart>
  cancelAudioJob: (jobId: string) => Promise<void>
  onAudioJobEvent: (listener: (event: AudioJobEvent) => void) => () => void
  pathForFile: (file: File) => string
  revealPath: (path: string) => Promise<void>
  trashPath: (path: string) => Promise<void>
  startFileDrag: (path: string) => void
  startFilesDrag: (paths: string[]) => void
  mediaUrl: (path: string) => string
}
