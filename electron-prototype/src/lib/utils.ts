import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat("fr-FR").format(value)
}

export function basename(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? path
}
