# Swarm Manifest

## Identity

- SWARM_ID: <SWARM_ID>
- Master goal: <USER_GOAL>
- Repository: <OWNER/REPO>
- Default branch: <BRANCH>
- Control-room issue: <ISSUE_NUMBER_OR_URL>
- Orchestrator: <AGENT_ID_OR_CHAT>

## Global constraints

- <constraint>
- <constraint>

## Definition of done

The swarm is complete when:

- <acceptance criterion>
- <acceptance criterion>

## Task graph

| Task ID | Agent | Role | Depends on | Status | Deliverable |
|---|---|---|---|---|---|
| TASK-01 | AGENT-01 | <role> | NONE | READY | <path/result> |
| TASK-02 | AGENT-02 | <role> | TASK-01 | TODO | <path/result> |

## Ownership map

| Agent | Owns | Shared/read-only | Must not edit |
|---|---|---|---|
| AGENT-01 | <scope> | <scope> | <scope> |

## Integration order

1. <dependency/integration step>
2. <dependency/integration step>

## Notes

- Workers must follow `SWARM_WORKER_PROTOCOL.md`.
- GitHub state is authoritative.
- Any scope/interface/ownership change must be recorded in `decisions.md`.
