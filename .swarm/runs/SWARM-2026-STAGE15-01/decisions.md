# SWARM-2026-STAGE15-01 Decisions

## DECISION-001
Status: ACCEPTED
Decision: Use one Orchestrator plus three orthogonal workers; GitHub is the shared blackboard and canonical truth.
Reason: Stage 15 now exposes separable uncertainty in prompt sensing, causal control/state semantics, and evaluator/replay validity. Duplicating the same end-to-end repair would increase merge conflict without increasing information gain.
Evidence: v25 run `33379193006` failed after recognizing all four tutorial directions; prior versions exposed independent OCR latency, stale async frames, and duplicate actuator focus/click defects.
Affected agents/tasks: ALL
Supersedes: NONE
Recorded by: ORCHESTRATOR

## DECISION-002
Status: ACCEPTED
Decision: No worker may weaken Stage-15 acceptance criteria, use hidden game/DOM state, replace the trusted keyboard actuator, or count tutorial/bootstrap score as gameplay score.
Reason: Those constraints define the experiment; relaxing them would create fake competence rather than solve Stage 15.
Evidence: `pixel-policy-contract-v1.1` and established Stage-15 evaluation contract.
Affected agents/tasks: ALL
Supersedes: NONE
Recorded by: ORCHESTRATOR

## DECISION-003
Status: ACCEPTED
Decision: Workers publish evidence and patches on isolated swarm branches; the Orchestrator alone integrates into `subway-video-corpus` after reviewing compatibility and verification.
Reason: Prevent concurrent edits to the canonical evaluator/workflow and make convergence reversible.
Evidence: `SWARM_WORKER_PROTOCOL.md` write/branch strategy.
Affected agents/tasks: AGENT-01, AGENT-02, AGENT-03, ORCHESTRATOR
Supersedes: NONE
Recorded by: ORCHESTRATOR