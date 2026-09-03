# ISSUE-0053 — Setting up the interview

Status: open
Type: AFK
Source: ISSUE-0049 · prototype `frontend/prototypes/interview-setup.prototype.html?variant=B`
Covers: the screen between Begin on `/session/new` and the first question

Blocked by: 0050, 0051, 0052 · Blocks: —

## What to build

A screen at **`/session/setup`**, a sibling of `/welcome` inside
`RequireOnboarding` and **outside `RootLayout`**. The routing comment already
there states the argument this screen reuses: a nav rail around a screen you are
meant to sit through is an invitation to leave it half-done — and here half-done
means a Session that is started, paid for and abandoned.

It must **not** use `PageHeader`, which calls `useShell()` and only resolves
inside `AppShell`. Hand-roll the header the way `AuthShell` does. It is **not**
lazy: it is on the critical path of every Session, and a chunk fetch would add a
round-trip to the screen that exists to remove waiting.

### Why the screen exists

The model download used to live in the composer, which appears with the first
question — by which time the clock is running, so a Candidate would spend the
opening seconds of a timed examination watching a progress bar. And it described
itself in our words: "Downloading model — 60MB" is our problem. Nobody sitting an
interview has a view about a model. They are waiting for the interview to be
ready, and that is what the screen says.

That is not permission to hide it. A friendly sentence over a silent 77MB
download is fine on fast wifi and a lie on slow, where it becomes a bar that never
moves with no reason given. **Plain language in the headline, the real detail one
disclosure away, and the network named the moment it is the cause.**

### The hand-off

`/session/new`'s Begin navigates to `/session/setup` with `StartInput` in
`location.state`, and `POST /v1/sessions` fires **there**, in flight.
`useStartSession` stops navigating and stops calling `remember()`; both move here.
A mutation hook that navigates is doing two jobs.

The alternative — navigate after the POST — means the Candidate stares at a frozen
`/session/new` for the whole slow synchronous call, which is today's behaviour and
exactly what step 1 exists to make visible. A check that is already green on first
paint checks nothing, and "the screen already says which of the three it was" is
the whole argument for this variant.

Two guards, both load-bearing:

- A reload without `location.state` redirects to `/session/new`. Nothing is lost:
  a reload before the Session exists loses nothing, and after it exists it is the
  running-Session case `useLatestRunningSession` already handles.
- The mutation fires from a `useRef` once-guard, because `POST /sessions` is not
  idempotent and StrictMode double-invokes effects. Say in the comment that this
  guard is load-bearing rather than defensive, or somebody will remove it.

### The three checks

`useInterviewSetup(input)` returns a `SetupState`; the screen splits into
`InterviewSetupScreen` (calls the hook) and `SetupBody` (pure, takes the state),
so the body is testable with hand-built props.

| step | driven by | fails when |
|---|---|---|
| 1 · Fixing the plan | the in-flight `POST /v1/sessions` | **the only fatal one** — render `ErrorState` from the API's own `message` |
| 2 · Checking your microphone | `getUserMedia({audio:true})`, then **immediately `track.stop()`** | `NotAllowedError`, `NotFoundError`, or an insecure context |
| 3 · Getting ready to hear you | `transcriber.prepare()` — a download on the Whisper arm, a capability check on Web Speech | any error |

All three run in parallel; the *display* is sequential — the "now" step is the
first unsettled one — which is what the drawing shows. Step 2 asks for permission
and then **lets go of the device**: holding the stream from here through a
50-minute Session would leave the recording indicator lit the whole time.

**Failure fall-through is structural, not copy.**
`ready = steps.every(s => s === "done" || s === "fail")`. A `fail` enables Begin
exactly as a `done` does, and forces the composer's mode to `type`. Only step 1
failing blocks, because there is no Session to enter. The rule from ISSUE-0049 —
*setup is never the reason somebody cannot sit their interview* — is enforced by
that one expression rather than by a sentence anybody can drift away from.

### Beginning

The Begin button calls `POST /v1/sessions/{id}/begin` (ISSUE-0050), then navigates
with `replace: true`. **Nothing auto-starts.** A clock that starts while the
Candidate is looking at their phone is a clock they lost.

### Copy

Verbatim from the prototype. Steps: *"Fixing the plan" / "What you will be asked
is decided once, now, and never changes."* · *"Checking your microphone" / "Asked
for here so a permission box never lands on a running clock."* · *"Getting ready
to hear you" / "A one-time setup on this machine. Instant every time after this."*

Headlines: `"This takes a few seconds."` → `"Everything is set. Begin when you
are."` / `"You will be typing."` / `"Nearly there — your connection is slow
today."`

The ready-state line *"The clock starts on the first question, not now"* is true
once ISSUE-0050 lands, so it stays.

The footer privacy line is **per-engine** (ISSUE-0052) and must be present in
every state — it is ISSUE-0049's "the screen says so" criterion. On the Whisper
arm it says nothing is uploaded. On the Web Speech arm it must say the audio is
sent to the browser's vendor to be transcribed, in the same place and the same
size.

The `<details>What is happening</details>` disclosure — plan, microphone, speech
model, runs on, uploaded, throughput — is the "real detail one disclosure away"
criterion. **Every row is computed, including the megabytes**, which come from
summed `progress` totals. A hard-coded figure is how the ticket ended up claiming
60MB for a 172MB model.

`facts()` — Questions, Time, Scope — builds from the `POST /sessions` response and
the input. If the response carries no question count, render Time and Scope and
leave it out rather than inventing one. Do not fetch the plan here: it adds a
request to the critical path and a 404 is a legitimate answer for some Sessions.

**Slow-network detection:** trailing-5s throughput under ~250KB/s **and** elapsed
over 6s. Two conditions, so a burst-then-stall on a fast line does not tell
somebody their connection is slow. Then the wrapper gets `data-stalled` and "Begin
now and type" becomes the primary button.

### iOS

`getUserMedia` on iOS Safari requires a **user gesture**, and step 2 fires from an
effect. On iOS, step 2 must be a button — "Check my microphone" — rather than an
automatic check. The design does not currently have that branch; add it, and say
why in the comment.

## Acceptance criteria

- [ ] `/session/setup` renders outside the shell, with no nav rail
- [ ] `POST /sessions` is in flight on the screen, and fires exactly once under StrictMode
- [ ] A reload without state returns to `/session/new` rather than erroring
- [ ] The three steps show wait / now / done / fail, and the "now" step is the first unsettled one
- [ ] A refused microphone still enables Begin, and forces typing mode
- [ ] A failed model still enables Begin, and forces typing mode
- [ ] A failed `POST /sessions` blocks, and shows the API's own message
- [ ] The privacy line is present in every state and matches the engine that will run
- [ ] Every figure in the disclosure is computed; no megabyte count is hard-coded
- [ ] A slow connection is named as the cause, and "Begin now and type" becomes primary
- [ ] The Session never begins on its own
- [ ] Begin stamps the clock before navigating; a Session sat on for two minutes still gets its full duration
- [ ] On iOS the microphone check is a button, not an effect
- [ ] `npm run verify` and `npm run test:e2e` green
