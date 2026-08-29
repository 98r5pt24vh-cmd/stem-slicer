import type { BrowserWindow, OpenDialogOptions, OpenDialogReturnValue } from "electron"
import { describe, expect, it, vi } from "vitest"

import { showOwnedOpenDialog, type NativeOpenDialog } from "./native-dialog"

describe("native file dialog ownership", () => {
  const result: OpenDialogReturnValue = { canceled: true, filePaths: [] }
  const options: OpenDialogOptions = { properties: ["openFile"] }

  it("parents Browse dialogs to the requesting Electron window", async () => {
    const owner = {} as BrowserWindow
    const showOpenDialog = vi.fn(async () => result)
    const nativeDialog = { showOpenDialog } as unknown as NativeOpenDialog

    await showOwnedOpenDialog(nativeDialog, owner, options)

    expect(showOpenDialog).toHaveBeenCalledWith(owner, options)
  })

  it("keeps a safe fallback when the requesting window has closed", async () => {
    const showOpenDialog = vi.fn(async () => result)
    const nativeDialog = { showOpenDialog } as unknown as NativeOpenDialog

    await showOwnedOpenDialog(nativeDialog, null, options)

    expect(showOpenDialog).toHaveBeenCalledWith(options)
  })
})
