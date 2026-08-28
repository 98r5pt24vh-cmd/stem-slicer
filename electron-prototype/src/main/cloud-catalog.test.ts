import { describe, expect, it } from "vitest"

import { audioMimeType, cloudCachePath, safeObjectFileName } from "./cloud-catalog"

describe("cloud catalogue helpers", () => {
  it("normalizes storage object names without losing the audio extension", () => {
    expect(safeObjectFileName("D♯ héro layer 01.MP3")).toBe("D- he-ro layer 01.mp3")
  })

  it("uses a deterministic isolated cache path", () => {
    expect(cloudCachePath("/cache", "owner", "library", "abc123", "Layer.wav"))
      .toBe("/cache/owner/library/abc123.wav")
  })

  it("maps the supported alpha audio formats", () => {
    expect(audioMimeType("layer.mp3")).toBe("audio/mpeg")
    expect(audioMimeType("layer.flac")).toBe("audio/flac")
    expect(audioMimeType("layer.unknown")).toBe("application/octet-stream")
  })
})

