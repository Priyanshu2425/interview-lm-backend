# Story coverage

Every user story in the five PRDs, mapped to the module that implements it
and the test that holds it. Generated from `interviewer/_audit/coverage.py`,
which `test_story_coverage.py` verifies on every run — so this file cannot
**191 stories, all mapped.**

drift from the code without the suite failing.

## PRD-0001 — Corpus Adapter Contract and Dossier Loader

29 stories.

| # | Story | Implemented in | Held by |
|---|---|---|---|
| 1 | **Interviewer** — to request a Topic dossier by `topic_id` | `corpus/loader.py` | `test_corpus_contract.py` |
| 2 | **Interviewer** — a dossier to arrive whole rather than chunked | `corpus/loader.py` | `test_corpus_contract.py` |
| 3 | **Interviewer** — the dossier to state its own token count | `corpus/loader.py:approx_tokens` | `test_corpus_contract.py` |
| 4 | **Interviewer** — teaching material and Ground Truth returned as separate fields | `corpus/loader.py:text_for_prompt` | `test_corpus_contract.py` |
| 5 | **Interviewer** — a dossier to tell me which Grading Mode it can support | `corpus/contract.py:grading_mode_ceiling` | `test_corpus_contract.py` |
| 6 | **Interviewer** — Classes within a Topic to arrive in curriculum order | `corpus/contract.py` | `test_corpus_contract.py` |
| 7 | **Interviewer** — Modules and Topics to expose their order | `corpus/contract.py` | `test_corpus_contract.py` |
| 8 | **Judge** — to receive only the grounding excerpt for the question I am scoring | `judge/judge.py:_grounding` | `test_judge.py` |
| 9 | **Judge** — an Assignment's Answer Key retrievable by the Assignment's id | `judge/judge.py:_grounding` | `test_judge.py` |
| 10 | **system operator** — ingest to fail loudly when a Corpus violates the contract | `corpus/adapters/interview_lm.py` | `test_corpus_contract.py` |
| 11 | **system operator** — the validation report to name every violation rather than the first one | `corpus/conformance.py:validate` | `test_conformance.py` |
| 12 | **system operator** — a report of Topic dossier sizes at ingest | `corpus/conformance.py` | `test_conformance.py` |
| 13 | **system operator** — ingest to record the Corpus's provenance — Source, extraction time, Adapter identity  | `corpus/contract.py:CorpusProvenance` | `test_conformance.py` |
| 14 | **system operator** — re-ingesting an unchanged Source to produce identical ids | `corpus/adapters/interview_lm.py` | `test_corpus_contract.py` |
| 15 | **system operator** — a re-ingest that changes Topic boundaries to be reported as such | `corpus/conformance.py:diff_topics` | `test_conformance.py` |
| 16 | **system operator** — Classes with no retrievable content to be recorded as stubs rather than omitted | `corpus/conformance.py` | `test_conformance.py` |
| 17 | **system operator** — a Topic whose Classes are all stubs to be flagged | `corpus/conformance.py` | `test_conformance.py` |
| 18 | **Adapter author** — the contract stated as a schema I can validate against locally | `corpus/cli.py` | `test_conformance.py` |
| 19 | **Adapter author** — to declare that my Source carries no Ground Truth | `corpus/contract.py` | `test_conformance.py` |
| 20 | **Adapter author** — to supply my own ordering when my Source has no natural one | `corpus/contract.py` | `test_conformance.py` |
| 21 | **Adapter author** — to be the one that splits oversized material into Topics | `corpus/contract.py` | `test_conformance.py` |
| 22 | **Adapter author** — a fixture Corpus and a conformance check I can run | `corpus/conformance.py:fixture_corpus` | `test_conformance.py` |
| 23 | **Session** — to ask for every Topic within a chosen set of Modules | `corpus/service.py` | `test_corpus_api.py` |
| 24 | **Session** — Topic listing to be cheap and content loading to be separate | `corpus/service.py` | `test_corpus_api.py` |
| 25 | **Candidate** — to choose a Session's scope by Module | `api/routes_corpus.py` | `test_corpus_api.py` |
| 26 | **Candidate** — a Module with no Answer Keys to still be selectable | `api/routes_corpus.py` | `test_corpus_api.py` |
| 27 | **tracker** — the canonical list of Topic ids for a Corpus | `corpus/service.py:topic_ids_for` | `test_selection.py` |
| 28 | **future maintainer** — all InterviewLM-specific vocabulary confined to the Adapter | `corpus/adapters/interview_lm.py` | `test_architecture.py` |
| 29 | **future maintainer** — a second Adapter to be implementable against the contract alone | `corpus/adapters/markdown_folder.py` | `test_conformance.py` |

