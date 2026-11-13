# Local account sign-in and recovery

Existing passenger accounts and their report history are retained. Usernames are case insensitive and ignore accidental spaces around the username. Passwords remain exact and must not be trimmed or guessed.

A registration response of 409 means the username is taken. The account dialog now returns to sign-in, keeps the username, clears the registration password and explains the next step. A sign-in response of 401 means the supplied credentials were rejected. These responses remain meaningful HTTP errors; the app must not bypass authentication to hide them.

The dialog has a fixed header and close control, compact form spacing, password visibility controls, a Caps Lock hint and visible error messages. Rate limits remain enabled; the submit button honours the server's retry interval.

## Recover a local account

The installation owner can issue a private, single-use link from the repository folder:

```powershell
..\.venv\Scripts\python.exe -m backend.app.manage create-password-reset rashi_gupta
```

Use the Python environment configured for this installation if it is elsewhere. The command reads the same private configuration as the backend. Share its output only with that account's owner. The app does not expose a public API that issues recovery credentials: there is no verified email or phone recovery channel configured.

Open the printed link, enter a new password of 12–128 characters twice and then sign in normally. A code can also be entered under **Sign in → Forgot password?**. The link expires after 30 minutes and works once. Issuing another link invalidates its predecessor. Issuing a link does not change the existing password or revoke sessions; redeeming it changes the password and revokes all of that account's sessions. Password changes and administrator actions invalidate outstanding links. Disabled accounts cannot recover access this way.

Only a SHA-256 digest of the random 256-bit recovery credential is stored in `password_resets`. Recovery secrets travel in the URL fragment, are removed from the address bar when the app loads, are never stored by the frontend and are submitted only in the reset request body. The API checks the permitted origin, password length, expiry, account state and attempt limits. PostgreSQL row locks serialize recovery with account updates. Expired grants are removed by the worker. Passwords retain the existing Argon2id hashing policy.

Run the account/recovery and migration tests before applying migrations. Migration 0006 adds the recovery table without modifying existing accounts. Email or SMS recovery would require a verified delivery channel and separate configuration.
