# Stem Slicer Electron UI invariants

These instructions apply to every task inside `electron-app`.

## Player-bound full-height pages

History, Review, Cloud and Profile use the global player as the visible lower
boundary of the workspace. Full-height page panels must visually continue
behind that boundary: their lower edges meet the player separator directly,
with no visible bottom corner, border, black wedge or gap.

When the user asks for a panel to "descend straight", "continue under the
player" or have an "infinite" lower edge:

- Change the outer full-height page panel that owns the surface and radius.
  Do not stretch or flatten list rows, producer cards, activity rows or other
  inner items.
- Preserve `height: 100%`/flex fill on the outer panel and remove only its
  bottom edge treatment with logical properties:
  `border-block-end: 0`, `border-end-start-radius: 0` and
  `border-end-end-radius: 0`.
- For Profile, the relevant outer surface is
  `.profile-main .cloud-profile-card`; the preview and editor are two columns
  inside that one card, not two independent page panels.
- Match the established implementation on the other full-height pages before
  introducing a new selector or layout rule.

## Required visual verification

Never report a visual fix as complete from CSS inspection, dimensions or a
browser-only renderer check.

1. Run lint and tests.
2. Verify the actual Electron application window on the affected page.
3. If the result does not reflect the source change, treat HMR as stale and
   restart the Electron development process before diagnosing the CSS again.
4. Capture the real Electron window with Computer Use and inspect the exact
   boundary above the global player.
5. Report completion only after the capture visibly confirms straight edges,
   no bottom radii and no gap on both sides of the panel.

Use the Better UI and Better Layout skills for interface-detail changes, and
keep the change scoped to the requested page unless the user explicitly asks
for a shared rule.
