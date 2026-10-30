# Sign-in and optional Gmail

Google sign-in and Gmail connection are separate. Dreams, Planner, saved trips and invitations require only the normal app session. Gmail is an optional connection for importing flight emails.

## Identity sign-in

`GET /auth/google/start?app_redirect_uri=...` requests only `openid profile email`. It does not request offline access, force Gmail consent or include previously granted scopes. Its callback verifies Google's identity token and verified email, creates or updates the app user, and issues the existing app JWT. No refresh token is needed. This path never creates or changes an `Account`, even if Google includes a previous Gmail grant in its response.

Web callbacks receive the app JWT in `#token=...`; native callbacks receive `?token=...`. A unique UUID `attempt` query is allowed and preserved. The client must match its own pending attempt before using the returned token.

## Explicit Gmail connection

Authenticated `POST /auth/google/gmail/start` accepts `{ "app_redirect_uri": "..." }` and returns `{ "url": "https://accounts.google.com/..." }`. Open this URL in a consent window. For web, use a same-origin popup so an in-progress plan stays in the original window.

The request adds only `https://www.googleapis.com/auth/gmail.readonly` to identity scopes, with offline access, consent and incremental authorization. Signed state binds the initiating app user ID, purpose, exact callback URI and a random attempt ID for ten minutes. Both new authorization flows send a Google nonce and verify that the signed ID token returns the same nonce. Google authorization codes remain one-use. Older pending identity states can finish within their existing ten-minute expiration.

Callback URLs may contain `flow=gmail&attempt=<UUID>`. Success preserves these fields and adds `gmail=connected`. Gmail connection never returns an app JWT, signs in a different user or changes the existing app session. Legacy Google users retain the same-account requirement. For an Apple account, this explicit consent can link an unclaimed, verified Google subject and email even when Apple uses a private relay address. It cannot replace an already linked Google subject or claim another Trotter user's email/identity. Connecting Gmail also makes that verified Google identity available for future sign-in to the same Trotter user.

Safe recoverable callback errors are `access_denied`, `gmail_permission_required`, `gmail_wrong_account`, `gmail_refresh_required` and `gmail_connect_failed`. The client keeps its original session on all errors and confirms the same user and `gmail_connected` via `/auth/me` after success. It may then explicitly start the first flight import. The callback does not queue a scan, and there is no recurring Gmail scan added by this change.

