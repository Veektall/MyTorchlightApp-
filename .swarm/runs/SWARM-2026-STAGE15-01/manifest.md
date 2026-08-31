# SWARM-2026-STAGE15-01 — Stage 15 Completion

## Master goal
Complete Subway Surfers Stage 15 under `pixel-policy-contract-v1.1` without weakening any evaluator or policy constraints.

## Canonical source of truth
- Repository: `Veektall/MyTorchlightApp-`
- Canonical branch: `subway-video-corpus`
- Baseline before swarm coordination: `e0552b96d1dd0c7eb44cdbaac795f0f58a931f29`
- Control room: GitHub issue #140
- Latest authoritative result at initialization: v25 / run `33379193006` = FAILED
- v25 materially improved prompt detection and observed `up -> down -> left -> right`, but no valid Stage-15 benchmark episode completed.

## Immutable acceptance contract
1. Official game remains Poki Subway Surfers.
2. Learned policy input is rendered pixels only: 8 RGB frames, canonical `8x3x54x96` tensor.
3. Policy actions remain `stay,left,right,jump,roll`; no hidden game state or DOM leakage.
4. Trusted actuator remains ordinary Playwright keyboard input through the proven canvas wrapper: one focus/click path and `locator.press(..., delay>=180)`; no synthetic DOM events.
5. Tutorial/bootstrap does not count as gameplay survival or score.
6. Benchmark clock starts only after normal endless play is visually/pixel-score verified.
7. Score is read from rendered pixels; death is visually detected.
8. Requested benchmark is exactly stay x1, always_jump x1, corridor_cv x1, learned x3.
9. Each requested episode must run to visually verified death; watchdog is a safety abort only.
10. `stage15_completed=true` requires all six requested episodes valid plus a discriminative score spread. Competence claim remains separate.
11. No geometry/Stage16 work until Stage 15 evaluator is genuinely discriminative.

## Task graph
- AGENT-01 — Prompt Vision: make tutorial prompt sensing fast/reliable from rendered frames and prove it on saved recordings/frames.
- AGENT-02 — State/Actuator: prove causal prompt -> trusted keypress -> new visual state semantics; eliminate stale/repeated lateral actuation bugs.
- AGENT-03 — Evaluator/Replay: independently classify v25 failure, audit handoff/score/death/restart/status logic, and create replay/verification evidence that shortens iteration cycles.
- ORCHESTRATOR — current GROK main chat: integrate only evidence-backed compatible fixes, resolve conflicts, run final authoritative Stage 15 workflow, verify durable status/artifacts, and close the swarm.

## Convergence rule
Parallelize hypotheses; centralize truth. Workers do not merge directly into canonical Stage-15 evaluator. They publish commits/handoffs on their own swarm branches. The Orchestrator reviews and ports/cherry-picks only the minimal compatible proven changes, then runs one authoritative end-to-end Stage 15 evaluation.

## Worker branches
- `swarm/SWARM-2026-STAGE15-01/AGENT-01`
- `swarm/SWARM-2026-STAGE15-01/AGENT-02`
- `swarm/SWARM-2026-STAGE15-01/AGENT-03`

## Completion
The swarm is complete only when the canonical branch contains a verified Stage-15 result satisfying the immutable acceptance contract and durable `subway_ai/status/stage15-latest.json` reports `stage15_completed=true`.