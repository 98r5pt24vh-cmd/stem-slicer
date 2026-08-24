import { contextBridge, ipcRenderer } from "electron"

import type { StemSlicerDesktopApi } from "./shared/contracts"

const api: StemSlicerDesktopApi = {
  getEnvironment: () => ipcRenderer.invoke("app:get-environment"),
  getLibraryOverview: () => ipcRenderer.invoke("library:get-overview"),
  getMigrationModules: () => ipcRenderer.invoke("migration:get-modules"),
  pickLibraryFolder: () => ipcRenderer.invoke("dialog:pick-library-folder"),
  pickAudioFiles: () => ipcRenderer.invoke("dialog:pick-audio-files"),
  revealPath: (path) => ipcRenderer.invoke("shell:reveal-path", path),
}

contextBridge.exposeInMainWorld("stemSlicer", api)
