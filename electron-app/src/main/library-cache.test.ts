import { describe, expect, it } from "vitest"

import { summarizeLibraryProducers, summarizeLibrarySelection } from "./library-cache"

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

  it("recalculates producer totals from only the selected libraries", () => {
    const rows = [
      { library_root: "/main", source_loop_id: "shared", filename: "Dm SHARED 140 +NRGY XT_L1.mp3" },
      { library_root: "/main", source_loop_id: "shared", filename: "Dm SHARED 140 +NRGY XT_L2.mp3" },
      { library_root: "/noise", source_loop_id: "noise", filename: "A#m NOISE 145 A#MIN XT_L1.mp3" },
    ]

    expect(summarizeLibraryProducers(rows, "+NRGY", ["/noise"])).toEqual([
      { name: "+NRGY", layerCount: 1, loopCount: 1, loopCountsByCreditCount: { "2": 1 }, layerCountsByCreditCount: { "2": 1 }, libraryRoots: ["/noise"] },
      { name: "XT", layerCount: 1, loopCount: 1, loopCountsByCreditCount: { "2": 1 }, layerCountsByCreditCount: { "2": 1 }, libraryRoots: ["/noise"] },
    ])
    expect(summarizeLibraryProducers(rows, "+NRGY", [])).toEqual([])
  })

  it("summarizes only layers eligible for the selected producers and credit limit", () => {
    const rows = [
      { library_root: "/library", source_loop_id: "solo", filename: "Dm SOLO 140 +NRGY_L1.mp3", category: "Keys" },
      { library_root: "/library", source_loop_id: "solo", filename: "Dm SOLO 140 +NRGY_L2.mp3", category: "Bass" },
      { library_root: "/library", source_loop_id: "duo", filename: "Dm DUO 140 +NRGY XT_L1.mp3", category: "Lead" },
      { library_root: "/library", source_loop_id: "trio", filename: "Dm TRIO 140 +NRGY XT LIV_L1.mp3", category: "Pad" },
    ]

    expect(summarizeLibrarySelection(rows, {
      allowedProducers: ["+NRGY"],
      allowedCreditCounts: [1],
    })).toEqual({
      layerCount: 2,
      loopCount: 1,
      categories: [{ name: "Bass", count: 1 }, { name: "Keys", count: 1 }],
    })

    expect(summarizeLibrarySelection(rows, {
      allowedProducers: ["+NRGY", "XT"],
      allowedCreditCounts: [1, 2],
    })).toEqual({
      layerCount: 3,
      loopCount: 2,
      categories: [{ name: "Bass", count: 1 }, { name: "Keys", count: 1 }, { name: "Lead", count: 1 }],
    })
  })

  it("treats the signed-in producer as the owner without injecting +NRGY", () => {
    const summaries = summarizeLibraryProducers([
      { library_root: "/xt", source_loop_id: "solo", filename: "FMIN PRIVATE 140_L1.mp3" },
      { library_root: "/xt", source_loop_id: "duo", filename: "DUO 140 +NRGY XT C#MIN_L1.mp3" },
    ], "XT")

    expect(summaries.map((summary) => summary.name)).toEqual(["XT", "+NRGY"])
    expect(summaries.find((summary) => summary.name === "C#MIN")).toBeUndefined()
  })

  it("merges local filename aliases into one Cloud producer identity", () => {
    const identities = [{ canonicalName: "XT", aliases: ["Tinex", "T-Next Is Here"] }]
    const rows = [
      { library_root: "/noise", source_loop_id: "first", filename: "A#m FIRST 145 A#MIN XT_L1.mp3" },
      { library_root: "/noise", source_loop_id: "second", filename: "Tinex 140 Tinex_L1.mp3" },
      { library_root: "/noise", source_loop_id: "third", filename: "Dm THIRD 140 T-Next Is Here_L1.mp3" },
    ]

    const summaries = summarizeLibraryProducers(rows, "+NRGY", ["/noise"], identities)
    expect(summaries.map((summary) => summary.name)).toEqual(["+NRGY", "XT"])
    expect(summaries.find((summary) => summary.name === "XT")).toMatchObject({ loopCount: 3, layerCount: 3 })
  })
})
