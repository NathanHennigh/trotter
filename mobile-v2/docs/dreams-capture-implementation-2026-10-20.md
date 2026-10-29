# Dreams and Capture implementation — October 20, 2026

## Authorized scope

Implemented the approved Dreams and Capture direction from the separate design preview. Globe, Trips, trip detail, Passport, Profile/settings and their navigation retain their existing design. The actual Countries collection is unchanged and awaits review of three preview alternatives.

## Behavior

- Library search covers name, city, country, source text and personal notes. Country postcards remain.
- Needs attention contains actionable saves; automatic uploads, sorting and scheduled retries have a separate organizing entry.
- Country pages open on Places with a compact header. Map is a separate view; the list stays mounted so returning preserves scroll. Search, broad type, city and sorting live in one filter panel. One- and two-save countries omit unnecessary controls unless an existing filter is active.
- Source pages keep the country or library mounted beneath them. Back returns to that context and its filters. Source pages have no country map or country filters.
- Map coverage and missing-location review are explicit. Existing exact/area precision, Google attribution, provider expiry and creator-gated inspiration behavior remain.
- Place details put Maps and original-post actions first. Missing/failed thumbnails shrink to a compact category illustration. Imported description and personal note are separate.
- Editing keeps name, city, country, type and personal note visible, with tags, region and manual pin controls behind More details. Dirty-draft protection remains. Only changed fields are submitted, compared with the edit baseline, preventing a background location update from being overwritten by a note edit.
- Paste capture leads with one link and a Save to Dreams button; optional caption follows. Capture closes only after durable local retention and shows local-save feedback.
- Android's Instagram receipt uses a small Trotter signature, compact thumbnail, one state-aware headline, and Open/Sign in/Retry. No generic success checkmark. Local retention is distinct from server success. Storage failure never displays raw exceptions. Four seconds of visible reading time, paused for interaction/backgrounding; screen-reader, sign-in and failure states remain open. Dismissal remains blocked until capture is durable or storage failure is known.

## Data and rollout

`0015_dream_personal_notes` adds a nullable text column; existing descriptions are not moved or rewritten. Note-only updates preserve enrichment jobs, inferred review status and location state. The migration refuses a destructive downgrade.

Apply `backend/.venv/Scripts/alembic.exe upgrade head` (or the deployment's normal Alembic command) against the intended backend database **before starting the updated backend**. Then deploy the backend and rebuild the Android app to include the native receipt. No production database migration, server deployment or device installation was performed in this task.

## Validation

- TypeScript typecheck passed.
- 127 targeted JavaScript tests passed: browsing, cards, editor, image fallback, outbox, maps, native bridge and retained home navigation.
- 21 Dreams API tests plus 75 migration/enrichment/source/location API tests passed against isolated SQLite fixtures.
- 10 native inbox tests, 10 receipt lifecycle tests and receipt copy checks passed against production Kotlin classes.
- Android `:app:compileDebugKotlin` passed.
- Browser inspected static React Native Web projections of the changed country, detail, editor and capture components. These are layout checks, not native-device screenshots; map imagery is stubbed.
- No Android device was connected. Native gesture, keyboard, TalkBack and real OS font scaling still require a device smoke test.

## Countries preview

https://trotter-design-preview-oct20.hennigh.chatgpt.site/#collections

Choose Country iteration: Atlas plates, Travel ledger or Luggage labels. Current mode retains the historical native capture. All data and actions in that webpage are illustrative; none modify the app.