## PRD-0002 — Evidence and Topic Confidence Tracker

38 stories.

| # | Story | Implemented in | Held by |
|---|---|---|---|
| 1 | **Candidate** — a Topic I have never been asked about to read as *Untested* | `confidence/math.py:Band` | `test_confidence.py` |
| 2 | **Candidate** — to see how much of a Track I have been examined on | `confidence/reporting.py` | `test_summary.py` |
| 3 | **Candidate** — Coverage and Mastery reported separately | `confidence/reporting.py` | `test_summary.py` |
| 4 | **Candidate** — a reading based on one answer to be hedged | `confidence/math.py:band` | `test_confidence.py` |
| 5 | **Candidate** — a Topic's reading to firm up as I am examined on it repeatedly | `confidence/math.py:band` | `test_confidence.py` |
| 6 | **Candidate** — to see which Topics look weakest | `confidence/summary.py:weakest` | `test_weakest.py` |
| 7 | **Candidate** — to know that answering after a hint still counts as an answer | `confidence/math.py:evidence_delta` | `test_confidence.py` |
| 8 | **Candidate** — to see who graded each answer and on what provider | `confidence/store.py:EvidenceLedger` | `test_judge.py` |
| 9 | **Candidate** — an answer graded against an authoritative Answer Key to carry more weight than one graded on a model's judgment | `corpus/contract.py:_WEIGHTS` | `test_confidence.py` |
| 10 | **Candidate** — my Topic Confidence to survive across Sessions | `db/schema.py:topic_confidence` | `test_walking_skeleton.py` |
| 11 | **Candidate** — my record to survive a rewrite of the interview engine | `db/schema.py:topic_confidence` | `test_walking_skeleton.py` |
| 12 | **Interviewer** — to be handed the next Topic to examine | `graph/machine.py:select_topic` | `test_selection.py` |
| 13 | **Interviewer** — Topic selection to favour Topics that are weak or untested | `confidence/selector.py` | `test_selection.py` |
| 14 | **Interviewer** — selection to be stochastic rather than always-the-weakest | `confidence/selector.py` | `test_selection.py` |
| 15 | **Interviewer** — an already-visited Topic excluded within the same Session | `graph/machine.py:select_topic` | `test_walking_skeleton.py` |
| 16 | **Interviewer** — the opening question of a Session drawn by curriculum order rather than by sampling | `graph/machine.py:select_topic` | `test_walking_skeleton.py` |
| 17 | **Interviewer** — selection confined to the Session's chosen Modules | `graph/machine.py:select_topic` | `test_walking_skeleton.py` |
| 18 | **Interviewer** — to seed a Session's opening difficulty from prior Topic Confidence | `confidence/selector.py` | `test_selection.py` |
| 19 | **graph** — to open a Topic Visit and receive an id for it | `confidence/store.py:VisitLifecycle` | `test_walking_skeleton.py` |
| 20 | **graph** — an Evidence write to be idempotent on the Topic Visit id | `confidence/store.py:EvidenceLedger` | `test_walking_skeleton.py` |
| 21 | **graph** — a Topic Visit to produce exactly one Evidence row however many Answer Turns it contained | `confidence/store.py:EvidenceLedger` | `test_walking_skeleton.py` |
| 22 | **graph** — an ungraded Topic Visit to write no Evidence at all | `confidence/store.py:VisitLifecycle` | `test_resumption.py` |
| 23 | **graph** — an interrupted Topic Visit to stay open until it is graded | `confidence/store.py:VisitLifecycle` | `test_resumption.py` |
| 24 | **graph** — the weight applied automatically from the Grading Mode recorded on the Visit | `confidence/store.py:EvidenceLedger` | `test_judge.py` |
| 25 | **Judge** — to submit a score and have the tracker decide the weight | `confidence/store.py:EvidenceLedger` | `test_judge.py` |
| 26 | **system operator** — every Evidence row to store the raw exchange behind it | `db/schema.py:evidence` | `test_judge.py` |
| 27 | **system operator** — every Evidence row to record its rubric version | `db/schema.py:evidence` | `test_judge.py` |
| 28 | **system operator** — every Evidence row to record grader identity and provider | `db/schema.py:evidence` | `test_judge.py` |
| 29 | **system operator** — to re-judge a batch of stored exchanges with a reference grader | `judge/rejudge.py` | `test_rejudge.py` |
| 30 | **system operator** — Topic Confidence stored in a table I own rather than inside a framework's state | `confidence/store.py:ConfidenceStore` | `test_resumption.py` |
| 31 | **system operator** — Topic Confidence to be readable outside a Session | `confidence/store.py:ConfidenceStore` | `test_resumption.py` |
| 32 | **system operator** — a Topic Confidence row to be created lazily at first Evidence | `confidence/store.py` | `test_walking_skeleton.py` |
| 33 | **system operator** — Evidence rows to be append-only | `db/schema.py:APPEND_ONLY_EVIDENCE_TRIGGER` | `test_walking_skeleton.py` |
| 34 | **system operator** — to know the effective evidence behind a Topic rather than a question count | `confidence/math.py:coverage` | `test_confidence.py` |
| 35 | **reporting surface** — the Evidence Floor bands read off the posterior as a credible interval | `confidence/math.py:Posterior` | `test_confidence.py` |
| 36 | **reporting surface** — to be refused a Mastery percentage below the floor | `confidence/math.py:Posterior` | `test_confidence.py` |
| 37 | **future maintainer** — the Grading Mode weights held as three named constants in one place | `corpus/contract.py:_WEIGHTS` | `test_confidence.py` |
| 38 | **future maintainer** — no provider normaliser to exist until data supports one | `judge/rejudge.py` | `test_rejudge.py` |

