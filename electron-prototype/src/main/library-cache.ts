import { existsSync } from "node:fs"
import path from "node:path"
import { DatabaseSync } from "node:sqlite"

import type {
  CategorySummary,
  LibraryOverview,
  LibraryProducerSummary,
  LibraryRootSummary,
} from "../shared/contracts"
import { PRIMARY_PRODUCER, sourceProvenance, uniqueProducerCredits } from "../lib/source-provenance"

interface CountRow {
  count: number
}

interface RootRow {
  library_root: string
  layer_count: number
  analyzed_key_count: number
}

interface CategoryRow {
  category: string
  layer_count: number
}

interface RootCategoryRow extends CategoryRow {
  library_root: string
}

interface ProducerSourceRow {
  library_root: string
  source_loop_id: string
  filename: string
}

function activeLayerWhere(database: DatabaseSync): string {
  const columns = database.prepare("PRAGMA table_info(layer_cache)").all() as unknown as Array<{ name: string }>
  return columns.some((column) => column.name === "manual_excluded")
    ? " WHERE COALESCE(manual_excluded, 0) = 0"
    : ""
}

function basename(libraryPath: string): string {
  return path.basename(libraryPath) || libraryPath
}

export function readLibraryOverview(acceptedCachePath: string): LibraryOverview {
  const databasePath = path.join(acceptedCachePath, "generate", "library.sqlite3")

  if (!existsSync(databasePath)) {
    return {
      databaseDetected: false,
      databasePath,
      totalLayers: 0,
      roots: [],
      categories: [],
      error: "Catalogue 1.9B introuvable.",
    }
  }

  let database: DatabaseSync | undefined
  try {
    database = new DatabaseSync(databasePath, { readOnly: true })
    const activeWhere = activeLayerWhere(database)
    const total = database
      .prepare(`SELECT COUNT(*) AS count FROM layer_cache${activeWhere}`)
      .get() as unknown as CountRow
    const rootRows = database
      .prepare(`
        SELECT
          library_root,
          COUNT(*) AS layer_count,
          SUM(CASE WHEN key_confidence_status <> 'unavailable' THEN 1 ELSE 0 END)
            AS analyzed_key_count
        FROM layer_cache
        ${activeWhere}
        GROUP BY library_root
        ORDER BY layer_count DESC
      `)
      .all() as unknown as RootRow[]
    const categoryRows = database
      .prepare(`
        SELECT
          COALESCE(NULLIF(manual_label, ''), NULLIF(predicted_label, ''), 'Unknown')
            AS category,
          COUNT(*) AS layer_count
        FROM layer_cache
        ${activeWhere}
        GROUP BY category
        ORDER BY layer_count DESC
        LIMIT 24
      `)
      .all() as unknown as CategoryRow[]
    const rootCategoryRows = database
      .prepare(`
        SELECT
          library_root,
          COALESCE(NULLIF(manual_label, ''), NULLIF(predicted_label, ''), 'Unknown')
            AS category,
          COUNT(*) AS layer_count
        FROM layer_cache
        ${activeWhere}
        GROUP BY library_root, category
        ORDER BY library_root, layer_count DESC
      `)
      .all() as unknown as RootCategoryRow[]
    const categoriesByRoot = new Map<string, CategorySummary[]>()
    for (const row of rootCategoryRows) {
      const categories = categoriesByRoot.get(row.library_root) ?? []
      categories.push({ name: row.category, count: Number(row.layer_count) })
      categoriesByRoot.set(row.library_root, categories)
    }

    const roots: LibraryRootSummary[] = rootRows.map((row) => ({
      path: row.library_root,
      name: basename(row.library_root),
      layerCount: Number(row.layer_count),
      analyzedKeyCount: Number(row.analyzed_key_count),
      keyCoverage:
        Number(row.analyzed_key_count) > 0 ? "analyzed" : "unavailable",
      categories: categoriesByRoot.get(row.library_root) ?? [],
    }))
    const categories: CategorySummary[] = categoryRows.map((row) => ({
      name: row.category,
      count: Number(row.layer_count),
    }))

    return {
      databaseDetected: true,
      databasePath,
      totalLayers: Number(total.count),
      roots,
      categories,
    }
  } catch (error) {
    return {
      databaseDetected: true,
      databasePath,
      totalLayers: 0,
      roots: [],
      categories: [],
      error: error instanceof Error ? error.message : "Lecture du catalogue impossible.",
    }
  } finally {
    database?.close()
  }
}

