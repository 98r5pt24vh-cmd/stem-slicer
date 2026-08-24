import { app, BrowserWindow, dialog, ipcMain, shell } from "electron"
import type { IpcMainInvokeEvent } from "electron"
import path from "node:path"
import { homedir } from "node:os"

import { readLibraryOverview } from "./main/library-cache"
import { migrationModules } from "./main/migration-modules"
import type { AudioSelection } from "./shared/contracts"

const acceptedCachePath = path.join(
  homedir(),
  "Library",
  "Caches",
  "Stem Slicer",
  "1.9",
)
const prototypeCachePath = path.join(
  homedir(),
  "Library",
  "Caches",
  "Stem Slicer",
  "electron-prototype",
)

app.setPath("userData", path.join(prototypeCachePath, "electron-user-data"))
app.setName("Stem Slicer Electron Prototype")

function createWindow(): void {
  const mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1040,
    minHeight: 700,
    backgroundColor: "#09090b",
    titleBarStyle: process.platform === "darwin" ? "hiddenInset" : "default",
    trafficLightPosition: { x: 18, y: 18 },
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  mainWindow.once("ready-to-show", () => mainWindow.show())

  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    void mainWindow.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL)
  } else {
    void mainWindow.loadFile(
      path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`),
    )
  }
}

function registerIpc(): void {
  ipcMain.handle("app:get-environment", () => ({
    platform: process.platform,
    architecture: process.arch,
    electronVersion: process.versions.electron,
    nodeVersion: process.versions.node,
    prototypeCachePath,
    acceptedCachePath,
    acceptedCacheAccess: "read-only" as const,
  }))
  ipcMain.handle("library:get-overview", () =>
    readLibraryOverview(acceptedCachePath),
  )
  ipcMain.handle("migration:get-modules", () => migrationModules)
  ipcMain.handle("dialog:pick-library-folder", async (): Promise<AudioSelection> => {
    const result = await dialog.showOpenDialog({
      title: "Choisir une bibliothèque de layers",
      properties: ["openDirectory"],
    })
    return { canceled: result.canceled, paths: result.filePaths }
  })
  ipcMain.handle("dialog:pick-audio-files", async (): Promise<AudioSelection> => {
    const result = await dialog.showOpenDialog({
      title: "Choisir des fichiers audio",
      properties: ["openFile", "multiSelections"],
      filters: [
        {
          name: "Audio",
          extensions: ["wav", "aif", "aiff", "flac", "mp3", "m4a"],
        },
      ],
    })
    return { canceled: result.canceled, paths: result.filePaths }
  })
  ipcMain.handle("shell:reveal-path", (_event: IpcMainInvokeEvent, targetPath: unknown) => {
    if (typeof targetPath !== "string" || targetPath.length === 0) return
    shell.showItemInFolder(targetPath)
  })
}

app.whenReady().then(() => {
  registerIpc()
  createWindow()

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit()
})
