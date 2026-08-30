import { randomUUID } from "node:crypto"
import { spawn } from "node:child_process"
import { existsSync, statSync } from "node:fs"
import { rename } from "node:fs/promises"
import path from "node:path"

export type CloudExportMasterTrash = (targetPath: string) => Promise<void>
export type CloudExportMasterConverter = (
  sourcePath: string,
  destinationPath: string,
  ffmpegPath: string,
) => Promise<void>

export interface CloudExportMasterOptions {
  convert?: CloudExportMasterConverter
  trashItem?: CloudExportMasterTrash
}

export function cloudExportWavPath(sourcePath: string): string {
  const extension = path.extname(sourcePath).toLocaleLowerCase()
  if (extension === ".wav") return sourcePath
  const baseName = path.basename(sourcePath, path.extname(sourcePath))
  return path.join(path.dirname(sourcePath), `${baseName}.cloud-activity.wav`)
}

async function convertWithFfmpeg(
  sourcePath: string,
  destinationPath: string,
  ffmpegPath: string,
): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const child = spawn(ffmpegPath, [
      "-n",
      "-hide_banner",
      "-loglevel",
      "error",
      "-nostdin",
      "-i",
      sourcePath,
      "-vn",
      "-map_metadata",
      "-1",
      "-acodec",
      "pcm_s16le",
      "-f",
      "wav",
      destinationPath,
    ], {
      stdio: ["ignore", "ignore", "pipe"],
      windowsHide: true,
    })
    let stderr = ""
    child.stderr.setEncoding("utf8")
    child.stderr.on("data", (chunk: string) => {
      if (stderr.length < 4_000) stderr += chunk
    })
    child.once("error", reject)
    child.once("close", (code) => {
      if (code === 0) {
        resolve()
        return
      }
      reject(new Error(stderr.trim() || `FFmpeg stopped with code ${code ?? "unknown"}.`))
    })
  })
}

export async function ensureCloudExportWavMaster(
  sourcePath: string,
  ffmpegPath: string,
  options: CloudExportMasterOptions = {},
): Promise<string> {
  if (!existsSync(sourcePath) || !statSync(sourcePath).isFile()) {
    throw new Error("The generated master for this Cloud activity is unavailable.")
  }
  const extension = path.extname(sourcePath).toLocaleLowerCase()
  if (extension === ".wav") return sourcePath
  if (extension !== ".mp3") {
    throw new Error("Cloud activity supports generated MP3 or WAV masters.")
  }
  if (!ffmpegPath.trim()) {
    throw new Error("FFmpeg is unavailable for the Cloud activity master.")
  }

  const destinationPath = cloudExportWavPath(sourcePath)
  if (existsSync(destinationPath)) {
    if (statSync(destinationPath).isFile() && statSync(destinationPath).size > 44) return destinationPath
    if (!options.trashItem) {
      throw new Error("The previous Cloud activity master is incomplete.")
    }
    await options.trashItem(destinationPath)
  }

  const temporaryPath = `${destinationPath}.${randomUUID()}.partial`
  const convert = options.convert ?? convertWithFfmpeg
  try {
    await convert(sourcePath, temporaryPath, ffmpegPath)
    if (!existsSync(temporaryPath) || !statSync(temporaryPath).isFile() || statSync(temporaryPath).size <= 44) {
      throw new Error("FFmpeg did not produce a valid Cloud activity WAV master.")
    }
    if (existsSync(destinationPath)) {
      if (statSync(destinationPath).isFile() && statSync(destinationPath).size > 44) {
        if (options.trashItem) await options.trashItem(temporaryPath)
        return destinationPath
      }
      if (!options.trashItem) throw new Error("The previous Cloud activity master is incomplete.")
      await options.trashItem(destinationPath)
    }
    await rename(temporaryPath, destinationPath)
    return destinationPath
  } catch (error) {
    if (existsSync(temporaryPath) && options.trashItem) {
      await options.trashItem(temporaryPath).catch(() => undefined)
    }
    throw error
  }
}
