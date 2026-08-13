# Swarm Workspace

This directory stores durable coordination state for multi-chat agent swarms.

Read `../SWARM_WORKER_PROTOCOL.md` before participating in any swarm.

## Layout

```text
.swarm/
  README.md
  templates/
  runs/
    <SWARM_ID>/
      manifest.md
      status.md
      decisions.md
      agents/
      outputs/
```

## Start a new swarm

The Orchestrator should:

1. choose a unique `SWARM_ID`;
2. copy the templates into `.swarm/runs/<SWARM_ID>/`;
3. define tasks, dependencies, ownership, deliverables, and acceptance criteria;
4. create one assignment file per worker;
5. create a GitHub control-room issue named `[SWARM:<SWARM_ID>] Control Room`;
6. give each worker the minimal join command from `SWARM_WORKER_PROTOCOL.md`.

GitHub is the source of truth. Worker chats are disposable; swarm state should not be.
