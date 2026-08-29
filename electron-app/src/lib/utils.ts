import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat("fr-FR").format(value)
}

export function formatDecimalBytes(bytes: number): string {
  const safeBytes = Math.max(0, Number.isFinite(bytes) ? bytes : 0)
  if (safeBytes < 1_000) return `${Math.round(safeBytes)} octets`
  const units = ["Ko", "Mo", "Go", "To"]
  const unitIndex = Math.min(units.length - 1, Math.floor(Math.log(safeBytes) / Math.log(1_000)) - 1)
  const value = safeBytes / (1_000 ** (unitIndex + 1))
  const maximumFractionDigits = value >= 100 ? 0 : value >= 10 ? 1 : 2
  return `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits }).format(value)} ${units[unitIndex]}`
}

export function basename(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? path
}

export function joinPath(root: string, child: string): string {
  const separator = root.includes("\\") && !root.includes("/") ? "\\" : "/"
  return `${root.replace(/[\\/]+$/, "")}${separator}${child.replace(/^[\\/]+/, "")}`
}

const INVALID_FOLDER_SYMBOLS = /[<>:"/\\|?*]/
const INVALID_FOLDER_SYMBOLS_GLOBAL = /[<>:"/\\|?*]/g
const RESERVED_WINDOWS_FOLDER_NAMES = /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$/i

function containsControlCharacter(value: string): boolean {
  return [...value].some((character) => character.charCodeAt(0) < 32)
}

export function extractionFolderNameForSource(sourcePath: string): string {
  const sourceName = basename(sourcePath)
    .replace(INVALID_FOLDER_SYMBOLS_GLOBAL, " ")
    .split("").map((character) => character.charCodeAt(0) < 32 ? " " : character).join("")
    .replace(/\s+/g, " ")
    .replace(/[. ]+$/g, "")
    .trim()
  const safeSourceName = sourceName && !RESERVED_WINDOWS_FOLDER_NAMES.test(sourceName) ? sourceName : "Loop pack"
  return `${safeSourceName} Extracted Layers`
}

export function outputFolderNameError(folderName: string): string {
  const normalized = folderName.trim()
  if (!normalized) return "Enter an output folder name."
  if (INVALID_FOLDER_SYMBOLS.test(normalized) || containsControlCharacter(normalized)) return "Remove slashes, colons, asterisks, question marks, quotes, angle brackets and pipes."
  if (normalized === "." || normalized === ".." || /[. ]$/.test(normalized) || RESERVED_WINDOWS_FOLDER_NAMES.test(normalized)) {
    return "Choose a different folder name."
  }
  return ""
}
