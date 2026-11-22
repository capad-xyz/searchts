# Firefox-family attach: WebDriver BiDi and Marionette research note

**Question:** can searchts attach to a Firefox-family browser (Firefox, Zen,
LibreWolf, Waterfox, Floorp, Mullvad) the user already has open, with the
profile they are signed in to, the way it attaches to Chromium over CDP?

**Answer: no, not for the stock running browser and its real profile.** The
Firefox family stays on cookie copy. This note records the reasons so the
shortcut is not attempted later without new evidence.

## Marionette

Marionette is Firefox's classic automation protocol. It is not on in a stock
release build:

- It has to be enabled at **process start**, with `--marionette` or with the
  `marionette.enabled` preference. There is no per-instance checkbox or
  runtime toggle equivalent to Chromium's
  `<browser>://inspect/#remote-debugging`.
- A running release Firefox cannot be switched into it after the fact.
  Writing the preference into the real profile only affects the *next*
  start, which is a write to the user's profile and a restart of the browser
  they are using.
- Starting a second Firefox with the same profile while one is running does
  not start a fresh process that honours the flag. Firefox's profile lock
  hands the launch to the existing instance, which was not started with
  Marionette, so there is no listening port to join.
- Even if it were reachable, Marionette is a full remote-control surface: it
  can navigate, execute privileged scripts and read every profile secret.
  That is a much larger blast radius than copying one site's cookies.

## WebDriver BiDi

Firefox ships WebDriver BiDi, and recent versions start its remote agent with
`--remote-debugging-port <port>` (a port of `0` writes the chosen endpoint to
`WebDriverBiDiServer.json` in the profile). It is a better protocol than
Marionette, but the lifecycle problem is the same:

- The remote agent is a **launch flag**, not an in-browser setting. A stock
  running Firefox has no agent to attach to.
- The single-instance profile lock applies here too. A second launch pointed
  at the real profile joins the existing process, which ignores the flag.
- Using a separate profile copy with the agent would work, but it is not the
  signed-in browser the user is looking at. It is the same "second client"
  pattern the cookie reader already avoids for Chromium, with the same stale
  session risk and the same need to copy the whole profile.
- BiDi can read cookies through the browser, but it can also do everything
  else a driver can do. Gating all of that behind a flag the user must add to
  a desktop shortcut is not a safe default for a read.

## What searchts does instead

- Firefox-family cookie stores are read **read-only** where the platform
  makes that possible, scoped to one registrable domain, with no decryption
  and no keychain prompt. On a platform where the store is encrypted, the
  copy path refuses and says why rather than escalating.
- A login wall offers a copy from an installed browser; nothing is copied
  without an explicit yes, and the exact command is printed when there is no
  terminal.
- Chromium keeps the CDP attach path because Chromium provides a per-instance
  opt-in (`Allow remote debugging for this browser instance`) that starts a
  loopback endpoint on the profile the user is already using.

If Firefox ever ships an equivalent per-instance, user-visible remote
debugging toggle for a stock profile, this note should be revisited. Until
then, cookie copy is the only path that does not require restarting the
user's browser or taking over the whole profile.
