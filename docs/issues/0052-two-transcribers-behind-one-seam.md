# ISSUE-0052 — Two transcribers behind one seam

Status: open
Type: **HITL** — the model is chosen by a measurement that has not been taken
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
exported constant, so the measurement below can change it in one line.

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

## Why HITL

**Two measurements have to be taken before this can be called done**, and both
change what ships:

1. **Term-level accuracy.** `whisper-base.en` is a *smaller* model than
   `distil-small.en`, so it will be worse on technical vocabulary — the axis
   ISSUE-0049 says matters most, because Coverage reads whether a Topic was
   addressed and a mistranscribed term is a Topic the record says was missed.
   Record 20 answers containing real Topic terms from three Modules, run both
   models, count term-level errors. The model id is one constant; if base is
   materially worse, take the 172MB and make the slow path better instead.
2. **Inference latency.** A 40-second answer on single-threaded wasm is plausibly
   8–20 seconds. ISSUE-0054's copy says "A few seconds." If the real number is
   fifteen, that copy is a lie and the state needs a meter. **Set the copy from
   the measurement**, not the other way round.

Record both in the commit message.

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
- [ ] Term-level accuracy and inference latency are measured, and the numbers are in the commit message
- [ ] `npm run verify` green
