# AGENT-03 — Evaluator Validity + Replay Verification

Role: VERIFIER/BUILD WORKER
Status: READY
Control room: issue #140
Worker branch: `swarm/SWARM-2026-STAGE15-01/AGENT-03`

## Assignment
Independently classify the latest v25 failure and audit the evaluator infrastructure around tutorial handoff, rendered-pixel score tracking, visual death detection, persistent restart behavior, six-run completeness, discriminative scoring, and durable GitHub status/artifact publication. Build replay/offline checks where practical so the Orchestrator can reject bad fixes before another expensive live run.

## Read first
- `SWARM_WORKER_PROTOCOL.md`
- swarm manifest/status/decisions
- `subway_ai/status/stage15-latest.json`
- `.github/workflows/subway-stage15.yml`
- evaluator v17-v25
- v24/v25 workflow artifacts/logs

## Owned area
- Replay/audit/test utilities on your branch.
- Failure classification and verification report.
- Workflow/status hardening proposals that do not alter experiment semantics.

## Constraints
- Never infer score from survival time.
- Tutorial/bootstrap score is never benchmark score.
- Visual death is required; watchdog is only a safety abort.
- Benchmark must contain exactly stay x1, always_jump x1, corridor_cv x1, learned x3, all valid.
- Discriminative evaluator gate must remain real; no fake completion.
- Do not begin geometry/Stage16.

## Acceptance criteria
1. Give an evidence-backed classification of v25's exact terminal failure and whether prompt sensing, actuation/state, handoff logic, or another evaluator component is responsible.
2. Verify score OCR/reset continuity, death detection, restart/handoff, episode-count enforcement, and durable status publication for obvious false-pass/false-fail paths.
3. Create deterministic replay/unit checks for at least the failure modes that can be tested without the official live game.
4. Challenge AGENT-01/02 style fixes conceptually: identify which evidence would be required before integration.
5. Publish exact commits/tests, results, unresolved risks, and one recommended integration action.

## Deliverable
Publish `.swarm/runs/SWARM-2026-STAGE15-01/outputs/AGENT-03-handoff.md` and post material blockers/conflicts to issue #140.