import path from "node:path"
import { describe, expect, it } from "vitest"

import { resolveRuntimePaths } from "./runtime-paths"

describe("resolveRuntimePaths", () => {
  it("keeps development resources in the source tree", () => {
    const paths = resolveRuntimePaths({
      appRoot: "/workspace/electron-prototype",
      resourcesPath: "/Applications/Slicer.app/Contents/Resources",
      isPackaged: false,
      platform: "darwin",
      environment: {},
    })

    expect(paths.bridgePath).toBe(path.join("/workspace/electron-prototype", "python", "engine_bridge.py"))
    expect(paths.sourceRoot).toBe(path.resolve("/workspace/electron-prototype", "../../../..", "Stem Slicer Repository"))
    expect(paths.pythonPath).toBe("python3.12")
  })

  it("uses packaged Windows resources instead of macOS paths", () => {
    const paths = resolveRuntimePaths({
      appRoot: "C:\\Program Files\\Slicer\\resources\\app.asar",
      resourcesPath: "C:\\Program Files\\Slicer\\resources",
      isPackaged: true,
      platform: "win32",
      environment: {},
    })

    expect(paths.bridgePath).toBe(path.join("C:\\Program Files\\Slicer\\resources", "python", "engine_bridge.py"))
    expect(paths.sourceRoot).toBe(path.join("C:\\Program Files\\Slicer\\resources", "engine"))
    expect(paths.pythonPath).toBe("python.exe")
  })

  it("honours explicit runtime overrides on every platform", () => {
    const paths = resolveRuntimePaths({
      appRoot: "/workspace/app",
      resourcesPath: "/workspace/resources",
      isPackaged: true,
      platform: "win32",
      environment: {
        STEM_SLICER_PYTHON: "D:\\runtime\\python.exe",
        STEM_SLICER_SOURCE_ROOT: "D:\\runtime\\engine",
      },
    })

    expect(paths.pythonPath).toBe("D:\\runtime\\python.exe")
    expect(paths.sourceRoot).toBe("D:\\runtime\\engine")
  })
})
