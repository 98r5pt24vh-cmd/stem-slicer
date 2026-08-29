import type { BrowserWindow, OpenDialogOptions, OpenDialogReturnValue } from "electron"

export interface NativeOpenDialog {
  showOpenDialog(options: OpenDialogOptions): Promise<OpenDialogReturnValue>
  showOpenDialog(window: BrowserWindow, options: OpenDialogOptions): Promise<OpenDialogReturnValue>
}

export function showOwnedOpenDialog(
  nativeDialog: NativeOpenDialog,
  owner: BrowserWindow | null,
  options: OpenDialogOptions,
): Promise<OpenDialogReturnValue> {
  return owner
    ? nativeDialog.showOpenDialog(owner, options)
    : nativeDialog.showOpenDialog(options)
}
