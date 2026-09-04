# ISSUE-0055 — The record of what is built

Status: resolved
Type: AFK
Source: ISSUE-0049
Covers: the tooling and documents that still say voice is not built

Blocked by: 0053, 0054 · Blocks: —

> Small, and last, and not optional. Three of these files are *refusal records* —
> they exist so nobody builds a thing by momentum. Repealing one is a deliberate
> act and deserves its own diff, where a reviewer can see which refusal was
> lifted and which was left standing.

## What to build

### `tools/fidelity.mjs`

Line 154 loops `for (const word of ["code editor", "voice", "microphone"])`
asserting those words do **not** appear in the built surface. Drop `"voice"` and
`"microphone"`; keep `"code editor"`. Update the surrounding comment to say why
one left the list and one did not — it is a record of what we refused to build,
not a lint.

Line 62's `FUTURE` loses `07-voice-visit.html`, and line 169's
`FUTURE.length === 2` must become `=== 1` or the check silently prints nothing
forever.

Optional, and worth doing: add `/session/setup` to `SCREENS`, diffed against
`prototypes/interview-setup.prototype.html?variant=B&state=ready`. `PROTO()`
resolves `design-system/screens/`, so this needs a second resolver for
`prototypes/` and a `waitForTimeout` because the prototype renders through JS.
It is the one screen in this set with a drawn counterpart the tool can compare.

### `frontend/README.md`

The "## Not built" paragraph says the code editor and voice surfaces are future
surfaces with no endpoints, deliberately absent. Half of that is now false:

> The code editor is a future surface with no endpoint, deliberately absent so
> nobody builds it by momentum. Voice was that too, until ISSUE-0049: the
> Candidate speaks, the browser transcribes, and the turn reaches the API as text
> with `spoken: true`.

### `docs/issues/README.md`

The "Not in this set" section says screens 06 and 07 are future surfaces, and that
*"voice needs the Answer Turn boundary problem solved first."* It was solved by
variant A: the boundary is the Candidate pressing submit on a transcript they have
read. Say so, and leave the code editor's entry standing.

### `CONTEXT.md`

The **Answer Turn** entry anticipates this exactly — *"Voice (later) — genuinely
hard; pauses are not endings, and barge-in means the boundary can move
backwards."* Record how it was answered: the boundary is not inferred from the
audio at all. The Candidate stops the recording, reads the transcript, and
submits. Pauses end nothing, and there is no barge-in, because the examiner does
not speak.

### `tools/a11y.mjs`

It navigates straight to `/examination/{sid}` over the API, so it keeps working —
and headless Chromium denies the microphone, so it exercises the `denied`
fallback, where a textbox named `/answer/` exists. Add two assertions, because
ISSUE-0049's last criterion is otherwise unverified:

- the way to answer out loud announces what it does
- the composer's own state is announced, not only the toast host

### `tests/run.mjs`

Add `/session/setup` to `SWEPT` so the refusal sweep covers it like every other
route. (The hand-off changes and the console-error switch land in ISSUE-0053 and
0052, where they break.)

### `docs/issues/0049-the-answer-is-spoken.md`

Update it with every correction the slices found, so the next person to read it
does not re-derive them: the model is 172MB and the named repo does not exist;
`webgpu` + `q8` is broken; per-word confidence is not available; the clock
started at `POST /sessions`; and the Web Speech arm cannot claim the audio stays
on the machine. Mark it resolved, pointing at 0050–0055.

## Acceptance criteria

- [ ] `npm run fidelity` passes and no longer asserts voice is absent
- [ ] The code editor's refusal is still asserted, and the comment says why
- [ ] `FUTURE.length` and its message agree
- [ ] `README.md`, `docs/issues/README.md` and `CONTEXT.md` describe what is built
- [ ] `CONTEXT.md` records how the Answer Turn boundary was answered, not just that it was
- [ ] `npm run a11y` verifies that the voice states announce themselves
- [ ] `/session/setup` is in the refusal sweep
- [ ] ISSUE-0049 carries every correction and is marked resolved
- [ ] `npm run verify`, `test:e2e`, `a11y`, `audit` and `fidelity` all green
