import { mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import { describe, expect, it, vi } from "vitest"

import { cloudExportWavPath, ensureCloudExportWavMaster } from "./cloud-export-master"

function fixture(extension: ".mp3" | ".wav" | ".flac") {
  const root = mkdtempSync(path.join(tmpdir(), "slicer-cloud-export-master-"))
  const sourcePath = path.join(root, `Generated master${extension}`)
  writeFileSync(sourcePath, "generated-audio")
  return { root, sourcePath }
}

describe("Cloud export master preparation", () => {
  it("uses a deterministic sibling WAV path for generated MP3 snapshots", () => {
    expect(cloudExportWavPath("/cache/event.mp3")).toBe("/cache/event.cloud-activity.wav")
    expect(cloudExportWavPath("/cache/event.wav")).toBe("/cache/event.wav")
  })

  it("keeps an existing WAV master without invoking FFmpeg", async () => {
    const { sourcePath } = fixture(".wav")
    const convert = vi.fn()

    await expect(ensureCloudExportWavMaster(sourcePath, "/runtime/ffmpeg", { convert }))
      .resolves.toBe(sourcePath)
    expect(convert).not.toHaveBeenCalled()
  })

  it("converts an MP3 snapshot once and reuses the durable WAV on retry", async () => {
    const { sourcePath } = fixture(".mp3")
    const convert = vi.fn(async (_source: string, destination: string) => {
      writeFileSync(destination, Buffer.alloc(64, 1))
    })

    const first = await ensureCloudExportWavMaster(sourcePath, "/runtime/ffmpeg", { convert })
    const second = await ensureCloudExportWavMaster(sourcePath, "/runtime/ffmpeg", { convert })

    expect(first).toBe(cloudExportWavPath(sourcePath))
    expect(second).toBe(first)
    expect(convert).toHaveBeenCalledTimes(1)
  })

  it("rejects masters outside the Generate MP3/WAV contract", async () => {
    const { sourcePath } = fixture(".flac")

    await expect(ensureCloudExportWavMaster(sourcePath, "/runtime/ffmpeg"))
      .rejects.toThrow("generated MP3 or WAV")
  })
})
