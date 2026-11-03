# Account 12 manual import audit — 2026-11-03 UTC

This read-only follow-up expands the pilot audit. The earlier six-missing-leg
inventory was incomplete: four more complete named legs were already present
in the captured originals. This is an evidence inventory, not a repair or a
claim that every booked flight was boarded.

## Coverage and safeguards

- Manually reviewed all 4,948 indexed sender/subject records, grouped into
  1,999 unique sender/subject groups, independently of parser outcomes.
- Ran 21 read-only, all-date Gmail searches, including Spam/Trash, covering
  airlines, agencies, attachments, compressed passenger names, booking references,
  changes, forwarded travel and international itineraries. All result sets were
  paginated to completion: 698 distinct matching messages.
- Reviewed metadata for 175 distinct matches absent from Trotter's index.
  These did not expose another complete flight ticket; the apparent new Amex
  confirmation was a hotel booking. Unrelated message bodies were not fetched.
- Retrieved 32 additional selected originals, taking the available original
  evidence collection from 293 to 325 messages. All requested originals were
  available. Existing bounded attachment text was retained.
- Read the unauthenticated shared Europe itinerary explicitly linked in an
  email. Another linked travel itinerary required an Axus login and was not
  accessed beyond the login page.
- Database reads used server-enforced read-only repeatable-read transactions;
  credentials remained in the current backend process. No scan/import job,
  mailbox mutation, database repair, cohort change or deployment was performed.
  Flight, trip and job snapshots matched before/after all five network phases.

This is broader than the original diagnostic selection but is not proof of
complete mailbox recall or of flights whose tickets are in a different inbox.

## Ten complete missing legs

Each has named passenger evidence and complete local schedules. No matching
cancellation was found in the reviewed evidence. The first four rows are the
additional complete legs omitted from the initial pilot inventory.

| Date | Flight | Route and local schedule | Evidence DB IDs |
| --- | --- | --- | --- |
| 2023-03-12 | UA1433 | MGA 13:15 → IAH 17:41 | 24903, 24904, 27851 |
| 2023-03-12 | UA1636 | IAH 21:57 → DFW 23:07 | 24903, 24904, 27851 |
| 2024-02-16 | WN40 | DAL 17:45 → ONT 19:05 | 25040, 25038 |
| 2024-02-20 | WN3704 | SAN 15:40 → DAL 20:30 | 25039 |
| 2025-07-12 | DL439 | DFW 06:15 → LAX 07:25 | 24377, 24387, 24401, 24900 |
| 2025-07-12 | DL487 | LAX 11:10 → ANC 15:26 | 24377, 24387, 24401, 24900 |
| 2026-09-17 | G42057 | SNA 12:27 → DSM 17:44 | 24121, 28080 |
| 2026-09-20 | G42056 | DSM 10:00 → SNA 11:37 | 24121, 28080 |
| 2026-10-20 | AS3492 | SNA 17:47 → SFO 19:19 | 24104 |
| 2026-10-23 | AS269 | SFO 17:04 → SNA 18:41 | 24104 |

The United legs complete the Nicaragua return after the two existing Spirit
outbound legs. The two Southwest bookings use different California airports;
there is no evidence for an additional flight between ONT and SAN.

## Four additional partial legs

- **SY474 ANC → MSP and SY501 MSP → DFW:** named booking, with outer itinerary
  bounds July 19, 2025 at 20:55 to July 20 at 08:57. MSP arrival/departure clocks
  remain absent. Do not create a nonstop ANC–DFW flight or invent intermediate
  times. Sources 25293–25295 and carrier corroboration 28270/28271.
- **UA2657 SNA → SFO, July 29, 2026; UA589 SFO → SNA, July 31:** flight numbers,
  routes and dates explicitly appear in newly fetched entertainment emails
  28117/28116. Companion booking reminders and a post-travel survey support the
  journey. Exact clocks and standalone full-name authority are absent in those
  entertainment messages; booking association remains contextual. The earlier
  unknown return origin/flight number is now resolved, not the missing clocks.

## Cancellation and attribution exceptions

- Existing segments 240/241 and 243 still have the previously documented
  pre-departure cancellations; unsupported segment 242 remains unchanged.
- The 2025 Austin cancellation arrived after its February 14 outbound and
  before its February 17 return, refunding half the original points/tax.
  Do not retroactively cancel the outbound solely from that reservation notice.
  Its final disposition is held for review, not counted among the ten above.
- The 2023 Allegiant cancellation arrived October 16, after the October 12/15
  travel dates. Later carrier surveys reference both journeys. This conflicts
  with treating both as definitely unflown. Preserve the conflict; do not
  automatically restore them or erase their historical evidence. This qualifies
  the earlier pilot document's categorical cancellation wording.
- Spirit NK435's delay notices cross midnight and culminate in a March 4
  02:00–03:57 estimate. These are delay estimates, not verified actual times.
  A named apology voucher corroborates disruption but creates no extra flight.
- The shared Europe document lists four flight entries, but does not name
  account 12's traveler. A repeated flight number also appears inconsistent.
  Sharing a document is not passenger ownership evidence; none are counted.

## What is failing

Most useful originals were already indexed. The main demonstrated failures
are downstream: passenger/leg association marked named Southwest and Expedia
bookings unknown; complete Alaska/Delta/Expedia formats failed extraction; and
promo filtering discarded operational facts. In particular, source 24387 is
an explicit named Amex schedule change, 28080 includes named Allegiant routes
and clocks, and 28116/28117 include United flight numbers/routes/dates, yet all
were marked `ignored_nonflight_promo`.

Repair work must preserve strong ownership requirements while recovering these
specific associations, protect useful itinerary blocks from marketing copy,
and reconcile cancellation chronology and scope. Partial evidence must remain
partial. The current six-record live result is materially incomplete and also
contains the known erroneous entries; ten missing legs must not simply be
added to six and presented as a correct total.

Private source captures, query inventories, hashes and independent reviews are
under `artifacts/production-readiness-20261102/grant-pilot-20261103` and the
corresponding existing private Oracle directory. `deep-audit-coverage.json`
records coverage; `grant-deep-existing-review.json` records source-backed facts.
No production parser or imported flight record was changed by this audit.
