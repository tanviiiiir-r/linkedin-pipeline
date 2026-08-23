# KICKOFF — paste this to start or resume {{PROJECT_NAME}} cold

> Works in any Codex session. The rest of the procedure is agent-agnostic.

## Load skills (skill canon — always)

- GSD suite: `gsd-execute-phase`, `gsd-verify-work`, `gsd-code-review`, `gsd-debug`, `gsd-audit-phase`, `gsd-ship`, `gsd-plan-phase`
- `modular-architecture`
- `production-readiness`
- `{{ROUTER_SKILL}}`
- If frontend milestone: `design-system` skill (MANDATORY)

## Read in order

1. `AGENTS.md` / `CLAUDE.md` — repo governance
2. `.genesis/PROJECT-BRIEF.md` — what we are building and why
3. `.genesis/DONE.html` — locked spec + definition of done + plan
4. `.genesis/PLAN.md` — milestones being executed
5. `graphify-out/GRAPH_REPORT.md` — god nodes + community structure (if graphify exists)
6. `.genesis/implementation-notes.html` — search for the milestone's nouns: what's LIVE now
7. `.genesis/LOOPS.md` — how the work gets done
8. `.genesis/checkpoints/CURRENT.md` — where we are, if it exists

## Then

1. Pick the next unstarted milestone (or resume from `CURRENT.md`).
2. Run **G0 Existence Pre-Flight** first. Verdicts:
   - **UNBUILT** → continue.
   - **PARTIAL** → revise scope in `PLAN.md`.
   - **BUILT** → halt and surface the existing artifact.
3. Run **L1 BUILD** per `LOOPS.md` exactly. Enforce G0 + all 5 gates (G1 Skill, G2 Progress, G3 Cost, G4 Quality, G5 Verify).
   - Gates are **COMPUTED** (run the command, paste exit code), not narrated.
4. Checkpoint every iteration to `.genesis/checkpoints/<milestone-id>.md`.
5. Spawn **L2 DEBUG** / **L3 RESEARCH** as needed. Exit through **L4 VERIFY** (separate context/model).
6. On milestone done: update `CURRENT.md`, append a row to `implementation-notes.html` "what's live", append progress to `PLAN.md`.

## Stop rules

- If any gate fails 3 times, stop, write what you tried to `CURRENT.md`, surface to the user.
- Never mark a milestone done without L4 VERIFY **APPROVE**.
- Never edit `DONE.html` / `PLAN.md` scope without being asked.
- If budget is exhausted, stop and surface.

