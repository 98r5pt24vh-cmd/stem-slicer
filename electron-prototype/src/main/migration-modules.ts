import type { MigrationModule } from "../shared/contracts"

export const migrationModules: MigrationModule[] = [
  {
    id: "desktop-shell",
    label: "Fenêtre, navigation et état de l’application",
    runtime: "TypeScript",
    state: "native",
    detail: "Electron, React, IPC typé et design system shadcn.",
  },
  {
    id: "library-catalog",
    label: "Catalogue des bibliothèques",
    runtime: "TypeScript",
    state: "connected",
    detail: "Lecture SQLite 1.9B sans aucune écriture dans le cache accepté.",
  },
  {
    id: "audio-playback",
    label: "Transport et lecture synchronisée",
    runtime: "TypeScript",
    state: "queued",
    detail: "Web Audio et transport partagé entre toutes les cards.",
  },
  {
    id: "audio-render",
    label: "Rendu, pitch et time-stretch",
    runtime: "External binary",
    state: "queued",
    detail: "FFmpeg et Bungee pilotés par les services Node.",
  },
  {
    id: "mert-inference",
    label: "Classification MERT et détection de clé",
    runtime: "Python adapter",
    state: "queued",
    detail: "Adaptateur temporaire jusqu’à validation ONNX/TypeScript à résultat égal.",
  },
]
