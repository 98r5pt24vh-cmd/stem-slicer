import { EventEmitter } from "node:events"
import { PassThrough } from "node:stream"
import path from "node:path"
import type { ChildProcessWithoutNullStreams } from "node:child_process"
import { beforeEach, describe, expect, it, vi } from "vitest"

const { existsSyncMock, spawnMock } = vi.hoisted(() => ({
  existsSyncMock: vi.fn(() => true),
  spawnMock: vi.fn(),
}))

vi.mock("node:fs", async (importOriginal) => ({
  ...await importOriginal<typeof import("node:fs")>(),
  existsSync: existsSyncMock,
}))

vi.mock("node:child_process", async (importOriginal) => ({
  ...await importOriginal<typeof import("node:child_process")>(),
  spawn: spawnMock,
}))

import { AudioEngineService } from "./audio-engine"

function fakeEngineProcess(): ChildProcessWithoutNullStreams {
  const child = new EventEmitter() as ChildProcessWithoutNullStreams
  Object.assign(child, {
    stdin: new PassThrough(),
    stdout: new PassThrough(),
    stderr: new PassThrough(),
    exitCode: null,
    signalCode: null,
    kill: vi.fn(() => true),
  })
  return child
}

describe("AudioEngineService", () => {
  beforeEach(() => {
    existsSyncMock.mockReset()
    existsSyncMock.mockReturnValue(true)
    spawnMock.mockReset()
  })

  it("starts a packaged engine from the resources directory, never from app.asar", async () => {
    const resourcesPath = path.join(path.sep, "portable", "Slicer", "resources")
    const appRoot = path.join(resourcesPath, "app.asar")
    const child = fakeEngineProcess()
    spawnMock.mockReturnValue(child)
    const service = new AudioEngineService(
      appRoot,
      path.join(path.sep, "cache", "electron"),
      resourcesPath,
      true,
      path.join(path.sep, "cache", "1.9"),
    )

    const starting = service.start()
    ;(child.stdout as PassThrough).write(`${JSON.stringify({ type: "ready" })}\n`)
    const status = await starting

    expect(spawnMock).toHaveBeenCalledWith(
      expect.any(String),
      ["-u", path.join(resourcesPath, "python", "engine_bridge.py")],
      expect.objectContaining({
        cwd: resourcesPath,
        windowsHide: true,
      }),
    )
    expect(status.components).toEqual({
      musicalAnalysis: { state: "ready", message: "Ready for key and tempo analysis." },
      midi: { state: "ready", message: "Ready for audio-to-MIDI conversion." },
      categorization: { state: "ready", message: "Ready for layer categorization." },
    })

    Object.assign(child, { exitCode: 0 })
    child.emit("exit", 0, null)
  })
})
