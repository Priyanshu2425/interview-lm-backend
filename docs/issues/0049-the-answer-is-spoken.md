# ISSUE-0049 — The answer is spoken

Status: proposed — needs a human signature on §"Two decisions that are not ours"
Type: surface
Source: none — asked for directly
Covers: how a Candidate gives an Answer Turn

> Prototype: `frontend/prototypes/voice-answer.prototype.html` — three variants,
> `?variant=A|B|C`, every state on the keys `1`–`0`. Nothing here is settled until
> one of them is picked.

## What to build

A Candidate answers by talking. Speech is transcribed **in the browser** by
Distil-Whisper under Transformers.js, and the Answer Turn is submitted as text.

The API does not change. `POST /v1/sessions/{session_id}/turns` already takes
text, and it takes text after this — the microphone is a way of filling a
field, not a new kind of turn. One field is added, and only one:

```
{ "answer": "...", "spoken": true }
```

`spoken` exists because grading is done on the text and the text is now a
machine's reading of a voice. A low Mastery on a Topic answered out loud and a
low Mastery on a Topic answered by typing are not the same evidence, and an
audit that cannot tell them apart cannot find a transcription problem. It is
recorded on the turn and reported; nothing weights on it.

Typing does not go away. It is the fallback for a refused microphone, a failed
model load, a noisy room, a 60MB download somebody will not wait for, and for
anybody who cannot or will not speak aloud. **"Substitute" means the default,
not the only way** — a graded examination that can only be sat by speaking is
one a deaf or non-speaking Candidate cannot sit at all.

## Why this is not just a mic button

The interesting decision is not the control. It is **who owns the words between
the mouth and the grader**, and the three prototype variants are three answers:

| | What happens when they stop talking |
|---|---|
| **A** | The transcript lands in an editable box. Nothing is sent until the Candidate agrees it is what they said. |
| **B** | Words stream in while they speak; the same confirmation at the end. |
| **C** | It transcribes and submits itself, with a short window to pull it back. |

The risk that decides between them: Distil-Whisper small at 8-bit gets
technical vocabulary wrong in a way that is **invisible to the person who said
it**. "PyTorch" comes back "pie torch". "logits" comes back "logics". "ReLU"
comes back "rely you". This Session is graded on that text, Topic by Topic, at
the end (ISSUE-0045) — and **Coverage is a reading of whether a Topic was
addressed at all**. A mistranscribed term is a Topic the Candidate covered and
the record says they did not, and they never find out.

That is a false negative in the one measurement this product exists to make,
and it is the argument for A: a confirmation step the Candidate cannot skip,
with low-confidence words marked so they know where to look.

**Recommendation: A**, with B's streaming added later if the confirmation step
proves to be the thing people dislike. C is the one that feels most like an
interview and the one that can send a misheard term to the grader unread; it
should not ship first.

## The states, and what each one owes the Candidate

Every variant has to answer all of these. Naming them is most of the work.

- **Model downloading** — 60MB, first visit, roughly ten seconds. The composer
  says so, shows real progress, and offers typing as the way through. Nobody
  mid-Session waits on a progress bar with a clock running.
- **Ready** — cached, warm, nothing said yet.
- **Listening** — a level meter driven by real amplitude, not a timer. A ring
  that pulses on its own says "recording" even when the microphone is muted at
  the OS, which is a lie the Candidate finds out about a minute later.
- **Transcribing** — the model is working. Nothing has been sent.
- **Transcribed** — the text, editable, with low-confidence words marked.
- **Nothing was heard** — the room came through and no speech did. Nothing is
  sent, the question is unchanged, and it says which of those two is true.
- **Microphone refused** — the browser will not give it up. The Session is
  fine; type this one.
- **Typing** — the fallback, one click away at all times.

## Shape of the implementation

```
src/features/examination/
  components/VoiceComposer.tsx     the control and its states
  components/Composer.tsx          unchanged, and the fallback
  hooks/useDictation.ts            worker lifecycle, capture, level meter
  dictation/worker.ts              the model; nothing else imports it
```

Rules the tree already enforces and this obeys:

- **The worker is the only thing that touches the model.** Inference on the
  main thread freezes the interface for both the download and the run, and the
  screen it freezes is the one with a Session clock on it.
- **The audio is a `Float32Array`, mono, at exactly 16kHz.** Whisper takes
  nothing else. `new AudioContext({ sampleRate: 16000 })` does the resample;
  `getChannelData(0)` takes the first channel and the rest are discarded.
- **The worker is created once, per Session, not per turn.** A worker per
  answer reloads the model from the Cache API on every question — fast, but not
  free, and it is a hitch at exactly the wrong moment.
- **`device: "webgpu"`, `dtype: "q8"`, and a fall back to `wasm`** where WebGPU
  is missing. It is slower on the CPU and it works. Which one ran is shown,
  because "why was that slow" is a question worth being able to answer.

Everything else follows `CODE_PRACTICES.md`: the feature owns its hook, the
hook owns the worker, the screen knows only that a string arrived.

## What the surface must not do

- **No transcription is graded that the Candidate has not seen** (variant A/B).
  If C wins instead, the undo window is the confirmation, and it is long enough
  to read the sentence.
- **The surface computes nothing about the answer.** No word count, no "that
  seems short", no confidence figure presented as a quality. Low-confidence
  marking is a hint to look at a word, and it is described as one.
- **Nothing is auto-sent while listening.** An Answer Turn is a deliberate act.
- **The audio never leaves the browser** and the screen says so, because a
  microphone in an examination is a thing people are right to ask about.

## Two decisions that are not ours

**Is the audio kept?** Right now nothing leaves the browser, so there is no
recording to appeal a bad transcription against — and no recording for anybody
else to ask us for either. That is a privacy win and an evidence loss at the
same time, and it is a product call.

**Is the browser the right place for this at all?** Client-side is free, private
and offline. It is also the smallest Whisper we can ship and the one worst at
the vocabulary this product exists to examine. A server transcription costs
money per minute and sends a Candidate's voice off their machine, and it is
materially more accurate on exactly the terms that matter. This ticket builds
the browser version because that is what was asked for; the seam is
`useDictation`, so the answer can change later without the screen knowing.

## Acceptance criteria

- [ ] A Candidate can answer a question by speaking, and the turn reaches the
      API as text
- [ ] The turn records `spoken`, and the record can distinguish a spoken answer
      from a typed one
- [ ] Typing is reachable from every state of the voice composer, including
      while the model is downloading
- [ ] A refused microphone leaves the Session usable and says what happened
- [ ] The model downloads once and is served from cache on the next Session
- [ ] Neither the download nor the inference blocks the main thread — the
      Session clock keeps ticking and the transcript keeps scrolling
- [ ] Audio is 16kHz mono before it reaches the model
- [ ] No audio is uploaded anywhere, and the screen says so
- [ ] Where WebGPU is absent, transcription still completes on `wasm`
- [ ] Recording that captures no speech sends nothing and says nothing was heard
- [ ] The whole composer is operable from the keyboard, and every state is
      announced to a screen reader
