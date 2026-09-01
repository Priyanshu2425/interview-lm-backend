# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles
to the label strings used in this repo's tracker.

This repo tracks issues as **files** rather than in GitHub Issues (see
`issue-tracker.md`), so a "label" is written on the `Status:` line of
`docs/issues/NNNN-<slug>.md` rather than applied through `gh`. One role per issue.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

Existing issues carry `Status: open` or `Status: resolved`. Both are outside this
vocabulary and stay as they are — `open` is a state, not a triage verdict, and
nothing rewrites the 46 issues already written. A triaged issue replaces `open`
with the role above; `resolved` is never overwritten.

## `Type:` is a second axis, not a label

Every issue also carries `Type: AFK` or `Type: **HITL**`, meaning "can be merged
without human interaction" and "needs a human decision, and says why in its body".
That axis predates these skills and is left alone. It reads close to
`ready-for-agent` / `ready-for-human` and is not the same thing: `Type` is a property
of the slice, fixed when it is written, while the triage role is a statement about
whether the slice is specified enough to start. An `AFK` slice can sit at
`needs-info`.

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), write the
label string from the table onto the `Status:` line. Don't touch `Type:`.
