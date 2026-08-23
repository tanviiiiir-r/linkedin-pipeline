# LOOPS.md — How {{PROJECT_NAME}} gets built

This file is **dev-only**. It defines the harness that prompts the agent so the human doesn't have to turn-by-turn.
It is designed for the GSD (Get Shit Done) skill suite already installed in this Codex workspace.

## Read order for any new session

1. `AGENTS.md` / `CLAUDE.md` (repo governance)
2. `.genesis/PROJECT-BRIEF.md` (what we are building and why)
3. `.genesis/DONE.html` (locked spec + definition of done + plan)
4. `.genesis/PLAN.md` (sliced milestones)
5. `graphify-out/GRAPH_REPORT.md` (god nodes + community structure)
6. `.genesis/implementation-notes.html` (what's live now)
7. `.genesis/LOOPS.md` (this file)
8. `.genesis/checkpoints/CURRENT.md` (resume point)

## Loop layers

| Loop | Purpose | GSD skill / action |
|---|---|---|
| **L0 SETUP** | One-time scaffold: graph, brief, plan, DoD, kickoff | `gsd-new-project` or manual `.genesis/` creation |
| **L1 BUILD** | Normal implementation pass | `gsd-execute-phase` or inline plan → execute → checkpoint |
| **L2 DEBUG** | Investigate repeated failures | `gsd-debug` |
| **L3 RESEARCH** | Unknown domain / API / library exploration | `gsd-explore` + browser / `gsd-spike` |
| **L4 VERIFY** | Separate context/model judges the milestone | `gsd-verify-work`, `gsd-code-review --depth=deep`, `gsd-audit-phase` |

## The five gates

Every L1 BUILD iteration must compute and record these gates. Narration is not enough.

| Gate | Check | Tool / command | Pass criteria |
|---|---|---|---|
| **G1 Skill** | Right skill canon loaded | Read skill list in session | Canon + milestone-specific skills loaded before code |
| **G2 Progress** | We know where we are | `cat .genesis/checkpoints/CURRENT.md` | Current milestone + status explicit |
| **G3 Cost** | Token budget respected | Compare actual vs milestone budget | Under budget; if over, stop and surface |
| **G4 Quality** | Code is clean and safe | Typecheck, lint, tests, `gsd-code-review` | Typecheck/lint/tests green; no Critical findings |
| **G5 Verify** | A separate context/model approves | `gsd-verify-work` or `gsd-code-review --depth=deep` | Verdict APPROVE, not APPROVE-WITH-CAVEATS |

## L1 BUILD protocol

1. **Load canon.** Always load: `agentic-swe-master` (if available), GSD skills, `modular-architecture`, `production-readiness`. Add milestone-specific skills from `PLAN.md`.
2. **G0 Existence Pre-Flight.** Before touching code, check if the artifact already exists:
   - Search for the milestone's nouns in `graphify query "<concept>"`.
   - Check `implementation-notes.html` for a matching "live" row.
   - Verdicts:
     - **UNBUILT** → continue to build.
     - **PARTIAL** → revise scope in `PLAN.md`, then continue.
     - **BUILT** → halt; do not rebuild silently. Surface to user.
3. **Build inside freeze boundary.** Only edit files listed in the milestone's `Files / freeze boundary`. If you need to touch others, stop and ask.
4. **Run G1–G4 after each meaningful change.** Record results in the checkpoint.
5. **Stop rule.** If any gate fails 3 times, stop, write what you tried to `CURRENT.md`, and surface to user.
6. **Exit through L4 VERIFY.** No milestone is done until a separate context/model returns APPROVE.

## L4 VERIFY protocol

The verifier must be a **separate model call / context** from the builder. In Codex this means:

1. Create a fresh goal/thread with the artifact only:
   - The changed files (or diff).
   - The milestone from `PLAN.md`.
   - The `DONE.html` definition-of-done gates.
   - `context-graph.json` invariants.
2. Run one or more of:
   - `gsd-verify-work` (conversational UAT)
   - `gsd-code-review --depth=deep`
   - `gsd-audit-phase`
3. Verdicts:
   - **APPROVE** → update `CURRENT.md`, append "live" row to `implementation-notes.html`, update `PLAN.md` progress.
   - **REJECT** → write reasons to `CURRENT.md`, spawn L2 DEBUG or L3 RESEARCH, loop again.
   - **APPROVE-WITH-CAVEATS** → treat as REJECT unless the caveat is a documentation-only follow-up.

## L2 DEBUG protocol

Trigger: G4 Quality fails 3 times, or L4 VERIFY rejects with a concrete bug.

1. Capture exact failure output.
2. Run `gsd-debug` with the failure snippet and milestone context.
3. Apply the smallest fix that resolves the failure.
4. Re-run G4 Quality before returning to L1 BUILD.

## L3 RESEARCH protocol

Trigger: Unknown API, library, pattern, or architecture decision.

1. Run `gsd-explore` or `gsd-spike`.
2. If web / docs needed, use browser skill or `gsd-spike`.
3. Write the decision and rationale into `.genesis/wiki/<topic>.md` and link from `wiki/index.md`.
4. Return to L1 BUILD.

## Stop conditions

- A milestone is done only when L4 VERIFY returns APPROVE.
- If scope must change, change `PLAN.md` and surface to user. Do not silently edit `DONE.html`.
- If budget is exhausted, stop and surface.
- If a gate fails 3 times, stop and surface.

## Output artifacts per milestone

- `.genesis/checkpoints/<milestone-id>.md` — full run log
- `.genesis/implementation-notes.html` — "what's live" row
- `.genesis/PLAN.md` — progress update
- `.genesis/explanations/<date>-<milestone-id>.html` (optional, if explain-diff enabled)

