import { describe, expect, it } from "vitest"

import { summarizeLibraryProducers } from "./library-cache"

describe("library producer summaries", () => {
  it("counts source producers without inventing +NRGY on collaborator-only loops", () => {
    const summaries = summarizeLibraryProducers([
      { library_root: "/library", source_loop_id: "nitro", filename: "Dm NITROV2 151 +NRGY TEENX_L1.mp3" },
      { library_root: "/library", source_loop_id: "nitro", filename: "Dm NITROV2 151 +NRGY TEENX_L2.mp3" },
      { library_root: "/library", source_loop_id: "take-me-out", filename: "638 TAKE ME OUT 197 Fmin Liv_L1.mp3" },
    ])

    expect(summaries).toEqual([
      { name: "+NRGY", layerCount: 2, loopCount: 1, libraryRoots: ["/library"] },
      { name: "Liv", layerCount: 1, loopCount: 1, libraryRoots: ["/library"] },
      { name: "TEENX", layerCount: 2, loopCount: 1, libraryRoots: ["/library"] },
    ])
  })
})
