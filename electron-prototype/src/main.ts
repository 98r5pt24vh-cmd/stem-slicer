import { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, net, protocol, shell } from "electron"
import type { IpcMainInvokeEvent } from "electron"
import path from "node:path"
import { homedir } from "node:os"
import { existsSync, mkdirSync, statSync, writeFileSync } from "node:fs"
import { pathToFileURL } from "node:url"

import { AudioEngineService } from "./main/audio-engine"
import { historyRoot, isAllowedHistoryOutput, readHistoryStorageUsage, readQuickActivityHistory } from "./main/activity-history"
import { dismissCategoryCorrections, getSourceLoopEditor, listCategoryCorrections, saveSourceLoopEdit, setLayerCategory } from "./main/catalog-edits"
import { CloudService, cloudErrorMessage } from "./main/cloud-service"
import { dismissKeyIssueReport, listKeyIssueReports, reportKeyIssue, setKeyIssueActive } from "./main/key-feedback"
import { readLibraryOverview, readLibraryProducers, readLibrarySelectionSummary, removeLibraryRoot } from "./main/library-cache"
import { mediaMimeType, parseByteRange } from "./main/media-range"
import { migrationModules } from "./main/migration-modules"
import { readGenerationStorageUsage } from "./main/storage-usage"
import type {
  AudioJobKind,
  AudioJobRequest,
  AudioSelection,
  CloudCredentialsRequest,
  CloudGenerationRecordRequest,
  CloudProfileUpdateRequest,
  CloudSignUpRequest,
  ConfigureCloudRequest,
  GenerateJobRequest,
  LibrarySelectionSummaryRequest,
  TrashHistoryOutputRequest,
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
const profileImageRoot = path.join(prototypeCachePath, "profile-images")
const generatedOutputRoot = path.join(
  homedir(),
  "Documents",
  "Stem Slicer",
  "Generated Loops",
)
const documentsRoot = path.join(homedir(), "Documents")
const slicerHistoryRoot = historyRoot(documentsRoot)
const dragPreviewMaxSize = 40
const profileImageMaxSize = 512

function importProfileImage(sourcePath: string): string {
  if (!existsSync(sourcePath) || !statSync(sourcePath).isFile()) {
    throw new Error("The selected profile image is unavailable.")
  }
  const source = nativeImage.createFromPath(sourcePath)
  if (source.isEmpty()) {
    throw new Error("Unable to read this image. Choose a PNG, JPEG, WebP, AVIF, GIF, BMP, TIFF or HEIC file.")
  }
  const sourceSize = source.getSize()
  const scale = Math.min(profileImageMaxSize / sourceSize.width, profileImageMaxSize / sourceSize.height, 1)
  const normalized = scale < 1
    ? source.resize({
        width: Math.max(1, Math.round(sourceSize.width * scale)),
        height: Math.max(1, Math.round(sourceSize.height * scale)),
        quality: "best",
      })
    : source
  mkdirSync(profileImageRoot, { recursive: true })
  const outputPath = path.join(profileImageRoot, "primary-profile.png")
  writeFileSync(outputPath, normalized.toPNG())
  return outputPath
}

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

function createApplicationIcon() {
  const iconPath = path.join(audioEngine.status().sourceRoot, "assets", "app-icon.png")
  if (!existsSync(iconPath)) return nativeImage.createEmpty()
  return nativeImage.createFromPath(iconPath)
}

function createRoundedDockIcon() {
  const source = createApplicationIcon()
  if (source.isEmpty()) return source
  const image = source.resize({ width: 512, height: 512, quality: "best" })
  const { width, height } = image.getSize()
  const bitmap = image.toBitmap()
  if (bitmap.length < width * height * 4) return image

  const inset = width * 0.045
  const radius = width * 0.22
  const centerX = width / 2
  const centerY = height / 2
  const halfWidth = width / 2 - inset
  const halfHeight = height / 2 - inset
  const feather = 1.25

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const offsetX = Math.abs(x + 0.5 - centerX) - (halfWidth - radius)
      const offsetY = Math.abs(y + 0.5 - centerY) - (halfHeight - radius)
      const outsideDistance = Math.hypot(Math.max(offsetX, 0), Math.max(offsetY, 0))
      const insideDistance = Math.min(Math.max(offsetX, offsetY), 0)
      const signedDistance = outsideDistance + insideDistance - radius
      const coverage = Math.max(0, Math.min(1, 0.5 - signedDistance / feather))
      const alphaIndex = (y * width + x) * 4 + 3
      bitmap[alphaIndex] = Math.round(bitmap[alphaIndex] * coverage)
    }
  }

  return nativeImage.createFromBitmap(bitmap, { width, height, scaleFactor: 1 })
}