## PRD-0003 — Managed Mode Interview Loop

42 stories.

| # | Story | Implemented in | Held by |
|---|---|---|---|
| 1 | **Candidate** — to start a mock interview scoped to the Modules I choose | `graph/sessions.py:SessionConfig` | `test_selection.py` |
| 2 | **Candidate** — to choose how long the Session runs before it starts | `graph/sessions.py:SessionConfig` | `test_selection.py` |
| 3 | **Candidate** — the Session to end after the current question completes rather than mid-question | `graph/machine.py:decide_next` | `test_walking_skeleton.py` |
| 4 | **Candidate** — the first question to be approachable | `graph/machine.py:select_topic` | `test_selection.py` |
| 5 | **Candidate** — questions drawn from the course material | `judge/question_writer.py` | `test_judge.py` |
| 6 | **Candidate** — to be asked one thing at a time | `judge/interviewer.py` | `test_agentic_region.py` |
| 7 | **Candidate** — a follow-up when my answer is vague | `judge/interviewer.py` | `test_agentic_region.py` |
| 8 | **Candidate** — a hint when I am stuck | `judge/interviewer.py` | `test_agentic_region.py` |
| 9 | **Candidate** — an answer reached after hints to still count as an answer | `judge/interviewer.py` | `test_agentic_region.py` |
| 10 | **Candidate** — the whole exchange on one Topic scored once | `confidence/store.py:EvidenceLedger` | `test_agentic_region.py` |
| 11 | **Candidate** — to move on when I genuinely do not know something | `judge/interviewer.py:_GIVE_UP` | `test_agentic_region.py` |
| 12 | **Candidate** — to see the score and the reasoning behind it after a Topic | `graph/machine.py:update_confidence` | `test_judge.py` |
| 13 | **Candidate** — to be told which grader and provider produced my score | `graph/machine.py:update_confidence` | `test_judge.py` |
| 14 | **Candidate** — to never be shown the Answer Key before I have answered | `graph/machine.py` | `test_api_sessions.py` |
| 15 | **Candidate** — an interrupted Session to be resumable | `graph/runner.py` | `test_resumption.py` |
| 16 | **Candidate** — an answer I submitted before an interruption to still be graded | `graph/runner.py` | `test_resumption.py` |
| 17 | **Candidate** — to end a Session early | `api/routes_sessions.py:end` | `test_api_sessions.py` |
| 18 | **Candidate** — a summary at the end covering what I was examined on and where I looked weak | `confidence/summary.py` | `test_summary.py` |
| 19 | **Candidate** — the summary to distinguish Topics I was not asked about from Topics I answered badly | `confidence/summary.py` | `test_summary.py` |
| 20 | **Candidate** — this Session's results to inform the next Session's question choice | `confidence/selector.py` | `test_selection.py` |
| 21 | **returning Candidate** — my opening difficulty seeded from prior Sessions | `confidence/selector.py` | `test_selection.py` |
| 22 | **Interviewer** — the Topic handed to me by the selector | `graph/machine.py` | `test_selection.py` |
| 23 | **Interviewer** — the whole Topic dossier in context | `graph/machine.py` | `test_selection.py` |
| 24 | **Interviewer** — to write a question from an Assignment and its Answer Key where one exists | `judge/question_writer.py:_ground` | `test_judge.py` |
| 25 | **Interviewer** — to write a question from Topic text where no Answer Key exists | `judge/question_writer.py:_ground` | `test_judge.py` |
| 26 | **Interviewer** — to fall back to my own knowledge, anchored to the Topic's syllabus and Module order, where no text exists at all | `judge/question_writer.py:_ground` | `test_judge.py` |
| 27 | **Interviewer** — the Grading Mode recorded on the Visit at the moment the question is written | `graph/machine.py:record_answer` | `test_judge.py` |
| 28 | **Interviewer** — to decide within a Topic Visit whether to probe, hint, or close | `judge/interviewer.py` | `test_agentic_region.py` |
| 29 | **Interviewer** — a bound on how long one Topic Visit can run | `judge/interviewer.py` | `test_agentic_region.py` |
| 30 | **Judge** — to receive only the question, the answer, and the grounding | `judge/judge.py` | `test_judge.py` |
| 31 | **Judge** — to return a score and a rationale together | `judge/judge.py` | `test_judge.py` |
| 32 | **Judge** — to apply a versioned rubric | `judge/judge.py` | `test_judge.py` |
| 33 | **Judge** — to grade against an Answer Key where one exists and against the dossier excerpt where it does not | `judge/judge.py` | `test_judge.py` |
| 34 | **graph** — the Evidence write to be an edge rather than a tool call | `graph/machine.py` | `test_walking_skeleton.py` |
| 35 | **graph** — to park at the Answer Turn and wait to be resumed | `graph/machine.py:answer_turn` | `test_resumption.py` |
| 36 | **graph** — to treat the Answer Turn as an event rather than a read from a kind of input | `graph/machine.py:answer_turn` | `test_resumption.py` |
| 37 | **graph** — checkpoints per Session thread | `graph/machine.py:answer_turn` | `test_resumption.py` |
| 38 | **system operator** — to replay a Session deterministically against changed prompts | `graph/ports.py` | `test_resumption.py` |
| 39 | **system operator** — every model call inside the Session attributable to a Topic Visit | `metering/client.py` | `test_metering_store.py` |
| 40 | **system operator** — a Session's chosen duration recorded | `db/schema.py:session` | `test_summary.py` |
| 41 | **system operator** — a Session that errors to end with an error the Candidate can act on | `graph/runner.py` | `test_remaining_stories.py` |
| 42 | **future maintainer** — the deterministic skeleton to exist before the agentic region grows | `graph/machine.py` | `test_architecture.py` |

