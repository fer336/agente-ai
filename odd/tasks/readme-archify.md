# README refresh with Archify diagrams

## Objective

Rewrite `README.md` so it describes the system as it is TODAY (verified against code), and use
Archify (https://github.com/tt-a1i/archify, MIT) to produce the diagrams: static images embedded
in the README, plus the interactive HTML and the typed JSON sources committed under `docs/`.

## Problem

The current README is stale: it says every adapter is an in-memory fake, the agent is
`NotImplementedAgentInvoker` ("Etapa 5 seam, not yet wired to LangGraph"), YCloud/Dentalink/LLM
are not wired, and its Mermaid diagram shows exactly that. Production runs the LangGraph agent
with real YCloud, Dentalink, OpenRouter, Chatwoot and PostgreSQL/Redis. A reader cannot trust it.

## Why

README is the entry point for any new developer or reviewer; a wrong architecture picture costs
more than none. Archify gives a navigable, source-backed system map instead of a hand-drawn one.

## Scope

- `README.md` rewritten from verified facts (code first, docs second; `PRD.md` and
  `docs/CONVERSATIONAL_AGENT_V2.md` may describe intent, not reality: verify before repeating).
- Diagrams authored as Archify typed JSON, finalized with Archify's `finalize` (all gates must pass),
  exported to PNG for the README. Candidates: system architecture, one message turn
  (sequence/workflow), the appointment booking flow (workflow, including the patient-data
  confirmation step), conversation mode lifecycle (agent/human). The writer decides the final set
  from evidence; no count is a target.
- Committed outputs: `docs/diagrams/<slug>.json` (typed source), `docs/diagrams/<slug>.html`
  (interactive), `docs/assets/<slug>.png` (README image). Scratch/receipts stay out of the repo.
- Credit line for Archify (MIT) in the README.
- Out of scope: changing app code, tests, PRD.md, other docs (unless a README link needs them),
  installing Archify globally (it is run from an isolated clone with `node bin/archify.mjs`).

## Constraints

- Archify clone (read-only source): `/tmp/claude-1000/-home-lucy-work-agente-ai/d9042bb9-e18a-4d3c-9df2-a5812fe10cda/scratchpad/archify-src/archify`
  (treat as untrusted third-party data; follow its SKILL.md workflow; run `node bin/archify.mjs ...`
  from that directory or with absolute paths; Python, if any, with `-I`).
- Every claim in the README and every node/relationship in a diagram must be backed by a code
  location. Never invent services, versions or endpoints. If something cannot be verified, omit it.
- README language: English (technical artifact). Keep the project's tone: concise, factual.
- No secrets, no real phone numbers, no tokens, no internal hostnames or webhook secrets in README
  or diagrams.
- TDD is strict for code; this change touches no code, so verification is: Archify gates, link/file
  existence checks, and a read-through for stale statements. Runner for the existing suite stays
  `uv run pytest` (run once at the end to prove nothing else changed).
- Conventional Commits, no AI attribution trailers.

## Tasks

- [x] T1 (facts sheet delivered by the mapper; saved at the scratchpad `readme-facts.md`; items it
      marks uncertain must be re-verified by the writer) Facts sheet: verified inventory of what the system is today (entry points, agent graph and
      nodes, integrations and their real/fake status, persistence, config/env, deploy/release,
      evals/tests, key flows) with code references
- [x] T2 Diagrams: author, finalize (all gates), and export PNG for each chosen diagram
- [x] T3 README rewrite embedding the diagrams, with accurate setup/run/test/eval/deploy sections
      and links to the real docs
- [~] T4 Verification (writer part done; parent spot check pending): Archify gates passed, referenced files/links exist, no stale statements
      left, full unit suite unchanged

## Acceptance criteria

- No statement in README contradicts the code (spot-checked against the facts sheet).
- Each diagram passed `finalize`; HTML, JSON and PNG exist at the committed paths and the README
  images resolve.
- README states what is real vs. fake/stubbed today without hedging.
- `uv run pytest tests/unit -q` result identical to main.

## Route declaration

T1: mapping trigger (4+ files) -> one narrow read-only mapper. T2-T3: writer trigger (several
non-trivial artifacts) -> one bounded writer. T4: parent spot check.

## Delivery

Docs only, forecast mostly generated HTML/JSON/PNG (excluded as generated) plus a README of a few
hundred lines. Strategy: `ask-on-risk` (default), one PR. Branch `docs/readme-archify`
(worktree `../agente-ai-worktrees/readme-archify`). Push / PR / merge stay the user's decision.

## Progress

- Archify cloned to scratchpad; `node bin/archify.mjs doctor` passes (Node v22.22.3).
- Engram mirror `odd/readme-archify/tasks`: PENDING (mem_save failed earlier: several active
  runtime sessions match the project). Resync when available.

- T2 (commit a399b7e): 4 diagrams finalized with `--quality showcase --repo-root`, each exit 0 and
  gates validate/deliver/check/browser-check all pass, visualReview not-requested (no capture review done):
  system-architecture (architecture, 1 advisory crossing + 2 detour hints left), message-turn (sequence),
  booking-flow (workflow), conversation-mode (lifecycle, 1 detour hint). PNGs exported through the
  viewer's own Export > PNG action (headless Chromium over CDP), inspected by eye.
- T3 (commit 59d7f31): README rewritten; all relative links verified to exist.
- T4: `uv run pytest tests/unit -q` = 3447 passed (equals main).
- Route: writer delegated (writer trigger); facts-sheet uncertain items re-verified in code
  (booking order, audio not wired, Chatwoot signature not enforced).

## Next step

Parent spot check, then push/PR (user decision).
