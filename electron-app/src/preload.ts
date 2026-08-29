import { contextBridge, ipcRenderer, webUtils, type IpcRendererEvent } from "electron"

import type { AudioJobEvent, CloudPublishEvent, EngineStatus, StemSlicerDesktopApi } from "./shared/contracts"

const api: StemSlicerDesktopApi = {
  getEnvironment: () => ipcRenderer.invoke("app:get-environment"),
  getGenerationStorageUsage: () => ipcRenderer.invoke("history:get-storage-usage"),
  getHistoryStorageUsage: (paths) => ipcRenderer.invoke("history:get-path-storage-usage", paths),
  getQuickActivityHistory: () => ipcRenderer.invoke("history:get-quick-activities"),
  openHistoryRoot: () => ipcRenderer.invoke("history:open-root"),
  trashHistoryPath: (request) => ipcRenderer.invoke("history:trash-output", request),
  getLibraryOverview: () => ipcRenderer.invoke("library:get-overview"),
  getLibraryProducers: (primaryProducer, libraryRoots, producerIdentities) => ipcRenderer.invoke("library:get-producers", primaryProducer, libraryRoots, producerIdentities),
  getLibrarySelectionSummary: (request) => ipcRenderer.invoke("library:get-selection-summary", request),
  removeLibraryRoot: (libraryRoot) => ipcRenderer.invoke("library:remove-root", libraryRoot),
  getKeyIssueReports: () => ipcRenderer.invoke("key-issues:list"),
  getCategoryCorrections: () => ipcRenderer.invoke("category-corrections:list"),
  dismissCategoryCorrections: (identities) => ipcRenderer.invoke("category-corrections:dismiss", identities),
  reportKeyIssue: (request) => ipcRenderer.invoke("key-issues:report", request),
  setKeyIssueActive: (issueId, active) => ipcRenderer.invoke("key-issues:set-active", issueId, active),
  dismissKeyIssueReport: (issueId) => ipcRenderer.invoke("key-issues:dismiss", issueId),
  getSourceLoopEditor: (libraryRoot, sourceLoopId) => ipcRenderer.invoke("source-loop:get-editor", libraryRoot, sourceLoopId),
  saveSourceLoopEdit: (request) => ipcRenderer.invoke("source-loop:save-editor", request),
  setLayerCategory: (request) => ipcRenderer.invoke("source-loop:set-layer-category", request),
  getEngineStatus: () => ipcRenderer.invoke("engine:get-status"),
  retryEngine: () => ipcRenderer.invoke("engine:retry"),
  onEngineStatus: (listener) => {
    const handler = (_event: IpcRendererEvent, payload: EngineStatus) => listener(payload)
    ipcRenderer.on("engine:status", handler)
    return () => ipcRenderer.removeListener("engine:status", handler)
  },
  getCloudState: () => ipcRenderer.invoke("cloud:get-state"),
  configureCloud: (request) => ipcRenderer.invoke("cloud:configure", request),
  cloudSignUp: (request) => ipcRenderer.invoke("cloud:sign-up", request),
  cloudSignIn: (request) => ipcRenderer.invoke("cloud:sign-in", request),
  cloudSignInTestAccount: (accountId) => ipcRenderer.invoke("cloud:sign-in-test-account", accountId),
  cloudSignOut: () => ipcRenderer.invoke("cloud:sign-out"),
  cloudUpdateProfile: (request) => ipcRenderer.invoke("cloud:update-profile", request),
  cloudConnect: (handle) => ipcRenderer.invoke("cloud:connect", handle),
  cloudAcceptConnection: (connectionId) => ipcRenderer.invoke("cloud:accept-connection", connectionId),
  cloudRemoveConnection: (connectionId) => ipcRenderer.invoke("cloud:remove-connection", connectionId),
  cloudPublishLibrary: (libraryRoot) => ipcRenderer.invoke("cloud:publish-library", libraryRoot),
  cloudSetLibraryEnabled: (libraryId, enabled) => ipcRenderer.invoke("cloud:set-library-enabled", libraryId, enabled),
  cloudSetLibrarySharing: (libraryId, sharing) => ipcRenderer.invoke("cloud:set-library-sharing", libraryId, sharing),
  cloudSetLibraryProducerAccess: (libraryId, producerId, allowed) => ipcRenderer.invoke("cloud:set-library-producer-access", libraryId, producerId, allowed),
  cloudRemoveLibrary: (libraryId) => ipcRenderer.invoke("cloud:remove-library", libraryId),
  cloudRecordGeneration: (request) => ipcRenderer.invoke("cloud:record-generation", request),
  getCloudGenerationActivity: () => ipcRenderer.invoke("cloud:get-generation-activity"),
  onCloudPublishEvent: (listener) => {
    const handler = (_event: IpcRendererEvent, payload: CloudPublishEvent) => listener(payload)
    ipcRenderer.on("cloud:publish-event", handler)
    return () => ipcRenderer.removeListener("cloud:publish-event", handler)
  },
  pickLibraryFolder: () => ipcRenderer.invoke("dialog:pick-library-folder"),
  pickAudioFiles: () => ipcRenderer.invoke("dialog:pick-audio-files"),
  pickImageFile: () => ipcRenderer.invoke("dialog:pick-image-file"),
  openExternalUrl: (url) => ipcRenderer.invoke("shell:open-external", url),
  startAudioJob: (kind, request) => ipcRenderer.invoke("audio-job:start", kind, request),
  cancelAudioJob: (jobId) => ipcRenderer.invoke("audio-job:cancel", jobId),
  onAudioJobEvent: (listener) => {
    const handler = (_event: IpcRendererEvent, payload: AudioJobEvent) => listener(payload)
    ipcRenderer.on("audio-job:event", handler)
    return () => ipcRenderer.removeListener("audio-job:event", handler)
  },
  pathForFile: (file) => webUtils.getPathForFile(file),
  revealPath: (path) => ipcRenderer.invoke("shell:reveal-path", path),
  trashPath: (path) => ipcRenderer.invoke("shell:trash-path", path),
  startFileDrag: (path) => ipcRenderer.send("drag:start", path),
  startFilesDrag: (paths) => ipcRenderer.send("drag:start-many", paths),
  mediaUrl: (path) => `stem-media://local/audio?path=${encodeURIComponent(path)}`,
}

contextBridge.exposeInMainWorld("stemSlicer", api)
