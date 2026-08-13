# Universal Swarm Worker Protocol

Version: 1.0
Status: Active

## Purpose

Coordinate multiple independent ChatGPT/AI worker chats through GitHub without requiring direct chat-to-chat messaging.

**Core model:** chats are workers; GitHub is the shared blackboard; repository state is authoritative.

## Roles

### Orchestrator
- Break the master goal into a dependency-aware task graph.
- Create the swarm manifest, assignments, status board, decision log, and control-room issue.
- Give every worker a bounded ownership area and acceptance criteria.
- Resolve conflicts, integrate outputs, and verify the final result.

### Worker
- Load this protocol and current swarm state before work.
- Stay inside the assigned scope.
- Publish durable results, evidence, blockers, and handoffs to GitHub.
- Re-sync before every continuation and before completion.

### Verifier
- Independently challenge important results.
- Reproduce claims where practical.
- Record disagreements explicitly.
- Mark findings VERIFIED, FAILED, or UNRESOLVED with evidence.

### Integrator
- Combine completed worker outputs.
- Resolve interface mismatches using accepted decisions.
- Run integration-level checks and publish a final integration handoff.

## Required layout

Each swarm gets a unique ID such as `SWARM-2026-001`.

```text
.swarm/runs/<SWARM_ID>/
  manifest.md
  status.md
  decisions.md
  agents/
    AGENT-01.md
    AGENT-02.md
  outputs/
    AGENT-01-handoff.md
    AGENT-02-handoff.md
```

Create one GitHub issue named `[SWARM:<SWARM_ID>] Control Room` for blockers, conflicts, cross-agent notes, and integration coordination.

## Global invariants

1. **GitHub is authoritative.** If chat memory conflicts with current GitHub state, GitHub wins unless the user explicitly overrides it.
2. **Read before write.** Read the latest relevant files, issue comments, branches, and dependency outputs before changing shared work.
3. **Resync on continuation.** When asked to continue/resume, re-read the manifest, status, decisions, control room, assignment, dependencies, and target files before acting.
4. **Explicit ownership.** Each assignment declares owned areas, shared areas, dependencies, deliverables, and completion criteria.
5. **No invisible coordination.** Information that affects another worker must be published to shared state.
6. **Evidence over assertion.** Material conclusions need reproducible evidence: sources, tests, commit references, file paths, calculations, or verification steps.
7. **No fake completion.** Writing an answer is not completion unless acceptance criteria are met and the handoff is published.
8. **Preserve user intent.** Do not silently change the master goal, constraints, budget, or scope.

## Worker startup sequence

Every worker must perform these steps before substantive work.

### 1. Identify
Resolve:

```text
SWARM_ID
AGENT_ID
ROLE
ASSIGNMENT_PATH
CONTROL_ROOM_ISSUE
```

Discover these from GitHub when possible instead of asking the user to repeat them.

### 2. Load protocol
Read `SWARM_WORKER_PROTOCOL.md` from the repository.

### 3. Load current state
Read in order:

1. `.swarm/runs/<SWARM_ID>/manifest.md`
2. `.swarm/runs/<SWARM_ID>/status.md`
3. `.swarm/runs/<SWARM_ID>/decisions.md`
4. this agent's assignment
5. control-room issue/comments
6. dependency deliverables
7. files the agent expects to modify

### 4. Validate readiness
Check whether the assignment is still active, required dependencies are ready, no accepted decision superseded it, and no unresolved ownership conflict exists.

If not ready, publish a blocker rather than modifying dependent work.

### 5. Claim work
Mark the task `IN_PROGRESS` before shared/destructive writes when practical.

## Execution loop

Every worker uses:

```text
SNAPSHOT -> CLAIM -> WORK -> PUBLISH -> RESYNC -> VERIFY -> HANDOFF
```

- **SNAPSHOT:** read current shared state and targets.
- **CLAIM:** mark active ownership where collision risk exists.
- **WORK:** execute within scope.
- **PUBLISH:** commit/write durable deliverables and evidence.
- **RESYNC:** re-read new decisions, blockers, dependencies, and target state.
- **VERIFY:** run assignment-specific checks.
- **HANDOFF:** publish what changed, evidence, risks, and the next action.

## Canonical status states

```text
TODO
READY
IN_PROGRESS
BLOCKED
REVIEW
DONE
FAILED
CANCELLED
```

- TODO: known but not ready/scheduled.
- READY: dependencies satisfied.
- IN_PROGRESS: currently owned by a worker.
- BLOCKED: cannot proceed without a dependency or decision.
- REVIEW: deliverable exists and needs verification/integration.
- DONE: acceptance criteria met and handoff published.
- FAILED: attempted but acceptance criteria not met.
- CANCELLED: no longer required.

