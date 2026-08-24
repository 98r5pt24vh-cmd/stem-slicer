import { existsSync } from "node:fs"
import path from "node:path"
import { DatabaseSync } from "node:sqlite"

import type {
  CategorySummary,
  LibraryOverview,
  LibraryRootSummary,
} from "../shared/contracts"

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
    const total = database
      .prepare("SELECT COUNT(*) AS count FROM layer_cache")
      .get() as unknown as CountRow
    const rootRows = database
      .prepare(`
        SELECT
          library_root,
          COUNT(*) AS layer_count,
          SUM(CASE WHEN key_confidence_status <> 'unavailable' THEN 1 ELSE 0 END)
            AS analyzed_key_count
        FROM layer_cache
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
