import { describe, expect, it } from "vitest"

import type { CloudGenerationActivity, CloudState } from "@/shared/contracts"
import { cloudActivityRevision, cloudStateRevision } from "./cloud-revision"

const state: CloudState = {
  configured: true,
  projectUrl: "https://example.supabase.co",
  authenticated: true,
  userEmail: "producer@example.com",
  profile: { id: "producer", handle: "producer", displayName: "Producer", aliases: [] },
  connections: [],
  libraries: [],
}

describe("silent Cloud synchronization", () => {
  it("does not treat a new object or a transient message as new Cloud data", () => {
    expect(cloudStateRevision({ ...state, message: "Saved." })).toBe(cloudStateRevision({ ...state }))
  })

  it("detects a real shared-library update", () => {
    const changed: CloudState = {
      ...state,
      libraries: [{
        id: "library",
        name: "Shared layers",
        owner: state.profile!,
        status: "ready",
        layerCount: 12,
        loopCount: 3,
        totalBytes: 10_000,
        own: false,
        enabledForGenerate: false,
        blockedProducerIds: [],
        updatedAt: "2026-08-30T04:30:00Z",
      }],
    }
    expect(cloudStateRevision(changed)).not.toBe(cloudStateRevision(state))
  })

  it("keeps identical activity lists stable and detects a new event", () => {
    const activity: CloudGenerationActivity[] = []
    expect(cloudActivityRevision([...activity])).toBe(cloudActivityRevision(activity))
    expect(cloudActivityRevision([{
      id: "generation",
      createdBy: state.profile!,
      contributors: [],
      seed: 42,
      targetBpm: 140,
      targetKey: "F# minor",
      layerCount: 5,
      createdAt: "2026-08-30T04:30:00Z",
      sources: [],
    }])).not.toBe(cloudActivityRevision(activity))
  })
})
