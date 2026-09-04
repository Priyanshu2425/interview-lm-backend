# ISSUE-0054 — Answering out loud

Status: resolved
Type: AFK
Source: ISSUE-0049 · prototype `frontend/prototypes/voice-answer.prototype.html?variant=A`
Covers: the composer, once an Answer Turn can be spoken

Blocked by: 0050, 0051, 0052 · Blocks: 0055

## What to build

Press, speak, stop, transcribe, **read it back**, submit.

The confirmation step is the whole design. Whisper gets technical vocabulary
wrong in a way that is invisible to the person who said it — "PyTorch" comes back
"pie torch", "ReLU" comes back "rely you" — and this Session is graded on that
text, Topic by Topic, at the end. **Coverage is a reading of whether a Topic was
addressed at all**, so a mistranscribed term is a Topic the Candidate covered and
the record says they did not, and they never find out. The editable box is the
only thing standing between that and a false negative in the one measurement this
product exists to make.

### Component breakdown

```
Composer.tsx        UNCHANGED — the typing mode, and the fallback
AnswerComposer.tsx  picks on useDictationStore(s => s.mode)
VoiceComposer.tsx   the speak surface and the mode switch
MicButton.tsx       the circle, its two states, the halo
LevelMeter.tsx      imperative, ref-driven, no React state
ReviewBox.tsx       the editable transcript and submit
```

`ExaminationScreen` changes by one expression. **`Composer.tsx` being unmodified
in the diff is the review checkpoint for this slice** — add a `Composer.test.tsx`
regression fence if none exists, because everything here rests on it.

### The states

From the prototype's list: `warming` · `idle` · `listening` · `transcribing` ·
`review` · `sending` · `silent` · `denied`. All state on `data-*` attributes.

`warming` is the rare one — setup normally finishes the model before the clock
starts, so a Candidate who sees this either skipped setup or the first question
outran the download. **It does not mention megabytes**: they are mid-examination,
and the only fact that helps them is that they can type this one right now. So
the primary button in that state is "Type this answer", not a progress bar to
watch.

`silent` distinguishes the two silences the engine reports (ISSUE-0052): nothing
reached the microphone, versus the room came through and speech did not. Nothing
is sent in either case and the question is unchanged.

`denied` renders the typing composer inline, plus "Try the microphone again". The
Session is fine.

### The transcribing state takes longer than the prototype claims

Measured in a browser (ISSUE-0052): **0.37–0.45× realtime**. A forty-second
answer is fifteen to twenty seconds of waiting, and more on a slower machine.

The prototype says *"A few seconds."* That is false, and a false wait is worse
than a long one — the Candidate starts wondering whether the button worked.
Say something they can hold us to:

> Writing down what you said. This takes about half as long as you spoke for.

### Two corrections to the prototype

**Replace `contenteditable role="textbox"` with a real `<textarea id="answer">`.**
Three reasons: `tests/run.mjs` does `p.fill("#answer", …)`; contenteditable has
genuinely bad IME and undo behaviour, which in a graded examination is not a
cosmetic problem; and with `marks: []` there is nothing for rich markup to render
anyway. When per-word marking becomes possible, the technique is an `aria-hidden`
mirror div under a transparent-text textarea — the textarea survives either way.

**Drop the confidence caption.** "Two words are underlined because the model was
unsure of them" claims a measurement the surface does not have and cannot get
(ISSUE-0052). Replace with copy that claims only what is true:

> It grades what is written here, not what you remember saying. Technical terms
> are what it gets wrong — read those.

### Accessibility, because `tools/a11y.mjs` enforces it

The tool asserts that every `button|link|textbox|checkbox|combobox` has a
non-empty accessible name, and that some textbox is named `/answer|response/i`.

- The mic gets `aria-label={listening ? "Stop and transcribe" : "Start speaking"}`
  with `aria-pressed`, and "Record again" for the redo.
- The mode switch is a `role="group" aria-label="How you answer"` of two
  `aria-pressed` buttons.
- A dedicated `role="status" aria-live="polite"` region inside `.composer` carries
  one sentence per state — "Listening.", "Writing down what you said.",
  "Transcribed — read it back before sending.", "Nothing was heard." `ToastHost`
  already satisfies the tool's live-region check globally, so this is for the
  Candidate rather than for the tool. `denied` and `silent` get `role="alert"`.

### Keyboard

`tests/run.mjs` has a keyboard-only block: it focuses the textarea, types, then
tabs to `Send|Submit|Answer` within a 20-tab budget. Keep `⌘↵` — it stops
recording while listening, and submits in `review`. Space-to-talk binds to the mic
button only, **never** to the document: a document-level Space handler on a screen
with a textarea is a bug waiting to happen.

### `spoken` reaches the API

`useExamination.submit` gains a second parameter — `submit(answer: string, spoken = false)` —
threading to `sessionService.submitTurn(…, spoken)`. The default keeps
`Composer.tsx`'s call site and every existing test valid.

`spoken` is **true even when the Candidate edited the transcript**, because it is
still a machine's reading of a voice, which is exactly the audit question the
field exists to answer (ISSUE-0050). It is false only when they typed from
scratch.

### What the surface must not do

- No word count, no "that seems short", no confidence figure presented as a
  quality. The surface computes nothing about the answer.
- Nothing is sent while listening. An Answer Turn is a deliberate act.
- The privacy claim matches the engine that actually ran (ISSUE-0052), in the
  composer as well as on the setup screen.

## Acceptance criteria

- [ ] A Candidate can answer by speaking, and the turn reaches the API as text
- [ ] Nothing is submitted that the Candidate has not seen in an editable field
- [ ] The turn records `spoken`, including when the transcript was edited first
- [ ] `Composer.tsx` is unmodified
- [ ] Typing is reachable from every state, including `warming`
- [ ] A refused microphone leaves the Session usable and says what happened
- [ ] The two silences are told apart, and neither sends anything
- [ ] The transcribing state's copy matches the measured 0.37–0.45× realtime
- [ ] `#answer` is a real `<textarea>` with an accessible name matching `/answer/i`
- [ ] Every control announces a name, and every state announces itself
- [ ] The keyboard-only path still reaches submit within the tab budget
- [ ] No word count, no percentage, no confidence figure anywhere in the composer
- [ ] The engine and its privacy claim agree
- [ ] `npm run verify`, `npm run test:e2e` and `npm run a11y` green
