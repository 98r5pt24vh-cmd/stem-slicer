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
