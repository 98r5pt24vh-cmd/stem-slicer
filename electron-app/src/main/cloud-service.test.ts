import { describe, expect, it } from "vitest"
import { mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

import type { GenerateJobRequest } from "../shared/contracts"
import {
  canonicalizeCloudProducerCredits,
  chunkCloudObjectPaths,
  cloudErrorMessage,
  cloudUploadConcurrency,
  CloudService,
  loadCloudBootstrapConfiguration,
  normalizeAliases,
  normalizeCloudHandle,
  normalizeInstagramHandle,
  profileAvatarCropRect,
} from "./cloud-service"

describe("Cloud bootstrap configuration", () => {
  it("loads only a public Supabase project configuration", () => {
    const root = mkdtempSync(path.join(tmpdir(), "slicer-cloud-config-"))
    const configurationPath = path.join(root, "project.json")
    writeFileSync(configurationPath, JSON.stringify({
      projectUrl: "https://example.supabase.co/",
      publishableKey: "sb_publishable_test",
    }))

    expect(loadCloudBootstrapConfiguration(configurationPath)).toEqual({
      projectUrl: "https://example.supabase.co",
      publishableKey: "sb_publishable_test",
    })
  })

  it("rejects secret keys from a packaged configuration", () => {
    const root = mkdtempSync(path.join(tmpdir(), "slicer-cloud-config-"))
    const configurationPath = path.join(root, "project.json")
    writeFileSync(configurationPath, JSON.stringify({
      projectUrl: "https://example.supabase.co",
      publishableKey: "sb_secret_forbidden",
    }))

    expect(loadCloudBootstrapConfiguration(configurationPath)).toBeNull()
  })
})

function request(sourcePool: GenerateJobRequest["sourcePool"]): GenerateJobRequest {
  return {
    databasePath: "/catalogue.sqlite3",
    libraryRoots: ["/local-library"],
    categories: ["Bass", "Chords", "Lead", "Counter", "Pluck"],
    targetBpm: 140,
    targetKey: "D Maj / B min",
    seed: 42,
    generationNumber: 1,
    sourcePool,
  }
}

function serviceWithMissingSession(): CloudService {
  const service = Object.create(CloudService.prototype) as CloudService
  Object.defineProperty(service, "settings", {
    value: {
      projectUrl: "https://example.supabase.co",
      publishableKey: "sb_publishable_test",
      enabledLibraryIds: ["cloud-library"],
    },
  })
  Object.defineProperty(service, "currentSession", {
    value: async () => { throw new Error("Sign in to Cloud first.") },
  })
  return service
}

describe("Cloud generation source isolation", () => {
  it("never reads Cloud state for a This Mac generation", async () => {
    const service = Object.create(CloudService.prototype) as CloudService
    Object.defineProperty(service, "settings", {
      get: () => { throw new Error("Cloud state must not be read") },
    })
    const localRequest = request("local-only")

    await expect(service.enrichGenerateRequest(localRequest)).resolves.toBe(localRequest)
  })

  it("falls back to Mac libraries when Mac + Cloud has no valid session", async () => {
    const mixedRequest = request("mixed")

    await expect(serviceWithMissingSession().enrichGenerateRequest(mixedRequest)).resolves.toBe(mixedRequest)
  })

  it("keeps authentication mandatory for Cloud only", async () => {
    await expect(serviceWithMissingSession().enrichGenerateRequest(request("cloud-only")))
      .rejects.toThrow("Sign in to Cloud first.")
  })
})

describe("Cloud library removal", () => {
  it("keeps Storage deletion requests within the 1,000-object API limit", () => {
    const paths = Array.from({ length: 2_305 }, (_, index) => `producer/library/${index}.mp3`)
    const batches = chunkCloudObjectPaths(paths)

    expect(batches.map((batch) => batch.length)).toEqual([1_000, 1_000, 305])
    expect(batches.flat()).toEqual(paths)
  })

  it("does not create an empty deletion request", () => {
    expect(chunkCloudObjectPaths([])).toEqual([])
  })
})

describe("Cloud library upload", () => {
  it("uses six workers when every layer fits the standard-upload fast path", () => {
    expect(cloudUploadConcurrency([310_000, 2_500_000, 6_000_000])).toBe(6)
  })

  it("keeps conservative concurrency when a layer is large or the manifest is empty", () => {
    expect(cloudUploadConcurrency([310_000, 6_000_001])).toBe(3)
    expect(cloudUploadConcurrency([])).toBe(3)
  })
})

describe("Cloud error copy", () => {
  it("replaces empty provider errors with an actionable fallback", () => {
    expect(cloudErrorMessage({ message: "<none>" }, "Check the connection and retry.")).toBe("Check the connection and retry.")
    expect(cloudErrorMessage({ message: "  " }, "Check the connection and retry.")).toBe("Check the connection and retry.")
  })

  it("preserves a useful provider error", () => {
    expect(cloudErrorMessage({ message: "The object already exists." })).toBe("The object already exists.")
  })
})

describe("Cloud producer profiles", () => {
  it("preserves a branded leading plus and transliterates accents in Cloud handles", () => {
    expect(normalizeCloudHandle("+Énergie")).toBe("+energie")
    expect(normalizeCloudHandle("+ NRGY")).toBe("+nrgy")
    expect(normalizeCloudHandle("Tnex is R")).toBe("tnex-is-r")
  })

  it("normalizes Instagram handles and profile links", () => {
    expect(normalizeInstagramHandle("@nrgy.loops")).toBe("nrgy.loops")
    expect(normalizeInstagramHandle("https://www.instagram.com/nrgy.loops/?hl=en")).toBe("nrgy.loops")
  })

  it("deduplicates aliases without losing their display spelling", () => {
    expect(normalizeAliases(["Tnex is R", " tnex   is   r ", "@Tnex is R", "XT"])).toEqual(["Tnex is R", "XT"])
    expect(normalizeAliases(["+NRGY", "NRGY", "+nrgy"])).toEqual(["+NRGY", "NRGY"])
  })

  it("maps an owner's aliases back to the canonical Cloud identity", () => {
    expect(canonicalizeCloudProducerCredits(
      ["+NRGY", "@Tnex is R"],
      {
        id: "xt",
        handle: "xt",
        displayName: "XT",
        aliases: ["Tnex is R"],
      },
    )).toEqual(["+NRGY", "XT"])
  })

  it("center-crops rectangular profile images before Cloud upload", () => {
    expect(profileAvatarCropRect(1200, 800)).toEqual({ x: 200, y: 0, width: 800, height: 800 })
    expect(profileAvatarCropRect(600, 900)).toEqual({ x: 0, y: 150, width: 600, height: 600 })
  })
})
