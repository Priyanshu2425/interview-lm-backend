# ISSUE-0027 — Notebook lifecycle: upload, delete, retire

Status: resolved
Type: AFK
Source: SPEC 2026-08-21 Notebook Adapter; ADR-0003, ADR-0010; PRD-0002
Covers: spec §Decisions/Deletion, §Persistence, §Failure modes (deletion mid-Session)

## What to build

The Candidate's side of the notebook, and the collision ADR-0003 predicted: two
persistence layers with opposite lifecycles, meeting at a delete button.

**Upload.** Sources are dragged in. Each shows its own state — extracting,
embedding, ready, or **stub** with the reason it produced no text. A notebook is
usable while later sources are still ingesting; a Session may be scoped to the
Modules that are ready.

**Delete.** Deleting a notebook, or one source inside it, removes chunks,
embeddings, centroids and dossiers from the content schema. It removes **no
Evidence**. The Topics it produced are **retired**: readable in the record,
absent from every picker, unreachable by a directly-constructed Session request.

**Snapshots** are what make that possible. An Evidence row already carries its
grounding excerpt and grader provenance; it also carries a denormalised Topic
title, Module title and the cited spans' text, written **at the time the Visit was
graded** rather than read back through content that may be gone. A retired Topic's
citations still render.

**Deletion mid-Session** ends the Session after the current Topic Visit finishes,
never inside it — the soft-deadline machinery already built for the duration
deadline. Evidence for that Visit is written, then the Topics retire.

Retired Topics keep their Topic Confidence. Their Coverage still counts. The
record is what the product exists to build, and it does not evaporate because the
Candidate tidied their files.

## Acceptance criteria

- [ ] Sources upload independently and report extracting / embedding / ready / stub-with-reason
- [ ] A Session can be scoped to ready Modules while other sources are still ingesting
- [ ] Deleting a notebook removes every chunk, embedding, centroid and dossier from the content schema
- [ ] Deleting a notebook removes no Evidence row and no Topic Confidence row
- [ ] A retired Topic is absent from the picker and rejected by a directly-constructed Session request
- [ ] A retired Topic's Evidence renders its title, grounding excerpt, grader provenance and citations from snapshots, with no read against deleted content
- [ ] Snapshot text is written at grading time, verified by deleting the notebook and diffing the rendered record against what it showed before
- [ ] Deleting a notebook mid-Session ends the Session after the current Topic Visit and writes that Visit's Evidence
- [ ] Deleting one source retires only that Module's Topics
- [ ] Retired Topics still count toward Coverage and still report Mastery above the Evidence Floor
- [ ] A retired Topic below the Evidence Floor still reports Untested and no number

## Blocked by

- ISSUE-0025 — the citation columns are the snapshots this slice must keep alive
