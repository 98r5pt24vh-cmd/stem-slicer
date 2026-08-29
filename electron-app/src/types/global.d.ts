import type { StemSlicerDesktopApi } from "@/shared/contracts"

declare global {
  const MAIN_WINDOW_VITE_DEV_SERVER_URL: string | undefined
  const MAIN_WINDOW_VITE_NAME: string

  interface Window {
    stemSlicer?: StemSlicerDesktopApi
  }
}

export {}
