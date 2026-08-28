import { describe, expect, it } from "vitest"

import { mediaMimeType, parseByteRange } from "./media-range"

describe("media byte ranges", () => {
  it("parses bounded, open-ended and suffix ranges", () => {
    expect(parseByteRange("bytes=100-199", 1000)).toEqual({ start: 100, end: 199 })
    expect(parseByteRange("bytes=750-", 1000)).toEqual({ start: 750, end: 999 })
    expect(parseByteRange("bytes=-125", 1000)).toEqual({ start: 875, end: 999 })
  })

  it("clamps valid ranges and rejects invalid ones", () => {
    expect(parseByteRange("bytes=900-1200", 1000)).toEqual({ start: 900, end: 999 })
    expect(parseByteRange("bytes=1000-1200", 1000)).toBeNull()
    expect(parseByteRange("bytes=200-100", 1000)).toBeNull()
    expect(parseByteRange("not-a-range", 1000)).toBeNull()
  })

  it("returns audio MIME types used by the prototype", () => {
    expect(mediaMimeType(".mp3")).toBe("audio/mpeg")
    expect(mediaMimeType(".WAV")).toBe("audio/wav")
    expect(mediaMimeType(".PNG")).toBe("image/png")
    expect(mediaMimeType(".unknown")).toBe("application/octet-stream")
  })
})
