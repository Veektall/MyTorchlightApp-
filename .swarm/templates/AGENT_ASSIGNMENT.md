# Agent Assignment

- SWARM_ID: <SWARM_ID>
- AGENT_ID: <AGENT_ID>
- Role: <ROLE>
- Task ID: <TASK_ID>
- Control room: <ISSUE_NUMBER_OR_URL>

## Objective
<BOUNDED OBJECTIVE>

## Owned scope
- <scope>

## Read-only context
- <scope>

## Dependencies
- <TASK/AGENT or NONE>

## Inputs
- <source/file/decision>

## Deliverables
- <deliverable>

## Acceptance criteria
- <criterion>
- <criterion>

## Verification
- <test/check>

## Handoff
Write the final handoff to `.swarm/runs/<SWARM_ID>/outputs/<AGENT_ID>-handoff.md`.

## Required behavior
1. Read `SWARM_WORKER_PROTOCOL.md`.
2. Read current manifest, status, decisions, control-room issue, dependencies, and target files.
3. Mark the task IN_PROGRESS when starting.
4. Work only inside the assigned scope.
5. Record blockers and conflicts in shared GitHub state.
6. Re-sync before completion.
7. Verify the acceptance criteria.
8. Publish the handoff and then mark DONE when all completion conditions are satisfied.