function createDragPreviewIcon() {
  const source = createApplicationIcon()
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
app.setName("Slicer")
protocol.registerSchemesAsPrivileged([
  {
    scheme: "stem-media",
    privileges: { corsEnabled: true, secure: true, standard: true, supportFetchAPI: true, stream: true },
  },
])

const audioEngine = new AudioEngineService(app.getAppPath(), prototypeCachePath, process.resourcesPath, app.isPackaged)
const cloudService = new CloudService(acceptedCachePath, prototypeCachePath)

async function runCloudRequest<T>(request: () => T | PromiseLike<T>): Promise<T> {
  try {
    return await request()
  } catch (error) {
    const message = cloudErrorMessage(error, "Cloud is temporarily unavailable.")
    if (/JWT issued at future/i.test(message)) {
      try {
        await cloudService.refreshSession()
        return await request()
      } catch (retryError) {
        throw new Error(cloudErrorMessage(retryError, "Your Cloud session could not be refreshed. Sign in again."))
      }
    }
    throw new Error(message)
  }
}

function createWindow(): void {
  const applicationIcon = createApplicationIcon()
  const mainWindow = new BrowserWindow({
    width: 1226,
    height: 786,
    minWidth: 1040,
    minHeight: 700,
    autoHideMenuBar: true,
    backgroundColor: "#09090b",
    icon: applicationIcon.isEmpty() ? undefined : applicationIcon,
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
  ipcMain.handle("history:get-path-storage-usage", (_event: IpcMainInvokeEvent, paths: unknown) => {
    if (!Array.isArray(paths) || !paths.every((item) => typeof item === "string")) {
      throw new Error("The history storage paths are invalid.")
    }
    return readHistoryStorageUsage(paths)
  })
  ipcMain.handle("history:get-quick-activities", () => readQuickActivityHistory(documentsRoot))
  ipcMain.handle("history:open-root", async () => {
    mkdirSync(slicerHistoryRoot, { recursive: true })
    const error = await shell.openPath(slicerHistoryRoot)
    if (error) throw new Error(error)
  })
  ipcMain.handle("history:trash-output", async (_event: IpcMainInvokeEvent, request: TrashHistoryOutputRequest) => {
    if (!request || typeof request !== "object" || !["generate", "extract", "convert"].includes(request.kind) || typeof request.targetPath !== "string") {
      throw new Error("The history output request is invalid.")
    }
    if (!isAllowedHistoryOutput(documentsRoot, request.kind, request.targetPath)) {
      throw new Error("Only a Slicer history output folder can be moved to Trash.")
    }
    const target = path.resolve(request.targetPath)
    if (!existsSync(target)) return
    if (!statSync(target).isDirectory()) throw new Error("The history output is not a folder.")
    await shell.trashItem(target)
  })
  ipcMain.handle("library:get-overview", () =>
    readLibraryOverview(acceptedCachePath),
  )
  ipcMain.handle("library:get-producers", () => readLibraryProducers(acceptedCachePath))
  ipcMain.handle("library:get-selection-summary", (_event: IpcMainInvokeEvent, request: LibrarySelectionSummaryRequest) => {
    if (!request || typeof request !== "object" || !Array.isArray(request.libraryRoots) || !Array.isArray(request.allowedProducers) || !Array.isArray(request.allowedCreditCounts)) {
      throw new Error("The Generate library selection is invalid.")
    }
    return readLibrarySelectionSummary(acceptedCachePath, request)
  })
  ipcMain.handle("library:remove-root", (_event: IpcMainInvokeEvent, libraryRoot: unknown) => {
    if (typeof libraryRoot !== "string") {
      throw new Error("The indexed library path is invalid.")
    }
    return removeLibraryRoot(acceptedCachePath, libraryRoot)
  })
  ipcMain.handle("key-issues:list", () => listKeyIssueReports(acceptedCachePath))
  ipcMain.handle("category-corrections:list", () => listCategoryCorrections(acceptedCachePath))
  ipcMain.handle("category-corrections:dismiss", (_event: IpcMainInvokeEvent, identities: unknown) =>
    dismissCategoryCorrections(acceptedCachePath, identities),
  )
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
  ipcMain.handle("cloud:get-state", () => runCloudRequest(() => cloudService.getState()))
  ipcMain.handle("cloud:configure", (_event: IpcMainInvokeEvent, request: ConfigureCloudRequest) => {
    if (!request || typeof request.projectUrl !== "string" || typeof request.publishableKey !== "string") {
      throw new Error("The Cloud project configuration is invalid.")
    }
    return runCloudRequest(() => cloudService.configure(request))
  })
  ipcMain.handle("cloud:sign-up", (_event: IpcMainInvokeEvent, request: CloudSignUpRequest) => {
    if (!request || typeof request.email !== "string" || typeof request.password !== "string" || typeof request.handle !== "string" || typeof request.displayName !== "string") {
      throw new Error("The Cloud account form is incomplete.")
    }
    return runCloudRequest(() => cloudService.signUp(request))
  })
  ipcMain.handle("cloud:sign-in", (_event: IpcMainInvokeEvent, request: CloudCredentialsRequest) => {
    if (!request || typeof request.email !== "string" || typeof request.password !== "string") {
      throw new Error("The Cloud sign-in form is incomplete.")
    }
    return runCloudRequest(() => cloudService.signIn(request))
  })
  ipcMain.handle("cloud:sign-in-test-account", (_event: IpcMainInvokeEvent, accountId: unknown) => {
    if (typeof accountId !== "string") throw new Error("The alpha account is invalid.")
    return runCloudRequest(() => cloudService.signInTestAccount(accountId))
  })
  ipcMain.handle("cloud:sign-out", () => runCloudRequest(() => cloudService.signOut()))
  ipcMain.handle("cloud:update-profile", (_event: IpcMainInvokeEvent, request: CloudProfileUpdateRequest) => {
    if (
      !request
      || typeof request.handle !== "string"
      || typeof request.displayName !== "string"
      || typeof request.bio !== "string"
      || typeof request.instagramHandle !== "string"
      || !Array.isArray(request.aliases)
      || request.aliases.some((alias) => typeof alias !== "string")
      || typeof request.openToCollaborate !== "boolean"
      || (request.avatarFilePath != null && typeof request.avatarFilePath !== "string")
    ) {
      throw new Error("The Cloud profile form is invalid.")
    }
    return runCloudRequest(() => cloudService.updateProfile(request))
  })
  ipcMain.handle("cloud:connect", (_event: IpcMainInvokeEvent, handle: unknown) => {
    if (typeof handle !== "string") throw new Error("The producer handle is invalid.")
    return runCloudRequest(() => cloudService.connect(handle))
  })
  ipcMain.handle("cloud:accept-connection", (_event: IpcMainInvokeEvent, connectionId: unknown) => {
    if (typeof connectionId !== "string") throw new Error("The connection request is invalid.")
    return runCloudRequest(() => cloudService.acceptConnection(connectionId))
  })
  ipcMain.handle("cloud:set-library-enabled", (_event: IpcMainInvokeEvent, libraryId: unknown, enabled: unknown) => {
    if (typeof libraryId !== "string" || typeof enabled !== "boolean") {
      throw new Error("The Cloud library selection is invalid.")
    }
    return runCloudRequest(() => cloudService.setLibraryEnabled(libraryId, enabled))
  })
  ipcMain.handle("cloud:set-library-sharing", (_event: IpcMainInvokeEvent, libraryId: unknown, sharing: unknown) => {
    if (typeof libraryId !== "string" || typeof sharing !== "boolean") {
      throw new Error("The Cloud library sharing request is invalid.")
    }
    return runCloudRequest(() => cloudService.setLibrarySharing(libraryId, sharing))
  })
  ipcMain.handle("cloud:remove-library", (_event: IpcMainInvokeEvent, libraryId: unknown) => {
    if (typeof libraryId !== "string") {
      throw new Error("The Cloud library removal request is invalid.")
    }
    return runCloudRequest(() => cloudService.removeLibrary(libraryId))
  })
  ipcMain.handle("cloud:record-generation", (_event: IpcMainInvokeEvent, request: CloudGenerationRecordRequest) =>
    runCloudRequest(() => cloudService.recordGeneration(request)),
  )
  ipcMain.handle("cloud:get-generation-activity", () => runCloudRequest(() => cloudService.generationActivity()))
  ipcMain.handle("cloud:publish-library", (event: IpcMainInvokeEvent, libraryRoot: unknown) => {
    if (typeof libraryRoot !== "string") throw new Error("The local library path is invalid.")
    const sender = event.sender
    return runCloudRequest(() => cloudService.publishLibrary(libraryRoot, (payload) => {
      if (!sender.isDestroyed()) sender.send("cloud:publish-event", payload)
    }))
  })
  ipcMain.handle(
    "audio-job:start",
    async (event: IpcMainInvokeEvent, kind: AudioJobKind, request: AudioJobRequest) => {
      const payload = kind === "generate"
        ? await cloudService.enrichGenerateRequest(request as GenerateJobRequest)
        : request
      return audioEngine.startJob(kind, payload as AudioJobRequest, event.sender)
    },
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
  ipcMain.handle("dialog:pick-image-file", async (): Promise<AudioSelection> => {
    const result = await dialog.showOpenDialog({
      title: "Choose a producer profile image",
      properties: ["openFile"],
      filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp", "avif", "gif", "bmp", "tif", "tiff", "heic", "heif"] }],
    })
    if (result.canceled || !result.filePaths[0]) return { canceled: true, paths: [] }
    return { canceled: false, paths: [importProfileImage(result.filePaths[0])] }
  })
  ipcMain.handle("shell:open-external", async (_event: IpcMainInvokeEvent, value: unknown) => {
    if (typeof value !== "string") throw new Error("The external link is invalid.")
    const target = new URL(value)
    if (target.protocol !== "https:") throw new Error("Only secure external links can be opened.")
    await shell.openExternal(target.toString())
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
  const dockIcon = createRoundedDockIcon()
  if (process.platform === "darwin" && !dockIcon.isEmpty()) {
    app.dock?.setIcon(dockIcon)
  }
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
