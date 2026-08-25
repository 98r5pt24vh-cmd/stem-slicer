import { app, BrowserWindow, dialog, ipcMain, nativeImage, net, protocol, shell } from "electron"
import type { IpcMainInvokeEvent } from "electron"
import path from "node:path"
import { homedir } from "node:os"
import { existsSync, statSync } from "node:fs"
import { pathToFileURL } from "node:url"

import { AudioEngineService } from "./main/audio-engine"
import { readLibraryOverview } from "./main/library-cache"
import { migrationModules } from "./main/migration-modules"
import type { AudioJobKind, AudioJobRequest, AudioSelection } from "./shared/contracts"

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
const generatedOutputRoot = path.join(
  homedir(),
  "Documents",
  "Stem Slicer",
  "Generated Loops",
)

app.setPath("userData", path.join(prototypeCachePath, "electron-user-data"))
app.setName("Stem Slicer Electron Prototype")
protocol.registerSchemesAsPrivileged([
  {
    scheme: "stem-media",
    privileges: { secure: true, standard: true, supportFetchAPI: true, stream: true },
  },
])

const audioEngine = new AudioEngineService(app.getAppPath(), prototypeCachePath)

function createWindow(): void {
  const mainWindow = new BrowserWindow({
    width: 1226,
    height: 786,
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
  ipcMain.handle("engine:get-status", () => audioEngine.status())
  ipcMain.handle(
    "audio-job:start",
    (event: IpcMainInvokeEvent, kind: AudioJobKind, request: AudioJobRequest) =>
      audioEngine.startJob(kind, request, event.sender),
  )
  ipcMain.handle("audio-job:cancel", (_event: IpcMainInvokeEvent, jobId: unknown) => {
    if (typeof jobId === "string") audioEngine.cancelJob(jobId)
  })
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
  ipcMain.handle("shell:trash-path", async (_event: IpcMainInvokeEvent, targetPath: unknown) => {
    if (typeof targetPath !== "string" || targetPath.length === 0 || !existsSync(targetPath)) return
    const resolvedTarget = path.resolve(targetPath)
    const relativeTarget = path.relative(generatedOutputRoot, resolvedTarget)
    if (!relativeTarget || relativeTarget.startsWith("..") || path.isAbsolute(relativeTarget) || path.dirname(resolvedTarget) !== generatedOutputRoot || !statSync(resolvedTarget).isDirectory()) {
      throw new Error("Only an individual generated output folder can be moved to Trash.")
    }
    await shell.trashItem(resolvedTarget)
  })
  ipcMain.on("drag:start", (event, targetPath: unknown) => {
    if (typeof targetPath !== "string" || !existsSync(targetPath)) return
    const iconPath = path.join(audioEngine.status().sourceRoot, "assets", "app-icon.png")
    event.sender.startDrag({
      file: targetPath,
      icon: existsSync(iconPath) ? nativeImage.createFromPath(iconPath) : nativeImage.createEmpty(),
    })
  })
  ipcMain.on("drag:start-many", (event, targetPaths: unknown) => {
    if (!Array.isArray(targetPaths)) return
    const files = targetPaths.filter((item): item is string => typeof item === "string" && existsSync(item))
    if (files.length === 0) return
    const iconPath = path.join(audioEngine.status().sourceRoot, "assets", "app-icon.png")
    event.sender.startDrag({
      file: files[0],
      files,
      icon: existsSync(iconPath) ? nativeImage.createFromPath(iconPath) : nativeImage.createEmpty(),
    })
  })
}

app.whenReady().then(() => {
  protocol.handle("stem-media", (request) => {
    const url = new URL(request.url)
    const targetPath = decodeURIComponent(url.pathname.replace(/^\//, ""))
    if (!path.isAbsolute(targetPath) || !existsSync(targetPath)) {
      return new Response("Media file unavailable.", { status: 404 })
    }
    return net.fetch(pathToFileURL(targetPath).toString())
  })
  registerIpc()
  createWindow()

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit()
})

app.on("before-quit", () => audioEngine.shutdown())
