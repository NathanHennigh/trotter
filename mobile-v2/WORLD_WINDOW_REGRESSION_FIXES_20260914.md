# World Window regression fixes

The installed `6338cbd` build exposed native transition regressions that static layout proofs did not catch. A physical-phone recording confirmed the duplicate wallet/destination handoff and vertical itinerary shift.

- Trip entry now moves a single opaque itinerary using a native-driven horizontal transition. Wallet taps no longer wait for layout measurement. Loading feedback lives in the fixed Back bar, and exact-flight positioning does not animate vertically during entry. Back can interrupt entry.
- Passport loading retains a cover with matching bounds until fonts, page textures and the initial rendered frame are ready. Early taps queue the opening. The runtime readiness message follows two painted frames, not HTML initialization.
- Dreams displays a matched Google location directly, with no pin approval UI. Existing Google matches waiting under the old review policy keep polling while the server rechecks them. Fresh Google place identity, address and coordinates update together; manual editing remains available.

The backend automatically resolves the first compatible Google result in provider relevance order and requeues old waiting matches through the scheduler. Original saves and manual pins are preserved. Google coordinates retain their existing expiring cache and business details remain transient. No schema migration is required.

Validation includes the full World Window mobile suite, TypeScript, 241 passport layout sizes, 98 passport browser motion samples, delayed-load/early-tap tests, interrupted trip navigation and Dreams automatic-location/polling tests. Physical Android and deployment results are recorded in the local `artifacts/` proofs.
