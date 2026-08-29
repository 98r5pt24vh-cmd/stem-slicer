import { existsSync } from "node:fs"
import path from "node:path"
import { randomUUID } from "node:crypto"
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process"

import type { WebContents } from "electron"

import type {
  AudioArtifact,
  AudioJobEvent,
  AudioJobKind,
  AudioJobRequest,
  AudioJobStart,
  EngineComponentState,
  EngineStatus,
} from "../shared/contracts"
import { resolveRuntimePaths } from "./runtime-paths"

interface BridgeMessage {
  id?: string
  type: "ready" | "engine-status" | "progress" | "artifact" | "result" | "error"
  component?: keyof EngineStatus["components"]
  state?: EngineComponentState
  message?: string
  error?: string
  phase?: string
  current?: number
  total?: number
  percent?: number
  artifact?: AudioArtifact
  result?: unknown
  python?: string
  version?: string
  sourceRoot?: string
}

interface ActiveJob {
  kind: AudioJobKind
  sender: WebContents
}

const JOB_KINDS = new Set<AudioJobKind>([
  "batch",
  "quick-scan",
  "quick-extract",
  "quick-convert",
  "library-scan",
  "generate",
  "generate-update",
])

const JOB_LABELS: Record<AudioJobKind, string> = {
  batch: "Stem Slicer",
  "quick-scan": "Quick Scan",
  "quick-extract": "Quick Extract",
  "quick-convert": "Quick Convert",
  "library-scan": "Library Scan",
  generate: "Generate",
  "generate-update": "Generate layer update",
}

export class AudioEngineService {
  private readonly appRoot: string
  private readonly prototypeCachePath: string
  private readonly bridgePath: string
  private readonly sourceRoot: string
  private readonly pythonPath: string
  private readonly runtimeBin: string
  private process: ChildProcessWithoutNullStreams | null = null
  private stdoutBuffer = ""
  private startupPromise: Promise<void> | null = null
  private resolveStartup: (() => void) | null = null
  private rejectStartup: ((error: Error) => void) | null = null
  private ready = false
  private lastError = ""
  private readonly activeJobs = new Map<string, ActiveJob>()
  private readonly statusListeners = new Set<(status: EngineStatus) => void>()
  private components: EngineStatus["components"] = {
    musicalAnalysis: { state: "idle", message: "Waiting to start." },
    midi: { state: "idle", message: "Waiting to start." },
    categorization: { state: "on-demand", message: "Loads when a library needs categorization." },
  }

  constructor(
    appRoot: string,
    prototypeCachePath: string,
    resourcesPath = appRoot,
    isPackaged = false,
    private readonly acceptedCachePath = path.join(path.dirname(prototypeCachePath), "1.9"),
  ) {
    this.appRoot = appRoot
    this.prototypeCachePath = prototypeCachePath
    const runtime = resolveRuntimePaths({ appRoot, resourcesPath, isPackaged })
    this.bridgePath = runtime.bridgePath
    this.sourceRoot = runtime.sourceRoot
    this.pythonPath = runtime.pythonPath
    this.runtimeBin = runtime.runtimeBin
  }

  status(): EngineStatus {
    const available = existsSync(this.bridgePath)
      && existsSync(this.sourceRoot)
      && (path.isAbsolute(this.pythonPath) ? existsSync(this.pythonPath) : true)
    const processAlive = Boolean(this.process && this.process.exitCode === null && this.process.signalCode === null)
    const stoppedUnexpectedly = this.ready && !processAlive
    const state = !available
      ? "unavailable"
      : stoppedUnexpectedly
        ? "failed"
        : this.ready && processAlive
          ? "ready"
          : this.process || this.startupPromise
            ? "starting"
            : this.lastError
              ? "failed"
              : "idle"
    const components = !available
      ? {
          musicalAnalysis: { state: "unavailable" as const, message: "The local engine runtime is unavailable." },
          midi: { state: "unavailable" as const, message: "The local engine runtime is unavailable." },
          categorization: { state: "unavailable" as const, message: "The local engine runtime is unavailable." },
        }
      : stoppedUnexpectedly
        ? {
            musicalAnalysis: { state: "failed" as const, message: "The local engine process stopped." },
            midi: { state: "failed" as const, message: "The local engine process stopped." },
            categorization: { state: "failed" as const, message: "The local engine process stopped." },
          }
        : this.components
    return {
      available,
      state,
      pythonPath: this.pythonPath,
      sourceRoot: this.sourceRoot,
      message: state === "ready"
        ? "Local engines are ready."
        : state === "starting" || state === "idle"
          ? "Local engines are starting in the background."
          : this.lastError || (stoppedUnexpectedly ? "The local engine process stopped." : "The local engine runtime is unavailable."),
      components,
    }
  }

  onStatus(listener: (status: EngineStatus) => void): () => void {
    this.statusListeners.add(listener)
    return () => this.statusListeners.delete(listener)
  }

  async start(): Promise<EngineStatus> {
    await this.ensureStarted()
    return this.status()
  }

