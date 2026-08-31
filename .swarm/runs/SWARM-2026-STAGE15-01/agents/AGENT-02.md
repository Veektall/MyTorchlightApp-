# AGENT-02 — Tutorial State Machine + Trusted Actuator

Role: BUILD/DEBUG WORKER
Status: READY
Control room: issue #140
Worker branch: `swarm/SWARM-2026-STAGE15-01/AGENT-02`

## Assignment
Own the causal tutorial-control problem: rendered prompt observation -> exactly one trusted key action -> visually new state. Identify why v25 can repeatedly issue Left/Right while score remains stalled and ensure stale asynchronous prompt frames can never authorize duplicate lateral actions.

## Read first
- `SWARM_WORKER_PROTOCOL.md`
- swarm manifest/status/decisions
- evaluator v20-v25
- `subway_ai/status/stage15-latest.json`
- relevant v22-v25 artifacts/recordings/logs

## Owned area
- Experimental tutorial state-machine/actuator patches on your branch.
- Instrumentation/tests proving action causality and generation semantics.
- Evidence report/handoff.

## Immutable actuator contract
The effective physical action must be the already proven canvas wrapper path: one focus/click path followed by ordinary Playwright `locator.press(key, delay>=180)`. No synthetic DOM keyboard events.

## Constraints
- No DOM/game-state leakage.
- Global world motion is not evidence a tutorial prompt cleared.
- Same direction may recur in a later tutorial obstacle; distinguish a genuinely new rendered prompt instance from a stale frame.
- Preserve persistent browser context and strict tutorial-to-endless-play handoff.

## Acceptance criteria
1. Trace v25's repeated lateral actions and identify the precise causal bug(s), not just symptoms.
2. Prove that a second Left/Right cannot be authorized by a frame captured before the previous lateral action.
3. Prove vertical retry behavior still handles Up/Down tutorial phases.
4. Prove exactly one trusted physical press path per authorized action.
5. Publish minimal patch/commit, instrumentation evidence, known risks, and integration instructions.
6. Do not weaken score/prompt handoff criteria to make the trace appear successful.

## Deliverable
Publish `.swarm/runs/SWARM-2026-STAGE15-01/outputs/AGENT-02-handoff.md` and post material blockers/conflicts to issue #140.