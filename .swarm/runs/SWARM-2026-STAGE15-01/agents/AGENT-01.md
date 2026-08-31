# AGENT-01 — Tutorial Prompt Vision

Role: BUILD/RESEARCH WORKER
Status: READY
Control room: issue #140
Worker branch: `swarm/SWARM-2026-STAGE15-01/AGENT-01`

## Assignment
Own the rendered-pixel tutorial prompt sensing problem. Make Up/Down/Left/Right instruction detection fast and reliable enough that bootstrap control is not dominated by Tesseract latency/misses.

## Read first
- `SWARM_WORKER_PROTOCOL.md`
- swarm manifest/status/decisions
- `subway_ai/status/stage15-latest.json`
- evaluator v20-v25 prompt code
- available Stage-15 artifacts/recordings, especially v24 and v25

## Owned area
- New/experimental prompt detector modules/scripts/tests on your branch.
- Offline extraction/replay tests for rendered prompt frames.
- Evidence report/handoff.

## Shared/read-only unless explicitly coordinated
- `.github/workflows/subway-stage15.yml`
- canonical `subway_ai/status/stage15-latest.json`
- canonical integration branch `subway-video-corpus`

## Constraints
- Pixels only. No DOM, game internals, hidden coordinates/state variables, or accessibility/JS game state.
- Prompt sensing is bootstrap-only and must never become learned-policy input.
- Do not weaken tutorial handoff or benchmark gates.
- Avoid synchronous OCR in the control loop.

## Acceptance criteria
1. Reproduce the known v24/v25 prompt frames from saved video/artifacts or equivalent deterministic evidence.
2. Demonstrate reliable detection of Up, Down, Left, Right with materially lower latency than v24's old broad OCR path.
3. Audit false positives on prompt-absent frames; detector must not fire on ordinary background text merely containing direction words.
4. Publish measured detection results, exact code/commit, known failure cases, and integration instructions.
5. Prefer offline/replay proof before launching expensive official-game runs.

## Deliverable
Publish `.swarm/runs/SWARM-2026-STAGE15-01/outputs/AGENT-01-handoff.md` and post material blockers/conflicts to issue #140.

Do not mark DONE merely because code exists; provide reproducible evidence.