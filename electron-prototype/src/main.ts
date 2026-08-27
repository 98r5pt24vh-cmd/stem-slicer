import { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, net, protocol, shell } from "electron"
import type { IpcMainInvokeEvent } from "electron"
import path from "node:path"
import { homedir } from "node:os"
import { existsSync, statSync } from "node:fs"
import { pathToFileURL } from "node:url"

import { AudioEngineService } from "./main/audio-engine"
import { getSourceLoopEditor, saveSourceLoopEdit, setLayerCategory } from "./main/catalog-edits"
import { dismissKeyIssueReport, listKeyIssueReports, reportKeyIssue, setKeyIssueActive } from "./main/key-feedback"
import { readLibraryOverview, removeLibraryRoot } from "./main/library-cache"
import { mediaMimeType, parseByteRange } from "./main/media-range"
import { migrationModules } from "./main/migration-modules"
import { readGenerationStorageUsage } from "./main/storage-usage"
import type {
  AudioJobKind,
  AudioJobRequest,
  AudioSelection,
  ReportKeyIssueRequest,
  SaveSourceLoopEditRequest,
  SetLayerCategoryRequest,
} from "./shared/contracts"

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
const dragPreviewMaxSize = 40

async function createMediaResponse(request: Request, targetPath: string): Promise<Response> {
  const size = statSync(targetPath).size
  const contentType = mediaMimeType(path.extname(targetPath))
  const commonHeaders = {
    "Accept-Ranges": "bytes",
    "Access-Control-Allow-Origin": "*",
    "Content-Type": contentType,
  }
  const rangeHeader = request.headers.get("range")

  if (request.method === "HEAD") {
    return new Response(null, {
      status: 200,
      headers: { ...commonHeaders, "Content-Length": String(size) },
    })
  }

  if (!rangeHeader) {
    const source = await net.fetch(pathToFileURL(targetPath).toString())
    return new Response(source.body, {
      status: 200,
      headers: { ...commonHeaders, "Content-Length": String(size) },
    })
  }

  const range = parseByteRange(rangeHeader, size)
  if (!range) {
    return new Response(null, {
      status: 416,
      headers: { ...commonHeaders, "Content-Range": `bytes */${size}` },
    })
  }

  const source = await net.fetch(pathToFileURL(targetPath).toString(), {
    headers: { Range: `bytes=${range.start}-${range.end}` },
  })
  return new Response(source.body, {
    status: 206,
    headers: {
      ...commonHeaders,
      "Content-Length": String(range.end - range.start + 1),
      "Content-Range": `bytes ${range.start}-${range.end}/${size}`,
    },
  })
}

function createDragPreviewIcon() {
  const iconPath = path.join(audioEngine.status().sourceRoot, "assets", "app-icon.png")
  if (!existsSync(iconPath)) return nativeImage.createEmpty()
  const source = nativeImage.createFromPath(iconPath)
  if (source.isEmpty()) return source
  const size = source.getSize()
  const scale = Math.min(dragPreviewMaxSize / size.width, dragPreviewMaxSize / size.height, 1)
  if (scale === 1) return source
  return source.resize({
    width: Math.max(1, Math.round(size.width * scale)),
    height: Math.max(1, Math.round(size.height * scale)),
    quality: "best",
  })
}

app.setPath("userData", path.join(prototypeCachePath, "electron-user-data"))
app.setName("Stem Slicer Electron Prototype")
protocol.registerSchemesAsPrivileged([
  {
    scheme: "stem-media",
    privileges: { corsEnabled: true, secure: true, standard: true, supportFetchAPI: true, stream: true },
  },
])

const audioEngine = new AudioEngineService(app.getAppPath(), prototypeCachePath)

function createWindow(): void {
  const mainWindow = new BrowserWindow({
    width: 1226,
    height: 786,
    minWidth: 1040,
    minHeight: 700,
    autoHideMenuBar: true,
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
  mainWindow.setMenu(null)

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
  ipcMain.handle("history:get-storage-usage", () => readGenerationStorageUsage(generatedOutputRoot))
  ipcMain.handle("library:get-overview", () =>
    readLibraryOverview(acceptedCachePath),
  )
  ipcMain.handle("library:remove-root", (_event: IpcMainInvokeEvent, libraryRoot: unknown) => {
    if (typeof libraryRoot !== "string") {
      throw new Error("The indexed library path is invalid.")
    }
    return removeLibraryRoot(acceptedCachePath, libraryRoot)
  })
  ipcMain.handle("key-issues:list", () => listKeyIssueReports(acceptedCachePath))
  ipcMain.handle("key-issues:report", (_event: IpcMainInvokeEvent, request: ReportKeyIssueRequest) =>
    reportKeyIssue(acceptedCachePath, request),
  )
  ipcMain.handle("key-issues:set-active", (_event: IpcMainInvokeEvent, issueId: unknown, active: unknown) => {
    if (typeof issueId !== "string" || typeof active !== "boolean") {
      throw new Error("The key-issue update is invalid.")
    }
    return setKeyIssueActive(acceptedCachePath, issueId, active)
  })
  ipcMain.handle("key-issues:dismiss", (_event: IpcMainInvokeEvent, issueId: unknown) => {
    if (typeof issueId !== "string") throw new Error("The key-issue report is invalid.")
    return dismissKeyIssueReport(acceptedCachePath, issueId)
  })
  ipcMain.handle("source-loop:get-editor", (_event: IpcMainInvokeEvent, libraryRoot: unknown, sourceLoopId: unknown) =>
    getSourceLoopEditor(acceptedCachePath, libraryRoot, sourceLoopId),
  )
  ipcMain.handle("source-loop:save-editor", (_event: IpcMainInvokeEvent, request: SaveSourceLoopEditRequest) =>
    saveSourceLoopEdit(acceptedCachePath, request),
  )
  ipcMain.handle("source-loop:set-layer-category", (_event: IpcMainInvokeEvent, request: SetLayerCategoryRequest) =>
    setLayerCategory(acceptedCachePath, request),
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
    event.sender.startDrag({
      file: targetPath,
      icon: createDragPreviewIcon(),
    })
  })
  ipcMain.on("drag:start-many", (event, targetPaths: unknown) => {
    if (!Array.isArray(targetPaths)) return
    const files = targetPaths.filter((item): item is string => typeof item === "string" && existsSync(item))
    if (files.length === 0) return
    event.sender.startDrag({
      file: files[0],
      files,
      icon: createDragPreviewIcon(),
    })
  })
}

app.whenReady().then(() => {
  Menu.setApplicationMenu(null)
  protocol.handle("stem-media", (request) => {
    const url = new URL(request.url)
    const targetPath = url.searchParams.get("path") ?? decodeURIComponent(url.pathname.replace(/^\//, ""))
    if (!path.isAbsolute(targetPath) || !existsSync(targetPath)) {
      return new Response("Media file unavailable.", { status: 404 })
    }
    return createMediaResponse(request, targetPath)
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
