export type QuickFileToolId = "extract" | "scan" | "convert"

const QUICK_FILE_TOOL_IDS = new Set<QuickFileToolId>(["extract", "scan", "convert"])

export function quickFileToolFromDragHover(
  tool: string,
  dragTypes: readonly string[],
): QuickFileToolId | null {
  if (!dragTypes.includes("Files") || !QUICK_FILE_TOOL_IDS.has(tool as QuickFileToolId)) return null
  return tool as QuickFileToolId
}
