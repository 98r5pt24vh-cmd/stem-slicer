import { contextBridge, ipcRenderer, webUtils, type IpcRendererEvent } from "electron"

import type { AudioJobEvent, StemSlicerDesktopApi } from "./shared/contracts"

const api: StemSlicerDesktopApi = {
  getEnvironment: () => ipcRenderer.invoke("app:get-environment"),
  getGenerationStorageUsage: () => ipcRenderer.invoke("history:get-storage-usage"),
  getLibraryOverview: () => ipcRenderer.invoke("library:get-overview"),
  removeLibraryRoot: (libraryRoot) => ipcRenderer.invoke("library:remove-root", libraryRoot),
  getKeyIssueReports: () => ipcRenderer.invoke("key-issues:list"),
  getCategoryCorrections: () => ipcRenderer.invoke("category-corrections:list"),
  reportKeyIssue: (request) => ipcRenderer.invoke("key-issues:report", request),
  setKeyIssueActive: (issueId, active) => ipcRenderer.invoke("key-issues:set-active", issueId, active),
  dismissKeyIssueReport: (issueId) => ipcRenderer.invoke("key-issues:dismiss", issueId),
  getSourceLoopEditor: (libraryRoot, sourceLoopId) => ipcRenderer.invoke("source-loop:get-editor", libraryRoot, sourceLoopId),
  saveSourceLoopEdit: (request) => ipcRenderer.invoke("source-loop:save-editor", request),
  setLayerCategory: (request) => ipcRenderer.invoke("source-loop:set-layer-category", request),
  getMigrationModules: () => ipcRenderer.invoke("migration:get-modules"),
  getEngineStatus: () => ipcRenderer.invoke("engine:get-status"),
  pickLibraryFolder: () => ipcRenderer.invoke("dialog:pick-library-folder"),
  pickAudioFiles: () => ipcRenderer.invoke("dialog:pick-audio-files"),
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
