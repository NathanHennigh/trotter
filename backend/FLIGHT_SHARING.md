# Flight sharing

Flight sharing uses the existing Oracle-hosted PostgreSQL database and API. It
adds a private “Flights for others” inbox and explicit invitations. This is a copy
of travel-history facts, not an airline ticket transfer or booking-management link.

## Flow

1. The owner reviews retained flights. Unknown passengers can be named with a
   separate annotation; immutable email extraction and personal trips stay intact.
   A named ticket cannot be relabeled to a different passenger.
2. The owner selects up to 40 complete, distinct flight legs for one traveler and
   enters the email that traveler uses to sign in with Google. Recipient existence
   is not disclosed and no user is created. No email or external message is sent
   automatically. The native share sheet lets the owner deliver the invitation.
3. Existing users see the invitation in Received. A new user follows the generic
   HTTPS link, opens Trotter or continues in the browser, signs in/joins using the
   addressed Google account, and reviews the flights. App auth requires verified
   Google email identity. Possession of the link alone cannot access the flights.
4. The recipient explicitly accepts. Already-imported dated flights are counted
   as existing and left intact; missing flights enter the normal itinerary builder.
   The imported flights can contribute to Trips, Globe and Passport as usual.

## API contract

All routes below require normal app authentication except `/open`.

| Method / path | Purpose / response |
| --- | --- |
| `GET /travel-sharing/inbox` | `{items, incoming, outgoing}`; excludes owner-identified items |
| `PATCH /travel-sharing/items/{id}` | `{passenger_name}` owner annotation; returns updated inbox item |
| `POST /travel-sharing` | `{item_ids, passenger_name, recipient_email, client_request_id?}` → `{share, share_url}` |
| `POST /travel-sharing/resolve` | `{token}` → sanitized share for sender or addressed recipient |
| `POST /travel-sharing/{id}/link` | Sender retrieves the same pending/unexpired URL; `{share_url}` |
| `POST /travel-sharing/{id}/accept` | Recipient accepts; `{share, added_flights, existing_flights}` |
| `POST /travel-sharing/{id}/decline` | Recipient declines; `{share}` |
| `POST /travel-sharing/{id}/revoke` | Sender revokes pending invitation; `{share}` |
| `GET /travel-sharing/open#token=…` | Generic no-store HTML landing; no flight or identity details |

Share fields: `id`, `passenger_name`, `sender_name`, `recipient_email`, `status`,
`created_at`, `expires_at`, `accepted_at`, `flights`. Flights expose only
`dep_airport`, `arr_airport`, `travel_date`, `flight_number`, `dep_time`, `arr_time`,
`airline`. Owner-only booking references and evidence pointers never enter the
share response or recipient evidence.

Inbox items add `assigned_passenger_name`, `shareable`, `requires_assignment`, and
`share_blocked_reason`. `requires_assignment` means a name is the sole blocker;
missing times, canceled flights and conflicting evidence cannot be bypassed by
typing a name. The initial inbox supports up to 5,000 records in each section,
returning an explicit error instead of silently dropping additional records.

## Safety and repeat behavior

- Invitations last 14 days. Status is pending, accepted, declined, revoked or
  expired. Expiry is projected at read/action time; no expiry worker is needed.
- The random 256-bit token is hashed for lookup and AES-GCM encrypted for the
  sender's explicit “Share link” action and retry-safe creation. Preserve the
  existing `ENCRYPTION_KEY`. Tokens appear in the landing fragment, not its request
  URL; authenticated resolution posts the token in a body.
- Clients reuse `client_request_id` on creation retries. A repeated identical
  request returns the same invitation/link. Changed input with the same ID fails.
- Sharing does not update the sender's personal flights or infer recipient
  ownership by matching names. Recipient identity uses the exact normalized Google
  sign-in email; dots, plus-addresses and aliases are not silently equated.
- Acceptance takes the existing per-user import locks for sender and recipient
  in sorted order, then locks the invitation row. Source identity/cancellation
  state and flight facts are revalidated. Changed bookings require a new share.
- Acceptance and imported evidence commit atomically while locks are held.
  Failed operations roll back. Repeated acceptance returns the original outcome.
- Existing dated route/flight matches are preserved; conflicting departures are
  blocked rather than overwritten. Zero-padded flight numbers use the itinerary's
  canonical normalizer. Accepted legs retain the original booking evidence time,
  separately from the acceptance time, so a later real rescheduling receipt is
  not artificially treated as older. Later verified self email imports can match
  an unreferenced accepted leg by unique dated route/number even if its departure
  time changed, then attach the recipient's own booking reference.
- Revocation/declining prevents future acceptance. Revocation does not retract
  an accepted travel history. Later sender-side changes/cancellations are not
  silently propagated across accounts; a future update-consent flow is separate.

## Rollout

Back up the intended database. Apply migration `0017_flight_sharing` (and any
pending ancestors) before starting the updated API/workers. It adds only the
`travel_inbox_assignments` and `flight_shares` tables; existing trips, observations
and inbox identities are untouched. Downgrade refuses to discard retained data.

Configure `TROTTER_API_URL` (or deployed `BACKEND_URL`) to the public HTTPS API origin and `WEB_APP_URL` to the
web app that supports the flight-invitation fragment. Without a valid web URL,
the landing offers the native app path only. Existing custom-scheme support uses
`trotterv2://flight-share?token=…`. A newly installed app can also find the invitation
in Received after sign-in, without depending on deferred deep-link installation.

This implementation does not deploy a database migration, publish a new web
build, send invitations, or change real flight data by itself. Run the sharing,
inbox, booking-import and migration regressions before deployment.
