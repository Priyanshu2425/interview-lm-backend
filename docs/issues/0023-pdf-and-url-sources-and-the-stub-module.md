# ISSUE-0023 — PDF and URL sources, and the stub Module

Status: resolved
Type: AFK
Source: SPEC 2026-08-21 Notebook Adapter; PRD-0001 §16, §17
Covers: spec §Extract, §Failure modes (scanned PDF, JS-only URL)

## What to build

The two source types people actually have, and the honest failure when they carry
no text.

**PDF.** Extract text per page; the locator's `page` is the real page number, so a
citation can say `source · p.14`. Structure for chunking comes from the document
outline where one exists, and from paragraph boundaries where it does not.

**URL.** Extract the main content, discard chrome. The locator carries the
nearest heading anchor so a citation can link back into the page.

*Deviation, taken during implementation:* the server does **not** fetch the URL.
HTML arrives already fetched, from the browser the Candidate was reading it in,
with the URL supplied alongside for citation. Two reasons: following a
user-supplied URL server-side is an SSRF surface this product has no need to
open, and SPEC-0005's rule that no module outside `metering` opens a socket is
worth more than the convenience. Extraction, anchors and the stub case are
unchanged by it.

**The stub Module.** A scanned PDF, a JS-only page and a paywalled page all
produce the same thing: a Module that exists, is visible, is **not selectable**,
and states why — "no extractable text" — in the Candidate's words rather than a
parser's. It is recorded, never omitted, because Coverage measures the real
notebook and not the part that happened to parse (PRD-0001 §16).

A stub Module holds no Topics and never reaches the Interviewer. It costs nothing:
extraction fails before the embedding call, so a notebook of ten scanned PDFs
spends nothing at all.

## Acceptance criteria

- [ ] A text PDF ingests with per-page locators, and every locator re-slices its page text exactly
- [ ] A citation locator for a PDF chunk names the page the text is actually on, verified against a fixture with known page breaks
- [ ] A URL source extracts main content and drops navigation, header and footer
- [ ] A scanned PDF produces a stub Module with reason "no extractable text" and zero Topics
- [ ] A JS-only or paywalled URL produces a stub Module with its own stated reason
- [ ] A stub Module is listed in the picker, is not selectable, and cannot be reached by a directly-constructed Session request
- [ ] A stub Module makes no embedding call and incurs no cost
- [ ] A stub Module is reported as part of the notebook rather than omitted from it — listed with `topic_count: 0`, `selectable: false` and its reason

  *Amended during implementation:* the criterion first read "Coverage counts stub
  Modules in the denominator". It cannot: Coverage is evidence per **Topic**, and
  a stub holds no Topic. Inventing one to fill a denominator would report a Topic
  that does not exist. The Candidate still sees every Source they uploaded and
  why an unexaminable one is unexaminable, which is what the criterion was for.
- [ ] A notebook of only stub Modules is a valid Corpus that passes conformance
- [ ] Fixtures include a real scanned PDF, a text PDF with known page breaks, and a saved HTML page

## Blocked by

- ISSUE-0021 — the pipeline these source types feed must exist first
