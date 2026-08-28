import type { ForgeConfig } from "@electron-forge/shared-types"
import { VitePlugin } from "@electron-forge/plugin-vite"
import { existsSync } from "node:fs"
import path from "node:path"

const packagingRoot = path.resolve(process.cwd(), ".packaging")
const packagedResources = ["engine", "python", ".runtime"]
  .map((name) => path.join(packagingRoot, name))
  .filter((resourcePath) => existsSync(resourcePath))

const config: ForgeConfig = {
  packagerConfig: {
    asar: true,
    name: "Slicer",
    executableName: "Slicer",
    icon: path.resolve(process.cwd(), process.platform === "win32" ? "../assets/StemSlicer.ico" : "../assets/StemSlicer.icns"),
    extraResource: packagedResources,
    win32metadata: {
      CompanyName: "Slicer",
      FileDescription: "Slicer Cloud alpha",
      InternalName: "Slicer",
      OriginalFilename: "Slicer.exe",
      ProductName: "Slicer",
    },
  },
  makers: [
    {
      name: "@electron-forge/maker-zip",
      platforms: ["win32"],
    },
  ],
  plugins: [
    new VitePlugin({
      build: [
        {
          entry: "src/main.ts",
          config: "vite.main.config.ts",
          target: "main",
        },
        {
          entry: "src/preload.ts",
          config: "vite.preload.config.ts",
          target: "preload",
        },
      ],
      renderer: [
        {
          name: "main_window",
          config: "vite.renderer.config.ts",
        },
      ],
    }),
  ],
}

export default config