## Dependency protocol

Assignments list dependencies by task/agent ID.

Before consuming a dependency, confirm it is `DONE` or explicitly approved for early use.

If a consumed dependency changes:
1. mark the dependent result potentially stale;
2. re-read the changed output;
3. rerun affected checks;
4. publish whether the dependent result remains valid.

## Blocker protocol

Publish blockers in the control room using:

```text
BLOCKED: <AGENT_ID>
Task: <task ID/title>
Blocking dependency: <agent/task/decision>
What I verified: <facts>
What is missing: <specific missing result>
Can continue independently on: <safe work or NONE>
Requested action: <single concrete action>
```

Do not ask the user to manually relay information that another worker can publish to GitHub.

## Conflict protocol

Never silently choose between incompatible worker outputs.

Publish:

```text
CONFLICT: <short title>
Agents/results: <A> vs <B>
Shared facts: <agreement>
Disagreement: <exact contradiction>
Evidence A: <reference>
Evidence B: <reference>
Impact: <what depends on this>
Recommended resolver: ORCHESTRATOR | VERIFIER | USER
```

The resolution must be recorded in `decisions.md`.

## Decision protocol

Record decisions that change scope, interfaces, assumptions, ownership, dependencies, acceptance criteria, or architecture.

```text
DECISION-ID
Status: PROPOSED | ACCEPTED | SUPERSEDED | REJECTED
Decision: ...
Reason: ...
Evidence: ...
Affected agents/tasks: ...
Supersedes: ...
Recorded by: ...
```

Workers obey accepted decisions. Superseded decisions stay historical rather than being silently deleted.

## Write/branch strategy

For code-heavy work, prefer one worker branch per editing agent:

```text
swarm/<SWARM_ID>/<AGENT_ID>
```

Avoid multiple agents editing the same mutable file. Assign one owner or use separate branches plus an Integrator.

Coordination markdown under `.swarm/runs/<SWARM_ID>/` may be updated on the shared branch when collision risk is low.

## Research worker requirements

Distinguish:
- sourced fact;
- inference;
- assumption;
- unresolved uncertainty.

When information may have changed, verify current sources.

Research handoffs should include conclusion, strongest evidence, contradictory evidence, uncertainty, and downstream implications.

## Build worker requirements

Publish:
1. files changed;
2. branch/commit reference;
3. interface assumptions;
4. tests/checks run;
5. known failures or untested areas;
6. integration instructions.

Code written is not automatically code verified.

## Verification requirements

Verification should be meaningfully independent. Prefer different tests, sources, or failure-seeking angles from the original worker.

A verifier may return work from `REVIEW`/`DONE` to `IN_PROGRESS` or `FAILED` when evidence does not support completion.

## Completion protocol

A worker may mark `DONE` only after:
1. required dependencies were consumed;
2. deliverables were published;
3. acceptance criteria were checked;
4. verification was performed;
5. latest shared state was re-read;
6. no newly accepted decision invalidates the work;
7. handoff was published.

Use this handoff format:

```text
HANDOFF: <AGENT_ID>
Status: DONE | REVIEW | BLOCKED | FAILED
Assignment: <task>
Deliverables: <paths/commits/issues>
Key result: <short conclusion>
Verification: <tests/evidence>
Decisions introduced: <IDs or NONE>
Risks/limitations: <items or NONE>
Dependencies affected: <agents/tasks or NONE>
Next recommended action: <single concrete next step>
```

## Orchestrator integration gate

Do not declare the swarm complete until:
1. required tasks are DONE or explicitly waived;
2. critical conflicts are resolved;
3. integration verification passes;
4. the final deliverable matches the original user goal;
5. GitHub reflects the final state;
6. remaining risks are disclosed.

## Human interaction rule

The user should primarily spawn worker chats and make true user-level decisions, not carry messages between agents.

Agents coordinate through GitHub. If another worker's output is required, read the blackboard or publish a dependency/blocker.

## Minimal join command

After initialization, a worker can be started with:

```text
Join swarm <SWARM_ID> as <AGENT_ID>. Use repository <OWNER/REPO>. Read SWARM_WORKER_PROTOCOL.md and your assignment from the swarm manifest. Execute until DONE, REVIEW, FAILED, or genuinely BLOCKED. Use GitHub as the source of truth and resync before every continuation and before completion.
```

## Recovery

If a worker chat is closed or lost:
1. spawn a replacement with the same agent ID or an explicit successor ID;
2. rebuild context from GitHub;
3. inspect prior commits/outputs;
4. continue from durable state;
5. record succession when relevant.

---

## Universal rule

**If it matters to another agent, write it to the blackboard. If it is not on the blackboard, do not assume the swarm knows it.**