  async retry(): Promise<EngineStatus> {
    if (this.process && (this.process.exitCode !== null || this.process.signalCode !== null)) {
      this.resetProcessState()
    }
    if (this.ready && this.process && this.process.exitCode === null && this.process.signalCode === null) return this.status()
    if (this.startupPromise) {
      await this.startupPromise
      return this.status()
    }
    this.lastError = ""
    this.components = {
      musicalAnalysis: { state: "idle", message: "Waiting to start." },
      midi: { state: "idle", message: "Waiting to start." },
      categorization: { state: "on-demand", message: "Loads when a library needs categorization." },
    }
    this.emitStatus()
    await this.ensureStarted()
    return this.status()
  }

  async startJob(kind: AudioJobKind, payload: AudioJobRequest, sender: WebContents): Promise<AudioJobStart> {
    if (!JOB_KINDS.has(kind)) throw new Error(`Unsupported audio job: ${kind}`)
    if (!payload || typeof payload !== "object") throw new Error("Audio job payload must be an object.")
    await this.ensureStarted()
    const runningJob = this.activeJobs.entries().next().value as [string, ActiveJob] | undefined
    if (runningJob) {
      const [, active] = runningJob
      throw new Error(`${JOB_LABELS[active.kind]} is already running. Cancel or wait for it before starting ${JOB_LABELS[kind]}.`)
    }
    const jobId = randomUUID()
    this.activeJobs.set(jobId, { kind, sender })
    this.process?.stdin.write(`${JSON.stringify({ id: jobId, kind, payload })}\n`)
    return { jobId }
  }

  cancelJob(jobId: string): void {
    const job = this.activeJobs.get(jobId)
    if (!job) return
    this.emit(jobId, job, {
      jobId,
      kind: job.kind,
      type: "cancelled",
      message: "Processing cancelled.",
    })
    this.restartAfterCancellation(jobId)
  }

  shutdown(): void {
    if (!this.process) return
    this.process.stdin.write(`${JSON.stringify({ type: "shutdown" })}\n`)
    const processToStop = this.process
    const timer = setTimeout(() => processToStop.kill("SIGTERM"), 2_000)
    processToStop.once("exit", () => clearTimeout(timer))
    this.resetProcessState()
  }

  private ensureStarted(): Promise<void> {
    if (this.process && (this.process.exitCode !== null || this.process.signalCode !== null)) {
      this.resetProcessState()
    }
    if (this.ready && this.process) return Promise.resolve()
    if (this.startupPromise) return this.startupPromise
    if (!existsSync(this.bridgePath)) return this.failBeforeStart(`Engine bridge is missing: ${this.bridgePath}`)
    if (!existsSync(this.sourceRoot)) return this.failBeforeStart(`Canonical source is missing: ${this.sourceRoot}`)

    this.lastError = ""
    this.components = {
      musicalAnalysis: { state: "starting", message: "Starting musical analysis…" },
      midi: { state: "starting", message: "Loading MIDI conversion…" },
      categorization: { state: "on-demand", message: "Loads when a library needs categorization." },
    }

    this.startupPromise = new Promise<void>((resolve, reject) => {
      this.resolveStartup = resolve
      this.rejectStartup = reject
    })
    this.emitStatus()
    const environment = {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      PYTHONDONTWRITEBYTECODE: "1",
      STEM_SLICER_SOURCE_ROOT: this.sourceRoot,
      STEM_SLICER_ACCEPTED_CACHE_ROOT: this.acceptedCachePath,
      STEM_SLICER_PROTOTYPE_CACHE_ROOT: this.prototypeCachePath,
      STEM_SLICER_DIAGNOSTICS_DIR: path.join(this.prototypeCachePath, "diagnostics"),
      PATH: `${this.runtimeBin}${path.delimiter}${process.env.PATH || ""}`,
    }
    const child = spawn(this.pythonPath, ["-u", this.bridgePath], {
      cwd: this.appRoot,
      env: environment,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    })
    this.process = child
    child.stdout.setEncoding("utf8")
    child.stderr.setEncoding("utf8")
    child.stdout.on("data", (chunk: string) => this.consumeStdout(chunk))
    child.stderr.on("data", (chunk: string) => {
      this.lastError = chunk.trim().split("\n").slice(-1)[0] || this.lastError
    })
    child.once("error", (error) => this.handleProcessFailure(error))
    child.once("exit", (code, signal) => {
      if (this.process !== child) return
      const detail = `Engine process stopped${code === null ? "" : ` with code ${code}`}${signal ? ` (${signal})` : ""}.`
      this.handleProcessFailure(new Error(this.lastError ? `${detail} ${this.lastError}` : detail))
    })
    const startupTimer = setTimeout(() => {
      if (this.ready || this.process !== child) return
      this.handleProcessFailure(new Error("The local engines did not finish starting within five minutes."))
      child.kill("SIGTERM")
    }, 300_000)
    child.once("exit", () => clearTimeout(startupTimer))
    return this.startupPromise
  }

