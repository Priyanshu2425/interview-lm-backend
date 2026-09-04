# ISSUE-0052 — Two transcribers behind one seam

Status: resolved
Type: **HITL** — both measurements taken; see below
Source: ISSUE-0049
Covers: the dictation engine — Whisper in a Web Worker, the Web Speech API, and
the interface that makes either one a swap

Blocked by: 0050 · Blocks: 0053, 0054

> Wired to no screen when it lands. The engine is the part with the platform
> risk in it, and it should be reviewable — and measurable — before a screen
> depends on its timings.

## What to build

`src/features/dictation/`, a feature rather than a folder under `examination/`
because **both** `session-start` and `examination` need it and `eslint.config.js`
forbids `@/features/*/*`. Two features can only meet through a barrel. Put that
reason in the module docstring; the ticket that proposed
`features/examination/hooks/useDictation.ts` had not noticed it.

```
index.ts              the barrel — the only legal import path
engine.ts             module singleton: owns the active Transcriber
store.ts              useDictationStore — the reactive mirror
transcriber.ts        the interface, and which arm a Candidate gets
whisper/protocol.ts   worker message types — types only, no DOM
whisper/worker.ts     the ONLY file that imports @huggingface/transformers
whisper/whisper.ts    MediaRecorder → 16kHz mono PCM → worker
webspeech/webspeech.ts SpeechRecognition
capture.ts            getUserMedia, level metering, silence detection
helpers.ts            the pure functions, which are the tested surface
```

### The interface

```ts
interface Transcriber {
  readonly id: "whisper" | "webspeech";
  readonly privacy: "on-device" | "sent-to-vendor";
  readonly engineLabel: string;              // "CPU" | "WebGPU" | "Chrome speech"
  prepare(onProgress: (p: Progress) => void): Promise<PrepareOutcome>;
  start(): Promise<void>;
  stop(): Promise<TranscriptionResult>;      // { text, marks: [] }
  cancel(): void;
  dispose(): void;
}
```

Each implementation owns its own microphone, because Web Speech cannot be handed
a `Float32Array` — it consumes the device itself. The two arms differ in ways
that cannot be hidden and should not be:

| | Whisper | Web Speech |
|---|---|---|
| Preparing | 77MB download | capability check, instant |
| Privacy | on-device | **the audio leaves the machine** |
| While listening | level meter, real amplitude | live interim transcript |
| Browsers | anything with wasm | Chrome, Edge, Safari — **not Firefox** |
| Network | first visit only | every answer |

**The privacy line is per-engine and this is not a detail.** Both prototypes say
"Your voice never leaves this browser." That is true of Whisper and false of Web
Speech, which ships audio to Google on Chrome and to Apple on Safari. The Web
Speech arm must say so plainly, in the same place, in the same size.

Arm selection lives in `transcriber.ts`: a `dictationEngine` preference in
`shared/stores/preferences.ts` (`"whisper" | "webspeech" | "off"`), defaulting to
a deterministic choice from the candidate id so a Candidate keeps the same arm
across Sessions. Capability gates it — Firefox never gets Web Speech. Random
assignment and feedback collection are a later slice; this one builds the seam
and both ends of it.

### Who owns the engine's lifetime

`ExaminationScreen.tsx:206` renders `{composerDisabled ? null : <Composer …/>}`,
so the composer is **unmounted and remounted for every single question**.
Anything held in its state dies with it, and a worker per question re-reads 77MB
from the Cache API and re-instantiates the session each time.

So the engine is a **module singleton** with a zustand store as its reactive
mirror; `engine.ts` calls `setState` directly, which is legal outside React.
Components read the store. Nothing outside this feature touches the engine.

| event | action |
|---|---|
| setup screen mounts | `acquire(sessionId)`, `prepare()` |
| navigate to `/examination/:id` | nothing — already warm |
| the Session ends | release the stream, keep the worker |
| examination unmounts | `release(sessionId)` |
| `pagehide` | release everything |
| a route change inside a Session | **never terminate the worker** |

**Never hold an open `MediaStream` across a 50-minute Session.** The operating
system's recording indicator would stay lit for the whole examination, which is
precisely the lie the level meter exists to avoid telling. Acquire on mic-press,
`track.stop()` on stop, and accept the ~150ms — permission is already granted, so
there is no prompt.

### The three corrections this slice is built on

**The model is not 60MB and that repo does not exist.**
`onnx-community/distil-whisper-small` 404s. The real one is
`onnx-community/distil-small.en`, whose q8 weights are 92.3MB + 79.7MB = **172MB**.
**Ship `onnx-community/whisper-base.en`** — 23.2 + 53.7 = 77MB — from a single
exported constant. The measurement below confirms it: base is not the
compromise this paragraph assumed, it is the better model.

