import type {
  CloudExportKind,
  CloudExportLayerSnapshot,
  CloudTrackedDragRequest,
} from "@/shared/contracts"

export interface CloudExportLayerInput {
  file: string
  category: string
  sourceFile?: string
  sourceLoopId?: string
  sourceLoopName?: string
  sourceOrigin?: "local" | "cloud"
  cloudLayerId?: string
  cloudOwnerId?: string
  sourceSha256?: string
}

export interface BuildCloudTrackedDragRequestInput {
  exportKind: CloudExportKind
  exportPath: string
  masterPath: string
  generatedLoopName: string
  generationSeed: number
  targetBpm: number
  targetKey: string
  durationSeconds: number
  layers: CloudExportLayerInput[]
  selectedSlotIndex?: number
}

function isTrackableCloudLayer(layer: CloudExportLayerInput): boolean {
  return layer.sourceOrigin === "cloud"
    && Boolean(layer.cloudLayerId)
    && Boolean(layer.cloudOwnerId)
}

function triggeredSlots(input: BuildCloudTrackedDragRequestInput): Set<number> {
  if (input.exportKind === "drag-all") {
    return new Set(input.layers.flatMap((layer, slotIndex) => (
      isTrackableCloudLayer(layer) ? [slotIndex] : []
    )))
  }

  const selectedSlotIndex = input.selectedSlotIndex
  if (
    selectedSlotIndex == null
    || !Number.isInteger(selectedSlotIndex)
    || selectedSlotIndex < 0
    || selectedSlotIndex >= input.layers.length
    || !isTrackableCloudLayer(input.layers[selectedSlotIndex])
  ) {
    return new Set()
  }
  return new Set([selectedSlotIndex])
}

function layerSnapshot(
  layer: CloudExportLayerInput,
  slotIndex: number,
  triggered: boolean,
): CloudExportLayerSnapshot {
  const sourceOrigin = layer.sourceOrigin === "cloud" ? "cloud" : "local"
  return {
    slotIndex,
    category: layer.category,
    sourceLayerName: layer.sourceFile || layer.file,
    sourceLoopId: layer.sourceLoopId ?? "",
    sourceLoopName: layer.sourceLoopName ?? "",
    sourceOrigin,
    cloudLayerId: sourceOrigin === "cloud" ? layer.cloudLayerId : undefined,
    cloudOwnerId: sourceOrigin === "cloud" ? layer.cloudOwnerId : undefined,
    sourceSha256: layer.sourceSha256,
    triggered,
  }
}

/**
 * Captures the exact generation snapshot associated with a native file drag.
 *
 * All Cloud layers are marked as triggered for a full-stack drag, preserving
 * every contributing layer while the receiver can still deduplicate owners.
 * Card Audio/MIDI drags mark only the selected slot. Local or incomplete Cloud
 * provenance can never create a tracked request.
 */
export function buildCloudTrackedDragRequest(
  input: BuildCloudTrackedDragRequestInput,
): CloudTrackedDragRequest | null {
  const slots = triggeredSlots(input)
  if (slots.size === 0) return null

  return {
    exportKind: input.exportKind,
    exportPath: input.exportPath,
    masterPath: input.masterPath,
    generatedLoopName: input.generatedLoopName,
    generationSeed: input.generationSeed,
    targetBpm: input.targetBpm,
    targetKey: input.targetKey,
    durationSeconds: input.durationSeconds,
    layers: input.layers.map((layer, slotIndex) => (
      layerSnapshot(layer, slotIndex, slots.has(slotIndex))
    )),
  }
}