export function summarizeLibraryProducers(rows: ProducerSourceRow[]): LibraryProducerSummary[] {
  const loops = new Map<string, {
    libraryRoot: string
    layerCount: number
    producers: Set<string>
  }>()
  for (const row of rows) {
    const loopIdentity = `${row.library_root}\u0000${row.source_loop_id}`
    const loop = loops.get(loopIdentity) ?? {
      libraryRoot: row.library_root,
      layerCount: 0,
      producers: new Set<string>(),
    }
    loop.layerCount += 1
    for (const producer of sourceProvenance(row.filename, row.source_loop_id).producers) {
      loop.producers.add(producer)
    }
    loops.set(loopIdentity, loop)
  }

  const summaries = new Map<string, {
    name: string
    layerCount: number
    loopIds: Set<string>
    libraryRoots: Set<string>
    loopCountsByCreditCount: Record<string, number>
  }>()
  for (const [loopIdentity, loop] of loops) {
    const credits = uniqueProducerCredits(loop.producers)
    const creditCount = String(credits.length)
    for (const producer of credits) {
      const key = producer.toLowerCase()
      const summary = summaries.get(key) ?? {
        name: producer,
        layerCount: 0,
        loopIds: new Set<string>(),
        libraryRoots: new Set<string>(),
        loopCountsByCreditCount: {},
      }
      summary.layerCount += loop.layerCount
      summary.loopIds.add(loopIdentity)
      summary.libraryRoots.add(loop.libraryRoot)
      summary.loopCountsByCreditCount[creditCount] = (summary.loopCountsByCreditCount[creditCount] ?? 0) + 1
      summaries.set(key, summary)
    }
  }
  return [...summaries.values()]
    .map((summary) => ({
      name: summary.name,
      layerCount: summary.layerCount,
      loopCount: summary.loopIds.size,
      loopCountsByCreditCount: summary.loopCountsByCreditCount,
      libraryRoots: [...summary.libraryRoots].sort((left, right) => left.localeCompare(right)),
    }))
    .sort((left, right) => {
      if (left.name === PRIMARY_PRODUCER) return -1
      if (right.name === PRIMARY_PRODUCER) return 1
      return right.loopCount - left.loopCount || left.name.localeCompare(right.name)
    })
}

export function readLibraryProducers(acceptedCachePath: string): LibraryProducerSummary[] {
  const databasePath = path.join(acceptedCachePath, "generate", "library.sqlite3")
  if (!existsSync(databasePath)) return []
  const database = new DatabaseSync(databasePath, { readOnly: true })
  try {
    const activeWhere = activeLayerWhere(database)
    const rows = database.prepare(`
      SELECT library_root, source_loop_id, filename
      FROM layer_cache
      ${activeWhere}
    `).all() as unknown as ProducerSourceRow[]
    return summarizeLibraryProducers(rows)
  } finally {
    database.close()
  }
}

export function removeLibraryRoot(
  acceptedCachePath: string,
  requestedRoot: string,
): LibraryOverview {
  const databasePath = path.join(acceptedCachePath, "generate", "library.sqlite3")
  if (!existsSync(databasePath)) {
    throw new Error("The Generate catalogue is unavailable.")
  }
  if (typeof requestedRoot !== "string" || !path.isAbsolute(requestedRoot)) {
    throw new Error("The indexed library path is invalid.")
  }

  const libraryRoot = path.resolve(requestedRoot)
  const database = new DatabaseSync(databasePath)
  try {
    database.exec("BEGIN IMMEDIATE")
    database
      .prepare("DELETE FROM layer_cache WHERE library_root = ?")
      .run(libraryRoot)
    database.exec("COMMIT")
  } catch (error) {
    try {
      database.exec("ROLLBACK")
    } catch {
      // Preserve the original database error.
    }
    throw error
  } finally {
    database.close()
  }

  return readLibraryOverview(acceptedCachePath)
}
