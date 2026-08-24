export type ViewId =
  | "stem-slicer"
  | "generate"
  | "library"
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

export interface StemSlicerDesktopApi {
  getEnvironment: () => Promise<AppEnvironment>
  getLibraryOverview: () => Promise<LibraryOverview>
  getMigrationModules: () => Promise<MigrationModule[]>
  pickLibraryFolder: () => Promise<AudioSelection>
  pickAudioFiles: () => Promise<AudioSelection>
  revealPath: (path: string) => Promise<void>
}