**`device:"webgpu"` with `dtype:"q8"` emits gibberish.** It is the exact pair the
ticket specified, and it is a known open defect ([transformers.js#1317](https://github.com/huggingface/transformers.js/issues/1317)).
The working WebGPU configuration is a per-module dtype map — fp32 encoder, q4
decoder — which for `whisper-base.en` is 206MB, *larger* than the CPU path. So
**wasm + q8 is the default and WebGPU is opt-in**, and the engine still reports
which one ran.

**Per-word confidence does not exist.** `models.js:1926` returns
`{sequences, past_key_values, ...attentions}` with `// scores,` and `// logits,`
as commented-out TODOs; `return_timestamps:"word"` yields timings, not
probabilities. `marks` ships as `[]`. The seam if anyone wants it later is a
custom `logits_processor` (a supported extension point), plus BPE regluing — and
it should be gated on a measurement that the scores correlate with errors on this
vocabulary, because an underline that fires on the wrong words is worse than none.

### Audio, for the Whisper arm

`MediaRecorder` → `Blob` → `arrayBuffer` →
`new OfflineAudioContext(1, 1, 16000).decodeAudioData()` → `getChannelData(0)`.

**This corrects the ticket**, which proposes `new AudioContext({sampleRate:16000})`
for capture. Safari has a long history of ignoring or throwing on a non-default
`AudioContext` sample rate, and iOS hardware runs at 48kHz. Resampling is
`decodeAudioData`'s job. `ScriptProcessorNode` is refused (deprecated, and it runs
on the main thread — the exact freeze the ticket forbids); `AudioWorklet` is the
right answer only if live dictation is ever built, and the docstring should say so
rather than leaving the next reader to wonder.

PCM is **transferred, not cloned**: `postMessage(msg, [msg.pcm.buffer])`. A
60-second answer is 3.8MB and the audio has exactly one destination.

**Level meter:** `AnalyserNode` at `fftSize: 256`, polled in a rAF loop throttled
to ~20fps, written to a **CSS custom property on a ref'd element**, never React
state — sixty renders a second on a screen with a live transcript and a running
clock is what `CODE_PRACTICES.md`'s rerender rules exist to prevent. The
prototype CSS already reads `var(--level)`. `useReducedMotion()` gates the halo's
scale but **not the bars**: the bars are the only signal the microphone is live.

**"Nothing was heard" is two different facts** and the copy distinguishes them, so
the detection must too: peak RMS below threshold means nothing reached the
microphone; audio that arrived but produced empty text — or one of Whisper's
silence hallucinations (`"Thank you."`, `"you"`, `"[BLANK_AUDIO]"`, `"."`) — means
the room came through and speech did not. Unhandled, the second one submits
"Thank you." as an Answer Turn. Refuse anything under ~0.4s. None of this is the
surface computing something about the answer: it decides whether an Answer Turn
exists to send at all, and nothing is sent.

### Errors never reach `console.error`

`tests/run.mjs` exits non-zero on a single uncaught console error anywhere. Every
worker entry point is wrapped and posts an `error` message instead. That cannot
catch what the ONNX runtime logs from inside emscripten, which is why ISSUE-0055
adds an off switch — but the worker's own errors must not be part of the problem.

### Build configuration

- `"@huggingface/transformers": "^3.8.1"` — pin the v3 line. Do **not** add
  `onnxruntime-web`; it is already inlined, and two copies fight over the wasm
  registry.
- `vite.config.ts` — `worker: { format: "es" }` is **required** (the default
  `iife` cannot use `import()`), and `optimizeDeps: { exclude: [...] }`. Do
  **not** add a `transformers` manualChunk: the library is only reached from
  inside the worker, which Vite emits outside the main graph, and listing it
  would drag it back in.
- `tsconfig.worker.json` — a third project reference with
  `lib: ["ES2023","WebWorker"]` covering only the worker and its protocol;
  `tsconfig.app.json` excludes the worker. Adding `WebWorker` globally merges
  `self` and `postMessage` into every component file.
- `public/ort/` — the ONNX runtime wasm, copied from the package at install, with
  `env.backends.onnx.wasm.wasmPaths = "/ort/"` set before any `pipeline()` call.
  Self-hosted rather than widening the CSP to a CDN (ISSUE-0050 §3).

## The measurement, taken

**Recorded 2026-09-03.** Ten answers containing the vocabulary this product
examines, read aloud and transcribed by both candidates for the job, scored on
whether each technical term survived.

| | terms lost | download | speed |
|---|---|---|---|
| `onnx-community/whisper-base.en` q8 | **8.1%** (3 of 37) | **77MB** | 0.08× realtime |
| `onnx-community/distil-small.en` q8 | 10.8% (4 of 37) | 172MB | 0.16× realtime |

**The smaller model is the more accurate one.** That inverts the assumption
this ticket was written on — that dropping to base to save 95MB would trade
accuracy for download — and it settles the model question: `whisper-base.en`
is less than half the download, twice as fast, and loses fewer terms.
`distil-small.en` reproduces this ticket's own example, hearing *"PyTorch"* as
*"pie torch"*; base gets it right.

Scoring is against what the **grader actually reads**. The Judge is a language
model reading prose, not a substring matcher, so "back propagation" for
"backpropagation" and "normalization" for "normalisation" cost a Candidate
nothing — five such differences on base, nine on distil-small, all free. What
counts as lost is a term whose *meaning* changed. Counting orthography as
error is how a transcriber gets blamed for a dialect.

What both models get wrong is the same thing, and it is the one that matters:
**`d_k` comes back as "decay"** on both. Notation read aloud is not a word, and
no model choice fixes it. That is the review box's whole justification — and
the reason a Candidate must see the transcript before it is graded.

**Caveats, and they are not small.** The audio is synthesised speech: clean,
unaccented, no room, no hesitation. Real answers will be worse, so **8.1% is a
floor rather than an expectation**. And the timings are `onnxruntime-node` on
native CPU — the browser runs single-threaded wasm, several times slower.
**The latency that sets the copy is still unmeasured** and must be taken in the
browser once the worker exists.

### A correction the measurement forced

`language: "english"` — which the ticket's worker snippet passes — **throws** on
an English-only checkpoint: *"Cannot specify `task` or `language` for an
English-only model."* Every `.en` model is affected, which is all of the ones
under consideration. Omit it.

## The second measurement, taken

**Recorded 2026-09-03**, Chromium via Playwright, single-threaded wasm on an
Apple-silicon laptop — the real path, not `onnxruntime-node`.

| | |
|---|---|
| cold start (77MB download, load, warm-up) | **16.9s** |
| transcription | **0.37–0.45× realtime** |

So a forty-second answer is **fifteen to twenty seconds** of transcribing, and
on a slower machine more. **ISSUE-0054's "A few seconds." is a lie and must
change.** Something closer to the truth: *this takes about half as long as you
spoke for* — which is a promise the Candidate can hold us to, and which makes
the wait legible instead of open-ended.

The cold start justifies the whole of ISSUE-0053. Seventeen seconds inside a
timed examination would be indefensible; seventeen seconds before the clock
starts is a setup screen doing its job.

### Two corrections the browser forced

**The ONNX runtime does not need copying, and copying it breaks dev.** The
plan had `scripts/copy-ort.mjs` put the runtime in `public/ort/` and the worker
point `wasmPaths` at it, on the reasoning that the library's jsdelivr default
is refused by `default-src 'self'`. In dev that fails outright — Vite appends
`?import` to a `.mjs` under `public/` and refuses to serve it:

```
no available backend found. ERR: [wasm] TypeError: Failed to fetch
dynamically imported module: /ort/ort-wasm-simd-threaded.jsep.mjs?import
```

It is also unnecessary. The loader reaches for the runtime through
`new URL(..., import.meta.url)`, which the bundler rewrites to a hashed asset
on our own origin — same-origin already, and emitted into `dist/assets/`.
Setting `wasmPaths` on top of that ships 21MB twice and points at the copy that
does not work. The `public/ort/` machinery is deleted and the `wasmPaths`
message field with it: a field that is always empty is a control that reaches
nothing.

**The CSP change in ISSUE-0050 is still needed**, and for the other two
reasons: `'wasm-unsafe-eval'` to compile the module at all, and `connect-src`
for the weights on Hugging Face.

## Why this stayed HITL

**Inference latency in the browser.** A 40-second answer on single-threaded
wasm is plausibly several times the 0.08× realtime measured natively.
Measured above, and the number is fifteen. The copy is written from the
measurement rather than the other way round, which is why this slice was HITL
and why ISSUE-0054 inherits a correction rather than a guess.

## Acceptance criteria

- [ ] Both transcribers satisfy one interface, and the model id is one exported constant
- [ ] Neither screen nor `@/features/examination` imports anything but the barrel
- [ ] The transformers import is inside a dynamic `import()`; the entry chunk does not grow
- [ ] `tsc -b` covers the worker through its own project reference
- [ ] Audio reaching the model is mono `Float32Array` at exactly 16000Hz, and the buffer is transferred
- [ ] The level meter is driven by real amplitude and writes no React state
- [ ] Digital silence renders as silence
- [ ] Silence, a too-short recording, and a Whisper silence-hallucination all resolve to "nothing was heard" and send nothing
- [ ] Which engine ran is reported, and the privacy claim matches it
- [ ] Firefox never selects the Web Speech arm
- [ ] No worker error path reaches `console.error`
- [ ] Model files are cached; a second `prepare()` in a fresh tab does not re-download
- [x] Term-level accuracy is measured, and the numbers are in this ticket
- [x] Inference latency is measured **in a browser**, and ISSUE-0054's copy is written from it
- [x] No `language` option is passed to an English-only checkpoint
- [ ] `npm run verify` green