## PRD-0004 — MCP Mode Server

35 stories.

| # | Story | Implemented in | Held by |
|---|---|---|---|
| 1 | **Candidate already working in Claude** — to run a mock interview without leaving my session | `mcp/server.py:start_session` | `test_mcp.py` |
| 2 | **Candidate in MCP Mode** — the Session scoped to Modules I choose | `mcp/server.py:start_session` | `test_mcp.py` |
| 3 | **Candidate in MCP Mode** — my Topic Confidence to be the same record as in Managed Mode | `confidence/store.py` | `test_mcp.py` |
| 4 | **Candidate in MCP Mode** — the host never to see an Answer Key before I have answered | `mcp/server.py:next_topic` | `test_mcp.py` |
| 5 | **Candidate in MCP Mode** — to be told my answer was graded by a Judge Subagent | `mcp/server.py:record_score` | `test_mcp.py` |
| 6 | **Candidate in MCP Mode** — my Session's cost paid by my own Claude subscription | `mcp/server.py` | `test_mcp.py` |
| 7 | **Candidate in MCP Mode** — an interrupted Session to be resumable | `mcp/server.py` | `test_remaining_stories.py` |
| 8 | **Candidate in MCP Mode** — to see the same score, rationale and Evidence Floor hedging as in Managed Mode | `confidence/summary.py` | `test_remaining_stories.py` |
| 9 | **host Claude** — a tool that starts a Session and returns its scope | `mcp/server.py` | `test_mcp.py` |
| 10 | **host Claude** — a tool that asks the server for the next Topic | `mcp/server.py` | `test_mcp.py` |
| 11 | **host Claude** — a tool that returns the interviewing dossier for a Topic | `mcp/server.py` | `test_mcp.py` |
| 12 | **host Claude** — that dossier to contain no Answer Key | `mcp/server.py:next_topic` | `test_mcp.py` |
| 13 | **host Claude** — a tool that submits the Candidate's answer and returns a Topic Visit id | `mcp/server.py:submit_answer` | `test_mcp.py` |
| 14 | **host Claude** — to dispatch a Judge Subagent with only a Topic Visit id | `mcp/server.py:submit_answer` | `test_mcp.py` |
| 15 | **host Claude** — the server to tell me when a Visit is unresolved | `mcp/server.py:VisitUnresolved` | `test_mcp.py` |
| 16 | **host Claude** — a tool that ends the Session and returns a summary | `mcp/server.py:end_session` | `test_remaining_stories.py` |
| 17 | **host Claude** — tool descriptions that state the intended loop | `mcp/server.py:TOOL_DESCRIPTIONS` | `test_remaining_stories.py` |
| 18 | **Judge Subagent** — to redeem a Topic Visit id for exactly the grounding of that one Visit | `mcp/server.py:redeem_grading_material` | `test_mcp.py` |
| 19 | **Judge Subagent** — to receive the question, the answer and the grounding and nothing else | `mcp/server.py:redeem_grading_material` | `test_mcp.py` |
| 20 | **Judge Subagent** — to submit a score against the Topic Visit id | `mcp/server.py:record_score` | `test_mcp.py` |
| 21 | **Judge Subagent** — to apply the same versioned rubric as the server Judge | `mcp/server.py:record_score` | `test_mcp.py` |
| 22 | **server** — to issue every Topic Visit id myself | `mcp/server.py` | `test_mcp.py` |
| 23 | **server** — a redemption to be valid only for its own Visit | `mcp/server.py` | `test_mcp.py` |
| 24 | **server** — redemption to be single-use or narrowly scoped in time | `mcp/server.py` | `test_mcp.py` |
| 25 | **server** — to refuse to open a new Topic Visit while one is unresolved | `mcp/server.py` | `test_mcp.py` |
| 26 | **server** — a second score submitted for the same Topic Visit id to be a no-op | `mcp/server.py` | `test_mcp.py` |
| 27 | **server** — to enforce Session scope on every Topic request | `mcp/server.py` | `test_mcp.py` |
| 28 | **server** — to apply the Grading Mode weight myself from the Visit's recorded mode | `mcp/server.py:record_score` | `test_mcp.py` |
| 29 | **server** — to record Grader Provenance as Judge Subagent on these rows | `mcp/server.py:record_score` | `test_mcp.py` |
| 30 | **server** — to store the raw exchange for every MCP-graded Visit | `mcp/server.py:record_score` | `test_mcp.py` |
| 31 | **server** — an unresolved Visit to remain open across a disconnect | `confidence/store.py:VisitLifecycle` | `test_mcp.py` |
| 32 | **system operator** — MCP Mode Sessions to be distinguishable in the record | `db/schema.py:session` | `test_mcp.py` |
| 33 | **system operator** — the server to be safe against a host that ignores every prompt | `mcp/server.py` | `test_mcp.py` |
| 34 | **system operator** — a fallback recorded when subagents cannot reach the server | `mcp/server.py:record_grading_unreachable` | `test_remaining_stories.py` |
| 35 | **future maintainer** — the MCP surface to be a driver over the same modules Managed Mode uses | `mcp/server.py` | `test_mcp.py` |