  private consumeStdout(chunk: string): void {
    this.stdoutBuffer += chunk
    let newline = this.stdoutBuffer.indexOf("\n")
    while (newline >= 0) {
      const line = this.stdoutBuffer.slice(0, newline).trim()
      this.stdoutBuffer = this.stdoutBuffer.slice(newline + 1)
      if (line) {
        try {
          this.handleMessage(JSON.parse(line) as BridgeMessage)
        } catch (error) {
          this.lastError = error instanceof Error ? error.message : "Invalid engine response."
        }
      }
      newline = this.stdoutBuffer.indexOf("\n")
    }
  }

  private handleMessage(message: BridgeMessage): void {
    if (message.type === "engine-status" && message.component && message.state) {
      this.components = {
        ...this.components,
        [message.component]: {
          state: message.state,
          message: message.message || this.components[message.component].message,
        },
      }
      this.emitStatus()
      return
    }
    if (message.type === "ready") {
      this.ready = true
      this.lastError = ""
      this.components = {
        ...this.components,
        musicalAnalysis: { state: "ready", message: "Ready for key and tempo analysis." },
        midi: { state: "ready", message: "Ready for audio-to-MIDI conversion." },
      }
      this.resolveStartup?.()
      this.resolveStartup = null
      this.rejectStartup = null
      this.startupPromise = null
      this.emitStatus()
      return
    }
    if (!message.id) return
    const job = this.activeJobs.get(message.id)
    if (!job) return
    if (message.type === "progress") {
      this.emit(message.id, job, {
        jobId: message.id,
        kind: job.kind,
        type: "progress",
        message: message.message || "Processing…",
        phase: message.phase,
        current: message.current,
        total: message.total,
        percent: message.percent,
      })
      return
    }
    if (message.type === "artifact" && message.artifact) {
      this.emit(message.id, job, {
        jobId: message.id,
        kind: job.kind,
        type: "artifact",
        message: message.message || message.artifact.name,
        artifact: message.artifact,
      })
      return
    }
    if (message.type === "result") {
      this.emit(message.id, job, {
        jobId: message.id,
        kind: job.kind,
        type: "completed",
        message: message.message || "Processing complete.",
        percent: 100,
        result: message.result as AudioJobEvent["result"],
      })
      this.activeJobs.delete(message.id)
      return
    }
    if (message.type === "error") {
      this.emit(message.id, job, {
        jobId: message.id,
        kind: job.kind,
        type: "failed",
        message: message.message || "Processing failed.",
        error: message.error || message.message || "Unknown engine error.",
      })
      this.activeJobs.delete(message.id)
    }
  }

  private emit(jobId: string, job: ActiveJob, event: AudioJobEvent): void {
    if (job.sender.isDestroyed()) {
      this.activeJobs.delete(jobId)
      return
    }
    job.sender.send("audio-job:event", event)
  }

  private restartAfterCancellation(cancelledJobId: string): void {
    const child = this.process
    for (const [jobId, job] of this.activeJobs) {
      if (jobId === cancelledJobId) continue
      this.emit(jobId, job, {
        jobId,
        kind: job.kind,
        type: "failed",
        message: "The engine was restarted after another job was cancelled.",
        error: "Engine restarted after cancellation.",
      })
    }
    this.activeJobs.clear()
    this.resetProcessState()
    this.components = {
      musicalAnalysis: { state: "idle", message: "Waiting to restart." },
      midi: { state: "idle", message: "Waiting to restart." },
      categorization: { state: "on-demand", message: "Loads when a library needs categorization." },
    }
    this.emitStatus()
    if (child) {
      child.once("exit", () => void this.start().catch(() => undefined))
      child.kill("SIGTERM")
    } else {
      void this.start().catch(() => undefined)
    }
  }

  private handleProcessFailure(error: Error): void {
    this.lastError = error.message
    this.rejectStartup?.(error)
    for (const [jobId, job] of this.activeJobs) {
      this.emit(jobId, job, {
        jobId,
        kind: job.kind,
        type: "failed",
        message: "The local audio engine stopped.",
        error: error.message,
      })
    }
    this.activeJobs.clear()
    this.components = {
      musicalAnalysis: { state: "failed", message: error.message },
      midi: { state: "failed", message: error.message },
      categorization: { state: "failed", message: error.message },
    }
    this.resetProcessState()
    this.emitStatus()
  }

  private failBeforeStart(message: string): Promise<void> {
    const error = new Error(message)
    this.lastError = message
    this.components = {
      musicalAnalysis: { state: "failed", message },
      midi: { state: "failed", message },
      categorization: { state: "failed", message },
    }
    this.emitStatus()
    return Promise.reject(error)
  }

  private emitStatus(): void {
    const status = this.status()
    for (const listener of this.statusListeners) listener(status)
  }

  private resetProcessState(): void {
    this.process = null
    this.ready = false
    this.stdoutBuffer = ""
    this.startupPromise = null
    this.resolveStartup = null
    this.rejectStartup = null
  }
}
