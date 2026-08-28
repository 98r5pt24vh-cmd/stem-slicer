import { describe, expect, it } from "vitest"

import { summarizeLibraryProducers } from "./library-cache"

describe("library producer summaries", () => {
  it("counts exact final-credit sizes for each available producer", () => {
    const summaries = summarizeLibraryProducers([
      { library_root: "/library", source_loop_id: "nitro", filename: "Dm NITROV2 151 +NRGY TEENX_L1.mp3" },
      { library_root: "/library", source_loop_id: "nitro", filename: "Dm NITROV2 151 +NRGY TEENX_L2.mp3" },
      { library_root: "/library", source_loop_id: "take-me-out", filename: "638 TAKE ME OUT 197 Fmin Liv_L1.mp3" },
      { library_root: "/library", source_loop_id: "solo", filename: "Dm SOLO 140 +NRGY_L1.mp3" },
    ])

    expect(summaries).toEqual([
      { name: "+NRGY", layerCount: 4, loopCount: 3, loopCountsByCreditCount: { "1": 1, "2": 2 }, layerCountsByCreditCount: { "1": 1, "2": 3 }, libraryRoots: ["/library"] },
      { name: "Liv", layerCount: 1, loopCount: 1, loopCountsByCreditCount: { "2": 1 }, layerCountsByCreditCount: { "2": 1 }, libraryRoots: ["/library"] },
      { name: "TEENX", layerCount: 2, loopCount: 1, loopCountsByCreditCount: { "2": 1 }, layerCountsByCreditCount: { "2": 2 }, libraryRoots: ["/library"] },
    ])
  })
})