Only exact registered `/oauthredirect` callbacks on `WEB_APP_URL` and the known native schemes are accepted. Arbitrary paths, fragments, extra query fields and repeated query parameters are rejected. Local Expo callbacks require `DEV_MODE`. OAuth start and callback responses use `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.

## Connection state and scans

`GET /auth/me` retains `user_id`, `email`, `name` and adds:

```json
{"gmail_connected": false, "gmail_connection_status": "not_connected"}
```

`gmail_connection_status` is `not_connected`, `connected` or `needs_reconnect`. Legacy accounts remain connected when they have a stored refresh token and a Gmail-readable scope. This reports the most recently known authorization; external revocation is detected on the next Gmail request.

New connections require an actual returned readable Gmail scope and a refresh token. A repeated consent flow may omit a replacement refresh token; if the existing connection is still usable, its encrypted token and original scopes are preserved. Denied or incomplete consent does not overwrite an existing connection. Revoked connections require a new refresh token to reconnect.

Unavailable Gmail connections receive HTTP 409 from scan endpoints before any job is created:

```json
{"detail":{"code":"gmail_connection_required","message":"Connect Gmail to import your flights.","action":"connect_gmail"}}
```

The message says `Reconnect` for an existing unavailable connection. Queued imports also check consent before Gmail access. Revoked grants, 401s and insufficient-scope responses persist `needs_reconnect`; network, quota and provider configuration failures do not. An older job cannot mark a replaced credential disconnected. Existing flight data and encrypted credentials are preserved.

## Migration and verification

Apply `0021_optional_gmail_connection` after `0020_planner_transport_modes` before deploying code. It adds one nullable `accounts.gmail_connection_status VARCHAR(24)` column and changes no existing rows, credentials, scopes, plans or timestamps. NULL preserves the legacy consent representation. Downgrade refuses to discard known revoked-connection state.

Offline tests cover identity without Gmail/refresh, existing credential preservation, same-account linking, wrong-account rejection, denied and partial consent, nonce/state/redirect checks, private app access without Gmail, scan guards, worker revocation, stale job credential races and migration preservation. Provider consent itself still needs a real-account release smoke test; these tests do not make Google OAuth or Gmail requests.

## iPhone identity support

Apply additive migration `0022_ios_auth_identities` before deploying the iPhone account code. It adds `auth_identities`, `apple_auth_challenges` and `account_erasure_cleanup`, without rewriting existing users or credentials. Existing Google users acquire their verified provider subject on their next sign-in. All new provider lookups use `(provider, subject)`; matching email never silently links Apple to an existing Google account. Unique database constraints enforce one subject owner and one identity per provider per user.

Server configuration:

- `APPLE_CLIENT_ID`: the native iPhone bundle identifier (`com.trotter.mobilev2` unless deliberately changed).
- `APPLE_TEAM_ID` and `APPLE_KEY_ID`: Apple Developer identifiers for the Sign in with Apple key.
- `APPLE_PRIVATE_KEY_FILE`: path to the secret `.p8` key on the backend, or `APPLE_PRIVATE_KEY` through the deployment secret manager. Never place this in Expo public environment variables, an app bundle, or source control.
- Existing `ENCRYPTION_KEY` protects retained Apple refresh tokens. `JWT_SECRET` still signs Trotter app sessions.

Missing Apple configuration returns HTTP 503 `apple_signin_unavailable`; Google sign-in continues to work. Credentials and response bodies containing tokens must not be logged. Apply the deployment's normal authentication endpoint rate limits to `/auth/apple/challenge` and `/auth/apple` before external launch.

1. `POST /auth/apple/challenge` with `{ "purpose": "signin" }` returns `{ "challenge_id": "UUID", "nonce": "random", "expires_in": 300 }`.
2. Pass the nonce unchanged to Expo's native Apple authentication request. `state=challenge_id` should be checked on return by the client.
3. `POST /auth/apple` with `challenge_id`, `identity_token`, `authorization_code`, and optional first-login `name` returns the existing `{access_token,user_id,email,name}` shape.

Challenges expire after five minutes and are atomically consumed before Apple validation, including failed attempts. Retry with a fresh challenge. Verification uses Apple's fixed HTTPS JWKS endpoint, only RS256, exact issuer and configured audience, required expiry/issued-at/subject/nonce, and verified email when supplied. The authorization code must exchange successfully; its separately verified ID token must have the same subject and nonce. Refresh tokens are retained encrypted for account deletion. Repeated Apple sign-in uses the stable subject and does not overwrite the user's name from unauthenticated profile text.

To link Apple, sign in to the existing Trotter account first, then request `purpose:"link"` and send its Bearer on both requests. The session must be less than ten minutes old; otherwise HTTP 403 `reauthentication_required` asks the client to reauthenticate first. A legacy account without a stored provider subject must first reauthenticate with Google to preserve its original login. The first Gmail connection on an Apple-only account also requires recent authentication because it enrolls Google as a login method; ordinary Gmail reconnects are unchanged. Apple credentials already owned elsewhere return HTTP 409 `apple_account_already_linked`; an existing email requiring explicit sign-in/linking returns HTTP 409 `account_link_required`.

`GET /auth/me` now includes `auth_providers` (`["google"]`, `["apple"]`, or both). Email-bound Planner and flight invitations recognize current verified provider emails, falling back to the primary email only for unmigrated legacy users. A renamed Google email ceases to authorize invitations to the old address. Apple private-relay accounts can accept invitations sent to their explicitly linked Gmail address without weakening recipient checks.

## Reauthentication and account deletion

For Google, authenticated `POST /auth/google/reauth/start` accepts `{app_redirect_uri}` and returns `{url}`. A callback may include `flow=reauth&attempt=<UUID>` to distinguish a temporary reauthentication token from normal sign-in. The start endpoints reject flow labels belonging to another purpose. Its signed state binds the current user and callback. Callback issues a fresh app JWT only for the same existing Google identity; it never creates or switches accounts. Mismatch returns `error=reauth_wrong_account` in the original callback.

For Apple, use challenge `purpose:"reauth"` and the original Bearer for both Apple endpoints. The returned subject must already belong to this account; no linking or creation occurs. The client checks `/auth/me` with the fresh token and confirms the same user before using it for deletion or linking. It need not persist the temporary reauthentication JWT.

- `GET /auth/account/deletion-preview` returns `{owned_trips,shared_owned_trips}` for the confirmation screen.
- `DELETE /auth/account` takes `{confirmation:"DELETE"}` and a Bearer issued within ten minutes. Success is HTTP 204. An old session receives HTTP 403 `reauthentication_required`.
- Apple and Gmail refresh grants are revoked before erasure. Provider/network failure returns HTTP 503 `account_deletion_retry`, preserving the account and credentials for retry. A legacy missing Apple refresh token returns HTTP 409 `apple_reauthentication_required`.
- Erasure removes personal Dreams, flights, inbox evidence, memberships, votes, account credentials, invitations, and **all owned Planner trips, including shared trips**. The UI must explicitly warn that friends lose access to owned trips. Places already contributed into someone else's trip remain without the deleted user's attribution; historical member references are scrubbed. Old JWTs stop working because the user no longer exists.
- Thumbnail IDs enter a durable cleanup queue in the same transaction. The API immediately removes cached covers, and the Celery cleanup task retries for 24 hours to catch already-running thumbnail requests. Cleanup rows contain no email or provider credentials and are removed after the final grace-period sweep. Filesystem failure does not report an already-completed account deletion as failed.

Tests cover RSA signature and claims validation, one-time concurrent replay, identity collision/explicit linking, missing repeated email, private-relay Gmail linking, invite recipient isolation, bound reauthentication, foreign-key erasure, shared-trip consequences, revocation failure/retry, migration preservation and cached-cover cleanup. Apple services are mocked for offline tests; real Apple sign-in/link/reauth/revocation and Gmail consent remain release checks on the signed iPhone build.

References: [Apple user verification](https://developer.apple.com/documentation/signinwithapple/verifying-a-user), [Apple token validation](https://developer.apple.com/documentation/signinwithapplerestapi/generate-and-validate-tokens), [Apple account deletion and token revocation](https://developer.apple.com/documentation/technotes/tn3194-handling-account-deletions-and-revoking-tokens-for-sign-in-with-apple).