## PRD-0005 — Credits, BYOK and Per-Visit Provider Metering

47 stories.

| # | Story | Implemented in | Held by |
|---|---|---|---|
| 1 | **Candidate** — to buy Credits and see them in my balance once payment clears | `metering/ledger.py:grant` | `test_metering_store.py` |
| 2 | **Candidate** — a Credit to mean one cent of real provider cost | `metering/credits.py` | `test_metering_pure.py` |
| 3 | **Candidate** — to choose a Provider before a Session starts | `graph/sessions.py:SessionConfig` | `test_api_sessions.py` |
| 4 | **Candidate** — to see each Provider's relative price before I choose | `metering/operator.py:PriceService` | `test_remaining_stories.py` |
| 5 | **Candidate** — to be told that a Session's total cost cannot be quoted in advance | `metering/operator.py:PriceService` | `test_remaining_stories.py` |
| 6 | **Candidate** — to see what a Topic Visit cost me after it completes | `metering/ledger.py:visit_cost` | `test_credits_in_session.py` |
| 7 | **Candidate** — a running total for the Session | `api/routes_sessions.py:spend` | `test_remaining_stories.py` |
| 8 | **Candidate** — the cost shown alongside which grader and provider produced my score | `graph/machine.py:update_confidence` | `test_judge.py` |
| 9 | **Candidate** — to be warned when my balance is running low | `api/routes_candidate.py:credits` | `test_api_sessions.py` |
| 10 | **Candidate** — a Session to stop opening new Topic Visits when my balance is exhausted | `graph/machine.py:decide_next` | `test_credits_in_session.py` |
| 11 | **Candidate** — the Topic Visit I am inside to finish even if it overruns my balance | `graph/machine.py:decide_next` | `test_credits_in_session.py` |
| 12 | **Candidate** — an exhausted balance to be a resumable state | `graph/runner.py` | `test_credits_in_session.py` |
| 13 | **Candidate** — to supply my own OpenRouter key | `metering/keyvault.py:attach` | `test_keyvault.py` |
| 14 | **BYOK Candidate** — to be told that my key spends no Credits | `api/routes_candidate.py` | `test_api_sessions.py` |
| 15 | **BYOK Candidate** — a failure at my provider to name that provider and the reason | `metering/failures.py` | `test_metering_pure.py` |
| 16 | **BYOK Candidate** — to never be told my Credits ran out | `metering/failures.py` | `test_metering_pure.py` |
| 17 | **BYOK Candidate** — my key held encrypted and revocable | `metering/keyvault.py` | `test_keyvault.py` |
| 18 | **BYOK Candidate** — to be told at the moment I attach a key whether it works | `metering/keyvault.py:OpenRouterValidator` | `test_keyvault.py` |
| 19 | **BYOK Candidate** — to remove my key and fall back to Credits | `metering/keyvault.py:revoke` | `test_keyvault.py` |
| 20 | **Candidate** — to know that only OpenRouter keys are accepted | `metering/keyvault.py` | `test_keyvault.py` |
| 21 | **Candidate** — grading to be paid for on the same key as the interviewing | `metering/client.py` | `test_metering_store.py` |
| 22 | **Candidate** — a refund when a failure was ours | `metering/ledger.py:refund_visit` | `test_metering_store.py` |
| 23 | **Candidate** — a refund credited against the Topic Visit it belongs to | `metering/ledger.py:refund_visit` | `test_metering_store.py` |
| 24 | **Candidate in MCP Mode** — no Credits and no key involved at all | `mcp/server.py` | `test_mcp.py` |
| 25 | **Interviewer** — a Provider bound for the whole Topic Visit | `metering/client.py:BindingStore` | `test_metering_store.py` |
| 26 | **Judge** — to run on the Provider recorded for the Visit | `metering/client.py:BindingStore` | `test_metering_store.py` |
| 27 | **graph** — a Provider failure mid-Visit to park and error rather than switch providers | `graph/runner.py:submit` | `test_remaining_stories.py` |
| 28 | **graph** — the retry after a parked Visit to run on whichever Provider is live when the next Visit opens | `graph/runner.py:submit` | `test_remaining_stories.py` |
| 29 | **graph** — the spend check to happen where a Session may legally end | `graph/machine.py:decide_next` | `test_credits_in_session.py` |
| 30 | **graph** — an ungraded Visit to write no Evidence even though its calls were metered | `metering/client.py` | `test_credits_in_session.py` |
| 31 | **system** — exactly one path to a model provider | `metering/client.py` | `test_architecture.py` |
| 32 | **system** — every model call attributed to a Topic Visit | `metering/client.py:complete` | `test_metering_store.py` |
| 33 | **system** — per-call spend recorded from the provider's reported cost | `metering/credits.py:usd_to_credits` | `test_metering_store.py` |
| 34 | **system** — a call whose cost the provider does not report to be recorded as unpriced rather than as zero | `metering/credits.py:usd_to_credits` | `test_metering_store.py` |
| 35 | **system** — the spend ledger idempotent on a call id | `metering/ledger.py:debit` | `test_metering_store.py` |
| 36 | **system** — Credits granted only after payment clears | `metering/ledger.py:grant` | `test_metering_store.py` |
| 37 | **system** — a failure classifier that cannot emit a Credit message on a BYOK Session | `metering/failures.py:classify` | `test_metering_pure.py` |
| 38 | **operator** — the pool topped up ahead of receipts | `metering/ledger.py:prefunded_for` | `test_remaining_stories.py` |
| 39 | **operator** — an alert when pool headroom falls below a threshold | `metering/operator.py:pool` | `test_operator.py` |
| 40 | **operator** — to see pool float as a working-capital figure | `metering/operator.py:pool` | `test_operator.py` |
| 41 | **operator** — promotional Credits to spend from the same pool as purchased ones | `metering/ledger.py:promo_grant` | `test_metering_store.py` |
| 42 | **operator** — per-Provider spend and per-Provider failure rates | `metering/operator.py:by_provider` | `test_operator.py` |
| 43 | **operator** — spend attributable to Topic Visit, Session and Candidate | `metering/operator.py:sessions` | `test_operator.py` |
| 44 | **operator** — refunds to be an explicit ledger entry rather than a balance edit | `metering/ledger.py:refund_visit` | `test_metering_store.py` |
| 45 | **future maintainer** — no provider normaliser anywhere in this system | `metering/operator.py` | `test_rejudge.py` |
| 46 | **future maintainer** — the raw exchange and provider recorded on every metered call | `db/schema.py:call_record` | `test_metering_store.py` |
| 47 | **future maintainer** — BYOK and Credits to differ in exactly one branch | `metering/client.py` | `test_metering_store.py` |
