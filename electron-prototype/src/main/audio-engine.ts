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
  EngineStatus,
} from "../shared/contracts"

interface BridgeMessage {
  id?: string
  type: "ready" | "progress" | "artifact" | "result" | "error"
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

export class AudioEngineService {
  private readonly appRoot: string
  private readonly prototypeCachePath: string
  private readonly bridgePath: string
  private readonly sourceRoot: string
  private readonly pythonPath: string
  private process: ChildProcessWithoutNullStreams | null = null
  private stdoutBuffer = ""
  private startupPromise: Promise<void> | null = null
  private resolveStartup: (() => void) | null = null
  private rejectStartup: ((error: Error) => void) | null = null
  private ready = false
  private lastError = ""
  private readonly activeJobs = new Map<string, ActiveJob>()

  constructor(appRoot: string, prototypeCachePath: string) {
    this.appRoot = appRoot
    this.prototypeCachePath = prototypeCachePath
    this.bridgePath = path.join(appRoot, "python", "engine_bridge.py")
    this.sourceRoot = process.env.STEM_SLICER_SOURCE_ROOT?.trim()
      || path.resolve(appRoot, "../../../..", "Stem Slicer Repository")
    const runtimePython = path.join(appRoot, ".runtime", "python", "bin", "python3.12")
    const runtimeFallback = path.join(appRoot, ".runtime", "python", "bin", "python3")
    this.pythonPath = process.env.STEM_SLICER_PYTHON?.trim()
      || (existsSync(runtimePython) ? runtimePython : existsSync(runtimeFallback) ? runtimeFallback : "python3.12")
  }

  status(): EngineStatus {
    const available = existsSync(this.bridgePath)
      && existsSync(this.sourceRoot)
      && (path.isAbsolute(this.pythonPath) ? existsSync(this.pythonPath) : true)
    return {
      available,
      state: this.ready ? "ready" : this.process ? "starting" : available ? "starting" : "unavailable",
      pythonPath: this.pythonPath,
      sourceRoot: this.sourceRoot,
      message: this.ready
        ? "Validated 1.9B engines are connected."
        : this.lastError || (available ? "Engine runtime will start on first use." : "The local engine runtime is unavailable."),
    }
  }

  async startJob(kind: AudioJobKind, payload: AudioJobRequest, sender: WebContents): Promise<AudioJobStart> {
    if (!JOB_KINDS.has(kind)) throw new Error(`Unsupported audio job: ${kind}`)
    if (!payload || typeof payload !== "object") throw new Error("Audio job payload must be an object.")
    await this.ensureStarted()
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
    if (this.ready && this.process) return Promise.resolve()
    if (this.startupPromise) return this.startupPromise
    if (!existsSync(this.bridgePath)) return Promise.reject(new Error(`Engine bridge is missing: ${this.bridgePath}`))
    if (!existsSync(this.sourceRoot)) return Promise.reject(new Error(`Canonical 1.9B source is missing: ${this.sourceRoot}`))

    this.startupPromise = new Promise<void>((resolve, reject) => {
      this.resolveStartup = resolve
      this.rejectStartup = reject
    })
    const runtimeBin = path.join(this.appRoot, ".runtime", "bin")
    const environment = {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      PYTHONDONTWRITEBYTECODE: "1",
      STEM_SLICER_SOURCE_ROOT: this.sourceRoot,
      STEM_SLICER_DIAGNOSTICS_DIR: path.join(this.prototypeCachePath, "diagnostics"),
      PATH: `${runtimeBin}${path.delimiter}${process.env.PATH || ""}`,
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
      this.handleProcessFailure(new Error("The local engine did not start within 20 seconds."))
      child.kill("SIGTERM")
    }, 20_000)
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
    if (message.type === "ready") {
      this.ready = true
      this.lastError = ""
      this.resolveStartup?.()
      this.resolveStartup = null
      this.rejectStartup = null
      this.startupPromise = null
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
    child?.kill("SIGTERM")
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
    this.resetProcessState()
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
