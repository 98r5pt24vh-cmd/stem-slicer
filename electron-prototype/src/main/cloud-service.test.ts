import { describe, expect, it } from "vitest"

import type { GenerateJobRequest } from "../shared/contracts"
import {
  canonicalizeCloudProducerCredits,
  CloudService,
  normalizeAliases,
  normalizeCloudHandle,
  normalizeInstagramHandle,
  profileAvatarCropRect,
} from "./cloud-service"

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
    value: async () => { throw new Error("Sign in to Slicer Cloud first.") },
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
      .rejects.toThrow("Sign in to Slicer Cloud first.")
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
    expect(normalizeAliases(["Tnex is R", " tnex   is   r ", "XT"])).toEqual(["Tnex is R", "XT"])
    expect(normalizeAliases(["+NRGY", "NRGY", "+nrgy"])).toEqual(["+NRGY", "NRGY"])
  })

  it("maps an owner's aliases back to the canonical Cloud identity", () => {
    expect(canonicalizeCloudProducerCredits(
      ["+NRGY", "Tnex is R"],
      {
        id: "xt",
        handle: "xt",
        displayName: "XT",
        aliases: ["Tnex is R"],
        openToCollaborate: true,
      },
    )).toEqual(["+NRGY", "XT"])
  })

  it("center-crops rectangular profile images before Cloud upload", () => {
    expect(profileAvatarCropRect(1200, 800)).toEqual({ x: 200, y: 0, width: 800, height: 800 })
    expect(profileAvatarCropRect(600, 900)).toEqual({ x: 0, y: 150, width: 600, height: 600 })
  })
})
