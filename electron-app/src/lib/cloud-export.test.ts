import { describe, expect, it } from "vitest"

import {
  buildCloudTrackedDragRequest,
  type BuildCloudTrackedDragRequestInput,
  type CloudExportLayerInput,
} from "./cloud-export"

const localLayer: CloudExportLayerInput = {
  file: "LOCAL LOOP_L1.wav",
  sourceFile: "LOCAL LOOP_L1.wav",
  sourceLoopId: "local-loop",
  sourceLoopName: "LOCAL LOOP",
  sourceOrigin: "local",
  category: "Bass",
}

const firstCloudLayer: CloudExportLayerInput = {
  file: "Bm FM 151 FMIN XT_L10.mp3",
  sourceFile: "Bm FM 151 FMIN XT_L10.mp3",
  sourceLoopId: "cloud:xt-loop",
  sourceLoopName: "Bm FM 151 FMIN XT",
  sourceOrigin: "cloud",
  cloudLayerId: "cloud-layer-1",
  cloudOwnerId: "xt",
  sourceSha256: "a".repeat(64),
  category: "Lead",
}

const secondCloudLayerFromSameOwner: CloudExportLayerInput = {
  file: "Bm FM 151 FMIN XT_L2.mp3",
  sourceFile: "Bm FM 151 FMIN XT_L2.mp3",
  sourceLoopId: "cloud:xt-loop",
  sourceOrigin: "cloud",
  cloudLayerId: "cloud-layer-2",
  cloudOwnerId: "xt",
  sourceSha256: "b".repeat(64),
  category: "Chords",
}

const cloudLayerFromAnotherOwner: CloudExportLayerInput = {
  file: "MOTION 140 Amin LIV_L3.wav",
  sourceFile: "MOTION 140 Amin LIV_L3.wav",
  sourceLoopId: "cloud:liv-loop",
  sourceLoopName: "MOTION",
  sourceOrigin: "cloud",
  cloudLayerId: "cloud-layer-3",
  cloudOwnerId: "liv",
  sourceSha256: "c".repeat(64),
  category: "Counter",
}

function request(overrides: Partial<BuildCloudTrackedDragRequestInput> = {}): BuildCloudTrackedDragRequestInput {
  return {
    exportKind: "drag-all",
    exportPath: "/generated/L Gen161/master.wav",
    masterPath: "/generated/L Gen161/master.wav",
    generatedLoopName: "L Gen161_140_Em XT +NRGY",
    generationSeed: 161,
    targetBpm: 140,
    targetKey: "E minor",
    durationSeconds: 7.4,
    layers: [localLayer, firstCloudLayer, secondCloudLayerFromSameOwner, cloudLayerFromAnotherOwner],
    ...overrides,
  }
}

describe("Cloud tracked drag request", () => {
  it("marks every contributing Cloud layer on Drag all while preserving the exact snapshot", () => {
    const result = buildCloudTrackedDragRequest(request())

    expect(result).toMatchObject({
      exportKind: "drag-all",
      exportPath: "/generated/L Gen161/master.wav",
      masterPath: "/generated/L Gen161/master.wav",
      generatedLoopName: "L Gen161_140_Em XT +NRGY",
      generationSeed: 161,
      targetBpm: 140,
      targetKey: "E minor",
      durationSeconds: 7.4,
    })
    expect(result?.layers.map((layer) => layer.triggered)).toEqual([false, true, true, true])
    expect(result?.layers[1]).toMatchObject({
      slotIndex: 1,
      sourceLayerName: "Bm FM 151 FMIN XT_L10.mp3",
      sourceLoopName: "Bm FM 151 FMIN XT",
      sourceOrigin: "cloud",
      cloudOwnerId: "xt",
    })
    expect(result?.layers[2].sourceLoopName).toBe("")
  })

  it.each(["layer-audio", "layer-midi"] as const)(
    "marks only the selected Cloud slot for %s",
    (exportKind) => {
      const result = buildCloudTrackedDragRequest(request({
        exportKind,
        exportPath: exportKind === "layer-midi" ? "/generated/L Gen161/lead.mid" : "/generated/L Gen161/lead.wav",
        selectedSlotIndex: 2,
      }))

      expect(result?.layers.map((layer) => layer.triggered)).toEqual([false, false, true, false])
      expect(result?.exportKind).toBe(exportKind)
    },
  )

  it("returns null when Drag all contains no trackable Cloud recipient", () => {
    expect(buildCloudTrackedDragRequest(request({ layers: [localLayer] }))).toBeNull()
  })

  it("returns null when the selected card is local, missing or has incomplete Cloud provenance", () => {
    expect(buildCloudTrackedDragRequest(request({ exportKind: "layer-audio", selectedSlotIndex: 0 }))).toBeNull()
    expect(buildCloudTrackedDragRequest(request({ exportKind: "layer-midi", selectedSlotIndex: 99 }))).toBeNull()
    expect(buildCloudTrackedDragRequest(request({
      exportKind: "layer-audio",
      selectedSlotIndex: 0,
      layers: [{ ...firstCloudLayer, cloudOwnerId: undefined }],
    }))).toBeNull()
  })

  it("does not reinterpret local provenance as Cloud when stale Cloud ids are present", () => {
    const staleLocalLayer = { ...localLayer, cloudLayerId: "stale-layer", cloudOwnerId: "stale-owner" }
    expect(buildCloudTrackedDragRequest(request({ layers: [staleLocalLayer] }))).toBeNull()

    const mixedResult = buildCloudTrackedDragRequest(request({ layers: [staleLocalLayer, firstCloudLayer] }))
    expect(mixedResult?.layers[0]).toMatchObject({
      sourceOrigin: "local",
      triggered: false,
    })
    expect(mixedResult?.layers[0].cloudLayerId).toBeUndefined()
    expect(mixedResult?.layers[0].cloudOwnerId).toBeUndefined()
    expect(mixedResult?.layers[1].cloudLayerId).toBe("cloud-layer-1")
  })
})
