# Itinerary and Dreams polish — October 27, 2026

The itinerary keeps every day in one continuous scroll. A compact date strip jumps
to measured day headings, follows manual scrolling, and pins below the existing
header. The inline strip is hidden from accessibility while its pinned copy is
active. Draft acceptance remains above the main navigation for organisers and
editors, with space reserved so the final content is reachable.

Reorder mode uses measured row heights, animated neighboring positions, and an
optimistic plan tied to the current account, trip, version, and request. A failed
save restores the saved order. A conflict refreshes the server plan without
retrying the write. Dragging pauses background replacement; cancellation does not
save. Progress remains in the day’s reserved instruction row rather than moving
the whole page.

Empty day periods retain full-row touch targets and editable place/text choices,
with smaller italic titles and quieter time detail. Dreams attention is a compact
text/count row; destination postcards keep the visual emphasis.

Planner sheets enter from the bottom with a coordinated scrim, use shorter dismiss
motion, and respect reduced motion. Hiding a retained screen immediately removes
the native modal while preserving form state. A cancelled close cannot dismiss a
new form. Programmatic unmount after a successful save remains immediate.

Validation: TypeScript and 74 planner tests passed, including navigation,
optimistic rollback, conflicts, account changes, varying row heights, cancelled
gestures, sheet identity, and keyboard reveal. The focused Dreams behavior checks
also passed. Actual React Native Web components were checked with simulated trip
data at 393px and 320px widths: day jumps, continuous scrolling, pinned controls,
drag save/failure, and contributor permissions. Android 0.1.2 / version code 3
built successfully with the existing beta certificate. No fresh on-phone check
was performed; the user will test the downloaded update later.
